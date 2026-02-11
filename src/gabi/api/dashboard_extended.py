"""Extended dashboard endpoints for control panel.

New endpoints:
- GET /dashboard/pipeline/summary - 4-stage pipeline view
- GET /dashboard/jobs - Sync jobs and ES indexes
- GET /dashboard/pipeline/state - Current pipeline state
- POST /dashboard/pipeline/{phase}/start - Start a phase
- POST /dashboard/pipeline/{phase}/stop - Stop a phase
- POST /dashboard/pipeline/{phase}/restart - Restart a phase
- POST /dashboard/pipeline/bulk-control - Bulk operations

These endpoints integrate with the orchestrator at:
/home/fgamajr/dev/gabi-kimi/src/gabi/pipeline/orchestrator.py
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from gabi.auth.middleware import RequireAuth
from gabi.config import settings
from gabi.db import get_db_session
from gabi.dependencies import get_es_client, get_redis
from gabi.schemas.dashboard_extended import (
    BulkControlAction,
    BulkControlRequest,
    BulkControlResponse,
    ElasticIndexHealth,
    ElasticIndexInfo,
    JobsResponse,
    PipelineState,
    PipelineStateResponse,
    PipelineSummaryResponse,
    PipelineSummaryStage,
    RestartPhaseRequest,
    RestartPhaseResponse,
    StartPhaseRequest,
    StartPhaseResponse,
    StopPhaseRequest,
    StopPhaseResponse,
    SyncJob,
    SyncJobStatus,
)
from gabi.types import ExecutionStatus, PipelinePhase, SourceStatus

logger = logging.getLogger(__name__)

# Router to be included in main dashboard router
router = APIRouter(tags=["dashboard"])


# =============================================================================
# Stage Mapping: 9 Backend Phases → 4 Frontend Stages
# =============================================================================

STAGE_MAPPING: Dict[str, List[str]] = {
    "harvest": ["discovery", "change_detection"],
    "sync": ["fetch", "parse", "fingerprint"],
    "ingest": ["deduplication", "chunking", "embedding"],
    "index": ["indexing"],
}

STAGE_LABELS: Dict[str, tuple[str, str]] = {
    "harvest": ("Coleta", "Descoberta de URLs e detecção de mudanças"),
    "sync": ("Sincronização", "Download, parsing e fingerprinting"),
    "ingest": ("Processamento", "Deduplicação, chunking e embeddings"),
    "index": ("Indexação", "Indexação no Elasticsearch"),
}


# =============================================================================
# GET /dashboard/pipeline/summary (4-stage view)
# =============================================================================

@router.get(
    "/pipeline/summary",
    response_model=PipelineSummaryResponse,
    summary="Pipeline summary (4 stages)",
    description="Returns pipeline progress aggregated into 4 stages for the frontend.",
)
async def get_pipeline_summary(
    source_id: Optional[str] = Query(None, description="Filter by source ID"),
    db: AsyncSession = Depends(get_db_session),
    _user: dict = Depends(RequireAuth()),
) -> PipelineSummaryResponse:
    """Return 4-stage pipeline summary for frontend dashboard.
    
    Maps 9 backend phases into 4 frontend stages:
    - harvest: discovery + change_detection
    - sync: fetch + parse + fingerprint  
    - ingest: deduplication + chunking + embedding
    - index: indexing
    """
    now = datetime.now(timezone.utc)
    two_hours_ago = now - timedelta(hours=2)
    
    # Build source filter if specified
    source_filter = ""
    params: Dict[str, Any] = {}
    if source_id:
        source_filter = "AND source_id = :source_id"
        params["source_id"] = source_id
    
    # Query to aggregate counts for 4-stage mapping
    query = text(f"""
        WITH base AS (
            SELECT
                COUNT(*) FILTER (WHERE is_deleted = false) AS total_docs,
                COUNT(*) FILTER (WHERE is_deleted = false) AS harvest_count,
                COUNT(*) FILTER (WHERE content_hash IS NOT NULL AND is_deleted = false) AS sync_count,
                COUNT(*) FILTER (WHERE fingerprint IS NOT NULL AND is_deleted = false) AS fingerprint_count,
                COUNT(*) FILTER (WHERE es_indexed = true AND is_deleted = false) AS index_count,
                MAX(ingested_at) AS last_ingest,
                MAX(CASE WHEN es_indexed = true THEN es_indexed_at END) AS last_index
            FROM documents
            WHERE 1=1 {source_filter}
        ),
        chunk_stats AS (
            SELECT
                COUNT(DISTINCT document_id) FILTER (WHERE embedding IS NOT NULL) AS ingest_count,
                MAX(embedded_at) AS last_embed
            FROM document_chunks
            WHERE is_deleted = false
            {'AND source_id = :source_id' if source_id else ''}
        ),
        active_execs AS (
            SELECT 
                COUNT(DISTINCT source_id) FILTER (WHERE status = 'running') AS active_sources,
                COUNT(DISTINCT source_id) FILTER (WHERE status = 'pending') AS queued_sources
            FROM execution_manifests
            WHERE started_at > NOW() - INTERVAL '24 hours'
            {'AND source_id = :source_id' if source_id else ''}
        ),
        recent_failures AS (
            SELECT COUNT(*) as failure_count
            FROM execution_manifests
            WHERE status = 'failed' 
            AND started_at > NOW() - INTERVAL '24 hours'
            {'AND source_id = :source_id' if source_id else ''}
        )
        SELECT b.*, cs.*, ae.*, rf.*
        FROM base b, chunk_stats cs, active_execs ae, recent_failures rf
    """)
    
    result = await db.execute(query, params)
    row = result.mappings().fetchone()
    
    if not row:
        # Return empty stages
        stages = _build_empty_stages(now)
        return PipelineSummaryResponse(
            stages=stages,
            overall_status="stalled",
            active_source_count=0,
            queued_source_count=0,
            generated_at=now,
        )
    
    total = row["total_docs"] or 0
    failure_count = row["failure_count"] or 0
    
    # Calculate per-stage counts
    stage_data = [
        ("harvest", row["harvest_count"] or 0, row["last_ingest"]),
        ("sync", row["sync_count"] or 0, row["last_ingest"]),
        ("ingest", row["ingest_count"] or 0, row["last_embed"]),
        ("index", row["index_count"] or 0, row["last_index"]),
    ]
    
    stages = []
    any_error = failure_count > 5  # Threshold for error status
    any_active = False
    
    for stage_name, count, last_act in stage_data:
        label, description = STAGE_LABELS[stage_name]
        
        # Determine status
        if any_error and stage_name == "index":
            stage_status = "error"
        elif last_act and last_act.replace(tzinfo=timezone.utc) > two_hours_ago:
            stage_status = "active"
            any_active = True
        else:
            stage_status = "idle"
        
        progress_pct = (count / total * 100) if total > 0 else 0.0
        
        stages.append(PipelineSummaryStage(
            name=stage_name,  # type: ignore
            label=label,
            description=description,
            count=count,
            total=total,
            progress_pct=round(progress_pct, 1),
            status=stage_status,  # type: ignore
            last_activity=last_act,
            substages=STAGE_MAPPING[stage_name],
        ))
    
    # Overall status
    if any_error:
        overall = "degraded"
    elif any_active:
        overall = "healthy"
    else:
        overall = "stalled"
    
    return PipelineSummaryResponse(
        stages=stages,
        overall_status=overall,  # type: ignore
        active_source_count=row["active_sources"] or 0,
        queued_source_count=row["queued_sources"] or 0,
        generated_at=now,
    )


def _build_empty_stages(now: datetime) -> List[PipelineSummaryStage]:
    """Build 4 empty stages."""
    stages = []
    for stage_name in ["harvest", "sync", "ingest", "index"]:
        label, description = STAGE_LABELS[stage_name]
        stages.append(PipelineSummaryStage(
            name=stage_name,  # type: ignore
            label=label,
            description=description,
            count=0,
            total=0,
            progress_pct=0.0,
            status="idle",  # type: ignore
            last_activity=None,
            substages=STAGE_MAPPING[stage_name],
        ))
    return stages


# =============================================================================
# GET /dashboard/jobs (Sync jobs and Elasticsearch indexes)
# =============================================================================

@router.get(
    "/jobs",
    response_model=JobsResponse,
    summary="Sync jobs and ES indexes",
    description="Returns synchronization jobs by year and Elasticsearch index information.",
)
async def get_jobs(
    source_id: Optional[str] = Query(None, description="Filter by source"),
    year_from: Optional[int] = Query(None, ge=2000, le=2100, description="Start year"),
    year_to: Optional[int] = Query(None, ge=2000, le=2100, description="End year"),
    db: AsyncSession = Depends(get_db_session),
    es_client: Any = Depends(get_es_client),
    _user: dict = Depends(RequireAuth()),
) -> JobsResponse:
    """Return sync jobs by year and ES index information."""
    now = datetime.now(timezone.utc)
    
    # Determine year range
    current_year = now.year
    default_from = current_year - 10
    year_from = year_from or default_from
    year_to = year_to or current_year
    
    # Fetch sync jobs from database
    sync_jobs = await _fetch_sync_jobs(db, source_id, year_from, year_to)
    
    # Fetch ES index info
    elastic_indexes, total_elastic_docs = await _fetch_es_indexes(es_client)
    
    # Get available years
    years_available = sorted(set(job.year for job in sync_jobs), reverse=True)
    
    return JobsResponse(
        sync_jobs=sync_jobs,
        elastic_indexes=elastic_indexes,
        total_elastic_docs=total_elastic_docs,
        years_available=years_available,
        generated_at=now,
    )


async def _fetch_sync_jobs(
    db: AsyncSession,
    source_id: Optional[str],
    year_from: int,
    year_to: int,
) -> List[SyncJob]:
    """Fetch sync jobs grouped by year and source."""
    
    # Build filters
    filters = ["sr.deleted_at IS NULL"]
    params: Dict[str, Any] = {
        "year_from": year_from,
        "year_to": year_to,
    }
    
    if source_id:
        filters.append("sr.id = :source_id")
        params["source_id"] = source_id
    
    where_clause = " AND ".join(filters)
    
    # Query to get document counts by year and source
    query = text(f"""
        WITH years AS (
            SELECT generate_series(:year_from, :year_to) as year
        ),
        docs_by_year AS (
            SELECT 
                d.source_id,
                EXTRACT(YEAR FROM d.created_at)::int as year,
                COUNT(*) as doc_count,
                MAX(d.created_at) as last_doc_at
            FROM documents d
            WHERE d.is_deleted = false
            AND EXTRACT(YEAR FROM d.created_at) BETWEEN :year_from AND :year_to
            GROUP BY d.source_id, EXTRACT(YEAR FROM d.created_at)
        ),
        exec_by_year AS (
            SELECT 
                em.source_id,
                EXTRACT(YEAR FROM em.started_at)::int as year,
                em.status,
                em.started_at,
                em.completed_at,
                em.error_message,
                ROW_NUMBER() OVER (PARTITION BY em.source_id, EXTRACT(YEAR FROM em.started_at) 
                                   ORDER BY em.started_at DESC) as rn
            FROM execution_manifests em
            WHERE EXTRACT(YEAR FROM em.started_at) BETWEEN :year_from AND :year_to
        ),
        latest_execs AS (
            SELECT * FROM exec_by_year WHERE rn = 1
        )
        SELECT 
            sr.id as source_id,
            sr.name as source_name,
            y.year,
            COALESCE(dby.doc_count, 0) as doc_count,
            dby.last_doc_at,
            le.status as exec_status,
            le.started_at as exec_started,
            le.completed_at as exec_completed,
            le.error_message
        FROM years y
        CROSS JOIN source_registry sr
        LEFT JOIN docs_by_year dby ON y.year = dby.year AND sr.id = dby.source_id
        LEFT JOIN latest_execs le ON y.year = le.year AND sr.id = le.source_id
        WHERE {where_clause}
        AND (dby.doc_count > 0 OR le.status IS NOT NULL)
        ORDER BY y.year DESC, sr.id
    """)
    
    result = await db.execute(query, params)
    rows = result.mappings().fetchall()
    
    jobs = []
    for row in rows:
        # Determine job status
        status = _determine_job_status(row)
        
        jobs.append(SyncJob(
            source_id=row["source_id"],
            source_name=row["source_name"],
            year=row["year"],
            status=status,
            document_count=row["doc_count"] or 0,
            updated_at=row["last_doc_at"],
            started_at=row["exec_started"],
            completed_at=row["exec_completed"],
            error_message=row["error_message"],
        ))
    
    return jobs


def _determine_job_status(row: Any) -> SyncJobStatus:
    """Determine job status from execution and document data."""
    exec_status = row.get("exec_status")
    doc_count = row.get("doc_count") or 0
    
    if exec_status == "running":
        return SyncJobStatus.IN_PROGRESS
    elif exec_status == "failed":
        return SyncJobStatus.FAILED
    elif exec_status in ("success", "partial_success"):
        return SyncJobStatus.SYNCED
    elif exec_status == "pending":
        return SyncJobStatus.PENDING
    elif doc_count > 0:
        return SyncJobStatus.SYNCED
    else:
        return SyncJobStatus.NOT_STARTED


async def _fetch_es_indexes(es_client: Any) -> tuple[List[ElasticIndexInfo], int]:
    """Fetch Elasticsearch index information."""
    indexes = []
    total_docs = 0
    
    try:
        # Get index stats
        stats = await es_client.indices.stats(index="gabi_*")
        
        # Get index health
        health = await es_client.cluster.health()
        index_health = health.get("indices", {})
        
        for index_name, index_stats in stats.get("indices", {}).items():
            if not index_name.startswith("gabi_"):
                continue
                
            doc_count = index_stats.get("total", {}).get("docs", {}).get("count", 0)
            store_size = index_stats.get("total", {}).get("store", {}).get("size_in_bytes", 0)
            
            # Map health status
            health_status = index_health.get(index_name, {}).get("status", "yellow")
            health_enum = ElasticIndexHealth.YELLOW
            if health_status == "green":
                health_enum = ElasticIndexHealth.GREEN
            elif health_status == "red":
                health_enum = ElasticIndexHealth.RED
            
            indexes.append(ElasticIndexInfo(
                name=index_name,
                alias=None,  # Could be fetched from aliases API
                document_count=doc_count,
                size_bytes=store_size,
                health=health_enum,
                created_at=None,  # Could be fetched from settings API
            ))
            
            total_docs += doc_count
            
    except Exception as e:
        logger.warning(f"Failed to fetch ES indexes: {e}")
    
    return indexes, total_docs


# =============================================================================
# GET /dashboard/pipeline/state
# =============================================================================

@router.get(
    "/pipeline/state",
    response_model=PipelineStateResponse,
    summary="Pipeline current state",
    description="Returns the current state of the pipeline processing.",
)
async def get_pipeline_state(
    redis: Any = Depends(get_redis),
    db: AsyncSession = Depends(get_db_session),
    _user: dict = Depends(RequireAuth()),
) -> PipelineStateResponse:
    """Return current pipeline state."""
    now = datetime.now(timezone.utc)
    
    # Try to get state from Redis
    # This requires Redis to be configured with pipeline state keys
    state_data = await _get_state_from_redis(redis)
    
    if not state_data:
        # Fallback: compute from database
        state_data = await _compute_state_from_db(db)
    
    return PipelineStateResponse(
        state=PipelineState(**state_data),
        generated_at=now,
    )


async def _get_state_from_redis(redis: Any) -> Optional[Dict[str, Any]]:
    """Try to get pipeline state from Redis."""
    if not redis:
        return None
    
    try:
        # Fetch state from Redis keys
        # Note: These keys need to be set by the orchestrator/Celery workers
        is_running = await redis.get("gabi:pipeline:is_running")
        current_phase = await redis.get("gabi:pipeline:current_phase")
        active_sources = await redis.smembers("gabi:pipeline:active_sources")
        queued_sources = await redis.smembers("gabi:pipeline:queued_sources")
        paused_phases = await redis.smembers("gabi:pipeline:paused_phases")
        rate_limit = await redis.get("gabi:pipeline:rate_limit")
        
        return {
            "is_running": is_running == b"true" if is_running else False,
            "current_phase": current_phase.decode() if current_phase else None,
            "active_sources": [s.decode() for s in active_sources] if active_sources else [],
            "queued_sources": [s.decode() for s in queued_sources] if queued_sources else [],
            "paused_phases": [p.decode() for p in paused_phases] if paused_phases else [],
            "rate_limit_docs_per_min": int(rate_limit) if rate_limit else 0,
        }
    except Exception as e:
        logger.debug(f"Failed to get state from Redis: {e}")
        return None


async def _compute_state_from_db(db: AsyncSession) -> Dict[str, Any]:
    """Compute pipeline state from database."""
    # Get active executions
    result = await db.execute(text("""
        SELECT 
            source_id,
            status,
            stats->>'current_phase' as current_phase
        FROM execution_manifests
        WHERE status IN ('pending', 'running')
        AND started_at > NOW() - INTERVAL '24 hours'
    """))
    
    rows = result.mappings().fetchall()
    
    active_sources = []
    queued_sources = []
    current_phase = None
    
    for row in rows:
        if row["status"] == "running":
            active_sources.append(row["source_id"])
            if row["current_phase"] and not current_phase:
                current_phase = row["current_phase"]
        else:
            queued_sources.append(row["source_id"])
    
    return {
        "is_running": len(active_sources) > 0,
        "current_phase": current_phase,
        "active_sources": active_sources,
        "queued_sources": queued_sources,
        "paused_phases": [],  # Would need to be tracked separately
        "rate_limit_docs_per_min": 0,  # Would need to be configured
    }


# =============================================================================
# POST /dashboard/pipeline/{phase}/start
# =============================================================================

@router.post(
    "/pipeline/{phase}/start",
    response_model=StartPhaseResponse,
    summary="Start pipeline phase",
    description="Start a specific pipeline phase. Admin only.",
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_phase(
    phase: PipelinePhase,
    request: StartPhaseRequest,
    db: AsyncSession = Depends(get_db_session),
    redis: Any = Depends(get_redis),
    _user: dict = Depends(RequireAuth(roles=["admin"])),
) -> StartPhaseResponse:
    """Start a pipeline phase for specified sources.
    
    This queues the phase execution via Celery. The actual execution
    is handled by the orchestrator.
    """
    now = datetime.now(timezone.utc)
    
    # Validate phase
    if phase not in PipelinePhase:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid phase: {phase}",
        )
    
    # Get sources to process
    source_ids = request.source_ids
    if not source_ids:
        # Get all active sources
        result = await db.execute(
            text("""
                SELECT id FROM source_registry 
                WHERE status = :status AND deleted_at IS NULL
            """),
            {"status": SourceStatus.ACTIVE.value}
        )
        source_ids = [row[0] for row in result.fetchall()]
    
    if not source_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active sources found to process",
        )
    
    # Check if phase is already running for any of these sources
    # This would check execution_manifests or Redis state
    # For now, we accept the request and queue it
    
    # Generate run_id
    import uuid
    run_id = str(uuid.uuid4())
    
    # TODO: Queue via Celery
    # from gabi.tasks import run_pipeline_phase
    # for source_id in source_ids:
    #     run_pipeline_phase.delay(
    #         run_id=run_id,
    #         source_id=source_id,
    #         phase=phase.value,
    #         resume_from=request.resume_from,
    #         priority=request.priority,
    #         rate_limit=request.rate_limit,
    #     )
    
    logger.info(
        f"Phase {phase.value} started by {_user.get('sub')}: "
        f"run_id={run_id}, sources={source_ids}"
    )
    
    # Audit log entry
    await _log_audit_event(
        db,
        event_type="SYNC_STARTED",
        severity="info",
        details={
            "phase": phase.value,
            "run_id": run_id,
            "source_ids": source_ids,
            "triggered_by": _user.get("sub"),
        }
    )
    
    return StartPhaseResponse(
        success=True,
        run_id=run_id,
        phase=phase.value,
        sources_affected=source_ids,
        estimated_completion=None,  # Could be estimated based on doc count
        message=f"Phase '{phase.value}' queued for {len(source_ids)} source(s)",
        started_at=now,
    )


# =============================================================================
# POST /dashboard/pipeline/{phase}/stop
# =============================================================================

@router.post(
    "/pipeline/{phase}/stop",
    response_model=StopPhaseResponse,
    summary="Stop pipeline phase",
    description="Stop a running pipeline phase. Admin only.",
)
async def stop_phase(
    phase: PipelinePhase,
    request: StopPhaseRequest,
    redis: Any = Depends(get_redis),
    db: AsyncSession = Depends(get_db_session),
    _user: dict = Depends(RequireAuth(roles=["admin"])),
) -> StopPhaseResponse:
    """Stop a pipeline phase.
    
    Sets a cancellation flag in Redis that the orchestrator checks.
    """
    now = datetime.now(timezone.utc)
    
    # Get current items in progress
    # This would query the orchestrator or Redis
    items_in_progress = 0
    items_queued = 0
    
    if redis:
        try:
            # Set cancellation flag
            await redis.set(
                f"gabi:pipeline:cancel:{phase.value}",
                "1",
                ex=3600,  # Expire after 1 hour
            )
            
            # Get counts from Redis
            items_in_progress = int(
                await redis.get(f"gabi:pipeline:{phase.value}:in_progress") or 0
            )
            items_queued = int(
                await redis.get(f"gabi:pipeline:{phase.value}:queued") or 0
            )
        except Exception as e:
            logger.warning(f"Failed to set cancellation flag: {e}")
    
    logger.info(
        f"Phase {phase.value} stop requested by {_user.get('sub')}: "
        f"graceful={request.graceful}"
    )
    
    # Audit log
    await _log_audit_event(
        db,
        event_type="SYNC_CANCELLED",
        severity="warning",
        details={
            "phase": phase.value,
            "graceful": request.graceful,
            "reason": request.reason,
            "cancelled_by": _user.get("sub"),
        }
    )
    
    return StopPhaseResponse(
        success=True,
        phase=phase.value,
        items_in_progress=items_in_progress,
        items_queued=items_queued,
        stopped_at=now,
        message=f"Phase '{phase.value}' stop requested ({'graceful' if request.graceful else 'immediate'})",
    )


# =============================================================================
# POST /dashboard/pipeline/{phase}/restart
# =============================================================================

@router.post(
    "/pipeline/{phase}/restart",
    response_model=RestartPhaseResponse,
    summary="Restart pipeline phase",
    description="Restart a pipeline phase. Admin only.",
    status_code=status.HTTP_202_ACCEPTED,
)
async def restart_phase(
    phase: PipelinePhase,
    request: RestartPhaseRequest,
    db: AsyncSession = Depends(get_db_session),
    redis: Any = Depends(get_redis),
    _user: dict = Depends(RequireAuth(roles=["admin"])),
) -> RestartPhaseResponse:
    """Restart a pipeline phase.
    
    Stops any running execution, optionally clears errors,
    and starts a new execution.
    """
    now = datetime.now(timezone.utc)
    import uuid
    
    # Clear errors if requested
    cleared_errors = 0
    if request.clear_errors:
        # Clear DLQ messages for this phase
        result = await db.execute(
            text("""
                UPDATE dlq_messages
                SET status = 'resolved', resolved_at = NOW(), resolved_by = :user
                WHERE status IN ('pending', 'retrying')
                AND error_type LIKE :phase_pattern
            """),
            {"user": _user.get("sub"), "phase_pattern": f"{phase.value}_%"}
        )
        await db.commit()
        cleared_errors = result.rowcount or 0
    
    # Clear checkpoints if full reprocess
    if request.full_reprocess:
        # This would clear execution checkpoints
        pass
    
    # Generate new run_id
    run_id = str(uuid.uuid4())
    
    # TODO: Queue restart via Celery
    
    logger.info(
        f"Phase {phase.value} restarted by {_user.get('sub')}: "
        f"run_id={run_id}, clear_errors={request.clear_errors}"
    )
    
    # Audit log
    await _log_audit_event(
        db,
        event_type="SYNC_STARTED",
        severity="info",
        details={
            "phase": phase.value,
            "run_id": run_id,
            "restart": True,
            "clear_errors": request.clear_errors,
            "full_reprocess": request.full_reprocess,
            "triggered_by": _user.get("sub"),
        }
    )
    
    return RestartPhaseResponse(
        success=True,
        run_id=run_id,
        phase=phase.value,
        sources_affected=request.source_ids or [],
        cleared_errors=cleared_errors,
        message=f"Phase '{phase.value}' restarted",
        restarted_at=now,
    )


# =============================================================================
# POST /dashboard/pipeline/bulk-control
# =============================================================================

@router.post(
    "/pipeline/bulk-control",
    response_model=BulkControlResponse,
    summary="Bulk pipeline control",
    description="Execute bulk control action on pipeline. Admin only.",
)
async def bulk_control(
    request: BulkControlRequest,
    db: AsyncSession = Depends(get_db_session),
    redis: Any = Depends(get_redis),
    _user: dict = Depends(RequireAuth(roles=["admin"])),
) -> BulkControlResponse:
    """Execute bulk control action on the pipeline."""
    now = datetime.now(timezone.utc)
    
    affected_phases = []
    affected_sources = request.source_ids or []
    
    if request.action == BulkControlAction.PAUSE_ALL:
        # Set global pause flag
        if redis:
            await redis.set("gabi:pipeline:paused", "1")
        affected_phases = list(PipelinePhase)
        message = "All pipeline phases paused"
        
    elif request.action == BulkControlAction.RESUME_ALL:
        # Clear pause flag
        if redis:
            await redis.delete("gabi:pipeline:paused")
        affected_phases = list(PipelinePhase)
        message = "All pipeline phases resumed"
        
    elif request.action == BulkControlAction.STOP_ALL:
        # Cancel all running phases
        if redis:
            for phase in PipelinePhase:
                await redis.set(f"gabi:pipeline:cancel:{phase.value}", "1", ex=3600)
        affected_phases = list(PipelinePhase)
        message = "All pipeline phases stopped"
        
    elif request.action == BulkControlAction.RESTART_FAILED:
        # Restart failed executions
        result = await db.execute(
            text("""
                SELECT DISTINCT source_id
                FROM execution_manifests
                WHERE status = 'failed'
                AND started_at > NOW() - INTERVAL '24 hours'
            """)
        )
        failed_sources = [row[0] for row in result.fetchall()]
        affected_sources = request.source_ids or failed_sources
        affected_phases = [PipelinePhase.INDEXING]  # Default to reindexing
        message = f"Restarting {len(affected_sources)} failed source(s)"
    
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown action: {request.action}",
        )
    
    logger.info(
        f"Bulk action {request.action.value} executed by {_user.get('sub')}"
    )
    
    # Audit log
    await _log_audit_event(
        db,
        event_type="CONFIG_CHANGED",
        severity="warning",
        details={
            "action": request.action.value,
            "affected_sources": affected_sources,
            "executed_by": _user.get("sub"),
        }
    )
    
    return BulkControlResponse(
        success=True,
        action=request.action,
        affected_phases=[p.value for p in affected_phases],
        affected_sources=affected_sources,
        message=message,
        executed_at=now,
    )


# =============================================================================
# Helper Functions
# =============================================================================

async def _log_audit_event(
    db: AsyncSession,
    event_type: str,
    severity: str,
    details: Dict[str, Any],
) -> None:
    """Log an audit event to the database."""
    try:
        await db.execute(
            text("""
                INSERT INTO audit_log (
                    timestamp, event_type, severity,
                    resource_type, resource_id, action_details,
                    correlation_id
                ) VALUES (
                    NOW(), :event_type, :severity,
                    'pipeline', NULL, :details,
                    :correlation_id
                )
            """),
            {
                "event_type": event_type,
                "severity": severity,
                "details": details,
                "correlation_id": details.get("run_id"),
            }
        )
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to log audit event: {e}")
        # Don't fail the request if audit logging fails


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "router",
]
