"""Internal API routes for the worker — registry and pipeline control.

Provides endpoints for registry status, pipeline runs, logs, trigger,
retry, pause/resume, and health monitoring.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from src.backend.worker.registry import Registry
from src.backend.worker.scheduler import (
    MANUAL_TRIGGER_MAP,
    PHASE_MAP,
    PHASE_SEQUENCE,
    get_scheduler_status,
    is_job_enabled,
    pause_scheduler,
    persist_pause_state,
    resume_scheduler,
    set_job_enabled,
    trigger_phase,
)

router = APIRouter()

# Set by main.py lifespan after registry init
_registry: Registry | None = None


def _get_registry() -> Registry:
    if _registry is None:
        raise HTTPException(status_code=503, detail="Registry not initialized")
    return _registry


# --- Health ---


@router.get("/health")
async def health() -> dict[str, Any]:
    """Health check with uptime and scheduler status."""
    from src.backend.worker.main import get_last_heartbeat, get_uptime_seconds

    reg = _get_registry()
    disk = await reg.get_disk_usage()
    sched = get_scheduler_status()

    return {
        "status": "ok",
        "uptime_seconds": round(get_uptime_seconds(), 1),
        "scheduler_running": sched["running"],
        "scheduler_paused": sched["paused"],
        "scheduler_jobs": sched["jobs"],
        "last_heartbeat": get_last_heartbeat(),
        "disk_usage": disk,
    }


# --- Registry ---


@router.get("/registry/status")
async def registry_status() -> dict[str, int]:
    """Return count of files by status."""
    reg = _get_registry()
    return await reg.get_status_counts()


@router.get("/registry/months")
async def registry_months(year: int | None = None) -> list[dict[str, Any]]:
    """Return month/file data, optionally filtered by year."""
    reg = _get_registry()
    return await reg.get_months(year)


@router.get("/registry/catalog-months")
async def registry_catalog_months(year: int | None = None) -> list[dict[str, Any]]:
    """Return catalog month-level state (coverage vs ingest) for dashboard."""
    reg = _get_registry()
    return await reg.get_catalog_months(year)


@router.get("/registry/stats")
async def registry_stats() -> dict[str, Any]:
    """Return dashboard-friendly summary statistics."""
    reg = _get_registry()
    return await reg.get_summary_stats()


@router.get("/registry/files/{file_id}")
async def registry_file(file_id: int) -> dict[str, Any]:
    """Return a single file record by ID."""
    reg = _get_registry()
    f = await reg.get_file(file_id)
    if f is None:
        raise HTTPException(status_code=404, detail=f"File {file_id} not found")
    return f


# --- Pipeline ---


@router.get("/pipeline/runs")
async def pipeline_runs(limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
    """Return recent pipeline runs."""
    reg = _get_registry()
    return await reg.get_pipeline_runs(limit)


@router.get("/pipeline/scheduler")
async def pipeline_scheduler() -> dict[str, Any]:
    """Return scheduler status, pause state, and next runs."""
    return get_scheduler_status()


@router.get("/pipeline/watchdog")
async def pipeline_watchdog() -> dict[str, Any]:
    """Return current watchdog evaluation (rules + alerts). Does not send Telegram."""
    from src.backend.worker.main import get_last_heartbeat
    from src.backend.worker.watchdog import Watchdog
    import httpx
    import os

    reg = _get_registry()
    es_green = True
    es_url = os.environ.get("ES_URL", "http://es.internal:9200")
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{es_url}/_cluster/health", timeout=5)
            if r.status_code == 200:
                data = r.json()
                es_green = data.get("status") == "green"
    except Exception:
        pass
    w = Watchdog(reg)
    return await w.evaluate(last_heartbeat=get_last_heartbeat(), es_green=es_green)


@router.get("/pipeline/logs")
async def pipeline_logs(
    run_id: str | None = None,
    file_id: int | None = None,
    level: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
) -> list[dict[str, Any]]:
    """Return filtered pipeline log entries."""
    reg = _get_registry()
    return await reg.get_logs(run_id=run_id, file_id=file_id, level=level, limit=limit)


@router.post("/pipeline/trigger/{phase}")
async def pipeline_trigger(phase: str) -> dict[str, str]:
    """Trigger a pipeline phase immediately."""
    valid_phases = [*PHASE_MAP.keys(), *MANUAL_TRIGGER_MAP.keys(), "full"]
    if phase not in valid_phases:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown phase: {phase}. Valid: {valid_phases}",
        )
    result = await trigger_phase(phase)
    return result


@router.post("/pipeline/retry/{file_id}")
async def pipeline_retry(file_id: int) -> dict[str, int]:
    """Retry a failed file — resets to QUEUED and increments retry_count."""
    reg = _get_registry()
    try:
        await reg.retry_file(file_id)
        return {"retried": file_id}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/pipeline/pause")
async def pipeline_pause() -> dict[str, bool]:
    """Pause the scheduler (jobs will skip on next trigger). Persists to SQLite and audit log."""
    pause_scheduler()
    await persist_pause_state(True)
    return {"paused": True}


@router.post("/pipeline/resume")
async def pipeline_resume() -> dict[str, bool]:
    """Resume the scheduler. Persists to SQLite and audit log."""
    resume_scheduler()
    await persist_pause_state(False)
    return {"paused": False}


@router.post("/pipeline/jobs/{job_id}/enable")
async def pipeline_job_enable(job_id: str) -> dict[str, Any]:
    """Enable automatic execution for one scheduler job."""
    try:
        return await set_job_enabled(job_id, True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/pipeline/jobs/{job_id}/disable")
async def pipeline_job_disable(job_id: str) -> dict[str, Any]:
    """Disable automatic execution for one scheduler job."""
    try:
        return await set_job_enabled(job_id, False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- Plant Status (SCADA Dashboard) ---

# Maps each pipeline stage to the file statuses representing its input queue
PENDING_GROUPS: dict[str, list[str]] = {
    "discovery": ["DISCOVERED"],
    "backfill_missing": [],
    "download": ["QUEUED", "DOWNLOADING"],
    "extract": ["DOWNLOADED", "EXTRACTING"],
    "bm25": ["EXTRACTED", "BM25_INDEXING"],
    "embed": ["BM25_INDEXED", "EMBEDDING"],
    "verify": ["BM25_INDEXED", "VERIFYING"],
}

# Maps each pipeline stage to its failure statuses
FAILURE_GROUPS: dict[str, list[str]] = {
    "discovery": [],
    "backfill_missing": [],
    "download": ["DOWNLOAD_FAILED"],
    "extract": ["EXTRACT_FAILED"],
    "bm25": ["BM25_INDEX_FAILED"],
    "embed": ["EMBEDDING_FAILED"],
    "verify": ["VERIFY_FAILED"],
}


def _derive_stage_state(
    phase_id: str,
    job: dict[str, Any] | None,
    failed_count: int,
    master_paused: bool,
) -> str:
    """Derive a stage's display state from job config and metrics."""
    if not is_job_enabled(phase_id):
        return "PAUSED"
    if job and not job.get("enabled", True):
        return "PAUSED"
    if master_paused:
        return "PAUSED"
    if failed_count > 0:
        return "ERROR"
    if not job:
        return "IDLE"
    return "AUTO"


@router.get("/registry/plant-status")
async def plant_status() -> dict[str, Any]:
    """Aggregated dashboard status for the SCADA industrial control panel.

    Returns stages, storage, totals, uptime, and heartbeat in a single response.
    """
    from src.backend.worker.main import get_last_heartbeat, get_uptime_seconds

    reg = _get_registry()
    status_counts = await reg.get_status_counts()
    disk = await reg.get_disk_usage()
    runs = await reg.get_pipeline_runs(20)
    sched = get_scheduler_status()

    master_paused = sched["paused"]

    # Index scheduler jobs by id for quick lookup
    jobs_by_id: dict[str, dict[str, Any]] = {}
    for job in sched["jobs"]:
        jobs_by_id[job["id"]] = job

    # Index latest run per phase
    latest_run_by_phase: dict[str, dict[str, Any]] = {}
    for run in runs:
        phase = run.get("phase", "")
        if phase not in latest_run_by_phase:
            latest_run_by_phase[phase] = run

    # Build stages array
    stages: list[dict[str, Any]] = []
    for phase_id in PHASE_SEQUENCE:
        job = jobs_by_id.get(phase_id)
        pending_statuses = PENDING_GROUPS.get(phase_id, [])
        failure_statuses = FAILURE_GROUPS.get(phase_id, [])

        queue_depth = sum(status_counts.get(s, 0) for s in pending_statuses)
        failed_count = sum(status_counts.get(s, 0) for s in failure_statuses)

        latest_run = latest_run_by_phase.get(phase_id)

        # Compute throughput from latest run
        throughput: int | None = None
        if latest_run:
            throughput = latest_run.get("files_succeeded", 0)

        state = _derive_stage_state(phase_id, job, failed_count, master_paused)

        stages.append({
            "id": phase_id,
            "state": state,
            "queue_depth": queue_depth,
            "failed_count": failed_count,
            "throughput": throughput,
            "last_run": latest_run,
            "next_run": job.get("next_run_time") if job else None,
            "enabled": is_job_enabled(phase_id),
        })

    # Compute totals
    total_files = sum(status_counts.values())
    verified = status_counts.get("VERIFIED", 0)
    failed = sum(
        status_counts.get(s, 0)
        for s in [
            "DOWNLOAD_FAILED", "EXTRACT_FAILED", "BM25_INDEX_FAILED",
            "EMBEDDING_FAILED", "VERIFY_FAILED",
        ]
    )
    in_transit = total_files - verified - failed

    return {
        "stages": stages,
        "master_paused": master_paused,
        "storage": {
            "sqlite_bytes": disk.get("db_size_bytes", 0),
            "disk_free_bytes": disk.get("free_bytes", 0),
            "disk_total_bytes": disk.get("total_bytes", 0),
        },
        "totals": {
            "total_files": total_files,
            "verified": verified,
            "failed": failed,
            "in_transit": in_transit,
        },
        "uptime_seconds": round(get_uptime_seconds(), 1),
        "last_heartbeat": get_last_heartbeat(),
    }


# --- Stage Control ---


@router.post("/pipeline/stage/{name}/pause")
async def stage_pause(name: str) -> dict[str, Any]:
    """Pause a single pipeline stage (disable its scheduled job)."""
    try:
        return await set_job_enabled(name, False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/pipeline/stage/{name}/resume")
async def stage_resume(name: str) -> dict[str, Any]:
    """Resume a single pipeline stage (enable its scheduled job)."""
    try:
        return await set_job_enabled(name, True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/pipeline/stage/{name}/trigger")
async def stage_trigger(name: str) -> dict[str, str]:
    """Trigger a single pipeline stage immediately."""
    valid_phases = [*PHASE_MAP.keys(), *MANUAL_TRIGGER_MAP.keys(), "full"]
    if name not in valid_phases:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown stage: {name}. Valid: {valid_phases}",
        )
    return await trigger_phase(name)


@router.post("/pipeline/pause-all")
async def pipeline_pause_all() -> dict[str, bool]:
    """Pause all pipeline stages (master pause)."""
    pause_scheduler()
    await persist_pause_state(True)
    return {"paused": True}


@router.post("/pipeline/resume-all")
async def pipeline_resume_all() -> dict[str, bool]:
    """Resume all pipeline stages (master resume)."""
    resume_scheduler()
    await persist_pause_state(False)
    return {"paused": False}
