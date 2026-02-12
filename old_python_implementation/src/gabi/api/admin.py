"""Admin endpoints for GABI API.

Este módulo fornece endpoints administrativos:
- Listar execuções
- Listar mensagens DLQ
- Retry de mensagem DLQ
"""

from typing import Optional
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc

from gabi.db import get_db_session
from gabi.models.execution import ExecutionManifest, ExecutionStatus
from gabi.models.dlq import DLQMessage, DLQStatus
from gabi.auth.middleware import RequireAuth
from gabi.schemas.admin import (
    ExecutionListResponse,
    ExecutionListItem,
    ExecutionDetail,
    ExecutionStats,
    DLQListResponse,
    DLQMessageItem,
    DLQRetryRequest,
    DLQRetryResponse,
    SystemStatsResponse,
    SystemStats,
)

router = APIRouter(tags=["admin"])


@router.get(
    "/executions",
    response_model=ExecutionListResponse,
    summary="Listar execuções",
    description="Lista execuções de ingestão com filtros. Requer role admin.",
)
async def list_executions(
    source_id: Optional[str] = Query(None, description="Filtrar por fonte"),
    status: Optional[ExecutionStatus] = Query(None, description="Filtrar por status"),
    page: int = Query(1, ge=1, description="Página"),
    page_size: int = Query(20, ge=1, le=100, description="Itens por página"),
    db: AsyncSession = Depends(get_db_session),
    user: dict = Depends(RequireAuth(roles=["admin"])),
) -> ExecutionListResponse:
    """Lista execuções de ingestão.
    
    Args:
        source_id: Filtrar por fonte
        status: Filtrar por status
        page: Número da página
        page_size: Itens por página
        db: Sessão do banco
        
    Returns:
        ExecutionListResponse com execuções
    """
    query = select(ExecutionManifest)
    
    # Apply filters
    conditions = []
    if source_id:
        conditions.append(ExecutionManifest.source_id == source_id)
    if status:
        conditions.append(ExecutionManifest.status == status)
    
    if conditions:
        query = query.where(and_(*conditions))
    
    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one_or_none() or 0
    
    # Pagination
    query = query.order_by(desc(ExecutionManifest.started_at))
    query = query.offset((page - 1) * page_size).limit(page_size)
    
    # Execute
    result = await db.execute(query)
    executions = result.scalars().all()
    
    # Map to response
    items = []
    for exec in executions:
        stats = exec.stats or {}
        stats_summary = ExecutionStats(
            urls_discovered=stats.get("urls_discovered"),
            documents_indexed=stats.get("documents_indexed"),
            documents_updated=stats.get("documents_updated"),
            documents_failed=stats.get("documents_failed"),
            chunks_created=stats.get("chunks_created"),
            embeddings_generated=stats.get("embeddings_generated"),
            bytes_processed=stats.get("bytes_processed"),
            duration_seconds=exec.duration_seconds,
        )
        
        items.append(ExecutionListItem(
            run_id=exec.run_id,
            source_id=exec.source_id,
            status=ExecutionStatus(exec.status),
            trigger=exec.trigger,
            triggered_by=exec.triggered_by,
            started_at=exec.started_at,
            completed_at=exec.completed_at,
            duration_seconds=exec.duration_seconds,
            stats_summary=stats_summary,
            error_message=exec.error_message,
        ))
    
    return ExecutionListResponse(
        total=total,
        page=page,
        page_size=page_size,
        executions=items,
    )


@router.get(
    "/executions/{run_id}",
    response_model=ExecutionDetail,
    summary="Detalhe da execução",
    description="Retorna detalhes completos de uma execução. Requer role admin.",
)
async def get_execution(
    run_id: UUID,
    db: AsyncSession = Depends(get_db_session),
    user: dict = Depends(RequireAuth(roles=["admin"])),
) -> ExecutionDetail:
    """Obtém detalhes de uma execução.
    
    Args:
        run_id: ID da execução
        db: Sessão do banco
        
    Returns:
        ExecutionDetail com detalhes
        
    Raises:
        HTTPException: Se execução não encontrada
    """
    query = select(ExecutionManifest).where(ExecutionManifest.run_id == run_id)
    result = await db.execute(query)
    exec = result.scalar_one_or_none()
    
    if not exec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execução não encontrada: {run_id}",
        )
    
    stats = exec.stats or {}
    return ExecutionDetail(
        run_id=exec.run_id,
        source_id=exec.source_id,
        status=ExecutionStatus(exec.status),
        trigger=exec.trigger,
        triggered_by=exec.triggered_by,
        started_at=exec.started_at,
        completed_at=exec.completed_at,
        duration_seconds=exec.duration_seconds,
        stats=ExecutionStats(
            urls_discovered=stats.get("urls_discovered"),
            documents_indexed=stats.get("documents_indexed"),
            documents_updated=stats.get("documents_updated"),
            documents_failed=stats.get("documents_failed"),
            chunks_created=stats.get("chunks_created"),
            embeddings_generated=stats.get("embeddings_generated"),
            bytes_processed=stats.get("bytes_processed"),
            duration_seconds=exec.duration_seconds,
        ),
        checkpoint=exec.checkpoint,
        error_message=exec.error_message,
        error_traceback=exec.error_traceback,
        logs=exec.logs,
    )


@router.get(
    "/dlq",
    response_model=DLQListResponse,
    summary="Listar mensagens DLQ",
    description="Lista mensagens da Dead Letter Queue. Requer role admin.",
)
async def list_dlq(
    status: Optional[DLQStatus] = Query(None, description="Filtrar por status"),
    source_id: Optional[str] = Query(None, description="Filtrar por fonte"),
    page: int = Query(1, ge=1, description="Página"),
    page_size: int = Query(20, ge=1, le=100, description="Itens por página"),
    db: AsyncSession = Depends(get_db_session),
    user: dict = Depends(RequireAuth(roles=["admin"])),
) -> DLQListResponse:
    """Lista mensagens DLQ.
    
    Args:
        status: Filtrar por status
        source_id: Filtrar por fonte
        page: Número da página
        page_size: Itens por página
        db: Sessão do banco
        
    Returns:
        DLQListResponse com mensagens
    """
    query = select(DLQMessage)
    
    # Apply filters
    conditions = []
    if status:
        conditions.append(DLQMessage.status == status)
    if source_id:
        conditions.append(DLQMessage.source_id == source_id)
    
    if conditions:
        query = query.where(and_(*conditions))
    
    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one_or_none() or 0
    
    # Count by status
    status_counts = {}
    for dlq_status in DLQStatus:
        count_query = select(func.count()).where(DLQMessage.status == dlq_status)
        count_result = await db.execute(count_query)
        count = count_result.scalar_one_or_none() or 0
        if count > 0:
            status_counts[dlq_status.value] = count
    
    # Pagination
    query = query.order_by(desc(DLQMessage.created_at))
    query = query.offset((page - 1) * page_size).limit(page_size)
    
    # Execute
    result = await db.execute(query)
    messages = result.scalars().all()
    
    # Map to response
    items = [
        DLQMessageItem(
            id=msg.id,
            source_id=msg.source_id,
            run_id=msg.run_id,
            url=msg.url,
            document_id=msg.document_id,
            error_type=msg.error_type,
            error_message=msg.error_message,
            error_hash=msg.error_hash,
            status=DLQStatus(msg.status),
            retry_count=msg.retry_count,
            max_retries=msg.max_retries,
            next_retry_at=msg.next_retry_at,
            last_retry_at=msg.last_retry_at,
            resolved_at=msg.resolved_at,
            resolved_by=msg.resolved_by,
            created_at=msg.created_at,
            updated_at=msg.updated_at,
        )
        for msg in messages
    ]
    
    return DLQListResponse(
        total=total,
        by_status=status_counts,
        page=page,
        page_size=page_size,
        messages=items,
    )


@router.post(
    "/dlq/{message_id}/retry",
    response_model=DLQRetryResponse,
    summary="Retry de mensagem DLQ",
    description="Força retry de uma mensagem da DLQ. Requer role admin.",
)
async def retry_dlq(
    message_id: UUID,
    request: DLQRetryRequest,
    db: AsyncSession = Depends(get_db_session),
    user: dict = Depends(RequireAuth(roles=["admin"])),
) -> DLQRetryResponse:
    """Força retry de uma mensagem DLQ.
    
    Args:
        message_id: ID da mensagem
        request: Parâmetros de retry
        db: Sessão do banco
        
    Returns:
        DLQRetryResponse com resultado
        
    Raises:
        HTTPException: Se mensagem não encontrada
    """
    # Find message
    query = select(DLQMessage).where(DLQMessage.id == message_id)
    result = await db.execute(query)
    msg = result.scalar_one_or_none()
    
    if not msg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mensagem DLQ não encontrada: {message_id}",
        )
    
    # Check if can retry
    if not request.force and msg.status == DLQStatus.EXHAUSTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mensagem atingiu limite de retries. Use force=true para forçar.",
        )
    
    if msg.status in (DLQStatus.RESOLVED, DLQStatus.ARCHIVED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mensagem já foi resolvida",
        )
    
    # Schedule retry
    if request.priority:
        msg.next_retry_at = datetime.utcnow()
    else:
        msg.schedule_next_retry(base_delay_seconds=30)
    
    msg.status = DLQStatus.RETRYING
    await db.commit()
    
    return DLQRetryResponse(
        success=True,
        message_id=msg.id,
        message="Mensagem agendada para retry",
        retry_scheduled_at=msg.next_retry_at,
        retried_at=datetime.utcnow(),
    )


@router.get(
    "/stats",
    response_model=SystemStatsResponse,
    summary="Estatísticas do sistema",
    description="Retorna estatísticas gerais do sistema. Requer role admin.",
)
async def get_system_stats(
    db: AsyncSession = Depends(get_db_session),
    user: dict = Depends(RequireAuth(roles=["admin"])),
) -> SystemStatsResponse:
    """Obtém estatísticas do sistema.
    
    Args:
        db: Sessão do banco
        
    Returns:
        SystemStatsResponse com estatísticas
    """
    from gabi.models.document import Document
    from gabi.models.source import SourceRegistry, SourceStatus
    
    # Document stats
    doc_count_query = select(func.count()).select_from(Document).where(
        Document.is_deleted == False
    )
    doc_result = await db.execute(doc_count_query)
    total_documents = doc_result.scalar_one_or_none() or 0
    
    # Source stats
    source_count_query = select(func.count()).select_from(SourceRegistry).where(
        SourceRegistry.deleted_at.is_(None)
    )
    source_result = await db.execute(source_count_query)
    total_sources = source_result.scalar_one_or_none() or 0
    
    active_sources_query = select(func.count()).select_from(SourceRegistry).where(
        and_(
            SourceRegistry.status == SourceStatus.ACTIVE,
            SourceRegistry.deleted_at.is_(None),
        )
    )
    active_result = await db.execute(active_sources_query)
    active_sources = active_result.scalar_one_or_none() or 0
    
    error_sources_query = select(func.count()).select_from(SourceRegistry).where(
        and_(
            SourceRegistry.status == SourceStatus.ERROR,
            SourceRegistry.deleted_at.is_(None),
        )
    )
    error_result = await db.execute(error_sources_query)
    sources_in_error = error_result.scalar_one_or_none() or 0
    
    # Chunk stats
    from gabi.models.chunk import DocumentChunk
    chunk_count_query = select(func.count()).select_from(DocumentChunk)
    chunk_result = await db.execute(chunk_count_query)
    total_chunks = chunk_result.scalar_one_or_none() or 0
    
    # DLQ stats
    dlq_pending_query = select(func.count()).select_from(DLQMessage).where(
        DLQMessage.status.in_([DLQStatus.PENDING, DLQStatus.RETRYING])
    )
    dlq_pending_result = await db.execute(dlq_pending_query)
    dlq_pending = dlq_pending_result.scalar_one_or_none() or 0
    
    dlq_exhausted_query = select(func.count()).select_from(DLQMessage).where(
        DLQMessage.status == DLQStatus.EXHAUSTED
    )
    dlq_exhausted_result = await db.execute(dlq_exhausted_query)
    dlq_exhausted = dlq_exhausted_result.scalar_one_or_none() or 0
    
    # Today's executions
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    exec_today_query = select(func.count()).select_from(ExecutionManifest).where(
        ExecutionManifest.started_at >= today_start
    )
    exec_today_result = await db.execute(exec_today_query)
    executions_today = exec_today_result.scalar_one_or_none() or 0
    
    exec_failed_today_query = select(func.count()).select_from(ExecutionManifest).where(
        and_(
            ExecutionManifest.started_at >= today_start,
            ExecutionManifest.status == ExecutionStatus.FAILED,
        )
    )
    exec_failed_result = await db.execute(exec_failed_today_query)
    executions_failed_today = exec_failed_result.scalar_one_or_none() or 0
    
    return SystemStatsResponse(
        stats=SystemStats(
            total_documents=total_documents,
            total_sources=total_sources,
            total_chunks=total_chunks,
            active_sources=active_sources,
            sources_in_error=sources_in_error,
            dlq_pending=dlq_pending,
            dlq_exhausted=dlq_exhausted,
            executions_today=executions_today,
            executions_failed_today=executions_failed_today,
        ),
        computed_at=datetime.utcnow(),
    )
