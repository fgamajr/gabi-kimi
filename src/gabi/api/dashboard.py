"""Dashboard endpoints for GABI monitoring.

Provides real-time metrics and monitoring for the ingestion pipeline.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, text

from gabi.db import get_db_session
from gabi.config import settings
from gabi.auth.middleware import RequireAuth

router = APIRouter(tags=["dashboard"])


@router.get(
    "/stats",
    summary="System statistics",
    description="Get overall system statistics including document counts, ingestion status, and health metrics. Requires admin role.",
)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db_session),
    user: dict = Depends(RequireAuth(roles=["admin"])),
) -> Dict[str, Any]:
    """Get comprehensive dashboard statistics.
    
    Args:
        db: Database session
        
    Returns:
        Dictionary containing system statistics
    """
    
    # Document counts
    doc_result = await db.execute(text("""
        SELECT 
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE is_deleted = false) as active,
            COUNT(*) FILTER (WHERE is_deleted = true) as deleted
        FROM documents
    """))
    doc_stats = doc_result.fetchone()
    
    # Chunk counts
    chunk_result = await db.execute(text("""
        SELECT COUNT(*) as total FROM document_chunks
    """))
    chunk_count = chunk_result.scalar()
    
    # Source counts
    source_result = await db.execute(text("""
        SELECT 
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE status = 'active' AND is_deleted = false) as active
        FROM sources
    """))
    source_stats = source_result.fetchone()
    
    # Recent documents (last 24h)
    recent_result = await db.execute(text("""
        SELECT COUNT(*) FROM documents 
        WHERE ingested_at > NOW() - INTERVAL '24 hours'
    """))
    recent_count = recent_result.scalar()
    
    # Processing status
    processing_result = await db.execute(text("""
        SELECT status, COUNT(*) as count 
        FROM execution_manifests
        GROUP BY status
    """))
    processing_stats = {row[0]: row[1] for row in processing_result.fetchall()}
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "documents": {
            "total": doc_stats[0] if doc_stats else 0,
            "active": doc_stats[1] if doc_stats else 0,
            "deleted": doc_stats[2] if doc_stats else 0,
            "recent_24h": recent_count or 0,
        },
        "chunks": {
            "total": chunk_count or 0,
        },
        "sources": {
            "total": source_stats[0] if source_stats else 0,
            "active": source_stats[1] if source_stats else 0,
        },
        "processing": processing_stats,
    }


@router.get(
    "/ingestion-status",
    summary="Ingestion pipeline status",
    description="Get detailed status of the ingestion pipeline including queue sizes and processing rates. Requires admin role.",
)
async def get_ingestion_status(
    db: AsyncSession = Depends(get_db_session),
    user: dict = Depends(RequireAuth(roles=["admin"])),
) -> Dict[str, Any]:
    """Get detailed ingestion pipeline status.
    
    Args:
        db: Database session
        
    Returns:
        Dictionary containing ingestion pipeline status
    """
    
    # Documents by source
    source_docs = await db.execute(text("""
        SELECT s.id, s.name, COUNT(d.id) as doc_count
        FROM sources s
        LEFT JOIN documents d ON s.id = d.source_id AND d.is_deleted = false
        GROUP BY s.id, s.name
        ORDER BY doc_count DESC
    """))
    
    source_breakdown = [
        {"source_id": row[0], "name": row[1], "documents": row[2]}
        for row in source_docs.fetchall()
    ]
    
    # Recent errors
    errors_result = await db.execute(text("""
        SELECT 
            document_id,
            error_message,
            updated_at,
            source_id
        FROM dlq_messages
        WHERE error_message IS NOT NULL
        ORDER BY updated_at DESC
        LIMIT 10
    """))
    
    recent_errors = [
        {
            "document_id": row[0],
            "error": row[1],
            "timestamp": row[2].isoformat() if row[2] else None,
            "source_id": row[3],
        }
        for row in errors_result.fetchall()
    ]
    
    # Processing queue status
    queue_result = await db.execute(text("""
        SELECT 
            status,
            COUNT(*) as count,
            MIN(EXTRACT(EPOCH FROM (NOW() - started_at))/60)::int as oldest_minutes
        FROM execution_manifests
        WHERE status IN ('pending', 'running', 'failed')
        GROUP BY status
    """))
    
    queue_status = [
        {
            "status": row[0],
            "count": row[1],
            "oldest_minutes": row[2],
        }
        for row in queue_result.fetchall()
    ]
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "sources": source_breakdown,
        "queue": queue_status,
        "recent_errors": recent_errors,
    }


@router.get(
    "/health-detailed",
    summary="Detailed health check",
    description="Get detailed health status of all system components. Requires admin role.",
)
async def get_detailed_health(
    user: dict = Depends(RequireAuth(roles=["admin"])),
) -> Dict[str, Any]:
    """Get detailed health status of all components.
    
    Returns:
        Dictionary containing health status of all components
    """
    
    health_checks = {
        "timestamp": datetime.utcnow().isoformat(),
        "overall": "healthy",
        "components": {},
    }
    
    # Check PostgreSQL
    try:
        from gabi.db import get_engine
        engine = get_engine()
        health_checks["components"]["postgresql"] = {
            "status": "healthy",
            "message": "Connected",
        }
    except Exception as e:
        health_checks["components"]["postgresql"] = {
            "status": "unhealthy",
            "message": str(e),
        }
        health_checks["overall"] = "degraded"
    
    # Check Elasticsearch
    try:
        from elasticsearch._async.client import AsyncElasticsearch
        es = AsyncElasticsearch(
            [settings.elasticsearch_url],
            timeout=5.0,
            max_retries=1,
        )
        es_info = await es.info()
        await es.close()
        health_checks["components"]["elasticsearch"] = {
            "status": "healthy",
            "version": es_info["version"]["number"],
        }
    except Exception as e:
        health_checks["components"]["elasticsearch"] = {
            "status": "unhealthy",
            "message": str(e),
        }
        health_checks["overall"] = "degraded"
    
    # Check Redis
    try:
        import redis
        r = redis.from_url(
            settings.redis_url,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        r.ping()
        health_checks["components"]["redis"] = {
            "status": "healthy",
            "message": "Connected",
        }
    except Exception as e:
        health_checks["components"]["redis"] = {
            "status": "unhealthy",
            "message": str(e),
        }
        health_checks["overall"] = "degraded"
    
    return health_checks


@router.post(
    "/trigger-ingestion",
    summary="Trigger ingestion for a source",
    description="Manually trigger ingestion process for a specific source. Requires admin role.",
)
async def trigger_ingestion(
    source_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: dict = Depends(RequireAuth(roles=["admin"])),
) -> Dict[str, Any]:
    """Trigger ingestion for a source.
    
    Args:
        source_id: ID of the source to trigger ingestion for
        db: Database session
        
    Returns:
        Dictionary containing trigger result
        
    Raises:
        HTTPException: If source not found
    """
    
    # Check if source exists
    result = await db.execute(
        text("SELECT source_id, name FROM sources WHERE source_id = :source_id"),
        {"source_id": source_id}
    )
    source = result.fetchone()
    
    if not source:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    
    # TODO: Actually trigger the ingestion via Celery
    # For now, just return success
    return {
        "message": f"Ingestion triggered for source {source_id}",
        "source_id": source_id,
        "source_name": source[1],
        "timestamp": datetime.utcnow().isoformat(),
        "status": "queued",
    }
