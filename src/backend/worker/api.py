"""Internal API routes for the worker — registry and pipeline control.

Provides endpoints for registry status, pipeline runs, logs, trigger,
retry, pause/resume, and health monitoring.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from src.backend.worker.registry import Registry
from src.backend.worker.scheduler import (
    PHASE_MAP,
    get_scheduler_status,
    pause_scheduler,
    persist_pause_state,
    resume_scheduler,
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
    if phase not in PHASE_MAP and phase != "full":
        raise HTTPException(
            status_code=400,
            detail=f"Unknown phase: {phase}. Valid: {[*PHASE_MAP.keys(), 'full']}",
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
