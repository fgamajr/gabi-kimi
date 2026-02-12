"""
MCP Resources - Recursos acessíveis via Model Context Protocol

Resources:
- document://{id} - Documento completo
- source://{id}/stats - Estatísticas de fonte

Formato: URI-based resource identification
"""

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

import aiofiles
import yaml

from gabi.config import settings
from gabi.db import get_session_no_commit
from gabi.models.document import Document

from sqlalchemy import select

logger = logging.getLogger(__name__)


# =============================================================================
# Resource Patterns
# =============================================================================

RESOURCE_PATTERNS = {
    "document": re.compile(r"^document://(.+)$"),
    "source_stats": re.compile(r"^source://([^/]+)/stats$"),
    "source_list": re.compile(r"^source://list$"),
}


# =============================================================================
# Resource Manager
# =============================================================================

class MCPResourceManager:
    """
    Gerenciador de recursos MCP.
    
    Recursos são identificados por URIs:
    - document://{document_id} - Documento específico
    - source://{source_id}/stats - Estatísticas da fonte
    - source://list - Lista de fontes
    
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
            }
        ]
    
    def list_resources(self) -> List[Dict[str, Any]]:
        """Retorna lista de templates de recursos disponíveis"""
        return self._uri_templates
    
    async def read_resource(
        self,
        uri: str,
        user: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Lê um recurso pelo URI.
        
        Args:
            uri: URI do recurso (ex: document://TCU-1234/2024)
            user: Informações do usuário autenticado
            
        Returns:
            Conteúdo do recurso no formato MCP
        """
        logger.info(f"Reading resource: {uri} (user: {user.get('sub')})")
        
        # Match patterns
        for resource_type, pattern in RESOURCE_PATTERNS.items():
            match = pattern.match(uri)
            if match:
                if resource_type == "document":
                    return await self._read_document(match.group(1))
                elif resource_type == "source_stats":
                    return await self._read_source_stats(match.group(1))
                elif resource_type == "source_list":
                    return await self._read_source_list()
        
        raise ValueError(f"Invalid resource URI: {uri}")
    
    async def _read_document(self, document_id: str) -> Dict[str, Any]:
        """
        Lê recurso document://{id}.
        
        Busca documento real no banco de dados PostgreSQL.
        """
        logger.debug(f"Reading document: {document_id}")
        
        try:
            async with get_session_no_commit() as session:
                # Buscar documento pelo document_id
                query = select(Document).where(
                    Document.document_id == document_id,
                    Document.is_deleted == False
                )
                result = await session.execute(query)
                document = result.scalar_one_or_none()
                
                if not document:
                    raise ValueError(f"Document not found: {document_id}")
                
                # Montar resposta com dados reais do documento
                doc_data = {
                    "document_id": document.document_id,
                    "title": document.title,
                    "content_preview": document.content_preview,
                    "source_id": document.source_id,
                    "metadata": document.doc_metadata,
                    "status": document.status.value if hasattr(document.status, 'value') else document.status,
                    "ingested_at": document.ingested_at.isoformat() if document.ingested_at else None,
                    "updated_at": document.updated_at.isoformat() if document.updated_at else None,
                    "url": document.url,
                    "language": document.language,
                    "content_type": document.content_type,
                    "fingerprint": document.fingerprint,
                    "chunks_count": document.chunks_count,
                    "es_indexed": document.es_indexed,
                }
                
                return {
                    "contents": [
                        {
                            "uri": f"document://{document_id}",
                            "mimeType": "application/json",
                            "text": self._json_text(doc_data)
                        }
                    ]
                }
                
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to read document {document_id}: {e}")
            raise
    
    async def _read_source_stats(self, source_id: str) -> Dict[str, Any]:
        """
        Lê recurso source://{id}/stats.
        
        Retorna estatísticas detalhadas da fonte.
        """
        logger.debug(f"Reading source stats: {source_id}")
        
        try:
            # Use aiofiles for async file I/O
            async with aiofiles.open(settings.sources_path, "r", encoding="utf-8") as f:
                content = await f.read()
                config = yaml.safe_load(content)
            
            source_config = config.get("sources", {}).get(source_id)
            if not source_config:
                raise ValueError(f"Source not found: {source_id}")
            
            metadata = source_config.get("metadata", {})
            lifecycle = source_config.get("lifecycle", {})
            indexing = source_config.get("indexing", {})
            embedding = source_config.get("embedding", {})
            
            return {
                "contents": [
                    {
                        "uri": f"source://{source_id}/stats",
                        "mimeType": "application/json",
                        "text": self._json_text({
                            "source_id": source_id,
                            "metadata": {
                                "name": metadata.get("description", source_id),
                                "authority": metadata.get("authority"),
                                "document_type": metadata.get("document_type"),
                                "canonical_type": metadata.get("canonical_type"),
                                "jurisdiction": metadata.get("jurisdiction"),
                            },
                            "sync_config": {
                                "frequency": lifecycle.get("sync", {}).get("frequency"),
                                "schedule": lifecycle.get("sync", {}).get("schedule"),
                                "mode": lifecycle.get("sync", {}).get("mode", "incremental"),
                            },
                            "indexing": {
                                "enabled": indexing.get("enabled", True),
                                "strategy": indexing.get("strategy", "hybrid"),
                                "fields": indexing.get("fields", []),
                            },
                            "embedding": {
                                "enabled": embedding.get("enabled", True),
                                "chunking_unit": embedding.get("chunking", {}).get("unit", "semantic_section"),
                                "dimensions": 384,  # IMUTÁVEL conforme ADR-001
                            },
                            # TODO: Estatísticas reais do banco
                            "statistics": {
                                "total_documents": 0,
                                "total_chunks": 0,
                                "last_sync_at": None,
                                "last_success_at": None,
                                "sync_status": "unknown",
                            }
                        })
                    }
                ]
            }
            
        except Exception as e:
            logger.error(f"Failed to read source stats: {e}")
            raise
    
    async def _read_source_list(self) -> Dict[str, Any]:
        """
        Lê recurso source://list.
        
        Lista todas as fontes disponíveis.
        """
        logger.debug("Reading source list")
        
        try:
            # Use aiofiles for async file I/O
            async with aiofiles.open(settings.sources_path, "r", encoding="utf-8") as f:
                content = await f.read()
                config = yaml.safe_load(content)
        except Exception as e:
            logger.error(f"Failed to load sources.yaml: {e}")
            config = {"sources": {}}
        
        sources = []
        for source_id, source_config in config.get("sources", {}).items():
            if not source_config.get("enabled", True):
                continue
            
            metadata = source_config.get("metadata", {})
            sources.append({
                "id": source_id,
                "name": metadata.get("description", source_id),
                "authority": metadata.get("authority"),
                "document_type": metadata.get("document_type"),
                "canonical_type": metadata.get("canonical_type"),
                "discovery_mode": source_config.get("discovery", {}).get("mode"),
            })
        
        return {
            "contents": [
                {
                    "uri": "source://list",
                    "mimeType": "application/json",
                    "text": self._json_text({
                        "sources": sources,
                        "total": len(sources),
                        "authorities": list(set(s["authority"] for s in sources if s.get("authority"))),
                        "document_types": list(set(s["document_type"] for s in sources if s.get("document_type"))),
                    })
                }
            ]
        }
    
    def _json_text(self, data: Dict[str, Any]) -> str:
        """Converte dict para JSON string formatado"""
        return json.dumps(data, indent=2, ensure_ascii=False, default=str)
    
    def subscribe_resource(self, uri: str, callback: callable) -> None:
        """
        Subscreve para notificações de mudança em um recurso.
        
        TODO: Implementar subscriptions quando houver sistema de eventos.
        """
        logger.debug(f"Subscribe to resource: {uri}")
        # Implementação futura com WebSockets ou SSE
    
    def unsubscribe_resource(self, uri: str) -> None:
        """Cancela subscrição de recurso"""
        logger.debug(f"Unsubscribe from resource: {uri}")


# Singleton
_resource_manager: Optional[MCPResourceManager] = None


def get_resource_manager() -> MCPResourceManager:
    """Factory para ResourceManager singleton"""
    global _resource_manager
    if _resource_manager is None:
        _resource_manager = MCPResourceManager()
    return _resource_manager
