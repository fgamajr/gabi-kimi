"""APScheduler cron job orchestration for the DOU ingestion pipeline.

Configures cron jobs for the pipeline phases + retry + daily ES snapshot.
Supports pause/resume and manual triggering of individual phases.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Coroutine

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.backend.core.logging import bind_pipeline, clear_context, get_logger
from src.backend.worker.pipeline.backfill import run_backfill_missing
from src.backend.worker.pipeline.discovery import run_discovery
from src.backend.worker.pipeline.downloader import run_download
from src.backend.worker.pipeline.embedder import run_embed
from src.backend.worker.pipeline.extractor import run_extract
from src.backend.worker.pipeline.ingestor import run_ingest
from src.backend.worker.pipeline.verifier import run_verify
from src.backend.worker.reconciler import run_reconciliation
from src.backend.worker.registry import FileStatus, Registry
from src.backend.worker.snapshots import create_snapshot

logger = get_logger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")

_registry: Registry | None = None
# Pause state is persisted in pipeline_config; _paused is in-memory cache
_paused: bool = False
_job_enabled: dict[str, bool] = {"embed": False}
SCHEDULER_SOURCE = "apscheduler"
SCHEDULER_TIMEZONE = "UTC"

PHASE_MAP: dict[str, Callable[..., Coroutine[Any, Any, dict[str, Any]]]] = {
    "discovery": run_discovery,
    "backfill_missing": run_backfill_missing,
    "download": run_download,
    "extract": run_extract,
    "bm25": run_ingest,
    "embed": run_embed,
    "verify": run_verify,
}
PHASE_SEQUENCE = ("discovery", "backfill_missing", "download", "extract", "bm25", "embed", "verify")
CONTROLLED_JOB_IDS = (
    *PHASE_SEQUENCE,
    "retry",
    "snapshot",
    "refresh_catalog_status",
    "reconciliation",
    "watchdog",
)
MANUAL_TRIGGER_MAP: dict[str, Callable[..., Coroutine[Any, Any, Any]]] = {}


def _job_config_key(job_id: str) -> str:
    return f"scheduler_job_enabled:{job_id}"


def is_job_enabled(job_id: str) -> bool:
    """Return whether a scheduled job is enabled for automatic execution."""
    return _job_enabled.get(job_id, True)


def _get_sentry_sdk():
    """Return sentry_sdk when installed/configured, otherwise None."""
    try:
        import sentry_sdk
    except ImportError:
        return None
    return sentry_sdk


def _normalize_phase_stats(phase: str, stats: dict[str, Any]) -> dict[str, int]:
    """Normalize per-phase stats into pipeline_runs counters."""
    if phase == "discovery":
        processed = int(stats.get("new_files", 0)) + int(stats.get("existing_files", 0))
        return {
            "processed": processed,
            "succeeded": int(stats.get("new_files", 0)),
            "failed": 0,
        }
    if phase == "download":
        return {
            "processed": int(stats.get("downloaded", 0)) + int(stats.get("failed", 0)),
            "succeeded": int(stats.get("downloaded", 0)),
            "failed": int(stats.get("failed", 0)),
        }
    if phase == "backfill_missing":
        return {
            "processed": int(stats.get("seeded_months", 0)) + int(stats.get("queued_files", 0)),
            "succeeded": int(stats.get("queued_files", 0)),
            "failed": 0,
        }
    if phase == "extract":
        return {
            "processed": int(stats.get("extracted", 0)) + int(stats.get("failed", 0)),
            "succeeded": int(stats.get("extracted", 0)),
            "failed": int(stats.get("failed", 0)),
        }
    if phase == "bm25":
        return {
            "processed": int(stats.get("indexed_files", 0)) + int(stats.get("failed_files", 0)),
            "succeeded": int(stats.get("indexed_files", 0)),
            "failed": int(stats.get("failed_files", 0)),
        }
    if phase == "embed":
        return {
            "processed": int(stats.get("embedded_files", 0)) + int(stats.get("failed_files", 0)),
            "succeeded": int(stats.get("embedded_files", 0)),
            "failed": int(stats.get("failed_files", 0)),
        }
    if phase == "verify":
        return {
            "processed": int(stats.get("verified", 0)) + int(stats.get("failed", 0)),
            "succeeded": int(stats.get("verified", 0)),
            "failed": int(stats.get("failed", 0)),
        }
    return {
        "processed": int(stats.get("processed", 0)),
        "succeeded": int(stats.get("succeeded", 0)),
        "failed": int(stats.get("failed", 0)),
    }


def _get_es_url() -> str:
    return os.environ.get("ES_URL", "http://es.internal:9200")


async def _run_phase(phase: str, *, respect_job_enabled: bool = True) -> dict[str, Any]:
    """Run a pipeline phase with registry tracking."""
    global _registry
    if _paused:
        logger.info("Scheduler paused, skipping phase: %s", phase)
        return {"skipped": True, "phase": phase}
    if respect_job_enabled and not is_job_enabled(phase):
        logger.info("Phase disabled, skipping automatic execution: %s", phase)
        return {"skipped": True, "phase": phase, "reason": "disabled"}

    if _registry is None:
        logger.error("Registry not initialized, cannot run phase: %s", phase)
        return {"error": "registry not initialized"}

    run_id = await _registry.create_pipeline_run(phase)
    bind_pipeline(run_id=run_id, phase=phase)
    func = PHASE_MAP[phase]
    es_url = _get_es_url()

    try:
        sentry_sdk = _get_sentry_sdk()
        if sentry_sdk is not None:
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("pipeline_phase", phase)
                scope.set_tag("run_id", run_id)
                # Each pipeline function has slightly different signatures.
                # discovery, verify, bm25, embed take (registry, run_id, es_url, ...)
                # download, extract take (registry, run_id, ...)
                if phase in ("discovery", "verify"):
                    stats = await func(_registry, run_id, es_url)
                elif phase in ("bm25", "embed"):
                    stats = await func(_registry, run_id, es_url)
                else:
                    stats = await func(_registry, run_id)
        else:
            if phase in ("discovery", "verify"):
                stats = await func(_registry, run_id, es_url)
            elif phase in ("bm25", "embed"):
                stats = await func(_registry, run_id, es_url)
            else:
                stats = await func(_registry, run_id)

        counters = _normalize_phase_stats(phase, stats)
        await _registry.complete_pipeline_run(
            run_id,
            files_processed=counters["processed"],
            files_succeeded=counters["succeeded"],
            files_failed=counters["failed"],
        )
        logger.info("Phase '%s' completed: %s", phase, stats)
        return stats
    except Exception as exc:
        logger.error("Phase '%s' failed: %s", phase, exc, exc_info=True)
        await _registry.complete_pipeline_run(
            run_id,
            files_processed=0,
            files_succeeded=0,
            files_failed=0,
            error_message=str(exc),
        )
        return {"error": str(exc)}
    finally:
        clear_context()


async def _run_snapshot() -> None:
    """Run daily ES snapshot."""
    if _paused:
        logger.info("Scheduler paused, skipping snapshot")
        return
    if not is_job_enabled("snapshot"):
        logger.info("Snapshot job disabled, skipping")
        return
    es_url = _get_es_url()
    await create_snapshot(es_url)


async def _run_refresh_catalog_status() -> None:
    """Refresh catalog_status for all dou_catalog_months (daily)."""
    global _registry
    if _paused:
        logger.info("Scheduler paused, skipping catalog status refresh")
        return
    if not is_job_enabled("refresh_catalog_status"):
        logger.info("Catalog status refresh disabled, skipping")
        return
    if _registry is None:
        logger.error("Registry not initialized, cannot refresh catalog status")
        return
    n = await _registry.refresh_catalog_month_status()
    logger.info("Refreshed catalog_status for %d months", n)


async def _run_watchdog() -> None:
    """Run watchdog evaluation and send Telegram alerts (every 6h)."""
    global _registry
    if _paused:
        logger.info("Scheduler paused, skipping watchdog")
        return
    if not is_job_enabled("watchdog"):
        logger.info("Watchdog disabled, skipping")
        return
    if _registry is None:
        logger.error("Registry not initialized, cannot run watchdog")
        return
    from src.backend.worker.main import get_last_heartbeat
    from src.backend.worker.watchdog import Watchdog

    es_green = True
    es_url = _get_es_url()
    try:
        import httpx

        async with httpx.AsyncClient() as client:
            r = await client.get(f"{es_url}/_cluster/health", timeout=5)
            if r.status_code == 200:
                data = r.json()
                es_green = data.get("status") == "green"
    except Exception as e:
        logger.warning("Watchdog could not check ES health: %s", e)

    w = Watchdog(_registry)
    outcome = await w.run_and_notify(
        last_heartbeat=get_last_heartbeat(),
        es_green=es_green,
        send_telegram=True,
    )
    logger.info("Watchdog run: status=%s alerts=%d", outcome.get("status"), len(outcome.get("alerts", [])))


async def _run_reconciliation() -> None:
    """Run catalog reconciliation: age-out to FALLBACK_PENDING + Liferay monthly probe (weekly)."""
    global _registry
    if _paused:
        logger.info("Scheduler paused, skipping reconciliation")
        return
    if not is_job_enabled("reconciliation"):
        logger.info("Reconciliation disabled, skipping")
        return
    if _registry is None:
        logger.error("Registry not initialized, cannot run reconciliation")
        return
    run_id = await _registry.create_pipeline_run("reconciliation")
    try:
        stats = await run_reconciliation(_registry, run_id=run_id)
        await _registry.complete_pipeline_run(
            run_id,
            files_processed=stats.get("recovered_files", 0) + stats.get("aged_to_fallback", 0),
            files_succeeded=stats.get("recovered_files", 0),
            files_failed=len(stats.get("errors", [])),
        )
        logger.info("Reconciliation completed: %s", stats)
    except Exception as exc:
        logger.exception("Reconciliation failed: %s", exc)
        await _registry.complete_pipeline_run(run_id, 0, 0, 0, error_message=str(exc))


async def _run_full_cycle() -> dict[str, Any]:
    """Run the full pipeline sequentially as a single manual trigger."""
    summary: dict[str, Any] = {"phase": "full", "steps": [], "errors": []}
    for phase in PHASE_SEQUENCE:
        result = await _run_phase(phase, respect_job_enabled=False)
        summary["steps"].append({"phase": phase, "result": result})
        if "error" in result:
            summary["errors"].append({"phase": phase, "error": result["error"]})
            break
    return summary


async def _run_phase_manual(phase: str) -> dict[str, Any]:
    """Run a phase immediately, bypassing per-job auto-run disable state."""
    return await _run_phase(phase, respect_job_enabled=False)


async def _run_retry() -> None:
    """Retry failed files with retry_count < 3."""
    global _registry
    if _paused:
        logger.info("Scheduler paused, skipping retry")
        return
    if not is_job_enabled("retry"):
        logger.info("Retry disabled, skipping")
        return
    if _registry is None:
        logger.error("Registry not initialized, cannot run retry")
        return

    failed_statuses = [
        FileStatus.DOWNLOAD_FAILED,
        FileStatus.EXTRACT_FAILED,
        FileStatus.BM25_INDEX_FAILED,
        FileStatus.EMBEDDING_FAILED,
        FileStatus.VERIFY_FAILED,
    ]
    retried = 0
    for status in failed_statuses:
        files = await _registry.get_files_by_status(status, limit=100)
        for f in files:
            if f["retry_count"] < 3:
                try:
                    await _registry.retry_file(f["id"])
                    retried += 1
                except ValueError:
                    pass
    logger.info("Retry completed: %d files re-queued", retried)


MANUAL_TRIGGER_MAP.update(
    {
        "retry": _run_retry,
        "snapshot": _run_snapshot,
        "refresh_catalog_status": _run_refresh_catalog_status,
        "reconciliation": _run_reconciliation,
        "watchdog": _run_watchdog,
    }
)


def configure_scheduler() -> None:
    """Add all cron jobs to the scheduler."""
    # Pipeline phases
    scheduler.add_job(
        _run_phase,
        CronTrigger(hour=23, minute=0),
        args=["discovery"],
        id="discovery",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _run_phase,
        CronTrigger(hour=23, minute=30),
        args=["backfill_missing"],
        id="backfill_missing",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _run_phase,
        CronTrigger(hour=23, minute=40),
        args=["download"],
        id="download",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _run_phase,
        CronTrigger(hour=23, minute=50),
        args=["extract"],
        id="extract",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _run_phase,
        CronTrigger(hour=0, minute=0),
        args=["bm25"],
        id="bm25",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _run_phase,
        CronTrigger(hour=0, minute=30),
        args=["embed"],
        id="embed",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _run_phase,
        CronTrigger(hour=1, minute=0),
        args=["verify"],
        id="verify",
        replace_existing=True,
        max_instances=1,
    )

    # Retry failed files
    scheduler.add_job(
        _run_retry,
        CronTrigger(hour=6, minute=0),
        id="retry",
        replace_existing=True,
        max_instances=1,
    )

    # Daily ES snapshot to Tigris
    scheduler.add_job(
        _run_snapshot,
        CronTrigger(hour=2, minute=0),
        id="snapshot",
        replace_existing=True,
        max_instances=1,
    )

    # Daily refresh of month-level catalog_status (INLABS_WINDOW, FALLBACK_ELIGIBLE, CLOSED)
    scheduler.add_job(
        _run_refresh_catalog_status,
        CronTrigger(hour=3, minute=0),
        id="refresh_catalog_status",
        replace_existing=True,
        max_instances=1,
    )

    # Weekly catalog reconciliation (aged DOWNLOAD_FAILED → FALLBACK_PENDING; Liferay monthly probe)
    scheduler.add_job(
        _run_reconciliation,
        CronTrigger(day_of_week="tue", hour=4, minute=0),
        id="reconciliation",
        replace_existing=True,
        max_instances=1,
    )

    # Watchdog every 6 hours
    scheduler.add_job(
        _run_watchdog,
        CronTrigger(hour="0,6,12,18", minute=0),
        id="watchdog",
        replace_existing=True,
        max_instances=1,
    )

    logger.info("Scheduler configured with %d jobs", len(scheduler.get_jobs()))


def pause_scheduler() -> None:
    """Pause all scheduled jobs (they will skip on next trigger)."""
    global _paused
    _paused = True
    logger.info("Scheduler paused")


def resume_scheduler() -> None:
    """Resume all scheduled jobs."""
    global _paused
    _paused = False
    logger.info("Scheduler resumed")


async def persist_pause_state(paused: bool) -> None:
    """Write pause state to pipeline_config and pipeline_log. Call from API after pause_scheduler/resume_scheduler."""
    global _registry
    if _registry is None:
        return
    from datetime import datetime, timezone

    await _registry.set_config("scheduler_paused", "true" if paused else "false")
    if paused:
        await _registry.set_config("scheduler_paused_at", datetime.now(timezone.utc).isoformat())
    else:
        await _registry.set_config("scheduler_paused_at", "")
    event = "scheduler_paused" if paused else "scheduler_resumed"
    run_id = await _registry.create_pipeline_run(event)
    await _registry.add_log_entry(
        run_id,
        None,
        "INFO",
        f"Pipeline {event} (trigger=manual)",
    )
    await _registry.complete_pipeline_run(run_id, 0, 0, 0)


async def load_pause_state_from_registry() -> bool:
    """Read persisted pause state from pipeline_config. Call at startup."""
    global _paused, _registry
    if _registry is None:
        return _paused
    val = await _registry.get_config("scheduler_paused")
    _paused = (val or "").strip().lower() == "true"
    return _paused


async def load_job_state_from_registry() -> dict[str, bool]:
    """Load persisted per-job enable/disable state from pipeline_config."""
    global _registry
    if _registry is None:
        return dict(_job_enabled)
    for job_id in CONTROLLED_JOB_IDS:
        val = await _registry.get_config(_job_config_key(job_id))
        if val is not None:
            _job_enabled[job_id] = val.strip().lower() == "true"
    return {job_id: is_job_enabled(job_id) for job_id in CONTROLLED_JOB_IDS}


async def set_job_enabled(job_id: str, enabled: bool) -> dict[str, Any]:
    """Persist per-job auto-run state and emit an audit event."""
    global _registry
    if job_id not in CONTROLLED_JOB_IDS:
        raise ValueError(f"Unknown job_id: {job_id}")
    _job_enabled[job_id] = enabled
    if _registry is not None:
        await _registry.set_config(_job_config_key(job_id), "true" if enabled else "false")
        event = "scheduler_job_enabled" if enabled else "scheduler_job_disabled"
        run_id = await _registry.create_pipeline_run(event)
        await _registry.add_log_entry(
            run_id,
            None,
            "INFO",
            f"Scheduler job {job_id} {'enabled' if enabled else 'disabled'} (trigger=manual)",
        )
        await _registry.complete_pipeline_run(run_id, 0, 0, 0)
    return {"job_id": job_id, "enabled": enabled}


def get_scheduler_status() -> dict[str, Any]:
    """Return scheduler status including job details."""
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append(
            {
                "id": job.id,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                "enabled": is_job_enabled(job.id),
                "group": "phase" if job.id in PHASE_MAP else "maintenance",
                "schedule_text": str(job.trigger),
                "source_of_truth": SCHEDULER_SOURCE,
                "timezone": SCHEDULER_TIMEZONE,
            }
        )
    return {
        "running": scheduler.running,
        "paused": _paused,
        "source_of_truth": SCHEDULER_SOURCE,
        "timezone": SCHEDULER_TIMEZONE,
        "jobs": jobs,
    }


async def trigger_phase(phase: str) -> dict[str, Any]:
    """Trigger a pipeline phase immediately.

    Validates phase name against PHASE_MAP. Adds a one-shot job to the scheduler.
    """
    if phase == "full":
        scheduler.add_job(_run_full_cycle, id="trigger_full", replace_existing=True)
        return {"triggered": phase}

    if phase in PHASE_MAP:
        scheduler.add_job(_run_phase_manual, args=[phase], id=f"trigger_{phase}", replace_existing=True)
        return {"triggered": phase}

    if phase in MANUAL_TRIGGER_MAP:
        scheduler.add_job(MANUAL_TRIGGER_MAP[phase], id=f"trigger_{phase}", replace_existing=True)
        return {"triggered": phase}

    valid = [*PHASE_MAP.keys(), *MANUAL_TRIGGER_MAP.keys(), "full"]
    raise ValueError(f"Unknown phase: {phase}. Valid: {valid}")


def set_registry(registry: Registry) -> None:
    """Set the registry instance for scheduler use. Called during lifespan."""
    global _registry
    _registry = registry
