"""Document endpoints for GABI API.

Este módulo fornece endpoints para gerenciamento de documentos:
- Listar documentos com filtros
- Obter detalhes de um documento
- Reindexar documento
- Soft delete de documento
"""

from typing import Optional
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from gabi.auth.middleware import RequireAuth
from gabi.config import settings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.orm import selectinload

from gabi.db import get_db_session
from gabi.models.document import Document
from gabi.models.chunk import DocumentChunk
from gabi.schemas.documents import (
    DocumentListResponse,
    DocumentListItem,
    DocumentDetailResponse,
    DocumentDetail,
    DocumentReindexRequest,
    DocumentReindexResponse,
    DocumentDeleteResponse,
    DocumentFilterParams,
    DocumentStatus,
    DocumentChunkInfo,
)

router = APIRouter(tags=["documents"])


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="Listar documentos",
    description="Lista documentos com suporte a filtros e paginação.",
)
async def list_documents(
    source_id: Optional[str] = Query(None, description="Filtrar por fonte"),
    status: Optional[DocumentStatus] = Query(None, description="Filtrar por status"),
    include_deleted: bool = Query(False, description="Incluir documentos deletados"),
    es_indexed: Optional[bool] = Query(None, description="Filtrar por indexação ES"),
    search: Optional[str] = Query(None, description="Busca em título"),
    page: int = Query(1, ge=1, description="Página"),
    page_size: int = Query(20, ge=1, le=100, description="Itens por página"),
    db: AsyncSession = Depends(get_db_session),
    user: dict = Depends(RequireAuth()),
) -> DocumentListResponse:
    """Lista documentos com filtros.
    
    Args:
        source_id: Filtrar por fonte
        status: Filtrar por status
        include_deleted: Incluir soft-deleted
        es_indexed: Filtrar por status de indexação ES
        search: Busca em título
        page: Número da página
        page_size: Itens por página
        db: Sessão do banco
        
    Returns:
        DocumentListResponse com documentos
    """
    # Build query with eager loading for future relationships
    # Note: selectinload prevents N+1 queries if relationships are accessed
    # Currently no relationships are loaded, but infrastructure is ready
    query = select(Document).options(
        # Add selectinload here when relationships are defined
        # Example: selectinload(Document.chunks), selectinload(Document.source)
    )
    
    # Aplicar filtros
    conditions = []
    
    if not include_deleted:
        conditions.append(Document.is_deleted == False)
    
    if source_id:
        conditions.append(Document.source_id == source_id)
    
    if status:
        conditions.append(Document.status == status)
    
    if es_indexed is not None:
        conditions.append(Document.es_indexed == es_indexed)
    
    if search:
        search_filter = or_(
            Document.title.ilike(f"%{search}%"),
            Document.content_preview.ilike(f"%{search}%"),
        )
        conditions.append(search_filter)
    
    if conditions:
        query = query.where(and_(*conditions))
    
    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one_or_none() or 0
    
    # Pagination
    query = query.order_by(desc(Document.ingested_at))
    query = query.offset((page - 1) * page_size).limit(page_size)
    
    # Execute with eager loading to prevent N+1 queries
    # If relationships are added to Document model, use:
    # query = query.options(selectinload(Document.relationship_name))
    result = await db.execute(query)
    documents = result.scalars().all()
    
    # Map to response
    items = [
        DocumentListItem(
            id=str(doc.id),
            document_id=doc.document_id,
            source_id=doc.source_id,
            title=doc.title,
            content_preview=doc.content_preview,
            status=DocumentStatus(doc.status),
            is_deleted=doc.is_deleted,
            version=doc.version,
            chunks_count=doc.chunks_count,
            es_indexed=doc.es_indexed,
            metadata=doc.doc_metadata,
            ingested_at=doc.ingested_at,
            updated_at=doc.updated_at,
            reindexed_at=doc.reindexed_at,
        )
        for doc in documents
    ]
    
    return DocumentListResponse(
        total=total,
        page=page,
        page_size=page_size,
        documents=items,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentDetailResponse,
    summary="Detalhe do documento",
    description="Retorna detalhes completos de um documento.",
)
async def get_document(
    document_id: str,
    include_chunks: bool = Query(False, description="Incluir chunks"),
    db: AsyncSession = Depends(get_db_session),
    user: dict = Depends(RequireAuth()),
) -> DocumentDetailResponse:
    """Obtém detalhes de um documento.
    
    Args:
        document_id: ID do documento (document_id ou UUID)
        include_chunks: Se deve incluir chunks
        db: Sessão do banco
        
    Returns:
        DocumentDetailResponse com detalhes
        
    Raises:
        HTTPException: Se documento não encontrado
    """
    # Try by document_id first, then by UUID
    query = select(Document).where(
        or_(
            Document.document_id == document_id,
            Document.id == document_id,
        )
    )
    result = await db.execute(query)
    doc = result.scalar_one_or_none()
    
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Documento não encontrado: {document_id}",
        )
    
    # Build detail
    detail = DocumentDetail(
        id=str(doc.id),
        document_id=doc.document_id,
        source_id=doc.source_id,
        fingerprint=doc.fingerprint,
        fingerprint_algorithm=doc.fingerprint_algorithm,
        title=doc.title,
        content_preview=doc.content_preview,
        content_hash=doc.content_hash,
        content_size_bytes=doc.content_size_bytes,
        metadata=doc.doc_metadata,
        url=doc.url,
        content_type=doc.content_type,
        language=doc.language,
        status=DocumentStatus(doc.status),
        version=doc.version,
        is_deleted=doc.is_deleted,
        deleted_at=doc.deleted_at,
        deleted_reason=doc.deleted_reason,
        deleted_by=doc.deleted_by,
        ingested_at=doc.ingested_at,
        updated_at=doc.updated_at,
        reindexed_at=doc.reindexed_at,
        es_indexed=doc.es_indexed,
        es_indexed_at=doc.es_indexed_at,
        chunks_count=doc.chunks_count,
    )
    
    # Get chunks if requested
    chunks = None
    if include_chunks:
        chunks_query = select(DocumentChunk).where(
            DocumentChunk.document_id == doc.document_id
        ).order_by(DocumentChunk.chunk_index)
        chunks_result = await db.execute(chunks_query)
        chunks_data = chunks_result.scalars().all()
        
        chunks = [
            DocumentChunkInfo(
                id=str(chunk.id),
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                content_preview=chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content,
                token_count=chunk.token_count,
                char_count=chunk.char_count,
                embedding_status=chunk.embedding_status,
                created_at=chunk.created_at,
            )
            for chunk in chunks_data
        ]
    
    return DocumentDetailResponse(
        document=detail,
        chunks=chunks,
    )


@router.post(
    "/{document_id}/reindex",
    response_model=DocumentReindexResponse,
    summary="Reindexar documento",
    description="Força reindexação de um documento no Elasticsearch. Requer role admin ou editor.",
)
async def reindex_document(
    document_id: str,
    request: DocumentReindexRequest,
    db: AsyncSession = Depends(get_db_session),
    user: dict = Depends(RequireAuth(roles=["admin", "editor"])),
) -> DocumentReindexResponse:
    """Reindexa um documento.
    
    Args:
        document_id: ID do documento
        request: Parâmetros de reindexação
        db: Sessão do banco
        
    Returns:
        DocumentReindexResponse com resultado
        
    Raises:
        HTTPException: Se documento não encontrado
    """
    # Find document
    query = select(Document).where(
        or_(
            Document.document_id == document_id,
            Document.id == document_id,
        )
    )
    result = await db.execute(query)
    doc = result.scalar_one_or_none()
    
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Documento não encontrado: {document_id}",
        )
    
    if doc.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não é possível reindexar documento deletado",
        )
    
    # Check if reindex is needed
    if not request.force and not doc.needs_es_reindex():
        return DocumentReindexResponse(
            success=True,
            document_id=doc.document_id,
            message="Documento já está indexado e atualizado",
            reindexed_at=doc.reindexed_at or datetime.utcnow(),
        )
    
    # Mark for reindex (real reindex happens async via worker)
    doc.reindexed_at = datetime.utcnow()
    doc.es_indexed = False  # Will be picked up by indexer worker
    
    await db.commit()
    
    return DocumentReindexResponse(
        success=True,
        document_id=doc.document_id,
        message="Documento marcado para reindexação",
        reindexed_at=doc.reindexed_at,
    )


@router.delete(
    "/{document_id}",
    response_model=DocumentDeleteResponse,
    summary="Deletar documento",
    description="Executa soft delete de um documento e seus chunks associados.",
)
async def delete_document(
    document_id: str,
    reason: Optional[str] = Query(None, description="Motivo da deleção"),
    db: AsyncSession = Depends(get_db_session),
    user: dict = Depends(RequireAuth(roles=["admin", "editor"])),
) -> DocumentDeleteResponse:
    """Soft delete de um documento com cascata para chunks.
    
    Args:
        document_id: ID do documento
        reason: Motivo da deleção
        db: Sessão do banco
        user: Usuário autenticado com roles admin ou editor
        
    Returns:
        DocumentDeleteResponse com resultado
        
    Raises:
        HTTPException: Se documento não encontrado ou já deletado
    """
    # Find document
    query = select(Document).where(
        or_(
            Document.document_id == document_id,
            Document.id == document_id,
        )
    )
    result = await db.execute(query)
    doc = result.scalar_one_or_none()
    
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Documento não encontrado: {document_id}",
        )
    
    if doc.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Documento já está deletado",
        )
    
    deleted_by = user.get("sub")
    
    # Soft-delete chunks first (cascading soft delete)
    # This ensures data consistency across document and its chunks
    chunks_query = select(DocumentChunk).where(
        DocumentChunk.document_id == doc.document_id,
        DocumentChunk.is_deleted == False
    )
    chunks_result = await db.execute(chunks_query)
    chunks = chunks_result.scalars().all()
    
    deleted_at = datetime.now(timezone.utc)
    cascade_reason = f"Cascade from document deletion: {reason}" if reason else "Cascade from document deletion"
    
    for chunk in chunks:
        chunk.is_deleted = True
        chunk.deleted_at = deleted_at
        chunk.deleted_by = deleted_by
        # Note: chunk model may not have deleted_reason, but we track it via deleted_by
    
    # Then soft-delete document
    doc.soft_delete(reason=reason, deleted_by=deleted_by)
    
    await db.commit()
    
    # Update ES (mark as deleted instead of hard delete)
    try:
        from gabi.db import get_es_client
        es = get_es_client()
        await es.update(
            index=settings.elasticsearch_index,
            id=doc.document_id,
            doc={
                "is_deleted": True,
                "deleted_at": datetime.now(timezone.utc).isoformat(),
                "deleted_by": deleted_by,
                "deleted_reason": reason,
            }
        )
    except Exception as e:
        # Logar erro mas não falhar a operação
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to update ES: {e}")
    
    return DocumentDeleteResponse(
        success=True,
        document_id=doc.document_id,
        message="Documento deletado com sucesso",
        deleted_at=doc.deleted_at or datetime.now(timezone.utc),
    )
