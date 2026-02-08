"""
MCP Tools - Ferramentas disponíveis via Model Context Protocol

Tools:
- search_documents: Busca híbrida em documentos
- get_document_by_id: Recupera documento por ID
- list_sources: Lista fontes disponíveis
- get_source_stats: Estatísticas de uma fonte
"""

import logging
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, ValidationError, field_validator

from gabi.config import settings
from gabi.db import get_session_no_commit
from gabi.models.document import Document
from gabi.models.chunk import DocumentChunk
from gabi.models.source import SourceRegistry
from gabi.services.search_service import SearchService
from gabi.schemas.search import SearchRequest
from gabi.types import SearchType

from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)


# =============================================================================
# Tool Definitions
# =============================================================================

TOOL_SCHEMAS = {
    "search_documents": {
        "name": "search_documents",
        "description": "Realiza busca híbrida (texto + semântica) em documentos jurídicos do TCU",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Termos de busca ou pergunta em linguagem natural"
                },
                "search_type": {
                    "type": "string",
                    "enum": ["hybrid", "text", "semantic"],
                    "default": "hybrid",
                    "description": "Tipo de busca: hybrid (padrão), text (BM25), semantic (vetorial)"
                },
                "filters": {
                    "type": "object",
                    "properties": {
                        "source_id": {
                            "type": "string",
                            "description": "Filtrar por fonte específica (ex: tcu_acordaos)"
                        },
                        "year": {
                            "type": "integer",
                            "description": "Ano do documento"
                        },
                        "year_from": {
                            "type": "integer",
                            "description": "Ano inicial (range)"
                        },
                        "year_to": {
                            "type": "integer",
                            "description": "Ano final (range)"
                        },
                        "type": {
                            "type": "string",
                            "description": "Tipo de documento"
                        },
                        "relator": {
                            "type": "string",
                            "description": "Nome do relator"
                        }
                    },
                    "description": "Filtros opcionais para refinar a busca"
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Número máximo de resultados"
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "minimum": 0,
                    "description": "Offset para paginação"
                }
            },
            "required": ["query"]
        }
    },
    
    "get_document_by_id": {
        "name": "get_document_by_id",
        "description": "Recupera um documento completo pelo seu ID único",
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "string",
                    "description": "ID único do documento (ex: TCU-1234/2024)"
                },
                "include_chunks": {
                    "type": "boolean",
                    "default": False,
                    "description": "Incluir chunks e embeddings do documento"
                }
            },
            "required": ["document_id"]
        }
    },
    
    "list_sources": {
        "name": "list_sources",
        "description": "Lista todas as fontes de dados disponíveis no GABI",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_disabled": {
                    "type": "boolean",
                    "default": False,
                    "description": "Incluir fontes desabilitadas"
                }
            }
        }
    },
    
    "get_source_stats": {
        "name": "get_source_stats",
        "description": "Obtém estatísticas detalhadas de uma fonte de dados",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_id": {
                    "type": "string",
                    "description": "ID da fonte (ex: tcu_acordaos)"
                }
            },
            "required": ["source_id"]
        }
    }
}


# =============================================================================
# Tool Manager
# =============================================================================

class MCPToolManager:
    """
    Gerenciador de ferramentas MCP.
    
    Responsável por:
    - Listar ferramentas disponíveis
    - Executar ferramentas
    - Validar parâmetros
    """
    
    def __init__(self):
        self._tools = TOOL_SCHEMAS
        self._handlers = {
            "search_documents": self._handle_search_documents,
            "get_document_by_id": self._handle_get_document,
            "list_sources": self._handle_list_sources,
            "get_source_stats": self._handle_source_stats,
        }
        # Lazy initialization do SearchService
        self._search_service: Optional[SearchService] = None
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """Retorna lista de ferramentas disponíveis"""
        return list(self._tools.values())
    
    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Executa uma ferramenta.
        
        Args:
            tool_name: Nome da ferramenta
            arguments: Argumentos da ferramenta
            user: Informações do usuário autenticado
            
        Returns:
            Resultado da execução no formato MCP
        """
        if tool_name not in self._handlers:
            raise ValueError(f"Tool not found: {tool_name}")
        
        # Validate arguments against schema before execution
        validation_result = self._validate_arguments(tool_name, arguments)
        if validation_result is not True:
            return validation_result
        
        # Coerce types after validation
        arguments = self._coerce_types(tool_name, arguments)
        
        logger.info(f"Executing tool '{tool_name}' for user {user.get('sub')}")
        
        handler = self._handlers[tool_name]
        result = await handler(arguments)
        
        # Formatar resultado no padrão MCP (content array)
        return {
            "content": [
                {
                    "type": "text",
                    "text": self._format_result(result)
                }
            ],
            "isError": False
        }
    
    def _validate_arguments(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Union[bool, Dict[str, Any]]:
        """
        Valida argumentos contra o schema da ferramenta.
        
        Args:
            tool_name: Nome da ferramenta
            arguments: Argumentos a validar
            
        Returns:
            True se válido, ou dict de erro MCP se inválido
        """
        tool_schema = self._tools.get(tool_name, {}).get("inputSchema", {})
        properties = tool_schema.get("properties", {})
        required = tool_schema.get("required", [])
        
        # Check required fields
        missing = [field for field in required if field not in arguments]
        if missing:
            return {
                "content": [{"type": "text", "text": f"Missing required field(s): {', '.join(missing)}"}],
                "isError": True
            }
        
        # Validate field types and constraints
        errors = []
        for field, value in arguments.items():
            if field not in properties:
                errors.append(f"Unknown field: {field}")
                continue
                
            prop_schema = properties[field]
            expected_type = prop_schema.get("type")
            
            # Type validation
            if expected_type == "string":
                if not isinstance(value, str):
                    errors.append(f"Field '{field}' must be a string, got {type(value).__name__}")
                    continue
                # String length validation
                min_length = prop_schema.get("minLength")
                max_length = prop_schema.get("maxLength")
                if min_length is not None and len(value) < min_length:
                    errors.append(f"Field '{field}' must be at least {min_length} characters")
                if max_length is not None and len(value) > max_length:
                    errors.append(f"Field '{field}' must be at most {max_length} characters")
                    
            elif expected_type == "integer":
                if not isinstance(value, int) or isinstance(value, bool):
                    errors.append(f"Field '{field}' must be an integer, got {type(value).__name__}")
                    continue
                # Integer range validation
                minimum = prop_schema.get("minimum")
                maximum = prop_schema.get("maximum")
                if minimum is not None and value < minimum:
                    errors.append(f"Field '{field}' must be >= {minimum}")
                if maximum is not None and value > maximum:
                    errors.append(f"Field '{field}' must be <= {maximum}")
                    
            elif expected_type == "boolean":
                if not isinstance(value, bool):
                    errors.append(f"Field '{field}' must be a boolean, got {type(value).__name__}")
                    
            elif expected_type == "object":
                if not isinstance(value, dict):
                    errors.append(f"Field '{field}' must be an object, got {type(value).__name__}")
                    
            elif expected_type == "array":
                if not isinstance(value, list):
                    errors.append(f"Field '{field}' must be an array, got {type(value).__name__}")
                    continue
                # Array items validation
                items_schema = prop_schema.get("items")
                if items_schema:
                    item_type = items_schema.get("type")
                    for idx, item in enumerate(value):
                        if item_type == "string" and not isinstance(item, str):
                            errors.append(f"Field '{field}[{idx}]' must be a string")
                        elif item_type == "integer" and not isinstance(item, int):
                            errors.append(f"Field '{field}[{idx}]' must be an integer")
            
            # Enum validation
            enum_values = prop_schema.get("enum")
            if enum_values is not None and value not in enum_values:
                errors.append(f"Field '{field}' must be one of: {', '.join(map(str, enum_values))}")
        
        if errors:
            return {
                "content": [{"type": "text", "text": "Validation errors:\n" + "\n".join(f"- {e}" for e in errors)}],
                "isError": True
            }
        
        return True
    
    def _coerce_types(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Coerce argument types based on schema (for flexible input handling).
        
        Args:
            tool_name: Nome da ferramenta
            arguments: Argumentos a converter
            
        Returns:
            Argumentos com tipos convertidos
        """
        tool_schema = self._tools.get(tool_name, {}).get("inputSchema", {})
        properties = tool_schema.get("properties", {})
        
        coerced = dict(arguments)
        for field, value in coerced.items():
            if field in properties:
                expected_type = properties[field].get("type")
                
                # Try to coerce string to int for integer fields
                if expected_type == "integer" and isinstance(value, str):
                    try:
                        coerced[field] = int(value)
                    except ValueError:
                        pass  # Validation will catch this
                        
                # Try to coerce int/float to bool for boolean fields
                elif expected_type == "boolean":
                    if isinstance(value, str):
                        coerced[field] = value.lower() in ("true", "1", "yes", "on")
                    elif isinstance(value, int):
                        coerced[field] = bool(value)
                        
        return coerced
    
    def _format_result(self, result: Any) -> str:
        """Formata resultado como JSON string"""
        import json
        return json.dumps(result, indent=2, ensure_ascii=False, default=str)
    
    def _get_search_service(self) -> SearchService:
        """Retorna instância do SearchService (lazy initialization)."""
        if self._search_service is None:
            from gabi.db import get_es_client
            self._search_service = SearchService(
                es_client=get_es_client(),
                settings=settings,
            )
        return self._search_service
    
    # ========================================================================
    # Tool Handlers
    # ========================================================================
    
    async def _handle_search_documents(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Busca documentos usando SearchService.
        
        Integração real com Elasticsearch para busca híbrida (BM25 + Vetorial).
        """
        query = args.get("query", "")
        search_type = args.get("search_type", "hybrid")
        filters = args.get("filters", {})
        limit = args.get("limit", 10)
        offset = args.get("offset", 0)
        
        logger.debug(f"Search: query='{query}', type={search_type}, filters={filters}")
        
        try:
            # Converter search_type string para enum
            search_type_enum = SearchType(search_type)
            
            # Configurar pesos baseados no tipo de busca
            hybrid_weights = None
            if search_type_enum == SearchType.TEXT:
                hybrid_weights = {"bm25": 1.0, "vector": 0.0}
            elif search_type_enum == SearchType.SEMANTIC:
                hybrid_weights = {"bm25": 0.0, "vector": 1.0}
            else:  # HYBRID
                hybrid_weights = {"bm25": 1.0, "vector": 1.0}
            
            # Criar request de busca
            search_request = SearchRequest(
                query=query,
                sources=[filters.get("source_id")] if filters.get("source_id") else None,
                filters=filters if filters else None,
                limit=limit,
                offset=offset,
                hybrid_weights=hybrid_weights,
            )
            
            # Executar busca via SearchService
            search_service = self._get_search_service()
            response = await search_service.search_api(search_request)
            
            # Formatar resultados
            results = []
            for hit in response.hits:
                match_sources = []
                if hit.bm25_score is not None:
                    match_sources.append("bm25")
                if hit.vector_score is not None:
                    match_sources.append("vector")
                
                results.append({
                    "document_id": hit.document_id,
                    "title": hit.title,
                    "snippet": hit.content_preview,
                    "source_id": hit.source_id,
                    "metadata": hit.metadata,
                    "score": hit.score,
                    "match_sources": match_sources,
                })
            
            return {
                "results": results,
                "total": response.total,
                "query": response.query,
                "search_type": search_type,
                "limit": limit,
                "offset": offset,
                "took_ms": response.took_ms,
            }
            
        except Exception as e:
            logger.error(f"Error in search_documents: {e}")
            return {
                "results": [],
                "total": 0,
                "query": query,
                "search_type": search_type,
                "limit": limit,
                "offset": offset,
                "error": str(e),
            }
    
    async def _handle_get_document(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recupera documento por ID do banco de dados.
        
        Busca real no PostgreSQL usando SQLAlchemy.
        """
        document_id = args.get("document_id", "")
        include_chunks = args.get("include_chunks", False)
        
        logger.debug(f"Get document: {document_id}, include_chunks={include_chunks}")
        
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
                    return {
                        "error": f"Document not found: {document_id}",
                        "document": None,
                        "chunks": [],
                    }
                
                # Montar resposta do documento
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
                    "chunks_count": document.chunks_count,
                }
                
                # Buscar chunks se solicitado
                chunks_data = []
                if include_chunks and document.chunks_count > 0:
                    chunks_query = select(DocumentChunk).where(
                        DocumentChunk.document_id == document_id
                    ).order_by(DocumentChunk.chunk_index)
                    
                    chunks_result = await session.execute(chunks_query)
                    chunks = chunks_result.scalars().all()
                    
                    for chunk in chunks:
                        chunks_data.append({
                            "index": chunk.chunk_index,
                            "text": chunk.chunk_text,
                            "token_count": chunk.token_count,
                            "char_count": chunk.char_count,
                            "has_embedding": chunk.embedding is not None,
                            "embedding_model": chunk.embedding_model,
                            "section_type": chunk.section_type,
                            "metadata": chunk.chunk_metadata,
                        })
                
                return {
                    "document": doc_data,
                    "chunks": chunks_data,
                }
                
        except Exception as e:
            logger.error(f"Error in get_document_by_id: {e}")
            return {
                "error": str(e),
                "document": None,
                "chunks": [],
            }
    
    async def _handle_list_sources(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Lista fontes disponíveis do banco de dados.
        
        Query real na tabela SourceRegistry.
        """
        include_disabled = args.get("include_disabled", False)
        
        try:
            async with get_session_no_commit() as session:
                # Construir query base
                if include_disabled:
                    # Incluir todas as fontes não deletadas
                    query = select(SourceRegistry).where(
                        SourceRegistry.deleted_at.is_(None)
                    )
                else:
                    # Apenas fontes ativas
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
                        "type": source.type.value if hasattr(source.type, 'value') else source.type,
                        "status": source.status.value if hasattr(source.status, 'value') else source.status,
                        "document_count": source.document_count,
                        "total_documents_ingested": source.total_documents_ingested,
                        "last_sync_at": source.last_sync_at.isoformat() if source.last_sync_at else None,
                        "last_success_at": source.last_success_at.isoformat() if source.last_success_at else None,
                        "consecutive_errors": source.consecutive_errors,
                        "is_healthy": source.is_healthy,
                        "owner_email": source.owner_email,
                        "sensitivity": source.sensitivity.value if hasattr(source.sensitivity, 'value') else source.sensitivity,
                        "created_at": source.created_at.isoformat() if source.created_at else None,
                    })
                
                return {
                    "sources": sources_list,
                    "total": len(sources_list),
                }
                
        except Exception as e:
            logger.error(f"Error in list_sources: {e}")
            return {
                "sources": [],
                "total": 0,
                "error": str(e),
            }
    
    async def _handle_source_stats(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Obtém estatísticas de uma fonte do banco de dados.
        
        Dados reais da tabela SourceRegistry.
        """
        source_id = args.get("source_id", "")
        
        logger.debug(f"Get source stats: {source_id}")
        
        try:
            async with get_session_no_commit() as session:
                # Buscar fonte no banco
                query = select(SourceRegistry).where(
                    SourceRegistry.id == source_id,
                    SourceRegistry.deleted_at.is_(None)
                )
                result = await session.execute(query)
                source = result.scalar_one_or_none()
                
                if not source:
                    raise ValueError(f"Source not found: {source_id}")
                
                # Extrair configurações relevantes se disponíveis
                config = source.config_json or {}
                sync_config = config.get("lifecycle", {}).get("sync", {})
                indexing_config = config.get("indexing", {})
                embedding_config = config.get("embedding", {})
                
                return {
                    "source_id": source.id,
                    "name": source.name,
                    "description": source.description,
                    "type": source.type.value if hasattr(source.type, 'value') else source.type,
                    "status": source.status.value if hasattr(source.status, 'value') else source.status,
                    
                    # Estatísticas reais do banco
                    "stats": {
                        "total_documents": source.document_count,
                        "total_documents_ingested": source.total_documents_ingested,
                        "last_sync": source.last_sync_at.isoformat() if source.last_sync_at else None,
                        "last_success": source.last_success_at.isoformat() if source.last_success_at else None,
                        "consecutive_errors": source.consecutive_errors,
                        "last_error_at": source.last_error_at.isoformat() if source.last_error_at else None,
                        "last_error_message": source.last_error_message,
                        "last_document_at": source.last_document_at.isoformat() if source.last_document_at else None,
                        "success_rate": round(source.success_rate, 4),
                        "is_healthy": source.is_healthy,
                    },
                    
                    # Configurações da fonte
                    "config": {
                        "sync_frequency": sync_config.get("frequency"),
                        "indexing_enabled": indexing_config.get("enabled", True) if indexing_config else True,
                        "embedding_enabled": embedding_config.get("enabled", True) if embedding_config else True,
                        "retention_days": source.retention_days,
                        "sensitivity": source.sensitivity.value if hasattr(source.sensitivity, 'value') else source.sensitivity,
                    },
                    
                    # Governança
                    "governance": {
                        "owner_email": source.owner_email,
                        "created_at": source.created_at.isoformat() if source.created_at else None,
                        "updated_at": source.updated_at.isoformat() if source.updated_at else None,
                        "config_hash": source.config_hash,
                    }
                }
                
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to get source stats: {e}")
            raise


# Singleton
_tool_manager: Optional[MCPToolManager] = None


def get_tool_manager() -> MCPToolManager:
    """Factory para ToolManager singleton"""
    global _tool_manager
    if _tool_manager is None:
        _tool_manager = MCPToolManager()
    return _tool_manager
