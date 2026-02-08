"""Source endpoints for GABI API.

Este módulo fornece endpoints para gerenciamento de fontes:
- Listar fontes
- Sincronizar fonte
- Obter status da fonte
"""

from typing import Optional
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status

from gabi.auth.middleware import RequireAuth
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from gabi.db import get_db_session
from gabi.models.source import SourceRegistry
from gabi.models.execution import ExecutionManifest, ExecutionStatus
from gabi.schemas.sources import (
    SourceListResponse,
    SourceListItem,
    SourceDetail,
    SourceSyncRequest,
    SourceSyncResponse,
    SourceStatusResponse,
    SourceType,
    SourceStatus,
    SensitivityLevel,
)

router = APIRouter(tags=["sources"])


@router.get(
    "",
    response_model=SourceListResponse,
    summary="Listar fontes",
    description="Lista todas as fontes de dados configuradas.",
)
async def list_sources(
    status: Optional[SourceStatus] = Query(None, description="Filtrar por status"),
    include_deleted: bool = Query(False, description="Incluir deletadas"),
    db: AsyncSession = Depends(get_db_session),
    user: dict = Depends(RequireAuth()),
) -> SourceListResponse:
    """Lista todas as fontes.
    
    Args:
        status: Filtrar por status
        include_deleted: Incluir soft-deleted
        db: Sessão do banco
        
    Returns:
        SourceListResponse com fontes
    """
    query = select(SourceRegistry)
    
    if status:
        query = query.where(SourceRegistry.status == status)
    
    if not include_deleted:
        query = query.where(SourceRegistry.deleted_at.is_(None))
    
    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one_or_none() or 0
    
    # Execute
    result = await db.execute(query)
    sources = result.scalars().all()
    
    # Map to response
    items = [
        SourceListItem(
            id=source.id,
            name=source.name,
            description=source.description,
            type=SourceType(source.type),
            status=SourceStatus(source.status),
            document_count=source.document_count,
            total_documents_ingested=source.total_documents_ingested,
            last_success_at=source.last_success_at,
            next_scheduled_sync=source.next_scheduled_sync,
            consecutive_errors=source.consecutive_errors,
            is_healthy=source.is_healthy,
            owner_email=source.owner_email,
            sensitivity=SensitivityLevel(source.sensitivity),
            created_at=source.created_at,
            updated_at=source.updated_at,
        )
        for source in sources
    ]
    
    return SourceListResponse(
        total=total,
        sources=items,
    )


@router.get(
    "/{source_id}",
    response_model=SourceDetail,
    summary="Detalhe da fonte",
    description="Retorna detalhes completos de uma fonte.",
)
async def get_source(
    source_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: dict = Depends(RequireAuth()),
) -> SourceDetail:
    """Obtém detalhes de uma fonte.
    
    Args:
        source_id: ID da fonte
        db: Sessão do banco
        
    Returns:
        SourceDetail com detalhes
        
    Raises:
        HTTPException: Se fonte não encontrada
    """
    query = select(SourceRegistry).where(SourceRegistry.id == source_id)
    result = await db.execute(query)
    source = result.scalar_one_or_none()
    
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fonte não encontrada: {source_id}",
        )
    
    return SourceDetail(
        id=source.id,
        name=source.name,
        description=source.description,
        type=SourceType(source.type),
        status=SourceStatus(source.status),
        config_hash=source.config_hash,
        config_json=source.config_json,
        document_count=source.document_count,
        total_documents_ingested=source.total_documents_ingested,
        last_document_at=source.last_document_at,
        last_sync_at=source.last_sync_at,
        last_success_at=source.last_success_at,
        next_scheduled_sync=source.next_scheduled_sync,
        consecutive_errors=source.consecutive_errors,
        last_error_message=source.last_error_message,
        last_error_at=source.last_error_at,
        owner_email=source.owner_email,
        sensitivity=SensitivityLevel(source.sensitivity),
        retention_days=source.retention_days,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


@router.post(
    "/{source_id}/sync",
    response_model=SourceSyncResponse,
    summary="Sincronizar fonte",
    description="Inicia sincronização de uma fonte de dados. Requer role admin ou editor.",
)
async def sync_source(
    source_id: str,
    request: SourceSyncRequest,
    db: AsyncSession = Depends(get_db_session),
    user: dict = Depends(RequireAuth(roles=["admin", "editor"])),
) -> SourceSyncResponse:
    """Inicia sincronização de uma fonte.
    
    Args:
        source_id: ID da fonte
        request: Parâmetros do sync
        db: Sessão do banco
        
    Returns:
        SourceSyncResponse com resultado
        
    Raises:
        HTTPException: Se fonte não encontrada ou desabilitada
    """
    # Find source
    query = select(SourceRegistry).where(SourceRegistry.id == source_id)
    result = await db.execute(query)
    source = result.scalar_one_or_none()
    
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fonte não encontrada: {source_id}",
        )
    
    if source.status == SourceStatus.DISABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fonte está desabilitada",
        )
    
    if source.deleted_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fonte foi deletada",
        )
    
    # Create execution manifest
    run_id = uuid4()
    manifest = ExecutionManifest(
        run_id=run_id,
        source_id=source_id,
        status=ExecutionStatus.PENDING,
        trigger="api",
        triggered_by=request.triggered_by or "api_user",
        stats={
            "mode": request.mode,
            "force": request.force,
        },
    )
    
    db.add(manifest)
    
    # Update source
    source.last_sync_at = datetime.utcnow()
    
    await db.commit()
    
    # TODO: Trigger actual sync via Celery/Redis
    
    return SourceSyncResponse(
        success=True,
        source_id=source_id,
        run_id=str(run_id),
        message=f"Sincronização iniciada em modo '{request.mode}'",
        started_at=datetime.utcnow(),
    )


@router.get(
    "/{source_id}/status",
    response_model=SourceStatusResponse,
    summary="Status da fonte",
    description="Retorna status atual e estatísticas de uma fonte.",
)
async def get_source_status(
    source_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: dict = Depends(RequireAuth()),
) -> SourceStatusResponse:
    """Obtém status de uma fonte.
    
    Args:
        source_id: ID da fonte
        db: Sessão do banco
        
    Returns:
        SourceStatusResponse com status
        
    Raises:
        HTTPException: Se fonte não encontrada
    """
    query = select(SourceRegistry).where(SourceRegistry.id == source_id)
    result = await db.execute(query)
    source = result.scalar_one_or_none()
    
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fonte não encontrada: {source_id}",
        )
    
    return SourceStatusResponse(
        source_id=source.id,
        status=SourceStatus(source.status),
        is_healthy=source.is_healthy,
        document_count=source.document_count,
        last_success_at=source.last_success_at,
        next_scheduled_sync=source.next_scheduled_sync,
        consecutive_errors=source.consecutive_errors,
        success_rate=source.success_rate,
        checked_at=datetime.utcnow(),
    )
