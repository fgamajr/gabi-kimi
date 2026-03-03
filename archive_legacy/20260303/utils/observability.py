"""Structured crawler observability using loguru + logfmt."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import sys
import uuid
from typing import Any

from loguru import logger


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _to_logfmt_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "":
        return '""'
    needs_quote = any(ch.isspace() or ch in '"=' for ch in text)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"' if needs_quote else escaped


def _build_logfmt(record: dict[str, Any]) -> str:
    ts = record["extra"].get("ts_utc", _utc_now_iso())
    lvl = record["level"].name
    svc = record["extra"].get("svc", "fake-browser")
    evt = record["extra"].get("evt", "unknown")

    parts: list[str] = [f"{ts}", f"lvl={lvl}", f"svc={svc}", f"evt={evt}"]

    excluded = {"svc", "evt", "ts_utc"}
    for key in sorted(record["extra"].keys()):
        if key in excluded:
            continue
        value = record["extra"][key]
        if value is None:
            continue
        parts.append(f"{key}={_to_logfmt_value(value)}")

    return " ".join(parts) + "\n"


@dataclass(slots=True)
class CrawlerLogger:
    svc: str = "fake-browser"
    env: str = "dev"

    @staticmethod
    def generate_run_id() -> str:
        return uuid.uuid4().hex[:8]

    @staticmethod
    def ua_hash(user_agent: str) -> str:
        return hashlib.sha1(user_agent.encode("utf-8")).hexdigest()[:6]

    def configure(self, log_path: str, level: str = "INFO") -> None:
        logger.remove()
        logger.add(sys.stdout, level=level, format=_build_logfmt, colorize=False)
        logger.add(log_path, level=level, format=_build_logfmt, colorize=False, enqueue=False)

    def _emit(self, severity: str, evt: str, **fields: Any) -> None:
        bound = logger.bind(svc=self.svc, evt=evt, env=self.env, ts_utc=_utc_now_iso(), **fields)
        bound.log(severity, "")

    def emit_event(self, evt: str, **fields: Any) -> None:
        self._emit("INFO", evt, **fields)

    def run_started(self, *, run: str, years: int, start_date: str, end_date: str, mode: str) -> None:
        self._emit(
            "INFO",
            "run_started",
            run=run,
            years=years,
            start_date=start_date,
            end_date=end_date,
            mode=mode,
        )

    def run_completed(
        self,
        *,
        run: str,
        duration_ms: int,
        total_targets: int,
        ok: int,
        fail: int,
        success_rate: float,
    ) -> None:
        self._emit(
            "INFO",
            "run_completed",
            run=run,
            duration_ms=duration_ms,
            total_targets=total_targets,
            ok=ok,
            fail=fail,
            success_rate=success_rate,
        )

    def request_planned(self, *, run: str, day: str, ua_id: int, ua_hash: str, url: str) -> None:
        self._emit(
            "INFO",
            "request_planned",
            run=run,
            day=day,
            ua_id=ua_id,
            ua_hash=ua_hash,
            url=url,
        )

    def request_result(
        self,
        *,
        run: str,
        day: str,
        ua_id: int,
        reachable: bool,
        simulated: bool,
        latency_ms: int,
        status: str,
    ) -> None:
        self._emit(
            "INFO",
            "request_result",
            run=run,
            day=day,
            ua_id=ua_id,
            reachable=reachable,
            simulated=simulated,
            latency_ms=latency_ms,
            status=status,
        )

    def parse_started(self, *, run: str, day: str | None = None) -> None:
        self._emit("INFO", "parse_started", run=run, day=day)

    def parse_completed(self, *, run: str, day: str | None = None) -> None:
        self._emit("INFO", "parse_completed", run=run, day=day)

    def extract_completed(
        self,
        *,
        run: str,
        extracted_items: int,
        section_count: int,
        day: str | None = None,
    ) -> None:
        self._emit(
            "INFO",
            "extract_completed",
            run=run,
            day=day,
            extracted_items=extracted_items,
            section_count=section_count,
        )

    def error(
        self,
        *,
        run: str,
        stage: str,
        error_type: str,
        error_message: str,
        day: str | None = None,
    ) -> None:
        self._emit(
            "ERROR",
            "error",
            run=run,
            stage=stage,
            error_type=error_type,
            error_message=error_message,
            day=day,
        )
