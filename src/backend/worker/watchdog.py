"""Production watchdog: health rules, rate limiting, Brazilian holidays, Telegram alerts.

Runs periodically (e.g. every 6h). Each rule fires at most once per 6 hours.
Holidays are stored in pipeline_config (editable) with default Brazilian calendar.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

try:
    from dateutil.easter import easter
except ImportError:
    easter = None  # type: ignore[assignment]

from src.backend.worker.registry import FileStatus, Registry

logger = logging.getLogger(__name__)

RATE_LIMIT_HOURS = 6
SILENCE_BUSINESS_DAYS = 3
FAILURE_ACCUMULATOR_THRESHOLD = 10
DISK_PRESSURE_PCT = 80
WORKER_STALE_MINUTES = 10
COST_ANOMALY_USD_24H = 5.0

# Default Brazilian fixed holidays (MM-DD)
DEFAULT_HOLIDAYS_FIXED = "01-01,04-21,05-01,09-07,10-12,11-02,11-15,12-25"


def _brazilian_holidays_for_year(year: int, fixed_csv: str = DEFAULT_HOLIDAYS_FIXED) -> set[date]:
    """Return set of Brazilian holiday dates for the year (fixed + variable from Easter)."""
    out: set[date] = set()
    for part in fixed_csv.split(","):
        part = part.strip()
        if not part or "-" not in part:
            continue
        try:
            m, d = int(part.split("-")[0]), int(part.split("-")[1])
            out.add(date(year, m, d))
        except (ValueError, IndexError):
            continue
    if easter is not None:
        e = easter(year)
        out.add(e - timedelta(days=48))  # Carnival Monday
        out.add(e - timedelta(days=47))  # Carnival Tuesday
        out.add(e - timedelta(days=2))   # Good Friday
        out.add(e + timedelta(days=60))  # Corpus Christi
    return out


def _is_business_day(d: date, holidays: set[date]) -> bool:
    """Weekday 0-4 and not a holiday."""
    if d.weekday() >= 5:
        return False
    return d not in holidays


class Watchdog:
    """Evaluate health rules and emit rate-limited alerts."""

    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self._last_alert: dict[str, str] = {}  # rule_id -> iso timestamp

    async def _get_config(self, key: str, default: str = "") -> str:
        return (await self.registry.get_config(key)) or default

    async def _set_config(self, key: str, value: str) -> None:
        await self.registry.set_config(key, value)

    async def _can_alert(self, rule_id: str) -> bool:
        """True if we are allowed to send an alert for this rule (rate limit)."""
        now = datetime.now(timezone.utc)
        key = f"watchdog_last_alert_{rule_id}"
        last = await self._get_config(key)
        if not last:
            return True
        try:
            then = datetime.fromisoformat(last.replace("Z", "+00:00"))
            return (now - then).total_seconds() >= RATE_LIMIT_HOURS * 3600
        except (ValueError, TypeError):
            return True

    async def _record_alert(self, rule_id: str) -> None:
        await self._set_config(f"watchdog_last_alert_{rule_id}", datetime.now(timezone.utc).isoformat())

    async def _holidays_for_range(self, start: date, end: date) -> set[date]:
        csv = await self._get_config("holidays_fixed", DEFAULT_HOLIDAYS_FIXED)
        out: set[date] = set()
        for y in range(start.year, end.year + 1):
            out |= _brazilian_holidays_for_year(y, csv)
        return {d for d in out if start <= d <= end}

    async def _rule_silence(self) -> tuple[str, str, str] | None:
        """No VERIFIED files in 3 business days → CRITICAL. Holiday-aware."""
        today = date.today()
        holidays = await self._holidays_for_range(today - timedelta(days=14), today)
        business_days_without = 0
        for delta in range(0, 14):
            d = today - timedelta(days=delta)
            if not _is_business_day(d, holidays):
                continue
            # Check if any file was verified on this day
            async with self.registry.get_db() as db:
                cursor = await db.execute(
                    """SELECT 1 FROM dou_files WHERE date(verified_at) = ? LIMIT 1""",
                    (d.isoformat(),),
                )
                if (await cursor.fetchone()) is not None:
                    business_days_without = 0
                    continue
            business_days_without += 1
            if business_days_without >= SILENCE_BUSINESS_DAYS:
                return (
                    "silence_detector",
                    "CRITICAL",
                    f"No VERIFIED files in the last {SILENCE_BUSINESS_DAYS} business days.",
                )
        return None

    async def _rule_failure_accumulator(self) -> tuple[str, str, str] | None:
        """More than 10 files in *_FAILED simultaneously → HIGH."""
        failed = [
            FileStatus.DOWNLOAD_FAILED,
            FileStatus.EXTRACT_FAILED,
            FileStatus.BM25_INDEX_FAILED,
            FileStatus.EMBEDDING_FAILED,
            FileStatus.VERIFY_FAILED,
        ]
        total = 0
        for s in failed:
            files = await self.registry.get_files_by_status(s, limit=20)
            total += len(files)
        if total > FAILURE_ACCUMULATOR_THRESHOLD:
            return (
                "failure_accumulator",
                "HIGH",
                f"More than {FAILURE_ACCUMULATOR_THRESHOLD} files in failed states ({total}).",
            )
        return None

    async def _rule_disk_pressure(self) -> tuple[str, str, str] | None:
        """Worker volume >80% → MEDIUM."""
        usage = await self.registry.get_disk_usage()
        total = usage.get("total_bytes") or 1
        free = usage.get("free_bytes") or 0
        used_pct = (1 - free / total) * 100 if total else 0
        if used_pct >= DISK_PRESSURE_PCT:
            return (
                "disk_pressure",
                "MEDIUM",
                f"Worker volume usage at {used_pct:.0f}% (threshold {DISK_PRESSURE_PCT}%).",
            )
        return None

    async def _rule_paused_too_long(self) -> tuple[str, str, str] | None:
        """Pipeline paused for more than 48h → MEDIUM."""
        val = await self._get_config("scheduler_paused", "false")
        if (val or "").strip().lower() != "true":
            return None
        at = await self._get_config("scheduler_paused_at", "")
        if not at:
            return None
        try:
            then = datetime.fromisoformat(at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if (now - then).total_seconds() > 48 * 3600:
                return (
                    "paused_too_long",
                    "MEDIUM",
                    "Pipeline has been paused for more than 48 hours.",
                )
        except (ValueError, TypeError):
            pass
        return None

    async def _rule_worker_stale(self, last_heartbeat: str | None) -> tuple[str, str, str] | None:
        """No heartbeat in 10 minutes → CRITICAL."""
        if not last_heartbeat:
            return ("worker_stale", "CRITICAL", "No heartbeat recorded.")
        try:
            then = datetime.fromisoformat(last_heartbeat.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if (now - then).total_seconds() > WORKER_STALE_MINUTES * 60:
                return (
                    "worker_stale",
                    "CRITICAL",
                    f"No heartbeat in more than {WORKER_STALE_MINUTES} minutes.",
                )
        except (ValueError, TypeError):
            return ("worker_stale", "CRITICAL", "Invalid heartbeat timestamp.")
        return None

    async def evaluate(
        self,
        *,
        last_heartbeat: str | None = None,
        es_green: bool = True,
    ) -> dict[str, Any]:
        """Run all rules and return status + list of alerts (respecting rate limit).

        Caller can pass last_heartbeat from worker main and es_green from ES health check.
        """
        results: dict[str, dict[str, Any]] = {}
        alerts: list[dict[str, str]] = []

        rule_calls = [
            ("silence_detector", self._rule_silence()),
            ("failure_accumulator", self._rule_failure_accumulator()),
            ("disk_pressure", self._rule_disk_pressure()),
            ("paused_too_long", self._rule_paused_too_long()),
            ("worker_stale", self._rule_worker_stale(last_heartbeat)),
        ]
        for rule_id, coro in rule_calls:
            outcome = await coro
            if outcome is None:
                results[rule_id] = {"fired": False, "severity": None, "message": None}
                continue
            rid, severity, message = outcome
            can = await self._can_alert(rid)
            results[rule_id] = {"fired": True, "severity": severity, "message": message}
            if can:
                alerts.append({"rule_id": rid, "severity": severity, "message": message})
                await self._record_alert(rid)

        # ES unhealthy
        if not es_green:
            results["es_unhealthy"] = {"fired": True, "severity": "CRITICAL", "message": "ES cluster status is not green."}
            if await self._can_alert("es_unhealthy"):
                alerts.append({"rule_id": "es_unhealthy", "severity": "CRITICAL", "message": "ES cluster status is not green."})
                await self._record_alert("es_unhealthy")
        else:
            results["es_unhealthy"] = {"fired": False, "severity": None, "message": None}

        return {
            "status": "ok" if not alerts else "alerts",
            "last_evaluated": datetime.now(timezone.utc).isoformat(),
            "rules": results,
            "alerts": alerts,
        }

    async def run_and_notify(
        self,
        *,
        last_heartbeat: str | None = None,
        es_green: bool = True,
        send_telegram: bool = True,
    ) -> dict[str, Any]:
        """Evaluate, log, and optionally send Telegram for each new alert."""
        outcome = await self.evaluate(last_heartbeat=last_heartbeat, es_green=es_green)
        for a in outcome.get("alerts", []):
            logger.warning("Watchdog alert [%s] %s: %s", a["severity"], a["rule_id"], a["message"])
            if send_telegram:
                await _send_telegram(f"[{a['severity']}] {a['rule_id']}: {a['message']}")
        return outcome


async def _send_telegram(text: str) -> None:
    """Send a plain text message via Telegram Bot API. No-op if token/chat not set."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        logger.debug("Telegram not configured, skipping alert.")
        return
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=10,
            )
    except Exception as e:
        logger.warning("Failed to send Telegram alert: %s", e)
