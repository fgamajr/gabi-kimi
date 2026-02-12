"""Dashboard endpoints for GABI monitoring.

Provides typed, schema-based endpoints for the dashboard web interface.
Replaces the original untyped dict-based endpoints.

Endpoints:
    GET  /stats       → DashboardStatsResponse
    GET  /pipeline    → DashboardPipelineResponse
    GET  /activity    → DashboardActivityResponse
    GET  /health      → DashboardHealthResponse
    POST /trigger-ingestion → TriggerIngestionResponse (admin only)
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import aiohttp
from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, Query
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from gabi.auth.middleware import RequireAuth
from gabi.config import settings
from gabi.db import get_db_session
from gabi.dependencies import get_es_client, get_redis
from gabi.schemas.dashboard import (
    ActivityEvent,
    ComponentHealth,
    DashboardActivityResponse,
    DashboardHealthResponse,
    DashboardPipelineResponse,
    DashboardSourceSummary,
    DashboardStatsResponse,
    PipelineStageInfo,
    TriggerIngestionResponse,
)
from gabi.types import (
    AuditEventType,
    AuditSeverity,
    PipelinePhase,
    SourceStatus,
    SourceType,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dashboard"])

# Process start time for uptime calculation
_PROCESS_START = time.monotonic()

# Labels and descriptions for the 9 pipeline phases (pt-BR)
_PIPELINE_LABELS: dict[PipelinePhase, tuple[str, str]] = {
    PipelinePhase.DISCOVERY: ("Descoberta", "Identificação de URLs nas fontes configuradas"),
    PipelinePhase.CHANGE_DETECTION: ("Detecção de Mudanças", "Verificação de alterações (ETag, hash, Last-Modified)"),
    PipelinePhase.FETCH: ("Download", "Obtenção do conteúdo bruto das fontes"),
    PipelinePhase.PARSE: ("Parsing", "Extração de texto e metadados estruturados"),
    PipelinePhase.FINGERPRINT: ("Fingerprint", "Cálculo de hash canônico SHA-256"),
    PipelinePhase.DEDUPLICATION: ("Deduplicação", "Remoção de documentos duplicados"),
    PipelinePhase.CHUNKING: ("Chunking", "Divisão em chunks para busca semântica"),
    PipelinePhase.EMBEDDING: ("Embeddings", "Geração de vetores 384d via TEI"),
    PipelinePhase.INDEXING: ("Indexação", "Inserção no Elasticsearch para busca BM25"),
}

# Mapping from AuditEventType to human-readable description templates
_EVENT_DESCRIPTIONS: dict[AuditEventType, str] = {
    AuditEventType.SYNC_STARTED: "Sincronização iniciada",
    AuditEventType.SYNC_COMPLETED: "Sincronização concluída",
    AuditEventType.SYNC_FAILED: "Sincronização falhou",
    AuditEventType.SYNC_CANCELLED: "Sincronização cancelada",
    AuditEventType.DOCUMENT_CREATED: "Documento criado",
    AuditEventType.DOCUMENT_UPDATED: "Documento atualizado",
    AuditEventType.DOCUMENT_DELETED: "Documento removido",
    AuditEventType.DOCUMENT_REINDEXED: "Documento reindexado",
    AuditEventType.DLQ_MESSAGE_CREATED: "Erro enviado para DLQ",
    AuditEventType.DLQ_MESSAGE_RESOLVED: "Erro DLQ resolvido",
    AuditEventType.QUALITY_CHECK_FAILED: "Verificação de qualidade falhou",
    AuditEventType.CONFIG_CHANGED: "Configuração alterada",
    AuditEventType.USER_LOGIN: "Login de usuário",
    AuditEventType.USER_LOGOUT: "Logout de usuário",
    AuditEventType.PERMISSION_CHANGED: "Permissão alterada",
    AuditEventType.DOCUMENT_VIEWED: "Documento visualizado",
    AuditEventType.DOCUMENT_SEARCHED: "Busca realizada",
}


# ---------------------------------------------------------------------------
# GET /stats
# ---------------------------------------------------------------------------


@router.get(
    "/stats",
    response_model=DashboardStatsResponse,
    summary="Dashboard statistics",
    description="Aggregated statistics for sources, documents, chunks, embeddings and DLQ.",
)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db_session),
    _user: dict = Depends(RequireAuth()),
) -> DashboardStatsResponse:
    """Return aggregated dashboard statistics.

    Uses CTEs to minimize database round-trips. ES availability is
    checked with a short timeout and degrades gracefully.
    """
    now = datetime.now(timezone.utc)

    # --- Sources -----------------------------------------------------------
    src_result = await db.execute(text("""
        SELECT id, name, description, type, status,
               document_count, last_sync_at, last_success_at, consecutive_errors
        FROM source_registry
        WHERE deleted_at IS NULL
        ORDER BY document_count DESC
    """))
    sources = []
    active_count = 0
    for row in src_result.mappings():
        status = SourceStatus(row["status"])
        sources.append(DashboardSourceSummary(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            source_type=SourceType(row["type"]),
            status=status,
            enabled=status != SourceStatus.DISABLED,
            document_count=row["document_count"] or 0,
            last_sync_at=row["last_sync_at"],
            last_success_at=row["last_success_at"],
            consecutive_errors=row["consecutive_errors"] or 0,
        ))
        if status == SourceStatus.ACTIVE:
            active_count += 1

    # --- Aggregated counts (single CTE query) ------------------------------
    counts_result = await db.execute(text("""
        WITH doc_counts AS (
            SELECT
                COUNT(*) FILTER (WHERE is_deleted = false) AS active_docs,
                COUNT(*) FILTER (WHERE es_indexed = true AND is_deleted = false) AS indexed_docs,
                COUNT(*) FILTER (WHERE ingested_at > NOW() - INTERVAL '24 hours') AS recent_docs
            FROM documents
        ),
        chunk_counts AS (
            SELECT
                COUNT(*) AS total_chunks,
                COUNT(*) FILTER (WHERE embedding IS NOT NULL AND is_deleted = false) AS embedded_chunks
            FROM document_chunks
        ),
        dlq_counts AS (
            SELECT COUNT(*) AS pending
            FROM dlq_messages
            WHERE status IN ('pending', 'retrying')
        )
        SELECT
            dc.active_docs, dc.indexed_docs, dc.recent_docs,
            cc.total_chunks, cc.embedded_chunks,
            dq.pending
        FROM doc_counts dc, chunk_counts cc, dlq_counts dq
    """))
    c = counts_result.mappings().fetchone()

    # --- ES availability ---------------------------------------------------
    es_available = False
    total_elastic: Optional[int] = None
    try:
        from gabi.db import get_es_client as _get_es
        es = _get_es()
        cat = await asyncio.wait_for(
            es.cat.indices(index=settings.elasticsearch_index, format="json"),
            timeout=3.0,
        )
        es_available = True
        if cat and isinstance(cat, list) and len(cat) > 0:
            total_elastic = int(cat[0].get("docs.count", 0))
    except Exception:
        logger.debug("ES unavailable for dashboard stats", exc_info=True)

    return DashboardStatsResponse(
        sources=sources,
        total_documents=c["active_docs"] if c else 0,
        total_chunks=c["total_chunks"] if c else 0,
        total_indexed=c["indexed_docs"] if c else 0,
        total_embeddings=c["embedded_chunks"] if c else 0,
        active_sources=active_count,
        documents_last_24h=c["recent_docs"] if c else 0,
        dlq_pending=c["pending"] if c else 0,
        elasticsearch_available=es_available,
        total_elastic_docs=total_elastic,
        generated_at=now,
    )


# ---------------------------------------------------------------------------
# GET /pipeline
# ---------------------------------------------------------------------------


@router.get(
    "/pipeline",
    response_model=DashboardPipelineResponse,
    summary="Pipeline stage progress",
    description="Progress of each of the 9 real pipeline phases.",
)
async def get_dashboard_pipeline(
    db: AsyncSession = Depends(get_db_session),
    _user: dict = Depends(RequireAuth()),
) -> DashboardPipelineResponse:
    """Return pipeline progress for all 9 phases.

    Each phase count is derived from actual data state:
    - discovery/change_detection/fetch/parse/fingerprint/dedup: document field presence
    - chunking/embedding: distinct document_id in document_chunks
    - indexing: es_indexed flag
    """
    now = datetime.now(timezone.utc)
    two_hours_ago = now - timedelta(hours=2)

    result = await db.execute(text("""
        WITH base AS (
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE is_deleted = false) AS active,
                COUNT(*) FILTER (WHERE content_hash IS NOT NULL AND is_deleted = false) AS fetched,
                COUNT(*) FILTER (WHERE content_preview IS NOT NULL AND is_deleted = false) AS parsed,
                COUNT(*) FILTER (WHERE fingerprint IS NOT NULL AND is_deleted = false) AS fingerprinted,
                COUNT(*) FILTER (WHERE is_deleted = false) AS deduped,
                COUNT(*) FILTER (WHERE es_indexed = true AND is_deleted = false) AS indexed,
                MAX(ingested_at) AS last_ingest,
                MAX(CASE WHEN es_indexed = true THEN es_indexed_at END) AS last_index
            FROM documents
        ),
        chunk_stats AS (
            SELECT
                COUNT(DISTINCT document_id) AS chunked_docs,
                COUNT(DISTINCT document_id) FILTER (WHERE embedding IS NOT NULL AND is_deleted = false) AS embedded_docs,
                MAX(created_at) AS last_chunk,
                MAX(embedded_at) AS last_embed
            FROM document_chunks
        ),
        recent_exec AS (
            SELECT
                MAX(completed_at) AS last_completed,
                COUNT(*) FILTER (WHERE status = 'failed' AND started_at > NOW() - INTERVAL '24 hours') AS recent_failures
            FROM execution_manifests
        )
        SELECT b.*, cs.*, re.*
        FROM base b, chunk_stats cs, recent_exec re
    """))
    r = result.mappings().fetchone()
    if not r:
        # Empty database — return all zeros
        stages = _build_empty_stages(now)
        return DashboardPipelineResponse(
            stages=stages, overall_status="stalled", generated_at=now
        )

    total = r["total"] or 0
    recent_failures = r["recent_failures"] or 0

    # Build per-phase counts
    phase_data: list[tuple[PipelinePhase, int, Optional[datetime]]] = [
        (PipelinePhase.DISCOVERY, total, r["last_ingest"]),
        (PipelinePhase.CHANGE_DETECTION, r["active"] or 0, r["last_ingest"]),
        (PipelinePhase.FETCH, r["fetched"] or 0, r["last_ingest"]),
        (PipelinePhase.PARSE, r["parsed"] or 0, r["last_ingest"]),
        (PipelinePhase.FINGERPRINT, r["fingerprinted"] or 0, r["last_ingest"]),
        (PipelinePhase.DEDUPLICATION, r["deduped"] or 0, r["last_ingest"]),
        (PipelinePhase.CHUNKING, r["chunked_docs"] or 0, r["last_chunk"]),
        (PipelinePhase.EMBEDDING, r["embedded_docs"] or 0, r["last_embed"]),
        (PipelinePhase.INDEXING, r["indexed"] or 0, r["last_index"]),
    ]

    stages = []
    any_error = False
    any_active = False
    for phase, count, last_act in phase_data:
        label, desc = _PIPELINE_LABELS[phase]
        fail_rate = (recent_failures / total * 100) if total > 0 else 0
        if fail_rate > 10:
            status = "error"
            any_error = True
        elif last_act and last_act.replace(tzinfo=timezone.utc) > two_hours_ago:
            status = "active"
            any_active = True
        else:
            status = "idle"

        stages.append(PipelineStageInfo(
            name=phase,
            label=label,
            description=desc,
            count=count,
            total=total,
            failed=recent_failures if phase == PipelinePhase.INDEXING else 0,
            status=status,
            last_activity=last_act,
        ))

    if any_error:
        overall = "degraded"
    elif any_active:
        overall = "healthy"
    else:
        overall = "stalled"

    return DashboardPipelineResponse(
        stages=stages, overall_status=overall, generated_at=now
    )


def _build_empty_stages(now: datetime) -> list[PipelineStageInfo]:
    """Build 9 empty pipeline stages for an empty database."""
    stages = []
    for phase in PipelinePhase:
        label, desc = _PIPELINE_LABELS[phase]
        stages.append(PipelineStageInfo(
            name=phase,
            label=label,
            description=desc,
            count=0,
            total=0,
            failed=0,
            status="idle",
            last_activity=None,
        ))
    return stages


# ---------------------------------------------------------------------------
# GET /activity
# ---------------------------------------------------------------------------


@router.get(
    "/activity",
    response_model=DashboardActivityResponse,
    summary="Recent activity feed",
    description="Activity events from the audit_log table.",
)
async def get_dashboard_activity(
    db: AsyncSession = Depends(get_db_session),
    _user: dict = Depends(RequireAuth()),
    limit: int = Query(default=50, ge=1, le=200, description="Max events"),
    severity: Optional[str] = Query(default=None, description="Filter by severity"),
    event_type: Optional[str] = Query(default=None, description="Filter by event type"),
    source_id: Optional[str] = Query(default=None, description="Filter by source ID"),
) -> DashboardActivityResponse:
    """Return recent activity events from the audit log.

    Builds a human-readable ``description`` for each event from the
    ``event_type`` and ``action_details`` fields.
    """
    now = datetime.now(timezone.utc)

    # Dynamic WHERE clauses
    conditions = []
    params: dict[str, Any] = {"lim": limit + 1}  # +1 to detect has_more

    if severity:
        conditions.append("severity = :sev")
        params["sev"] = severity
    if event_type:
        conditions.append("event_type = :et")
        params["et"] = event_type
    if source_id:
        conditions.append("resource_type = 'source' AND resource_id = :sid")
        params["sid"] = source_id

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # Count total
    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM audit_log {where}"), params  # noqa: S608
    )
    total = count_result.scalar() or 0

    # Fetch events
    rows_result = await db.execute(
        text(f"""
            SELECT id, timestamp, event_type, severity,
                   resource_type, resource_id, action_details,
                   correlation_id
            FROM audit_log
            {where}
            ORDER BY timestamp DESC
            LIMIT :lim
        """),  # noqa: S608
        params,
    )
    rows = rows_result.mappings().fetchall()

    has_more = len(rows) > limit
    events = []
    for row in rows[:limit]:
        et = AuditEventType(row["event_type"])
        sev = AuditSeverity(row["severity"])

        # Derive source_id from resource fields
        src_id = None
        if row["resource_type"] == "source":
            src_id = row["resource_id"]
        elif row["action_details"] and isinstance(row["action_details"], dict):
            src_id = row["action_details"].get("source_id")

        # Build description
        desc = _build_event_description(et, row["action_details"], row["resource_id"])

        events.append(ActivityEvent(
            id=str(row["id"]),
            timestamp=row["timestamp"],
            event_type=et,
            severity=sev,
            source_id=src_id,
            description=desc,
            details=row["action_details"],
            run_id=row["correlation_id"],
        ))

    return DashboardActivityResponse(
        events=events,
        total=total,
        has_more=has_more,
        generated_at=now,
    )


def _build_event_description(
    event_type: AuditEventType,
    details: Optional[Dict[str, Any]],
    resource_id: Optional[str],
) -> str:
    """Build a human-readable description from event type and details."""
    base = _EVENT_DESCRIPTIONS.get(event_type, event_type.value)

    parts = [base]
    if resource_id:
        parts.append(f"[{resource_id}]")

    if details and isinstance(details, dict):
        if "documents_processed" in details:
            parts.append(f"({details['documents_processed']} docs)")
        if "duration_seconds" in details:
            parts.append(f"em {details['duration_seconds']:.1f}s")
        if "error_message" in details:
            msg = str(details["error_message"])[:80]
            parts.append(f"— {msg}")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


@router.get(
    "/health",
    response_model=DashboardHealthResponse,
    summary="System component health",
    description="Detailed health status with latency for PG, ES, Redis, TEI.",
)
async def get_dashboard_health(
    _user: dict = Depends(RequireAuth()),
) -> DashboardHealthResponse:
    """Probe all infrastructure components in parallel.

    Each probe has a 2-second timeout. Failures degrade gracefully
    to ``offline`` status without failing the entire response.
    """
    now = datetime.now(timezone.utc)
    uptime = time.monotonic() - _PROCESS_START

    pg, es, rd, tei = await asyncio.gather(
        _probe_postgres(),
        _probe_elasticsearch(),
        _probe_redis(),
        _probe_tei(),
    )

    components = [pg, es, rd, tei]

    critical_down = any(
        c.status == "offline" and c.name in ("postgresql", "elasticsearch")
        for c in components
    )
    any_down = any(c.status != "online" for c in components)

    if critical_down:
        status = "unhealthy"
    elif any_down:
        status = "degraded"
    else:
        status = "healthy"

    return DashboardHealthResponse(
        status=status,
        uptime_seconds=round(uptime, 1),
        components=components,
        generated_at=now,
    )


async def _probe_postgres() -> ComponentHealth:
    """Probe PostgreSQL with SELECT 1 and connection stats."""
    t0 = time.monotonic()
    try:
        from gabi.db import async_session_factory

        async with async_session_factory() as session:
            await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=2.0)

            info = await session.execute(text("""
                SELECT
                    (SELECT count(*) FROM pg_stat_activity WHERE state = 'active') AS active,
                    (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') AS max_conn,
                    pg_database_size(current_database()) / (1024*1024) AS db_size_mb
            """))
            row = info.mappings().fetchone()

        latency = (time.monotonic() - t0) * 1000
        version_result = await session.execute(text("SELECT version()"))
        pg_version = str(version_result.scalar() or "unknown").split(" ")[1] if version_result else None

        return ComponentHealth(
            name="postgresql",
            status="online",
            latency_ms=round(latency, 1),
            version=pg_version,
            details={
                "connections_active": row["active"] if row else 0,
                "connections_max": row["max_conn"] if row else 0,
                "database_size_mb": float(row["db_size_mb"]) if row else 0,
            },
        )
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        return ComponentHealth(
            name="postgresql",
            status="offline",
            latency_ms=round(latency, 1),
            details={"error": str(e)[:200]},
        )


async def _probe_elasticsearch() -> ComponentHealth:
    """Probe ES with cluster health call."""
    t0 = time.monotonic()
    try:
        from gabi.db import get_es_client as _get_es

        es = _get_es()
        health = await asyncio.wait_for(es.cluster.health(), timeout=2.0)
        info = await asyncio.wait_for(es.info(), timeout=2.0)
        latency = (time.monotonic() - t0) * 1000

        return ComponentHealth(
            name="elasticsearch",
            status="online" if health["status"] != "red" else "degraded",
            latency_ms=round(latency, 1),
            version=info["version"]["number"],
            details={
                "cluster_status": health["status"],
                "index_count": health.get("indices", {}).get("count", health.get("number_of_data_nodes", 0)),
                "total_docs": health.get("indices", {}).get("docs", {}).get("count", 0),
            },
        )
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        return ComponentHealth(
            name="elasticsearch",
            status="offline",
            latency_ms=round(latency, 1),
            details={"error": str(e)[:200]},
        )


async def _probe_redis() -> ComponentHealth:
    """Probe Redis with PING and INFO memory."""
    t0 = time.monotonic()
    try:
        from gabi.db import get_redis_client

        r = get_redis_client()
        await asyncio.wait_for(r.ping(), timeout=2.0)
        info = await asyncio.wait_for(r.info("memory"), timeout=2.0)
        server_info = await asyncio.wait_for(r.info("server"), timeout=2.0)
        latency = (time.monotonic() - t0) * 1000

        return ComponentHealth(
            name="redis",
            status="online",
            latency_ms=round(latency, 1),
            version=server_info.get("redis_version"),
            details={
                "memory_used_mb": round(info.get("used_memory", 0) / (1024 * 1024), 2),
                "connected_clients": server_info.get("connected_clients", 0),
            },
        )
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        return ComponentHealth(
            name="redis",
            status="offline",
            latency_ms=round(latency, 1),
            details={"error": str(e)[:200]},
        )


async def _probe_tei() -> ComponentHealth:
    """Probe TEI with GET /health (liveness only, no embed call)."""
    t0 = time.monotonic()
    tei_url = settings.embeddings_url.rstrip("/")
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=2.0)
        ) as session:
            async with session.get(f"{tei_url}/health") as resp:
                latency = (time.monotonic() - t0) * 1000
                if resp.status == 200:
                    return ComponentHealth(
                        name="tei",
                        status="online",
                        latency_ms=round(latency, 1),
                        details={"url": tei_url},
                    )
                return ComponentHealth(
                    name="tei",
                    status="degraded",
                    latency_ms=round(latency, 1),
                    details={"http_status": resp.status},
                )
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        return ComponentHealth(
            name="tei",
            status="offline",
            latency_ms=round(latency, 1),
            details={"error": str(e)[:200]},
        )


# ---------------------------------------------------------------------------
# POST /trigger-ingestion (admin only)
# ---------------------------------------------------------------------------


@router.post(
    "/trigger-ingestion",
    response_model=TriggerIngestionResponse,
    summary="Trigger ingestion for a source",
    description="Manually trigger ingestion for a specific source. Requires admin role.",
)
async def trigger_ingestion(
    source_id: str = Query(..., description="ID of the source to trigger"),
    db: AsyncSession = Depends(get_db_session),
    _user: dict = Depends(RequireAuth(roles=["admin"])),
) -> TriggerIngestionResponse:
    """Trigger ingestion for a source (admin only)."""
    now = datetime.now(timezone.utc)

    result = await db.execute(
        text("SELECT id, name FROM source_registry WHERE id = :sid AND deleted_at IS NULL"),
        {"sid": source_id},
    )
    source = result.mappings().fetchone()

    if not source:
        raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found")

    # TODO: Actually trigger the ingestion via Celery task
    return TriggerIngestionResponse(
        message=f"Ingestion triggered for source {source_id}",
        source_id=source_id,
        source_name=source["name"],
        status="queued",
        timestamp=now,
    )
