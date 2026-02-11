"""
MCP Hybrid Search Tools - Ferramentas de busca avançada (exata, semântica, híbrida)

Este módulo implementa as ferramentas MCP para busca em documentos jurídicos do TCU:
- search_exact: Busca exata por campos específicos (normas, acórdãos, publicações, leis)
- search_semantic: Busca semântica baseada em significado
- search_hybrid: Busca híbrida combinando exata + semântica com RRF

Integração com ChatTCU via transporte SSE.
Spec: MCP 2025-03-26
"""

import json
import logging
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from gabi.config import settings
from gabi.db import get_session_no_commit
from gabi.models.document import Document
from gabi.models.chunk import DocumentChunk
from gabi.models.source import SourceRegistry
from gabi.services.search_service import SearchService
from gabi.schemas.search import SearchRequest, SearchHit
from gabi.types import SearchType

from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)


# =============================================================================
# Search Field Definitions (by document type)
# =============================================================================

EXACT_SEARCH_FIELDS = {
    "normas": {
        "fields": ["numero", "ano", "tipo", "ementa", "conteudo"],
        "description": "Normas jurídicas (portarias, instruções normativas, resoluções)",
        "examples": {
            "numero": "1234",
            "ano": 2024,
            "tipo": "Portaria",
            "ementa": "Dispõe sobre..."
        }
    },
    "acordaos": {
        "fields": ["numero", "ano", "relator", "ementa", "decisao", "orgao_julgador"],
        "description": "Acórdãos do TCU",
        "examples": {
            "numero": "4567/2024",
            "ano": 2024,
            "relator": "Ministro Nome",
            "orgao_julgador": "Plenário"
        }
    },
    "publicacoes": {
        "fields": ["titulo", "autor", "data_publicacao", "tipo", "revista"],
        "description": "Publicações jurídicas",
        "examples": {
            "titulo": "Título da publicação",
            "autor": "Nome do autor",
            "data_publicacao": "2024-01-15",
            "tipo": "Artigo",
            "revista": "RICE"
        }
    },
    "leis": {
        "fields": ["numero", "ano", "tipo", "ementa", "conteudo"],
        "description": "Leis e decretos",
        "examples": {
            "numero": "14133",
            "ano": 2021,
            "tipo": "Lei"
        }
    }
}


# =============================================================================
# Tool Schemas (JSON Schema for MCP)
# =============================================================================

TOOL_SCHEMAS = {
    "search_exact": {
        "name": "search_exact",
        "description": """Busca exata em documentos jurídicos por campos específicos.
        
Suporta busca precisa em normas, acórdãos, publicações e leis.
Use para encontrar documentos quando você conhece valores específicos de campos.

Exemplos:
- Buscar acórdão por número: {"document_type": "acordaos", "fields": {"numero": "4567/2024"}}
- Buscar normas de 2024: {"document_type": "normas", "fields": {"ano": 2024}}
- Buscar por relator: {"document_type": "acordaos", "fields": {"relator": "Ministro Nome"}}
""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_type": {
                    "type": "string",
                    "enum": ["normas", "acordaos", "publicacoes", "leis"],
                    "description": "Tipo de documento a buscar"
                },
                "fields": {
                    "type": "object",
                    "description": "Campos e valores para busca exata",
                    "properties": {
                        "numero": {"type": "string", "description": "Número do documento"},
                        "ano": {"type": "integer", "description": "Ano do documento"},
                        "tipo": {"type": "string", "description": "Tipo específico (Portaria, Lei, etc.)"},
                        "relator": {"type": "string", "description": "Nome do relator (acórdãos)"},
                        "orgao_julgador": {"type": "string", "description": "Órgão julgador (acórdãos)"},
                        "autor": {"type": "string", "description": "Autor da publicação"},
                        "titulo": {"type": "string", "description": "Título da publicação"},
                        "ementa": {"type": "string", "description": "Texto da ementa"},
                        "decisao": {"type": "string", "description": "Texto da decisão"},
                        "data_publicacao": {"type": "string", "description": "Data de publicação (YYYY-MM-DD)"}
                    },
                    "additionalProperties": True
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filtrar por sources específicas (ex: [\"tcu_acordaos\", \"tcu_normas\"])"
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
            "required": ["document_type", "fields"]
        }
    },
    
    "search_semantic": {
        "name": "search_semantic",
        "description": """Busca semântica baseada no significado do texto.
        
Use para busca conceitual quando você quer encontrar documentos relacionados
a um tema ou conceito, mesmo que não contenham exatamente as mesmas palavras.

Exemplos:
- "licitação pregão eletrônico"
- "princípio da economicidade"
- "responsabilidade fiscal"
""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Texto da consulta em linguagem natural",
                    "minLength": 1,
                    "maxLength": 1000
                },
                "document_type": {
                    "type": "string",
                    "enum": ["normas", "acordaos", "publicacoes", "leis", None],
                    "default": None,
                    "description": "Opcional: filtrar por tipo de documento"
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filtrar por sources específicas"
                },
                "filters": {
                    "type": "object",
                    "description": "Filtros adicionais",
                    "properties": {
                        "year_from": {"type": "integer", "description": "Ano inicial"},
                        "year_to": {"type": "integer", "description": "Ano final"},
                        "relator": {"type": "string", "description": "Nome do relator"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tags para filtrar"
                        }
                    }
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Número máximo de resultados"
                }
            },
            "required": ["query"]
        }
    },
    
    "search_hybrid": {
        "name": "search_hybrid",
        "description": """Busca híbrida combinando busca exata (BM25) e semântica (vetorial) com RRF.
        
Use quando você quer os melhores resultados combinando:
- Precisão da busca por palavras-chave (BM25)
- Cobertura conceitual da busca semântica (vetorial)
- Fusão inteligente via Reciprocal Rank Fusion (RRF)

Exemplos:
- "sustentabilidade fiscal"
- "contratos administrativos"
- "improbidade administrativa"
""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Texto da consulta",
                    "minLength": 1,
                    "maxLength": 1000
                },
                "document_type": {
                    "type": "string",
                    "enum": ["normas", "acordaos", "publicacoes", "leis", None],
                    "default": None,
                    "description": "Opcional: filtrar por tipo de documento"
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filtrar por sources específicas"
                },
                "filters": {
                    "type": "object",
                    "description": "Filtros adicionais",
                    "properties": {
                        "year_from": {"type": "integer", "description": "Ano inicial"},
                        "year_to": {"type": "integer", "description": "Ano final"},
                        "relator": {"type": "string", "description": "Nome do relator"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tags para filtrar"
                        }
                    }
                },
                "hybrid_weights": {
                    "type": "object",
                    "description": "Pesos para fusão híbrida (bm25, vector)",
                    "properties": {
                        "bm25": {
                            "type": "number",
                            "default": 1.0,
                            "minimum": 0,
                            "maximum": 10,
                            "description": "Peso para busca BM25"
                        },
                        "vector": {
                            "type": "number",
                            "default": 1.0,
                            "minimum": 0,
                            "maximum": 10,
                            "description": "Peso para busca vetorial"
                        }
                    }
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
    
    "get_document_details": {
        "name": "get_document_details",
        "description": """Recupera detalhes completos de um documento pelo ID.
        
Inclui metadados, conteúdo preview e opcionalmente os chunks processados.
""",
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
                },
                "include_full_content": {
                    "type": "boolean",
                    "default": False,
                    "description": "Incluir conteúdo completo (se disponível)"
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
# Response Models
# =============================================================================

class ExactSearchResult(BaseModel):
    """Resultado de busca exata."""
    document_id: str
    title: Optional[str]
    source_id: str
    document_type: Optional[str]
    metadata: Dict[str, Any]
    score: float
    matched_fields: List[str]


class SemanticSearchResult(BaseModel):
    """Resultado de busca semântica."""
    document_id: str
    title: Optional[str]
    content_preview: Optional[str]
    source_id: str
    semantic_score: float
    metadata: Dict[str, Any]


class HybridSearchResult(BaseModel):
    """Resultado de busca híbrida com RRF."""
    document_id: str
    title: Optional[str]
    content_preview: Optional[str]
    source_id: str
    rrf_score: float
    bm25_score: Optional[float]
    vector_score: Optional[float]
    rank_bm25: Optional[int]
    rank_vector: Optional[int]
    metadata: Dict[str, Any]
    match_sources: List[str]


# =============================================================================
# Hybrid Search Tool Manager
# =============================================================================

class HybridSearchToolManager:
    """
    Gerenciador de ferramentas MCP para busca híbrida.
    
    Responsável por:
    - Listar ferramentas disponíveis
    - Executar buscas exata, semântica e híbrida
    - Validar parâmetros
    - Integrar com HybridSearchService
    """
    
    def __init__(self):
        self._tools = TOOL_SCHEMAS
        self._handlers = {
            "search_exact": self._handle_search_exact,
            "search_semantic": self._handle_search_semantic,
            "search_hybrid": self._handle_search_hybrid,
            "get_document_details": self._handle_get_document_details,
            "list_sources": self._handle_list_sources,
            "get_source_stats": self._handle_source_stats,
        }
        self._search_service: Optional[SearchService] = None
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """Retorna lista de ferramentas disponíveis."""
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
        
        # Validate arguments
        validation_result = self._validate_arguments(tool_name, arguments)
        if validation_result is not True:
            return validation_result
        
        # Coerce types
        arguments = self._coerce_types(tool_name, arguments)
        
        logger.info(f"Executing tool '{tool_name}' for user {user.get('sub')}")
        
        try:
            handler = self._handlers[tool_name]
            result = await handler(arguments)
            
            return {
                "content": [
                    {
                        "type": "text",
                        "text": self._format_result(result)
                    }
                ],
                "isError": False
            }
        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({
                            "error": str(e),
                            "tool": tool_name
                        }, ensure_ascii=False, indent=2)
                    }
                ],
                "isError": True
            }
    
    def _validate_arguments(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Union[bool, Dict[str, Any]]:
        """Valida argumentos contra o schema da ferramenta."""
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
        
        # Validate field types
        errors = []
        for field, value in arguments.items():
            if field not in properties:
                errors.append(f"Unknown field: {field}")
                continue
                
            prop_schema = properties[field]
            expected_type = prop_schema.get("type")
            
            if expected_type == "string":
                if not isinstance(value, str):
                    errors.append(f"Field '{field}' must be a string")
            elif expected_type == "integer":
                if not isinstance(value, int) or isinstance(value, bool):
                    errors.append(f"Field '{field}' must be an integer")
            elif expected_type == "boolean":
                if not isinstance(value, bool):
                    errors.append(f"Field '{field}' must be a boolean")
            elif expected_type == "array":
                if not isinstance(value, list):
                    errors.append(f"Field '{field}' must be an array")
            elif expected_type == "object":
                if not isinstance(value, dict):
                    errors.append(f"Field '{field}' must be an object")
            
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
        """Converte tipos de argumentos baseado no schema."""
        tool_schema = self._tools.get(tool_name, {}).get("inputSchema", {})
        properties = tool_schema.get("properties", {})
        
        coerced = dict(arguments)
        for field, value in coerced.items():
            if field in properties:
                expected_type = properties[field].get("type")
                
                if expected_type == "integer" and isinstance(value, str):
                    try:
                        coerced[field] = int(value)
                    except ValueError:
                        pass
                elif expected_type == "boolean":
                    if isinstance(value, str):
                        coerced[field] = value.lower() in ("true", "1", "yes", "on")
                    elif isinstance(value, int):
                        coerced[field] = bool(value)
                elif expected_type == "array" and isinstance(value, str):
                    # Try to parse comma-separated string as array
                    coerced[field] = [v.strip() for v in value.split(",")]
                        
        return coerced
    
    def _format_result(self, result: Any) -> str:
        """Formata resultado como JSON string."""
        return json.dumps(result, indent=2, ensure_ascii=False, default=str)
    
    def _get_search_service(self) -> SearchService:
        """Retorna instância do SearchService (lazy initialization)."""
        if self._search_service is None:
            from gabi.db import get_es_client
            self._search_service = SearchService(
                es_client=get_es_client(),
                settings=settings,
                vector_search_backend="elasticsearch",
            )
        return self._search_service
    
    # ========================================================================
    # Tool Handlers
    # ========================================================================
    
    async def _handle_search_exact(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Busca exata por campos específicos.
        
        Implementa busca precisa em normas, acórdãos, publicações e leis.
        """
        document_type = args.get("document_type")
        fields = args.get("fields", {})
        sources = args.get("sources")
        limit = args.get("limit", 10)
        offset = args.get("offset", 0)
        
        logger.debug(f"Exact search: type={document_type}, fields={fields}")
        
        try:
            # Build Elasticsearch query for exact search
            es_query = self._build_exact_query(document_type, fields, sources)
            
            # Execute search
            search_service = self._get_search_service()
            if not search_service.es_client:
                return {
                    "results": [],
                    "total": 0,
                    "search_type": "exact",
                    "document_type": document_type,
                    "fields": fields,
                    "error": "Elasticsearch not configured"
                }
            
            response = await search_service.es_client.search(
                index=search_service.index_name,
                query=es_query,
                size=limit,
                from_=offset,
                timeout=f"{search_service.timeout_ms}ms"
            )
            
            # Format results
            results = []
            matched_fields_list = []
            
            for hit in response.get("hits", {}).get("hits", []):
                source = hit.get("_source", {})
                doc_metadata = source.get("metadata", {})
                
                # Determine which fields matched
                matched = []
                for field, value in fields.items():
                    if self._field_matches(doc_metadata, field, value):
                        matched.append(field)
                
                results.append({
                    "document_id": hit.get("_id", ""),
                    "title": source.get("title"),
                    "source_id": source.get("source_id"),
                    "document_type": doc_metadata.get("tipo") or doc_metadata.get("document_type"),
                    "metadata": doc_metadata,
                    "score": hit.get("_score", 0.0),
                    "matched_fields": matched
                })
            
            return {
                "results": results,
                "total": response.get("hits", {}).get("total", {}).get("value", 0),
                "search_type": "exact",
                "document_type": document_type,
                "fields": fields,
                "limit": limit,
                "offset": offset
            }
            
        except Exception as e:
            logger.error(f"Error in search_exact: {e}")
            return {
                "results": [],
                "total": 0,
                "search_type": "exact",
                "document_type": document_type,
                "fields": fields,
                "error": str(e)
            }
    
    def _build_exact_query(
        self,
        document_type: str,
        fields: Dict[str, Any],
        sources: Optional[List[str]]
    ) -> Dict[str, Any]:
        """Build Elasticsearch query for exact search."""
        must_clauses = []
        
        # Map document type to source filter if possible
        type_to_source = {
            "acordaos": ["tcu_acordaos"],
            "normas": ["tcu_normas", "tcu_instrucoes_normativas", "tcu_portarias"],
            "leis": ["planalto_leis", "planalto_decretos"],
            "publicacoes": ["tcu_publicacoes", "tcu_rice"]
        }
        
        # Build field queries
        for field, value in fields.items():
            if field in ("ano", "year"):
                must_clauses.append({
                    "term": {"metadata.ano": value}
                })
            elif field == "numero":
                must_clauses.append({
                    "match": {"metadata.numero": value}
                })
            elif field == "relator":
                must_clauses.append({
                    "match": {"metadata.relator": {"query": value, "fuzziness": "AUTO"}}
                })
            elif field == "orgao_julgador":
                must_clauses.append({
                    "term": {"metadata.orgao_julgador": value}
                })
            elif field == "tipo":
                must_clauses.append({
                    "term": {"metadata.tipo": value}
                })
            elif field == "autor":
                must_clauses.append({
                    "match": {"metadata.autor": {"query": value, "fuzziness": "AUTO"}}
                })
            elif field == "titulo":
                must_clauses.append({
                    "match": {"title": {"query": value, "boost": 3.0}}
                })
            elif field in ("ementa", "decisao", "conteudo"):
                must_clauses.append({
                    "match": {
                        "content": {"query": value, "boost": 2.0}
                    }
                })
            elif field == "data_publicacao":
                must_clauses.append({
                    "range": {"metadata.data_publicacao": {"gte": value, "lte": value}}}
                )
            else:
                # Generic metadata field
                must_clauses.append({
                    "match": {f"metadata.{field}": value}
                })
        
        # Build filter clauses
        filter_clauses = [{"term": {"is_deleted": False}}]
        
        # Add source filter
        if sources:
            filter_clauses.append({"terms": {"source_id": sources}})
        elif document_type in type_to_source:
            filter_clauses.append({"terms": {"source_id": type_to_source[document_type]}})
        
        return {
            "bool": {
                "must": must_clauses,
                "filter": filter_clauses
            }
        }
    
    def _field_matches(self, metadata: Dict[str, Any], field: str, value: Any) -> bool:
        """Check if a field matches the search value."""
        field_mapping = {
            "ano": ["ano", "year"],
            "numero": ["numero", "number"],
            "relator": ["relator", "relator_nome"],
            "orgao_julgador": ["orgao_julgador", "orgao"],
            "tipo": ["tipo", "type"],
            "autor": ["autor", "author"],
            "titulo": ["titulo", "title"]
        }
        
        possible_keys = field_mapping.get(field, [field])
        
        for key in possible_keys:
            if key in metadata:
                meta_value = str(metadata[key]).lower()
                search_value = str(value).lower()
                if search_value in meta_value or meta_value in search_value:
                    return True
        
        return False
    
    async def _handle_search_semantic(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Busca semântica baseada em significado.
        
        Usa embeddings vetoriais para encontrar documentos semanticamente similares.
        """
        query = args.get("query", "")
        document_type = args.get("document_type")
        sources = args.get("sources")
        filters = args.get("filters", {})
        limit = args.get("limit", 10)
        
        logger.debug(f"Semantic search: query='{query}', type={document_type}")
        
        try:
            search_service = self._get_search_service()
            
            # Get embedding for query
            from gabi.pipeline.embedder import Embedder
            embedder = Embedder(
                base_url=settings.embeddings_url,
                model=settings.embeddings_model,
                batch_size=1,
            )
            
            try:
                embedding = await embedder.embed(query)
            finally:
                await embedder.close()
            
            if not embedding:
                return {
                    "results": [],
                    "total": 0,
                    "search_type": "semantic",
                    "query": query,
                    "error": "Failed to generate embedding"
                }
            
            # Build additional filters
            additional_filters = {}
            if document_type:
                type_to_source = {
                    "acordaos": ["tcu_acordaos"],
                    "normas": ["tcu_normas"],
                    "leis": ["planalto_leis"],
                    "publicacoes": ["tcu_publicacoes"]
                }
                if document_type in type_to_source and not sources:
                    sources = type_to_source[document_type]
            
            # Execute vector search
            from gabi.schemas.search import SearchFilters
            search_filters = None
            if filters:
                search_filters = SearchFilters(
                    source_id=sources[0] if sources and len(sources) == 1 else None,
                    metadata=filters if filters else None
                )
            
            vector_results = await search_service._search_vector(
                embedding=embedding,
                filters=search_filters,
                sources=sources,
                additional_filters=additional_filters if additional_filters else None,
                limit=limit
            )
            
            # Format results
            results = []
            for idx, hit in enumerate(vector_results[:limit]):
                results.append({
                    "document_id": hit.id,
                    "title": hit.title,
                    "content_preview": hit.content_preview or hit.content[:500] if hit.content else None,
                    "source_id": hit.source_id or "unknown",
                    "semantic_score": round(hit.score, 4),
                    "metadata": hit.metadata or {},
                    "rank": idx + 1
                })
            
            return {
                "results": results,
                "total": len(results),
                "search_type": "semantic",
                "query": query,
                "limit": limit,
                "embedding_used": True
            }
            
        except Exception as e:
            logger.error(f"Error in search_semantic: {e}")
            return {
                "results": [],
                "total": 0,
                "search_type": "semantic",
                "query": query,
                "error": str(e)
            }
    
    async def _handle_search_hybrid(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Busca híbrida combinando BM25 + vetorial com RRF.
        
        Executa busca exata e semântica em paralelo e funde resultados via RRF.
        """
        query = args.get("query", "")
        document_type = args.get("document_type")
        sources = args.get("sources")
        filters = args.get("filters", {})
        hybrid_weights = args.get("hybrid_weights", {"bm25": 1.0, "vector": 1.0})
        limit = args.get("limit", 10)
        offset = args.get("offset", 0)
        
        logger.debug(f"Hybrid search: query='{query}', weights={hybrid_weights}")
        
        try:
            search_service = self._get_search_service()
            
            # Build sources filter from document_type if needed
            if document_type and not sources:
                type_to_source = {
                    "acordaos": ["tcu_acordaos"],
                    "normas": ["tcu_normas"],
                    "leis": ["planalto_leis"],
                    "publicacoes": ["tcu_publicacoes"]
                }
                sources = type_to_source.get(document_type)
            
            # Create search request
            search_request = SearchRequest(
                query=query,
                sources=sources,
                filters=filters if filters else None,
                limit=limit,
                offset=offset,
                hybrid_weights=hybrid_weights,
            )
            
            # Execute hybrid search
            response = await search_service.search_api(search_request)
            
            # Format results
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
                    "content_preview": hit.content_preview,
                    "source_id": hit.source_id,
                    "rrf_score": hit.score,
                    "bm25_score": hit.bm25_score,
                    "vector_score": hit.vector_score,
                    "rank_bm25": hit.rank_bm25,
                    "rank_vector": hit.rank_vector,
                    "metadata": hit.metadata,
                    "match_sources": match_sources
                })
            
            return {
                "results": results,
                "total": response.total,
                "search_type": "hybrid",
                "query": response.query,
                "limit": limit,
                "offset": offset,
                "took_ms": response.took_ms,
                "rrf_k": search_service.rrf_k,
                "weights": hybrid_weights
            }
            
        except Exception as e:
            logger.error(f"Error in search_hybrid: {e}")
            return {
                "results": [],
                "total": 0,
                "search_type": "hybrid",
                "query": query,
                "limit": limit,
                "offset": offset,
                "error": str(e)
            }
    
    async def _handle_get_document_details(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Recupera detalhes completos de um documento."""
        document_id = args.get("document_id", "")
        include_chunks = args.get("include_chunks", False)
        include_full_content = args.get("include_full_content", False)
        
        logger.debug(f"Get document details: {document_id}")
        
        try:
            async with get_session_no_commit() as session:
                # Buscar documento
                query = select(Document).where(
                    Document.document_id == document_id,
                    Document.is_deleted == False
                )
                result = await session.execute(query)
                document = result.scalar_one_or_none()
                
                if not document:
                    return {
                        "error": f"Document not found: {document_id}",
                        "document": None
                    }
                
                # Montar resposta
                doc_data = {
                    "document_id": document.document_id,
                    "title": document.title,
                    "content_preview": document.content_preview,
                    "source_id": document.source_id,
                    "metadata": document.doc_metadata,
                    "status": document.status.value if hasattr(document.status, 'value') else str(document.status),
                    "language": document.language,
                    "content_type": document.content_type,
                    "url": document.url,
                    "fingerprint": document.fingerprint,
                    "chunks_count": document.chunks_count,
                    "es_indexed": document.es_indexed,
                    "ingested_at": document.ingested_at.isoformat() if document.ingested_at else None,
                    "updated_at": document.updated_at.isoformat() if document.updated_at else None,
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
                        chunk_data = {
                            "index": chunk.chunk_index,
                            "text": chunk.chunk_text,
                            "token_count": chunk.token_count,
                            "char_count": chunk.char_count,
                            "has_embedding": chunk.embedding is not None,
                            "embedding_model": chunk.embedding_model,
                            "section_type": chunk.section_type,
                            "metadata": chunk.chunk_metadata,
                        }
                        chunks_data.append(chunk_data)
                
                return {
                    "document": doc_data,
                    "chunks": chunks_data if include_chunks else None,
                    "chunks_included": include_chunks
                }
                
        except Exception as e:
            logger.error(f"Error getting document details: {e}")
            return {
                "error": str(e),
                "document": None
            }
    
    async def _handle_list_sources(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Lista fontes disponíveis."""
        include_disabled = args.get("include_disabled", False)
        
        try:
            async with get_session_no_commit() as session:
                from gabi.types import SourceStatus
                
                if include_disabled:
                    query = select(SourceRegistry).where(
                        SourceRegistry.deleted_at.is_(None)
                    )
                else:
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
                        "status": source.status.value if hasattr(source.status, 'value') else str(source.status),
                        "document_count": source.document_count,
                        "last_sync_at": source.last_sync_at.isoformat() if source.last_sync_at else None,
                        "is_healthy": source.is_healthy,
                    })
                
                return {
                    "sources": sources_list,
                    "total": len(sources_list)
                }
                
        except Exception as e:
            logger.error(f"Error listing sources: {e}")
            return {
                "sources": [],
                "total": 0,
                "error": str(e)
            }
    
    async def _handle_source_stats(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Obtém estatísticas de uma fonte."""
        source_id = args.get("source_id", "")
        
        try:
            async with get_session_no_commit() as session:
                query = select(SourceRegistry).where(
                    SourceRegistry.id == source_id,
                    SourceRegistry.deleted_at.is_(None)
                )
                result = await session.execute(query)
                source = result.scalar_one_or_none()
                
                if not source:
                    raise ValueError(f"Source not found: {source_id}")
                
                return {
                    "source_id": source.id,
                    "name": source.name,
                    "description": source.description,
                    "type": source.type.value if hasattr(source.type, 'value') else str(source.type),
                    "status": source.status.value if hasattr(source.status, 'value') else str(source.status),
                    "stats": {
                        "total_documents": source.document_count,
                        "total_ingested": source.total_documents_ingested,
                        "last_sync": source.last_sync_at.isoformat() if source.last_sync_at else None,
                        "last_success": source.last_success_at.isoformat() if source.last_success_at else None,
                        "consecutive_errors": source.consecutive_errors,
                        "success_rate": round(source.success_rate, 4),
                        "is_healthy": source.is_healthy,
                    },
                    "governance": {
                        "owner_email": source.owner_email,
                        "sensitivity": source.sensitivity.value if hasattr(source.sensitivity, 'value') else str(source.sensitivity),
                        "retention_days": source.retention_days,
                        "created_at": source.created_at.isoformat() if source.created_at else None,
                    }
                }
                
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error getting source stats: {e}")
            raise


# =============================================================================
# Singleton
# =============================================================================

_tool_manager: Optional[HybridSearchToolManager] = None


def get_hybrid_tool_manager() -> HybridSearchToolManager:
    """Factory para HybridSearchToolManager singleton."""
    global _tool_manager
    if _tool_manager is None:
        _tool_manager = HybridSearchToolManager()
    return _tool_manager
