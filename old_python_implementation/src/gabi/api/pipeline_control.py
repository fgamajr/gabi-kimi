"""Pipeline Control API - Start/Stop/Restart pipeline phases.

Endpoints for controlling pipeline phases via dashboard.
"""

import logging
from datetime import datetime, timezone
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from gabi.auth.middleware import RequireAuth
from gabi.db import get_db_session
from gabi.types import PipelinePhase
from gabi.models.execution import ExecutionManifest
from gabi.models.source import SourceRegistry
from gabi.dependencies import get_redis
from gabi.schemas.pipeline import PipelineExecutionRequest
from gabi.services.pipeline_control_service import PipelineControlService
from gabi.worker import celery_app
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(tags=["pipeline-control"])


class PipelineControlRequest(BaseModel):
    """Request to control a pipeline phase."""
    source_id: str = Field(..., description="ID of the source to control")
    phase: Optional[PipelinePhase] = Field(None, description="Specific phase to control (None=all phases)")
    action: str = Field(..., description="Action: start, stop, restart", pattern=r"^(start|stop|restart)$")


class PipelineControlResponse(BaseModel):
    """Response for pipeline control request."""
    message: str
    source_id: str
    phase: Optional[PipelinePhase]
    action: str
    status: str
    timestamp: datetime


class PipelineStatusResponse(BaseModel):
    """Response for pipeline status."""
    source_id: str
    phase: Optional[PipelinePhase]
    status: str
    active_executions: int
    last_execution: Optional[datetime]
    next_scheduled: Optional[datetime]


class PipelineActionRequest(BaseModel):
    """Stable REST request model for start/stop/restart endpoints."""
    source_id: str = Field(..., description="ID of the source to control")
    phase: Optional[PipelinePhase] = Field(
        None, description="Specific phase to control (None=all phases)"
    )


async def _ensure_source_exists(source_id: str, db: AsyncSession) -> None:
    """Validate source existence before pipeline actions."""
    source = await db.get(SourceRegistry, source_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found")


@router.post("/control", response_model=PipelineControlResponse)
async def control_pipeline(
    request: PipelineControlRequest,
    db: AsyncSession = Depends(get_db_session),
    redis=Depends(get_redis),
    user: dict = Depends(RequireAuth(roles=["admin"])),
) -> PipelineControlResponse:
    """Control pipeline phases (start/stop/restart)."""
    logger.info(f"Pipeline control request: {request.action} for {request.source_id}:{request.phase}")

    # Validate source exists
    await _ensure_source_exists(request.source_id, db)

    service = PipelineControlService(redis, celery_app)

    try:
        if request.action == "start":
            action_id, run_id, task_id = await service.start(
                db,
                source_id=request.source_id,
                phase=request.phase,
                requested_by=user.get("sub"),
            )
            message = (
                f"Started pipeline for source {request.source_id} "
                f"(run: {run_id}, action: {action_id}, task: {task_id})"
            )
            status_value = "queued"

        elif request.action == "stop":
            action_id, task_ids = await service.stop(
                db,
                source_id=request.source_id,
                phase=request.phase,
                requested_by=user.get("sub"),
            )
            message = (
                f"Stop requested for {request.source_id} "
                f"(action: {action_id}, revoked_tasks: {len(task_ids)})"
            )
            status_value = "stopped"

        elif request.action == "restart":
            stop_action_id, start_action_id, run_id, task_id = await service.restart(
                db,
                source_id=request.source_id,
                phase=request.phase,
                requested_by=user.get("sub"),
            )
            message = (
                f"Restarted pipeline for {request.source_id} "
                f"(stop_action: {stop_action_id}, start_action: {start_action_id}, "
                f"run: {run_id}, task: {task_id})"
            )
            status_value = "restarted"

        else:
            raise HTTPException(status_code=400, detail=f"Invalid action: {request.action}")

        return PipelineControlResponse(
            message=message,
            source_id=request.source_id,
            phase=request.phase,
            action=request.action,
            status=status_value,
            timestamp=datetime.now(timezone.utc)
        )

    except Exception as e:
        logger.error(f"Pipeline control error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to {request.action} pipeline: {str(e)}")


@router.post("/start", response_model=PipelineControlResponse)
async def start_pipeline(
    request: PipelineActionRequest,
    db: AsyncSession = Depends(get_db_session),
    redis=Depends(get_redis),
    user: dict = Depends(RequireAuth(roles=["admin"])),
) -> PipelineControlResponse:
    """Stable REST endpoint to start pipeline/phase."""
    return await control_pipeline(
        request=PipelineControlRequest(
            source_id=request.source_id,
            phase=request.phase,
            action="start",
        ),
        db=db,
        redis=redis,
        user=user,
    )


@router.post("/stop", response_model=PipelineControlResponse)
async def stop_pipeline(
    request: PipelineActionRequest,
    db: AsyncSession = Depends(get_db_session),
    redis=Depends(get_redis),
    user: dict = Depends(RequireAuth(roles=["admin"])),
) -> PipelineControlResponse:
    """Stable REST endpoint to stop pipeline/phase."""
    return await control_pipeline(
        request=PipelineControlRequest(
            source_id=request.source_id,
            phase=request.phase,
            action="stop",
        ),
        db=db,
        redis=redis,
        user=user,
    )


@router.post("/restart", response_model=PipelineControlResponse)
async def restart_pipeline(
    request: PipelineActionRequest,
    db: AsyncSession = Depends(get_db_session),
    redis=Depends(get_redis),
    user: dict = Depends(RequireAuth(roles=["admin"])),
) -> PipelineControlResponse:
    """Stable REST endpoint to restart pipeline/phase."""
    return await control_pipeline(
        request=PipelineControlRequest(
            source_id=request.source_id,
            phase=request.phase,
            action="restart",
        ),
        db=db,
        redis=redis,
        user=user,
    )


@router.get("/status", response_model=PipelineStatusResponse)
async def get_pipeline_status(
    source_id: str,
    phase: Optional[PipelinePhase] = None,
    db: AsyncSession = Depends(get_db_session),
    redis=Depends(get_redis),
    user: dict = Depends(RequireAuth()),
) -> PipelineStatusResponse:
    """Get current status of pipeline phases."""
    logger.info(f"Getting pipeline status for {source_id}:{phase}")

    service = PipelineControlService(redis, celery_app)
    runtime = await service.runtime_status(source_id=source_id, phase=phase)
    active_count = 1 if runtime.get("is_running") == "true" else 0
    
    # Get last execution from DB
    last_exec = await db.execute(
        select(ExecutionManifest)
        .where(ExecutionManifest.source_id == source_id)
        .order_by(ExecutionManifest.started_at.desc())
        .limit(1)
    )
    last_execution_record = last_exec.scalar_one_or_none()

    last_execution = last_execution_record.started_at if last_execution_record else None

    # Calculate next scheduled time based on source config
    source = await db.get(SourceRegistry, source_id)
    next_scheduled = None
    if source and source.config_json:
        sync_freq = source.config_json.get("lifecycle", {}).get("sync", {}).get("frequency")
        if sync_freq and last_execution:
            if sync_freq == "daily":
                next_scheduled = last_execution + timedelta(days=1)
            elif sync_freq == "hourly":
                next_scheduled = last_execution + timedelta(hours=1)

    # Determine status
    if runtime:
        status = runtime.get("status", "running" if active_count > 0 else "idle")
    elif active_count > 0:
        status = "running"
    elif last_execution_record:
        status = last_execution_record.status.value if hasattr(last_execution_record.status, 'value') else str(last_execution_record.status)
    else:
        status = "idle"

    return PipelineStatusResponse(
        source_id=source_id,
        phase=phase,
        status=status,
        active_executions=active_count,
        last_execution=last_execution,
        next_scheduled=next_scheduled
    )


@router.post("/execute", response_model=PipelineControlResponse)
async def execute_pipeline_now(
    request: PipelineExecutionRequest,
    db: AsyncSession = Depends(get_db_session),
    redis=Depends(get_redis),
    user: dict = Depends(RequireAuth(roles=["admin"])),
) -> PipelineControlResponse:
    """Execute pipeline immediately with custom parameters."""
    logger.info(f"Immediate pipeline execution request for {request.source_id}")

    # Validate source exists
    await _ensure_source_exists(request.source_id, db)

    service = PipelineControlService(redis, celery_app)

    try:
        phase = request.phases[0] if request.phases else None
        action_id, run_id, task_id = await service.start(
            db,
            source_id=request.source_id,
            phase=phase,
            requested_by=user.get("sub"),
        )

        message = (
            f"Started immediate execution for source {request.source_id} "
            f"(action: {action_id}, run: {run_id}, task: {task_id})"
        )
        if request.phases:
            message += f" (phases: {', '.join([p.value for p in request.phases])})"
        if request.force_refresh:
            message += " (forced refresh)"
        if request.dry_run:
            message += " (dry run)"

        return PipelineControlResponse(
            message=message,
            source_id=request.source_id,
            phase=None,  # Applies to all phases in execution
            action="execute_now",
            status="started",
            timestamp=datetime.now(timezone.utc)
        )

    except Exception as e:
        logger.error(f"Pipeline execution error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to execute pipeline: {str(e)}")
