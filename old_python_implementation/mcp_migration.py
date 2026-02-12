#!/usr/bin/env python3
"""
MCP Migration Script

This script migrates the old MCP implementation to the new one with enhanced search capabilities.
"""

import os
import shutil
import sys
from pathlib import Path


def backup_old_mcp():
    """Create backup of old MCP files"""
    print("Creating backup of old MCP files...")
    
    mcp_dir = Path("src/gabi/mcp")
    backup_dir = Path("backup_mcp_old")
    
    if backup_dir.exists():
        print(f"Backup directory {backup_dir} already exists. Please remove it first.")
        return False
    
    backup_dir.mkdir(exist_ok=True)
    
    # Files to backup
    files_to_backup = [
        "server.py",
        "tools.py",
        "tools_hybrid.py",
        "resources.py",
        "__init__.py"
    ]
    
    for filename in files_to_backup:
        src_file = mcp_dir / filename
        if src_file.exists():
            dest_file = backup_dir / filename
            shutil.copy2(src_file, dest_file)
            print(f"  Backed up {filename}")
    
    print(f"Backup completed in {backup_dir}")
    return True


def replace_with_new_mcp():
    """Replace old MCP implementation with new one"""
    print("Replacing old MCP with new implementation...")
    
    # Copy the new server to replace the old one
    new_server = Path("src/gabi/mcp/new_server.py")
    old_server = Path("src/gabi/mcp/server.py")
    
    if new_server.exists():
        # Backup the old server first
        backup_server = Path("src/gabi/mcp/server.py.backup")
        if old_server.exists():
            shutil.copy2(old_server, backup_server)
            print(f"  Backed up old server.py to server.py.backup")
        
        # Replace with new server
        shutil.move(str(new_server), str(old_server))
        print(f"  Replaced server.py with new implementation")
    else:
        print("  Error: New server implementation not found!")
        return False
    
    # Update __init__.py to use new server
    init_file = Path("src/gabi/mcp/__init__.py")
    if init_file.exists():
        with open(init_file, 'r') as f:
            content = f.read()
        
        # Update imports to use new server
        new_content = content.replace(
            "from .server import create_mcp_app",
            "from .server import create_mcp_app"
        )
        
        # If the import is different, add the correct one
        if "create_mcp_app" not in new_content:
            new_content += "\nfrom .server import create_mcp_app\n"
        
        with open(init_file, 'w') as f:
            f.write(new_content)
        
        print(f"  Updated __init__.py")
    
    return True


def create_new_tools_module():
    """Create new tools module with enhanced search capabilities"""
    print("Creating new tools module...")
    
    tools_content = '''
"""
Enhanced MCP Tools - Advanced search capabilities for legal documents

This module implements tools for:
- Exact match search using Elasticsearch
- Semantic search using embeddings  
- Hybrid search combining both approaches
"""

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from gabi.config import settings
from gabi.db import get_es_client
from gabi.pipeline.embedder import Embedder
from gabi.services.search_service import SearchService
from gabi.types import SearchType

logger = logging.getLogger(__name__)


# =============================================================================
# Tool Schemas
# =============================================================================

TOOL_SCHEMAS = {
    "search_exact": {
        "name": "search_exact",
        "description": "Busca exata em normas, acórdãos, publicações, leis usando Elasticsearch",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Termo de busca exata",
                    "minLength": 1,
                    "maxLength": 500
                },
                "document_type": {
                    "type": "string",
                    "enum": ["normas", "acordaos", "publicacoes", "leis", "sumulas", "instrucoes_normativas"],
                    "description": "Tipo de documento a pesquisar"
                },
                "filters": {
                    "type": "object",
                    "properties": {
                        "year": {"type": "integer", "description": "Ano do documento"},
                        "numero": {"type": "string", "description": "Número do documento"},
                        "relator": {"type": "string", "description": "Relator do acórdão"},
                        "orgao_julgador": {"type": "string", "description": "Órgão julgador"}
                    },
                    "description": "Filtros adicionais para refinar a busca"
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Número máximo de resultados"
                }
            },
            "required": ["query", "document_type"]
        }
    },
    
    "search_semantic": {
        "name": "search_semantic", 
        "description": "Busca semântica usando embeddings para encontrar documentos conceitualmente relacionados",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string", 
                    "description": "Consulta semântica em linguagem natural",
                    "minLength": 1,
                    "maxLength": 1000
                },
                "document_type": {
                    "type": "string",
                    "enum": ["normas", "acordaos", "publicacoes", "leis", "sumulas", "instrucoes_normativas"],
                    "description": "Tipo de documento a pesquisar"
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
        "description": "Busca híbrida combinando busca exata e semântica com RRF (Reciprocal Rank Fusion)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Consulta para busca híbrida",
                    "minLength": 1,
                    "maxLength": 1000
                },
                "document_type": {
                    "type": "string",
                    "enum": ["normas", "acordaos", "publicacoes", "leis", "sumulas", "instrucoes_normativas"],
                    "description": "Tipo de documento a pesquisar"
                },
                "weight_bm25": {
                    "type": "number",
                    "default": 0.7,
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Peso para busca BM25 (exata)"
                },
                "weight_vector": {
                    "type": "number", 
                    "default": 0.3,
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Peso para busca vetorial (semântica)"
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
    
    "get_document_by_id": {
        "name": "get_document_by_id",
        "description": "Recupera documento completo por ID",
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "string",
                    "description": "ID único do documento"
                },
                "include_content": {
                    "type": "boolean",
                    "default": False,
                    "description": "Incluir conteúdo completo do documento"
                }
            },
            "required": ["document_id"]
        }
    }
}


class EnhancedMCPTools:
    """Enhanced tools with exact match and hybrid search capabilities"""
    
    def __init__(self):
        self.es_client = get_es_client()
        self.embedder = Embedder(
            base_url=settings.embeddings_url,
            model=settings.embeddings_model,
            dimensions=settings.embeddings_dimensions
        )
        self.search_service = SearchService(
            es_client=self.es_client,
            settings=settings
        )
    
    async def search_exact(self, query: str, document_type: str, filters: Optional[Dict] = None, limit: int = 10) -> Dict[str, Any]:
        """Perform exact match search using Elasticsearch"""
        try:
            # Build query based on document type and filters
            es_query = self._build_exact_query(query, document_type, filters)
            
            response = await self.es_client.search(
                index=settings.elasticsearch_index,
                query=es_query,
                size=limit
            )
            
            results = []
            for hit in response.get("hits", {}).get("hits", []):
                source = hit.get("_source", {})
                results.append({
                    "document_id": hit.get("_id", ""),
                    "title": source.get("title", ""),
                    "content_preview": source.get("content_preview", "")[:300],
                    "source_id": source.get("source_id", ""),
                    "metadata": source.get("metadata", {}),
                    "score": hit.get("_score", 0.0),
                    "highlight": hit.get("highlight", {})
                })
            
            return {
                "results": results,
                "total": response.get("hits", {}).get("total", {}).get("value", 0),
                "search_type": "exact",
                "query": query,
                "document_type": document_type
            }
        except Exception as e:
            logger.error(f"Exact search failed: {e}")
            return {"results": [], "total": 0, "error": str(e), "search_type": "exact"}
    
    async def search_semantic(self, query: str, document_type: str, limit: int = 10) -> Dict[str, Any]:
        """Perform semantic search using embeddings"""
        try:
            # Get embedding for the query
            query_embedding = await self.embedder.embed(query)
            
            if not query_embedding:
                return {"results": [], "total": 0, "error": "Failed to generate embedding", "search_type": "semantic"}
            
            # Prepare filters
            filters = {"document_type": document_type} if document_type else None
            
            # Perform vector search
            response = await self.search_service.search_vectors(
                query_embedding,
                filters=filters,
                limit=limit
            )
            
            results = []
            for hit in response.hits:
                results.append({
                    "document_id": hit.document_id,
                    "title": hit.title,
                    "content_preview": hit.content_preview[:300] if hit.content_preview else "",
                    "source_id": hit.source_id,
                    "metadata": hit.metadata,
                    "score": hit.score,
                    "distance": hit.distance if hasattr(hit, 'distance') else None
                })
            
            return {
                "results": results,
                "total": response.total,
                "search_type": "semantic",
                "query": query,
                "document_type": document_type
            }
        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return {"results": [], "total": 0, "error": str(e), "search_type": "semantic"}
    
    async def search_hybrid(self, query: str, document_type: str, weight_bm25: float = 0.7, weight_vector: float = 0.3, limit: int = 10) -> Dict[str, Any]:
        """Perform hybrid search combining exact and semantic with weighted scoring"""
        try:
            # Run both searches
            exact_results = await self.search_exact(query, document_type, limit=limit*2)  # Get more for fusion
            semantic_results = await self.search_semantic(query, document_type, limit=limit*2)  # Get more for fusion
            
            # Combine results using weighted RRF
            combined_results = self._fuse_results_weighted_rrf(
                exact_results.get("results", []),
                semantic_results.get("results", []),
                weight_bm25,
                weight_vector,
                limit
            )
            
            return {
                "results": combined_results,
                "total": len(combined_results),
                "search_type": "hybrid",
                "query": query,
                "document_type": document_type,
                "weight_bm25": weight_bm25,
                "weight_vector": weight_vector,
                "exact_results_count": len(exact_results.get("results", [])),
                "semantic_results_count": len(semantic_results.get("results", []))
            }
        except Exception as e:
            logger.error(f"Hybrid search failed: {e}")
            return {"results": [], "total": 0, "error": str(e), "search_type": "hybrid"}
    
    def _build_exact_query(self, query: str, document_type: str, filters: Optional[Dict] = None) -> Dict[str, Any]:
        """Build Elasticsearch query for exact search"""
        # Base query structure
        bool_query = {"bool": {"should": [], "filter": []}}
        
        # Add document type filter if specified
        if document_type:
            bool_query["bool"]["filter"].append({
                "term": {"metadata.document_type.keyword": document_type}
            })
        
        # Add additional filters
        if filters:
            for field, value in filters.items():
                if field == "year":
                    bool_query["bool"]["filter"].append({
                        "term": {f"metadata.ano": value}
                    })
                elif field == "numero":
                    bool_query["bool"]["should"].append({
                        "match_phrase": {f"metadata.numero": {"query": value, "boost": 2.0}}
                    })
                elif field == "relator":
                    bool_query["bool"]["should"].append({
                        "match_phrase": {f"metadata.relator": {"query": value, "boost": 1.5}}
                    })
                elif field == "orgao_julgador":
                    bool_query["bool"]["should"].append({
                        "match_phrase": {f"metadata.orgao_julgador": {"query": value, "boost": 1.5}}
                    })
        
        # Add text search in multiple fields
        text_search_fields = [
            {"match_phrase": {"title": {"query": query, "boost": 3.0}}},
            {"match": {"title": {"query": query, "boost": 2.0}}},
            {"match_phrase": {"content": {"query": query, "boost": 2.0}}},
            {"match": {"content": {"query": query, "boost": 1.0}}},
            {"match_phrase": {"metadata.ementa": {"query": query, "boost": 2.5}}},
            {"match_phrase": {"metadata.decisao": query}},
        ]
        
        bool_query["bool"]["should"].extend(text_search_fields)
        
        # Add filter for non-deleted documents
        bool_query["bool"]["filter"].append({"term": {"is_deleted": False}})
        
        # Use dis_max to pick the best match from should clauses
        query_body = {
            "dis_max": {
                "queries": [bool_query],
                "tie_breaker": 0.7
            }
        }
        
        return query_body
    
    def _fuse_results_weighted_rrf(self, bm25_results: List[Dict], vector_results: List[Dict], weight_bm25: float, weight_vector: float, limit: int) -> List[Dict]:
        """Fuse results using weighted Reciprocal Rank Fusion"""
        # Create a map of document_id to all occurrences with scores
        scores_map = {}
        
        # Add BM25 scores with weight
        for rank, result in enumerate(bm25_results, 1):
            doc_id = result["document_id"]
            if doc_id not in scores_map:
                scores_map[doc_id] = {"result": result, "weighted_score": 0.0}
            # Weighted RRF score: weight * (1 / (k + rank))
            scores_map[doc_id]["weighted_score"] += weight_bm25 * (1.0 / (60 + rank))
        
        # Add Vector scores with weight
        for rank, result in enumerate(vector_results, 1):
            doc_id = result["document_id"]
            if doc_id not in scores_map:
                # Use the vector result as base if not in bm25 results
                scores_map[doc_id] = {"result": result, "weighted_score": 0.0}
            # Weighted RRF score: weight * (1 / (k + rank))
            scores_map[doc_id]["weighted_score"] += weight_vector * (1.0 / (60 + rank))
        
        # Sort by weighted score and return top results
        sorted_results = sorted(
            scores_map.values(),
            key=lambda x: x["weighted_score"],
            reverse=True
        )
        
        # Return the results up to the limit
        return [item["result"] for item in sorted_results[:limit]]
    
    async def get_document_by_id(self, document_id: str, include_content: bool = False) -> Dict[str, Any]:
        """Retrieve document by ID"""
        try:
            # Get document from Elasticsearch
            response = await self.es_client.get(
                index=settings.elasticsearch_index,
                id=document_id
            )
            
            source = response["_source"]
            
            result = {
                "document_id": response["_id"],
                "title": source.get("title", ""),
                "source_id": source.get("source_id", ""),
                "metadata": source.get("metadata", {}),
                "created_at": source.get("created_at"),
                "updated_at": source.get("updated_at"),
            }
            
            if include_content:
                result["content"] = source.get("content", "")
                result["content_preview"] = source.get("content_preview", "")
            
            return {
                "document": result,
                "found": True
            }
        except Exception as e:
            logger.error(f"Get document by ID failed: {e}")
            return {
                "document": None,
                "found": False,
                "error": str(e)
            }


# Singleton
_enhanced_tools: Optional[EnhancedMCPTools] = None


def get_enhanced_tools() -> EnhancedMCPTools:
    """Get singleton instance of enhanced tools"""
    global _enhanced_tools
    if _enhanced_tools is None:
        _enhanced_tools = EnhancedMCPTools()
    return _enhanced_tools
'''
    
    tools_file = Path("src/gabi/mcp/tools.py")
    with open(tools_file, 'w') as f:
        f.write(tools_content)
    
    print(f"  Created new enhanced tools module")
    return True


def finalize_migration():
    """Finalize the migration process"""
    print("Finalizing migration...")
    
    # Remove the temporary new_server.py if it still exists
    new_server = Path("src/gabi/mcp/new_server.py")
    if new_server.exists():
        new_server.unlink()
        print("  Removed temporary new_server.py")
    
    print("\nMigration completed successfully!")
    print("\nNew MCP features:")
    print("- Exact match search for normas, acórdãos, publicações, leis")
    print("- Semantic search using embeddings")
    print("- Hybrid search with weighted RRF")
    print("- Advanced filtering capabilities")
    print("- Improved error handling")
    
    return True


def main():
    """Main migration function"""
    print("GABI MCP Migration to Enhanced Search Implementation")
    print("="*55)
    
    # Ask for confirmation
    response = input("\nThis will replace the old MCP implementation with the new enhanced version.\nDo you want to continue? (yes/no): ")
    if response.lower() not in ['yes', 'y']:
        print("Migration cancelled.")
        return
    
    print("\nStarting migration...\n")
    
    # Step 1: Backup old MCP
    if not backup_old_mcp():
        print("Migration failed during backup step.")
        return
    
    # Step 2: Create new tools module
    if not create_new_tools_module():
        print("Migration failed during tools creation step.")
        return
    
    # Step 3: Replace with new server
    if not replace_with_new_mcp():
        print("Migration failed during server replacement step.")
        return
    
    # Step 4: Finalize
    if not finalize_migration():
        print("Migration failed during finalization step.")
        return
    
    print("\nThe new MCP implementation is now active!")
    print("You can start the server with: python -m gabi.mcp.server")


if __name__ == "__main__":
    main()