"""APScheduler cron job orchestration for the DOU ingestion pipeline.

Configures cron jobs for 5 pipeline phases + retry + daily ES snapshot.
Supports pause/resume and manual triggering of individual phases.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Coroutine

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.backend.worker.pipeline.discovery import run_discovery
from src.backend.worker.pipeline.downloader import run_download
from src.backend.worker.pipeline.extractor import run_extract
from src.backend.worker.pipeline.ingestor import run_ingest
from src.backend.worker.pipeline.verifier import run_verify
from src.backend.worker.registry import FileStatus, Registry
from src.backend.worker.snapshots import create_snapshot

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")

_paused: bool = False
_registry: Registry | None = None

PHASE_MAP: dict[str, Callable[..., Coroutine[Any, Any, dict[str, Any]]]] = {
    "discovery": run_discovery,
    "download": run_download,
    "extract": run_extract,
    "ingest": run_ingest,
    "verify": run_verify,
}


def _get_es_url() -> str:
    return os.environ.get("ES_URL", "http://es.internal:9200")


async def _run_phase(phase: str) -> dict[str, Any]:
    """Run a pipeline phase with registry tracking."""
    global _registry
    if _paused:
        logger.info("Scheduler paused, skipping phase: %s", phase)
        return {"skipped": True, "phase": phase}

    if _registry is None:
        logger.error("Registry not initialized, cannot run phase: %s", phase)
        return {"error": "registry not initialized"}

    run_id = await _registry.create_pipeline_run(phase)
    func = PHASE_MAP[phase]
    es_url = _get_es_url()

    try:
        # Each pipeline function has slightly different signatures.
        # discovery, verify, ingest take (registry, run_id, es_url, ...)
        # download, extract take (registry, run_id, ...)
        if phase in ("discovery", "verify"):
            stats = await func(_registry, run_id, es_url)
        elif phase == "ingest":
            stats = await func(_registry, run_id, es_url)
        else:
            stats = await func(_registry, run_id)

        await _registry.complete_pipeline_run(
            run_id,
            files_processed=stats.get("processed", 0),
            files_succeeded=stats.get("succeeded", 0),
            files_failed=stats.get("failed", 0),
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


async def _run_snapshot() -> None:
    """Run daily ES snapshot."""
    if _paused:
        logger.info("Scheduler paused, skipping snapshot")
        return
    es_url = _get_es_url()
    await create_snapshot(es_url)


async def _run_retry() -> None:
    """Retry failed files with retry_count < 3."""
    global _registry
    if _paused:
        logger.info("Scheduler paused, skipping retry")
        return
    if _registry is None:
        logger.error("Registry not initialized, cannot run retry")
        return

    failed_statuses = [
        FileStatus.DOWNLOAD_FAILED,
        FileStatus.EXTRACT_FAILED,
        FileStatus.INGEST_FAILED,
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


def configure_scheduler() -> None:
    """Add all cron jobs to the scheduler."""
    # Pipeline phases
    scheduler.add_job(
        _run_phase, CronTrigger(hour=23, minute=0),
        args=["discovery"], id="discovery", replace_existing=True, max_instances=1,
    )
    scheduler.add_job(
        _run_phase, CronTrigger(hour=23, minute=30),
        args=["download"], id="download", replace_existing=True, max_instances=1,
    )
    scheduler.add_job(
        _run_phase, CronTrigger(hour=23, minute=45),
        args=["extract"], id="extract", replace_existing=True, max_instances=1,
    )
    scheduler.add_job(
        _run_phase, CronTrigger(hour=0, minute=0),
        args=["ingest"], id="ingest", replace_existing=True, max_instances=1,
    )
    scheduler.add_job(
        _run_phase, CronTrigger(hour=1, minute=0),
        args=["verify"], id="verify", replace_existing=True, max_instances=1,
    )

    # Retry failed files
    scheduler.add_job(
        _run_retry, CronTrigger(hour=6, minute=0),
        id="retry", replace_existing=True, max_instances=1,
    )

    # Daily ES snapshot to Tigris
    scheduler.add_job(
        _run_snapshot, CronTrigger(hour=2, minute=0),
        id="snapshot", replace_existing=True, max_instances=1,
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


def get_scheduler_status() -> dict[str, Any]:
    """Return scheduler status including job details."""
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
        })
    return {
        "running": scheduler.running,
        "paused": _paused,
        "jobs": jobs,
    }


async def trigger_phase(phase: str) -> dict[str, Any]:
    """Trigger a pipeline phase immediately.

    Validates phase name against PHASE_MAP. Adds a one-shot job to the scheduler.
    """
    if phase not in PHASE_MAP:
        raise ValueError(f"Unknown phase: {phase}. Valid: {list(PHASE_MAP.keys())}")

    scheduler.add_job(_run_phase, args=[phase], id=f"trigger_{phase}", replace_existing=True)
    return {"triggered": phase}


def set_registry(registry: Registry) -> None:
    """Set the registry instance for scheduler use. Called during lifespan."""
    global _registry
    _registry = registry
