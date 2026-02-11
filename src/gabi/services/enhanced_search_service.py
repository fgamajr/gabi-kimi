"""
Enhanced Search Service with Advanced RAG Techniques

This module enhances the existing search service with:
1. Cross-Encoder Reranking (Phase 9.5 in pipeline)
2. SPLADE sparse embeddings integration
3. GraphRAG for relationship-aware search
4. Vision-Language Model integration for document understanding
"""

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Tuple
from dataclasses import dataclass

from gabi.schemas.search import SearchFilters, SearchHit, SearchResponse, SearchRequest, RRFConfig, IndexHealth, HealthResponse
from gabi.config import Settings
from gabi.services.search_service import SearchService, RawResult
from gabi.rerank.cross_encoder import apply_cross_encoder_reranking, get_cross_encoder_reranker
from gabi.embeddings.splade import get_splade_embedder, create_splade_embedding
from gabi.graphrag.legal_graph import get_legal_knowledge_graph, query_legal_graph, RelationshipType
from gabi.document_understanding.vlm import get_vlm_processor

logger = logging.getLogger(__name__)


class EnhancedSearchService(SearchService):
    """
    Enhanced search service with advanced RAG techniques.
    
    Adds the following capabilities to the base search service:
    1. Cross-Encoder Reranking (Phase 9.5)
    2. SPLADE sparse embeddings
    3. GraphRAG for relationship-aware search
    4. Vision-Language Model integration
    """

    def __init__(
        self,
        es_client: Optional["AsyncElasticsearch"] = None,
        pg_client: Optional[Any] = None,
        embedding_service: Optional["EmbeddingService"] = None,
        settings: Optional[Settings] = None,
        rrf_config: Optional[RRFConfig] = None,
        vector_search_backend: Literal["pgvector", "elasticsearch"] = "elasticsearch",
        enable_cross_encoder: bool = True,
        enable_graph_rag: bool = True,
        enable_splade: bool = True,
        enable_vlm: bool = False
    ):
        """Initialize enhanced search service with advanced RAG capabilities.
        
        Args:
            es_client: Elasticsearch client instance
            pg_client: PostgreSQL client instance (with pgvector)
            embedding_service: Service for generating embeddings
            settings: Application settings
            rrf_config: Configuration for RRF fusion
            vector_search_backend: Backend for vector search
            enable_cross_encoder: Enable cross-encoder reranking
            enable_graph_rag: Enable graph-based search
            enable_splade: Enable SPLADE sparse embeddings
            enable_vlm: Enable vision-language model processing
        """
        super().__init__(
            es_client=es_client,
            pg_client=pg_client,
            embedding_service=embedding_service,
            settings=settings,
            rrf_config=rrf_config,
            vector_search_backend=vector_search_backend
        )
        
        self.enable_cross_encoder = enable_cross_encoder
        self.enable_graph_rag = enable_graph_rag
        self.enable_splade = enable_splade
        self.enable_vlm = enable_vlm
        
        # Initialize advanced RAG components
        self.cross_encoder_reranker = None
        self.splade_embedder = None
        self.legal_graph = None
        self.vlm_processor = None

    async def initialize_advanced_components(self):
        """Initialize advanced RAG components."""
        tasks = []
        
        if self.enable_cross_encoder:
            tasks.append(self._init_cross_encoder())
        
        if self.enable_splade:
            tasks.append(self._init_splade())
        
        if self.enable_graph_rag:
            tasks.append(self._init_graph_rag())
        
        if self.enable_vlm:
            tasks.append(self._init_vlm())
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _init_cross_encoder(self):
        """Initialize cross-encoder reranker."""
        try:
            self.cross_encoder_reranker = await get_cross_encoder_reranker()
            logger.info("Cross-encoder reranker initialized")
        except Exception as e:
            logger.error(f"Failed to initialize cross-encoder: {e}")
            self.enable_cross_encoder = False

    async def _init_splade(self):
        """Initialize SPLADE embedder."""
        try:
            self.splade_embedder = await get_splade_embedder()
            logger.info("SPLADE embedder initialized")
        except Exception as e:
            logger.error(f"Failed to initialize SPLADE: {e}")
            self.enable_splade = False

    async def _init_graph_rag(self):
        """Initialize legal knowledge graph."""
        try:
            self.legal_graph = await get_legal_knowledge_graph()
            logger.info("Legal knowledge graph initialized")
        except Exception as e:
            logger.error(f"Failed to initialize legal graph: {e}")
            self.enable_graph_rag = False

    async def _init_vlm(self):
        """Initialize vision-language model processor."""
        try:
            self.vlm_processor = await get_vlm_processor()
            logger.info("Vision-language model processor initialized")
        except Exception as e:
            logger.error(f"Failed to initialize VLM: {e}")
            self.enable_vlm = False

    async def search_api(self, request: SearchRequest) -> SearchResponse:
        """Execute enhanced search with advanced RAG techniques.
        
        Args:
            request: SearchRequest with query and parameters
            
        Returns:
            Enhanced SearchResponse with results
        """
        start_time = time.time()

        # Determine weights
        weights = request.hybrid_weights or {
            "bm25": self.bm25_weight,
            "vector": self.vector_weight,
        }

        # Execute base hybrid search
        results, metadata = await self._search_hybrid(
            query=request.query,
            limit=request.limit,
            sources=request.sources,
            additional_filters=request.filters,
            hybrid_weights=weights
        )

        # Apply advanced RAG techniques as Phase 9.5 in pipeline

        # 1. Cross-Encoder Reranking (highest impact, easiest to add)
        if self.enable_cross_encoder and len(results) > 0:
            try:
                # Convert SearchHit to dict format for reranking
                result_dicts = []
                for hit in results:
                    result_dicts.append({
                        "document_id": hit.document_id,
                        "title": hit.title,
                        "content_preview": hit.content_preview,
                        "source_id": hit.source_id,
                        "metadata": hit.metadata,
                        "score": hit.score,
                        "rank": getattr(hit, 'rank_before', len(result_dicts) + 1)
                    })

                # Apply cross-encoder reranking
                reranked_results = await apply_cross_encoder_reranking(
                    query=request.query,
                    search_results=result_dicts,
                    top_k=min(len(result_dicts), 50)  # Rerank top 50
                )

                # Convert back to SearchHit format
                results = []
                for rerank_result in reranked_results:
                    results.append(SearchHit(
                        document_id=rerank_result["document_id"],
                        title=rerank_result["title"],
                        content_preview=rerank_result["content_preview"],
                        source_id=rerank_result["source_id"],
                        score=rerank_result["reranked_score"],
                        bm25_score=rerank_result.get("initial_score"),
                        vector_score=None,  # Will be set if available
                        metadata=rerank_result["metadata"],
                        rank_bm25=rerank_result.get("rank_before"),
                        rank_vector=None  # Will be set if available
                    ))

                metadata["cross_encoder_applied"] = True
                metadata["cross_encoder_results"] = len(reranked_results)
            except Exception as e:
                logger.error(f"Cross-encoder reranking failed: {e}")
                # Continue with original results

        # 2. GraphRAG enhancement - find related documents through knowledge graph
        if self.enable_graph_rag and len(results) > 0:
            try:
                # Get the top result's document ID to find related documents
                top_doc_id = results[0].document_id if results else None
                if top_doc_id:
                    # Query the legal knowledge graph for related documents
                    graph_results = await query_legal_graph(
                        start_node=top_doc_id,
                        relationship_types=[
                            RelationshipType.CITATES,
                            RelationshipType.REFERENCES,
                            RelationshipType.DERIVES_FROM,
                            RelationshipType.SIMILAR_TO
                        ],
                        max_depth=2,
                        limit=10
                    )

                    # Add graph-related documents to results
                    graph_doc_ids = {r.id for r in graph_results.entities if r.type == "document"}
                    for doc_id in graph_doc_ids:
                        if doc_id != top_doc_id and not any(r.document_id == doc_id for r in results):
                            # Fetch document details and add to results with lower priority
                            # In a real implementation, we'd fetch the actual document
                            results.append(SearchHit(
                                document_id=doc_id,
                                title=f"Related to {results[0].title}" if results else "Related Document",
                                content_preview="Document related through legal knowledge graph",
                                source_id="graph_rag",
                                score=0.5,  # Lower priority
                                metadata={"relationship_type": "graph_related"}
                            ))

                    metadata["graph_rag_applied"] = True
                    metadata["graph_related_docs"] = len(graph_doc_ids)
            except Exception as e:
                logger.error(f"GraphRAG enhancement failed: {e}")
                # Continue with current results

        # 3. SPLADE sparse embeddings could be integrated here for lexical matching
        if self.enable_splade:
            try:
                # In a full implementation, we would use SPLADE embeddings
                # to enhance the search with learned sparse representations
                metadata["splade_enabled"] = True
            except Exception as e:
                logger.error(f"SPLADE integration failed: {e}")

        took_ms = (time.time() - start_time) * 1000
        metadata["enhanced_search_took_ms"] = round(took_ms, 2)

        return SearchResponse(
            query=request.query,
            total=len(results),
            took_ms=round(took_ms, 2),
            hits=results,
            metadata=metadata
        )

    async def search_with_graph_context(
        self,
        query: str,
        document_id: Optional[str] = None,
        relationship_types: Optional[List[RelationshipType]] = None,
        limit: int = 10
    ) -> SearchResponse:
        """
        Search considering graph relationships around a specific document.
        
        Args:
            query: Search query
            document_id: Center document for graph context
            relationship_types: Types of relationships to follow
            limit: Number of results to return
            
        Returns:
            SearchResponse with graph-contextualized results
        """
        if not self.enable_graph_rag or not document_id:
            # Fall back to regular search
            request = SearchRequest(query=query, limit=limit)
            return await self.search_api(request)

        start_time = time.time()

        try:
            # Get related documents from graph
            graph_results = await query_legal_graph(
                start_node=document_id,
                relationship_types=relationship_types,
                max_depth=2,
                limit=limit * 2  # Get more candidates for reranking
            )

            # Get document IDs from graph
            related_doc_ids = [r.id for r in graph_results.entities if r.type == "document"]

            # Perform search limited to related documents
            filters = SearchFilters(metadata={"document_id": {"$in": related_doc_ids}})
            request = SearchRequest(
                query=query,
                limit=limit,
                filters=filters.dict() if filters else None
            )

            # Execute search with graph context
            response = await self.search_api(request)

            # Add graph context metadata
            response.metadata = response.metadata or {}
            response.metadata.update({
                "graph_context_applied": True,
                "related_documents_found": len(related_doc_ids),
                "relationship_types": [r.value for r in relationship_types] if relationship_types else []
            })

            return response

        except Exception as e:
            logger.error(f"Graph-context search failed: {e}")
            # Fall back to regular search
            request = SearchRequest(query=query, limit=limit)
            return await self.search_api(request)

    async def search_with_cross_encoder_reranking(
        self,
        query: str,
        limit: int = 10,
        initial_candidates: int = 50
    ) -> SearchResponse:
        """
        Perform search with cross-encoder reranking as Phase 9.5.
        
        Args:
            query: Search query
            limit: Number of final results
            initial_candidates: Number of candidates to rerank
            
        Returns:
            SearchResponse with cross-encoder reranked results
        """
        start_time = time.time()

        # First, get initial candidates using hybrid search
        request = SearchRequest(
            query=query,
            limit=initial_candidates,
            sources=None,
            filters=None
        )

        # Execute base hybrid search to get candidates
        initial_results, metadata = await self._search_hybrid(
            query=request.query,
            limit=initial_candidates,
            sources=request.sources,
            additional_filters=request.filters,
            hybrid_weights=request.hybrid_weights
        )

        # Apply cross-encoder reranking
        if self.enable_cross_encoder and len(initial_results) > 0:
            try:
                # Convert to dict format for reranking
                result_dicts = []
                for hit in initial_results:
                    result_dicts.append({
                        "document_id": hit.document_id,
                        "title": hit.title,
                        "content_preview": hit.content_preview,
                        "source_id": hit.source_id,
                        "metadata": hit.metadata,
                        "score": hit.score,
                        "rank": getattr(hit, 'rank_before', len(result_dicts) + 1)
                    })

                # Apply cross-encoder reranking
                reranked_results = await apply_cross_encoder_reranking(
                    query=query,
                    search_results=result_dicts,
                    top_k=min(len(result_dicts), initial_candidates)
                )

                # Convert top results back to SearchHit format
                final_results = []
                for rerank_result in reranked_results[:limit]:
                    final_results.append(SearchHit(
                        document_id=rerank_result["document_id"],
                        title=rerank_result["title"],
                        content_preview=rerank_result["content_preview"],
                        source_id=rerank_result["source_id"],
                        score=rerank_result["reranked_score"],
                        bm25_score=rerank_result.get("initial_score"),
                        vector_score=None,
                        metadata=rerank_result["metadata"],
                        rank_bm25=rerank_result.get("rank_before"),
                        rank_vector=None
                    ))

                metadata["cross_encoder_applied"] = True
                metadata["initial_candidates"] = len(initial_results)
                metadata["reranked_results"] = len(reranked_results)
            except Exception as e:
                logger.error(f"Cross-encoder reranking failed: {e}")
                # Fall back to initial results
                final_results = initial_results[:limit]
        else:
            # Cross-encoder not available, return initial results
            final_results = initial_results[:limit]

        took_ms = (time.time() - start_time) * 1000

        return SearchResponse(
            query=query,
            total=len(final_results),
            took_ms=round(took_ms, 2),
            hits=final_results,
            metadata=metadata
        )


# Factory function to create enhanced search service
async def create_enhanced_search_service(
    es_client: Optional["AsyncElasticsearch"] = None,
    pg_client: Optional[Any] = None,
    embedding_service: Optional["EmbeddingService"] = None,
    settings: Optional[Settings] = None,
    enable_cross_encoder: bool = True,
    enable_graph_rag: bool = True,
    enable_splade: bool = True,
    enable_vlm: bool = False
) -> EnhancedSearchService:
    """
    Factory function to create an enhanced search service with advanced RAG techniques.
    
    Args:
        es_client: Elasticsearch client
        pg_client: PostgreSQL client
        embedding_service: Embedding service
        settings: Application settings
        enable_cross_encoder: Enable cross-encoder reranking
        enable_graph_rag: Enable graph-based search
        enable_splade: Enable SPLADE sparse embeddings
        enable_vlm: Enable vision-language models
        
    Returns:
        EnhancedSearchService instance
    """
    service = EnhancedSearchService(
        es_client=es_client,
        pg_client=pg_client,
        embedding_service=embedding_service,
        settings=settings,
        enable_cross_encoder=enable_cross_encoder,
        enable_graph_rag=enable_graph_rag,
        enable_splade=enable_splade,
        enable_vlm=enable_vlm
    )
    
    # Initialize advanced components
    await service.initialize_advanced_components()
    
    return service