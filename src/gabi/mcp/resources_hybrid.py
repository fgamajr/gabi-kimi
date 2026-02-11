"""
MCP Hybrid Search Resources - Recursos acessíveis via Model Context Protocol

Resources:
- document://{id} - Documento completo
- document://{id}/chunks - Chunks do documento
- chunk://{document_id}/{chunk_index} - Chunk específico
- source://{id}/stats - Estatísticas de fonte
- source://list - Lista de fontes
- search://health - Health check da busca

Formato: URI-based resource identification
Spec: MCP 2025-03-26
"""

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime

import aiofiles
import yaml
from pydantic import BaseModel, Field

from gabi.config import settings
from gabi.db import get_session_no_commit
from gabi.models.document import Document
from gabi.models.chunk import DocumentChunk
from gabi.models.source import SourceRegistry
from gabi.services.search_service import SearchService

from sqlalchemy import select, func

logger = logging.getLogger(__name__)


# =============================================================================
# Resource Schemas
# =============================================================================

class DocumentResource(BaseModel):
    """Schema para recurso de documento."""
    uri: str
    document_id: str
    title: Optional[str]
    content_preview: Optional[str]
    source_id: str
    metadata: Dict[str, Any]
    status: str
    language: str
    url: Optional[str]
    ingested_at: Optional[str]
    updated_at: Optional[str]
    chunks_count: int
    es_indexed: bool


class ChunkResource(BaseModel):
    """Schema para recurso de chunk."""
    uri: str
    document_id: str
    chunk_index: int
    text: str
    token_count: int
    char_count: int
    section_type: Optional[str]
    has_embedding: bool
    embedding_model: Optional[str]
    metadata: Dict[str, Any]


class SourceResource(BaseModel):
    """Schema para recurso de fonte."""
    uri: str
    source_id: str
    name: str
    description: Optional[str]
    type: str
    status: str
    document_count: int
    last_sync_at: Optional[str]
    is_healthy: bool


class SearchHealthResource(BaseModel):
    """Schema para health check de busca."""
    uri: str = "search://health"
    status: str
    elasticsearch_status: str
    indices: List[Dict[str, Any]]
    checked_at: str


# =============================================================================
# Resource Patterns
# =============================================================================

RESOURCE_PATTERNS = {
    "document": re.compile(r"^document://([^/]+)$"),
    "document_chunks": re.compile(r"^document://([^/]+)/chunks$"),
    "chunk": re.compile(r"^chunk://([^/]+)/(\d+)$"),
    "source_stats": re.compile(r"^source://([^/]+)/stats$"),
    "source_list": re.compile(r"^source://list$"),
    "search_health": re.compile(r"^search://health$"),
}


# =============================================================================
# Hybrid Resource Manager
# =============================================================================

class HybridSearchResourceManager:
    """
    Gerenciador de recursos MCP para busca híbrida.
    
    Recursos são identificados por URIs:
    - document://{document_id} - Documento específico
    - document://{document_id}/chunks - Chunks do documento
    - chunk://{document_id}/{chunk_index} - Chunk específico
    - source://{source_id}/stats - Estatísticas da fonte
    - source://list - Lista de fontes
    - search://health - Health check da busca
    
    Implementa o padrão Resource do MCP 2025-03-26.
    """
    
    def __init__(self):
        self._uri_templates = [
            {
                "uriTemplate": "document://{document_id}",
                "name": "Documento por ID",
                "description": "Recupera um documento jurídico completo pelo seu ID",
                "mimeType": "application/json"
            },
            {
                "uriTemplate": "document://{document_id}/chunks",
                "name": "Chunks do Documento",
                "description": "Recupera todos os chunks processados de um documento",
                "mimeType": "application/json"
            },
            {
                "uriTemplate": "chunk://{document_id}/{chunk_index}",
                "name": "Chunk Específico",
                "description": "Recupera um chunk específico de um documento",
                "mimeType": "application/json"
            },
            {
                "uriTemplate": "source://{source_id}/stats",
                "name": "Estatísticas da Fonte",
                "description": "Estatísticas de indexação e sincronização de uma fonte",
                "mimeType": "application/json"
            },
            {
                "uriTemplate": "source://list",
                "name": "Lista de Fontes",
                "description": "Lista todas as fontes de dados disponíveis",
                "mimeType": "application/json"
            },
            {
                "uriTemplate": "search://health",
                "name": "Health Check da Busca",
                "description": "Status de saúde dos índices de busca",
                "mimeType": "application/json"
            }
        ]
        self._search_service: Optional[SearchService] = None
    
    def list_resources(self) -> List[Dict[str, Any]]:
        """Retorna lista de templates de recursos disponíveis."""
        return self._uri_templates
    
    async def read_resource(
        self,
        uri: str,
        user: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Lê um recurso pelo URI.
        
        Args:
            uri: URI do recurso
            user: Informações do usuário autenticado
            
        Returns:
            Conteúdo do recurso no formato MCP
        """
        logger.info(f"Reading resource: {uri} (user: {user.get('sub')})")
        
        # Match patterns
        for resource_type, pattern in RESOURCE_PATTERNS.items():
            match = pattern.match(uri)
            if match:
                try:
                    if resource_type == "document":
                        return await self._read_document(match.group(1))
                    elif resource_type == "document_chunks":
                        return await self._read_document_chunks(match.group(1))
                    elif resource_type == "chunk":
                        return await self._read_chunk(match.group(1), int(match.group(2)))
                    elif resource_type == "source_stats":
                        return await self._read_source_stats(match.group(1))
                    elif resource_type == "source_list":
                        return await self._read_source_list()
                    elif resource_type == "search_health":
                        return await self._read_search_health()
                except Exception as e:
                    logger.error(f"Error reading resource {uri}: {e}")
                    raise ValueError(f"Failed to read resource: {str(e)}")
        
        raise ValueError(f"Invalid resource URI: {uri}")
    
    def _get_search_service(self) -> Optional[SearchService]:
        """Retorna instância do SearchService (lazy initialization)."""
        if self._search_service is None:
            try:
                from gabi.db import get_es_client
                self._search_service = SearchService(
                    es_client=get_es_client(),
                    settings=settings,
                )
            except Exception as e:
                logger.warning(f"Could not initialize search service: {e}")
        return self._search_service
    
    async def _read_document(self, document_id: str) -> Dict[str, Any]:
        """
        Lê recurso document://{id}.
        
        Busca documento real no banco de dados PostgreSQL.
        """
        logger.debug(f"Reading document: {document_id}")
        
        async with get_session_no_commit() as session:
            query = select(Document).where(
                Document.document_id == document_id,
                Document.is_deleted == False
            )
            result = await session.execute(query)
            document = result.scalar_one_or_none()
            
            if not document:
                raise ValueError(f"Document not found: {document_id}")
            
            doc_data = DocumentResource(
                uri=f"document://{document_id}",
                document_id=document.document_id,
                title=document.title,
                content_preview=document.content_preview,
                source_id=document.source_id,
                metadata=document.doc_metadata,
                status=document.status.value if hasattr(document.status, 'value') else str(document.status),
                language=document.language,
                url=document.url,
                ingested_at=document.ingested_at.isoformat() if document.ingested_at else None,
                updated_at=document.updated_at.isoformat() if document.updated_at else None,
                chunks_count=document.chunks_count,
                es_indexed=document.es_indexed
            )
            
            return {
                "contents": [
                    {
                        "uri": f"document://{document_id}",
                        "mimeType": "application/json",
                        "text": doc_data.model_dump_json(indent=2)
                    }
                ]
            }
    
    async def _read_document_chunks(self, document_id: str) -> Dict[str, Any]:
        """
        Lê recurso document://{id}/chunks.
        
        Retorna todos os chunks de um documento.
        """
        logger.debug(f"Reading document chunks: {document_id}")
        
        async with get_session_no_commit() as session:
            # Verificar se documento existe
            doc_query = select(Document).where(
                Document.document_id == document_id,
                Document.is_deleted == False
            )
            doc_result = await session.execute(doc_query)
            document = doc_result.scalar_one_or_none()
            
            if not document:
                raise ValueError(f"Document not found: {document_id}")
            
            # Buscar chunks
            chunks_query = select(DocumentChunk).where(
                DocumentChunk.document_id == document_id
            ).order_by(DocumentChunk.chunk_index)
            
            chunks_result = await session.execute(chunks_query)
            chunks = chunks_result.scalars().all()
            
            chunks_data = []
            for chunk in chunks:
                chunk_data = ChunkResource(
                    uri=f"chunk://{document_id}/{chunk.chunk_index}",
                    document_id=document_id,
                    chunk_index=chunk.chunk_index,
                    text=chunk.chunk_text,
                    token_count=chunk.token_count,
                    char_count=chunk.char_count,
                    section_type=chunk.section_type,
                    has_embedding=chunk.embedding is not None,
                    embedding_model=chunk.embedding_model,
                    metadata=chunk.chunk_metadata or {}
                )
                chunks_data.append(json.loads(chunk_data.model_dump_json()))
            
            return {
                "contents": [
                    {
                        "uri": f"document://{document_id}/chunks",
                        "mimeType": "application/json",
                        "text": json.dumps({
                            "document_id": document_id,
                            "total_chunks": len(chunks_data),
                            "chunks": chunks_data
                        }, indent=2, ensure_ascii=False)
                    }
                ]
            }
    
    async def _read_chunk(self, document_id: str, chunk_index: int) -> Dict[str, Any]:
        """
        Lê recurso chunk://{document_id}/{chunk_index}.
        
        Retorna um chunk específico.
        """
        logger.debug(f"Reading chunk: {document_id}/{chunk_index}")
        
        async with get_session_no_commit() as session:
            query = select(DocumentChunk).where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.chunk_index == chunk_index
            )
            result = await session.execute(query)
            chunk = result.scalar_one_or_none()
            
            if not chunk:
                raise ValueError(f"Chunk not found: {document_id}/{chunk_index}")
            
            chunk_data = ChunkResource(
                uri=f"chunk://{document_id}/{chunk_index}",
                document_id=document_id,
                chunk_index=chunk.chunk_index,
                text=chunk.chunk_text,
                token_count=chunk.token_count,
                char_count=chunk.char_count,
                section_type=chunk.section_type,
                has_embedding=chunk.embedding is not None,
                embedding_model=chunk.embedding_model,
                metadata=chunk.chunk_metadata or {}
            )
            
            return {
                "contents": [
                    {
                        "uri": f"chunk://{document_id}/{chunk_index}",
                        "mimeType": "application/json",
                        "text": chunk_data.model_dump_json(indent=2)
                    }
                ]
            }
    
    async def _read_source_stats(self, source_id: str) -> Dict[str, Any]:
        """
        Lê recurso source://{id}/stats.
        
        Retorna estatísticas detalhadas da fonte do banco de dados.
        """
        logger.debug(f"Reading source stats: {source_id}")
        
        async with get_session_no_commit() as session:
            query = select(SourceRegistry).where(
                SourceRegistry.id == source_id,
                SourceRegistry.deleted_at.is_(None)
            )
            result = await session.execute(query)
            source = result.scalar_one_or_none()
            
            if not source:
                raise ValueError(f"Source not found: {source_id}")
            
            # Get document count by status
            doc_stats_query = select(
                Document.status,
                func.count().label('count')
            ).where(
                Document.source_id == source_id,
                Document.is_deleted == False
            ).group_by(Document.status)
            
            doc_stats_result = await session.execute(doc_stats_query)
            doc_stats = {str(row.status): row.count for row in doc_stats_result.all()}
            
            stats = {
                "source_id": source.id,
                "name": source.name,
                "description": source.description,
                "type": source.type.value if hasattr(source.type, 'value') else str(source.type),
                "status": source.status.value if hasattr(source.status, 'value') else str(source.status),
                
                # Estatísticas do banco
                "statistics": {
                    "total_documents": source.document_count,
                    "documents_by_status": doc_stats,
                    "total_ingested": source.total_documents_ingested,
                    "last_sync": source.last_sync_at.isoformat() if source.last_sync_at else None,
                    "last_success": source.last_success_at.isoformat() if source.last_success_at else None,
                    "consecutive_errors": source.consecutive_errors,
                    "success_rate": round(source.success_rate, 4),
                    "is_healthy": source.is_healthy,
                },
                
                # Configurações
                "config": {
                    "retention_days": source.retention_days,
                    "sensitivity": source.sensitivity.value if hasattr(source.sensitivity, 'value') else str(source.sensitivity),
                },
                
                # Governança
                "governance": {
                    "owner_email": source.owner_email,
                    "created_at": source.created_at.isoformat() if source.created_at else None,
                    "updated_at": source.updated_at.isoformat() if source.updated_at else None,
                }
            }
            
            return {
                "contents": [
                    {
                        "uri": f"source://{source_id}/stats",
                        "mimeType": "application/json",
                        "text": json.dumps(stats, indent=2, ensure_ascii=False, default=str)
                    }
                ]
            }
    
    async def _read_source_list(self) -> Dict[str, Any]:
        """
        Lê recurso source://list.
        
        Lista todas as fontes disponíveis do banco de dados.
        """
        logger.debug("Reading source list")
        
        async with get_session_no_commit() as session:
            from gabi.types import SourceStatus
            
            query = select(SourceRegistry).where(
                SourceRegistry.status == SourceStatus.ACTIVE,
                SourceRegistry.deleted_at.is_(None)
            )
            
            result = await session.execute(query)
            sources = result.scalars().all()
            
            sources_list = []
            for source in sources:
                sources_list.append({
                    "id": source.id,
                    "name": source.name,
                    "description": source.description,
                    "type": source.type.value if hasattr(source.type, 'value') else str(source.type),
                    "document_count": source.document_count,
                    "is_healthy": source.is_healthy,
                })
            
            return {
                "contents": [
                    {
                        "uri": "source://list",
                        "mimeType": "application/json",
                        "text": json.dumps({
                            "sources": sources_list,
                            "total": len(sources_list)
                        }, indent=2, ensure_ascii=False)
                    }
                ]
            }
    
    async def _read_search_health(self) -> Dict[str, Any]:
        """
        Lê recurso search://health.
        
        Retorna health check dos índices de busca.
        """
        logger.debug("Reading search health")
        
        search_service = self._get_search_service()
        
        if not search_service:
            return {
                "contents": [
                    {
                        "uri": "search://health",
                        "mimeType": "application/json",
                        "text": json.dumps({
                            "status": "unknown",
                            "elasticsearch_status": "not_configured",
                            "indices": [],
                            "checked_at": datetime.utcnow().isoformat()
                        }, indent=2)
                    }
                ]
            }
        
        try:
            health = await search_service.health_check()
            
            health_data = SearchHealthResource(
                status=health.status,
                elasticsearch_status=health.status,
                indices=[
                    {
                        "index": idx.index,
                        "status": idx.status,
                        "docs_count": idx.docs_count,
                        "size_mb": idx.size_mb
                    }
                    for idx in health.indices
                ],
                checked_at=datetime.utcnow().isoformat()
            )
            
            return {
                "contents": [
                    {
                        "uri": "search://health",
                        "mimeType": "application/json",
                        "text": health_data.model_dump_json(indent=2)
                    }
                ]
            }
            
        except Exception as e:
            logger.error(f"Error getting search health: {e}")
            return {
                "contents": [
                    {
                        "uri": "search://health",
                        "mimeType": "application/json",
                        "text": json.dumps({
                            "status": "error",
                            "elasticsearch_status": "error",
                            "error": str(e),
                            "indices": [],
                            "checked_at": datetime.utcnow().isoformat()
                        }, indent=2)
                    }
                ]
            }
    
    def subscribe_resource(self, uri: str, callback: Callable) -> None:
        """
        Subscreve para notificações de mudança em um recurso.
        
        TODO: Implementar subscriptions quando houver sistema de eventos.
        """
        logger.debug(f"Subscribe to resource: {uri}")
    
    def unsubscribe_resource(self, uri: str) -> None:
        """Cancela subscrição de recurso."""
        logger.debug(f"Unsubscribe from resource: {uri}")


# =============================================================================
# Singleton
# =============================================================================

_resource_manager: Optional[HybridSearchResourceManager] = None


def get_hybrid_resource_manager() -> HybridSearchResourceManager:
    """Factory para HybridSearchResourceManager singleton."""
    global _resource_manager
    if _resource_manager is None:
        _resource_manager = HybridSearchResourceManager()
    return _resource_manager
