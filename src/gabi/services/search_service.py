"""GABI Search Services Module.

Provides hybrid search capabilities combining BM25 (Elasticsearch)
and semantic vector search (pgvector) with Reciprocal Rank Fusion (RRF).

Example:
    >>> from gabi.services.search_service import SearchService
    >>> service = SearchService()
    >>> results = await service.search("query", "hybrid")

Attributes:
    DEFAULT_RRF_K: Constante padrão para RRF (Reciprocal Rank Fusion).
"""

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Tuple
from dataclasses import dataclass

from gabi.schemas.search import SearchFilters, SearchHit, SearchResponse, SearchRequest, RRFConfig, IndexHealth, HealthResponse
from gabi.config import Settings

if TYPE_CHECKING:
    from elasticsearch import AsyncElasticsearch
    from gabi.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


@dataclass
class RawResult:
    """Internal representation of a raw search result."""
    id: str
    content: str
    score: float
    source_id: Optional[str] = None
    source_type: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    title: Optional[str] = None
    content_preview: Optional[str] = None
    url: Optional[str] = None


class SearchService:
    """Service for performing various types of search.
    
    Supports BM25 search via Elasticsearch, vector search via either
    PostgreSQL/pgvector or Elasticsearch kNN, and hybrid search with RRF fusion.
    """
    
    DEFAULT_RRF_K = 60
    
    def __init__(
        self,
        es_client: Optional["AsyncElasticsearch"] = None,
        pg_client: Optional[Any] = None,
        embedding_service: Optional["EmbeddingService"] = None,
        settings: Optional[Settings] = None,
        rrf_config: Optional[RRFConfig] = None,
        vector_search_backend: Literal["pgvector", "elasticsearch"] = "elasticsearch"
    ):
        """Initialize search service with required clients.
        
        Args:
            es_client: Elasticsearch client instance
            pg_client: PostgreSQL client instance (with pgvector)
            embedding_service: Service for generating embeddings
            settings: Application settings (optional, for API compatibility)
            rrf_config: Configuration for RRF fusion
            vector_search_backend: Backend for vector search ("pgvector" or "elasticsearch")
        """
        self.es_client = es_client
        self.pg_client = pg_client
        self.embedding_service = embedding_service
        # Default to elasticsearch for better scalability if not specified
        self.vector_search_backend = vector_search_backend or "elasticsearch"
        
        # Use settings if provided, otherwise use defaults
        if settings:
            self.settings = settings
            self.index_name = settings.elasticsearch_index
            self.rrf_k = settings.search_rrf_k
            self.default_limit = settings.search_default_limit
            self.max_limit = settings.search_max_limit
            self.bm25_weight = settings.search_bm25_weight
            self.vector_weight = settings.search_vector_weight
            self.timeout_ms = settings.search_timeout_ms
        else:
            self.settings = None
            self.index_name = "documents"
            self.rrf_k = self.DEFAULT_RRF_K
            self.default_limit = 10
            self.max_limit = 100
            self.bm25_weight = 1.0
            self.vector_weight = 1.0
            self.timeout_ms = 5000
        
        # RRF config (legacy support)
        self.rrf_config = rrf_config or RRFConfig(
            k=self.rrf_k,
            weight_bm25=self.bm25_weight,
            weight_vector=self.vector_weight
        )
    
    def _build_es_query(
        self,
        query: str,
        filters: Optional[SearchFilters] = None,
        sources: Optional[List[str]] = None,
        additional_filters: Optional[Dict[str, Any]] = None,
        size: int = 100
    ) -> Dict[str, Any]:
        """Build Elasticsearch query with filters.
        
        Args:
            query: Search query text
            filters: Optional search filters (SearchFilters)
            sources: Optional list of source IDs to filter
            additional_filters: Optional additional filters dict
            size: Number of results to return
            
        Returns:
            Elasticsearch query dictionary
        """
        must_clauses = [
            {
                "multi_match": {
                    "query": query,
                    "fields": ["title^3", "content^2", "content_preview", "metadata.*"],
                    "type": "best_fields",
                    "fuzziness": "AUTO"
                }
            }
        ]
        
        filter_clauses = [{"term": {"is_deleted": False}}]
        
        # Handle SearchFilters (from core service)
        if filters:
            if filters.source_id:
                filter_clauses.append({"term": {"source_id": filters.source_id}})
            
            if filters.source_type:
                filter_clauses.append({"term": {"source_type": filters.source_type}})
            
            if filters.date_from or filters.date_to:
                date_range = {"range": {"created_at": {}}}
                if filters.date_from:
                    if hasattr(filters.date_from, 'isoformat'):
                        date_range["range"]["created_at"]["gte"] = filters.date_from.isoformat()
                    else:
                        date_range["range"]["created_at"]["gte"] = filters.date_from
                if filters.date_to:
                    if hasattr(filters.date_to, 'isoformat'):
                        date_range["range"]["created_at"]["lte"] = filters.date_to.isoformat()
                    else:
                        date_range["range"]["created_at"]["lte"] = filters.date_to
                filter_clauses.append(date_range)
            
            if filters.tags:
                filter_clauses.append({"terms": {"tags": filters.tags}})
            
            if filters.metadata:
                for key, value in filters.metadata.items():
                    filter_clauses.append({"term": {f"metadata.{key}": value}})
        
        # Handle sources list (from API)
        if sources:
            filter_clauses.append({"terms": {"source_id": sources}})
        
        # Handle additional filters (from API)
        if additional_filters:
            for key, value in additional_filters.items():
                filter_clauses.append({"term": {key: value}})
        
        es_query = {
            "bool": {
                "must": must_clauses,
                "filter": filter_clauses
            }
        }
        
        return es_query
    
    async def _search_bm25(
        self,
        query: str,
        filters: Optional[SearchFilters] = None,
        sources: Optional[List[str]] = None,
        additional_filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[RawResult]:
        """Perform BM25 text search using Elasticsearch.
        
        Args:
            query: Search query text
            filters: Optional search filters (SearchFilters)
            sources: Optional list of source IDs
            additional_filters: Optional additional filters
            limit: Maximum number of results
            offset: Offset for pagination
            
        Returns:
            List of raw search results
        """
        if not self.es_client:
            logger.warning("Elasticsearch client not configured")
            return []
        
        try:
            es_query = self._build_es_query(
                query, filters, sources, additional_filters, size=limit + offset
            )
            
            response = await self.es_client.search(
                index=self.index_name,
                query=es_query,
                size=min(limit + offset, self.max_limit),
                from_=offset,
                timeout=f"{self.timeout_ms}ms"
            )
            
            results = []
            for hit in response.get("hits", {}).get("hits", []):
                source = hit.get("_source", {})
                results.append(RawResult(
                    id=hit.get("_id", ""),
                    content=source.get("content", ""),
                    content_preview=source.get("content_preview"),
                    title=source.get("title"),
                    score=hit.get("_score", 0.0),
                    source_id=source.get("source_id"),
                    source_type=source.get("source_type"),
                    metadata=source.get("metadata"),
                    created_at=source.get("created_at"),
                    updated_at=source.get("updated_at"),
                    url=source.get("url")
                ))
            
            logger.debug(f"BM25 search returned {len(results)} results")
            return results
            
        except Exception as e:
            logger.error(f"BM25 search failed: {e}")
            return []
    
    async def _search_vector_pg(
        self,
        embedding: List[float],
        filters: Optional[SearchFilters] = None,
        limit: int = 100
    ) -> List[RawResult]:
        """Perform vector search using PostgreSQL with pgvector.
        
        Args:
            embedding: Query embedding vector
            filters: Optional search filters
            limit: Maximum number of results
            
        Returns:
            List of raw search results
        """
        try:
            from gabi.db import get_session_no_commit
            from gabi.models.chunk import DocumentChunk
            from gabi.models.document import Document
            from sqlalchemy import select
            
            fetch_limit = max(limit * 3, limit)
            
            # Build vector similarity query
            query = (
                select(
                    DocumentChunk.document_id,
                    DocumentChunk.chunk_text,
                    DocumentChunk.chunk_metadata.label("chunk_metadata"),
                    DocumentChunk.embedding.cosine_distance(embedding).label("distance"),
                    Document.title,
                    Document.content_preview,
                    Document.source_id,
                    Document.doc_metadata.label("doc_metadata"),
                    Document.url,
                )
                .join(
                    Document,
                    DocumentChunk.document_id == Document.document_id,
                )
                .where(DocumentChunk.embedding.isnot(None))
                .where(Document.is_deleted == False)
                .order_by("distance")
                .limit(fetch_limit)
            )
            
            # Apply filters if provided
            if filters and filters.source_id:
                query = query.where(Document.source_id == filters.source_id)
            
            # Execute query
            try:
                async with get_session_no_commit() as session:
                    result = await session.execute(query)
                    rows = result.all()
            except RuntimeError as e:
                logger.warning(f"Vector search (pgvector) unavailable: {e}")
                return []
            
            results = []
            seen_docs = set()
            for row in rows:
                doc_id = row.document_id
                if doc_id in seen_docs:
                    continue
                seen_docs.add(doc_id)
                # Convert distance to similarity score (1 - distance)
                similarity = 1.0 - float(row.distance)
                metadata = row.doc_metadata or {}
                results.append(RawResult(
                    id=str(doc_id),
                    content=row.chunk_text or "",
                    score=similarity,
                    source_id=row.source_id,
                    source_type=None,
                    metadata=metadata,
                    title=row.title,
                    content_preview=row.content_preview,
                    url=row.url,
                ))
                if len(results) >= limit:
                    break
            
            logger.debug(f"Vector search (pgvector) returned {len(results)} results")
            return results
            
        except Exception as e:
            logger.error(f"Vector search (pgvector) failed: {e}")
            return []
    
    async def _search_vector_es(
        self,
        embedding: List[float],
        filters: Optional[SearchFilters] = None,
        sources: Optional[List[str]] = None,
        additional_filters: Optional[Dict[str, Any]] = None,
        limit: int = 100
    ) -> List[RawResult]:
        """Perform vector search using Elasticsearch kNN.
        
        Args:
            embedding: Query embedding vector
            filters: Optional search filters
            sources: Optional list of source IDs
            additional_filters: Optional additional filters
            limit: Maximum number of results
            
        Returns:
            List of raw search results
        """
        if not self.es_client:
            logger.warning("Elasticsearch client not configured for kNN search")
            return []
        
        try:
            # Build kNN query with correct field path
            # Per elasticsearch_setup.py: top-level content_vector field
            knn_query = {
                "field": "content_vector",
                "query_vector": embedding,
                "k": min(limit * 2, self.max_limit),
                "num_candidates": 100,
            }
            
            # Add filters
            filter_clauses = [{"term": {"is_deleted": False}}]
            
            if sources:
                filter_clauses.append({"terms": {"source_id": sources}})
            
            if additional_filters:
                for key, value in additional_filters.items():
                    filter_clauses.append({"term": {key: value}})
            
            if filters:
                if filters.source_id:
                    filter_clauses.append({"term": {"source_id": filters.source_id}})
                if filters.source_type:
                    filter_clauses.append({"term": {"source_type": filters.source_type}})
            
            if len(filter_clauses) > 1:
                knn_query["filter"] = {"bool": {"filter": filter_clauses}}
            else:
                knn_query["filter"] = filter_clauses[0]
            
            # Execute kNN search
            response = await self.es_client.search(
                index=self.index_name,
                knn=knn_query,
                size=limit,
                timeout=f"{self.timeout_ms}ms"
            )
            
            results = []
            for hit in response.get("hits", {}).get("hits", []):
                source = hit.get("_source", {})
                results.append(RawResult(
                    id=hit.get("_id", ""),
                    content=source.get("content", ""),
                    content_preview=source.get("content_preview"),
                    title=source.get("title"),
                    score=hit.get("_score", 0.0),
                    source_id=source.get("source_id"),
                    source_type=source.get("source_type"),
                    metadata=source.get("metadata"),
                    url=source.get("url")
                ))
            
            logger.debug(f"Vector search (ES kNN) returned {len(results)} results")
            return results
            
        except Exception as e:
            logger.error(f"Vector search (ES kNN) failed: {e}")
            return []
    
    async def _search_vector(
        self,
        embedding: List[float],
        filters: Optional[SearchFilters] = None,
        sources: Optional[List[str]] = None,
        additional_filters: Optional[Dict[str, Any]] = None,
        limit: int = 100
    ) -> List[RawResult]:
        """Perform vector search using configured backend.
        
        Args:
            embedding: Query embedding vector
            filters: Optional search filters
            sources: Optional list of source IDs
            additional_filters: Optional additional filters
            limit: Maximum number of results
            
        Returns:
            List of raw search results
        """
        if self.vector_search_backend == "pgvector":
            return await self._search_vector_pg(embedding, filters, limit)
        else:
            # Default to elasticsearch for better scalability
            return await self._search_vector_es(
                embedding, filters, sources, additional_filters, limit
            )
    
    def _compute_rrf_score(
        self,
        rank_bm25: Optional[int],
        rank_vector: Optional[int],
        k: int = 60,
        weight_bm25: float = 1.0,
        weight_vector: float = 1.0
    ) -> float:
        """Compute RRF (Reciprocal Rank Fusion) score.
        
        Formula: score = Σ weight/(k + rank)
        where k=60 is the industry standard constant to reduce the impact of high rankings
        
        Args:
            rank_bm25: Ranking position from BM25 search (1-indexed)
            rank_vector: Ranking position from vector search (1-indexed)
            k: RRF constant (default 60)
            weight_bm25: Weight for BM25 scores
            weight_vector: Weight for vector scores
            
        Returns:
            Combined RRF score
        """
        score = 0.0
        
        if rank_bm25 is not None and rank_bm25 > 0:
            score += weight_bm25 / (k + rank_bm25)
        
        if rank_vector is not None and rank_vector > 0:
            score += weight_vector / (k + rank_vector)
        
        return score
    
    def _fuse_results_rrf(
        self,
        bm25_results: List[RawResult],
        vector_results: List[RawResult],
        limit: int,
        k: int = 60,
        weights: Optional[Dict[str, float]] = None
    ) -> List[SearchHit]:
        """Fuse BM25 and vector search results using RRF.
        
        Args:
            bm25_results: Results from BM25 search
            vector_results: Results from vector search
            limit: Maximum number of fused results
            k: RRF constant (default 60)
            weights: Optional weights dict with "bm25" and "vector" keys
            
        Returns:
            Fused and ranked search results as SearchHit objects
        """
        # Use provided weights or fall back to settings
        weight_bm25 = weights.get("bm25", self.bm25_weight) if weights else self.bm25_weight
        weight_vector = weights.get("vector", self.vector_weight) if weights else self.vector_weight
        
        # Create ranking dictionaries (1-indexed)
        bm25_ranks = {r.id: idx + 1 for idx, r in enumerate(bm25_results)}
        vector_ranks = {r.id: idx + 1 for idx, r in enumerate(vector_results)}
        
        # Combine all unique document IDs
        all_ids = set(bm25_ranks.keys()) | set(vector_ranks.keys())
        
        # Collect all results with their data
        all_results = {}
        for r in bm25_results:
            all_results[r.id] = r
        for r in vector_results:
            if r.id not in all_results:
                all_results[r.id] = r
        
        # Compute RRF scores
        fused_scores = []
        for doc_id in all_ids:
            rrf_score = self._compute_rrf_score(
                bm25_ranks.get(doc_id),
                vector_ranks.get(doc_id),
                k,
                weight_bm25,
                weight_vector
            )
            fused_scores.append((doc_id, rrf_score))
        
        # Sort by RRF score descending
        fused_scores.sort(key=lambda x: x[1], reverse=True)
        
        # Build final results as SearchHit objects
        final_results = []
        for doc_id, score in fused_scores[:limit]:
            raw = all_results[doc_id]
            final_results.append(SearchHit(
                document_id=doc_id,
                title=raw.title,
                content_preview=raw.content_preview or raw.content[:500] if raw.content else None,
                source_id=raw.source_id or "unknown",
                score=round(score, 4),
                bm25_score=raw.score if doc_id in bm25_ranks else None,
                vector_score=raw.score if doc_id in vector_ranks else None,
                metadata=raw.metadata or {},
                url=raw.url
            ))
        
        return final_results
    
    async def _search_hybrid(
        self,
        query: str,
        limit: int = 10,
        filters: Optional[SearchFilters] = None,
        sources: Optional[List[str]] = None,
        additional_filters: Optional[Dict[str, Any]] = None,
        hybrid_weights: Optional[Dict[str, float]] = None
    ) -> Tuple[List[SearchHit], Dict[str, Any]]:
        """Perform hybrid search combining BM25 and vector search with RRF.
        
        Uses asyncio.gather() to execute BM25 and vector searches in parallel
        for improved performance.
        
        Args:
            query: Search query text
            limit: Number of results to return
            filters: Optional search filters
            sources: Optional list of source IDs
            additional_filters: Optional additional filters
            hybrid_weights: Optional weights for RRF fusion
            
        Returns:
            Tuple of (search results as SearchHit list, metadata dict)
        """
        # Get embeddings for vector search first (needed before parallel search)
        embedding = None
        if self.embedding_service:
            try:
                if hasattr(self.embedding_service, 'embed'):
                    embedding = await self.embedding_service.embed(query)
                else:
                    embedding = self.embedding_service.embed(query)
            except Exception as e:
                logger.warning(f"Failed to generate embedding: {e}")
        
        # Execute BM25 and vector searches in parallel for better performance
        # This reduces overall search latency significantly
        bm25_task = self._search_bm25(
            query, filters, sources, additional_filters, limit=limit * 3
        )
        
        # Create tasks list - BM25 always runs, vector only if we have embedding
        tasks: List[asyncio.Task] = [asyncio.create_task(bm25_task)]
        
        if embedding:
            vector_task = self._search_vector(
                embedding, filters, sources, additional_filters, limit=limit * 3
            )
            tasks.append(asyncio.create_task(vector_task))
        
        # Wait for all searches to complete in parallel
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.error(f"Error during parallel search execution: {e}")
            results = []
        
        # Extract results (handle exceptions)
        bm25_results: List[RawResult] = []
        vector_results: List[RawResult] = []
        
        if len(results) >= 1:
            bm25_result = results[0]
            if isinstance(bm25_result, Exception):
                logger.error(f"BM25 search failed: {bm25_result}")
                bm25_results = []
            else:
                bm25_results = bm25_result
        
        if len(results) >= 2 and embedding:
            vector_result = results[1]
            if isinstance(vector_result, Exception):
                logger.error(f"Vector search failed: {vector_result}")
                vector_results = []
            else:
                vector_results = vector_result
        
        # Fuse results using RRF
        fused_results = self._fuse_results_rrf(
            bm25_results,
            vector_results,
            limit=limit,
            k=self.rrf_k,
            weights=hybrid_weights
        )
        
        metadata = {
            "bm25_count": len(bm25_results),
            "vector_count": len(vector_results),
            "rrf_k": self.rrf_k,
            "embedding_used": embedding is not None,
            "vector_backend": self.vector_search_backend if embedding else None,
            "parallel_search": True,  # Indicate that parallel search was used
        }
        
        return fused_results, metadata

    # =============================================================================
    # Core Service API (legacy format)
    # =============================================================================
    
    async def search(
        self,
        query: str,
        search_type: str = "hybrid",
        filters: Optional[SearchFilters] = None,
        limit: int = 10
    ) -> Dict[str, Any]:
        """Execute search with specified type (legacy core service format).
        
        Args:
            query: Search query text
            search_type: Type of search (bm25, vector, hybrid)
            filters: Optional search filters
            limit: Number of results to return
            
        Returns:
            Search response dictionary
        """
        start_time = time.time()
        
        if not query or not query.strip():
            return {
                "query": query,
                "search_type": search_type,
                "total_results": 0,
                "results": [],
                "took_ms": 0,
                "filters_applied": filters.model_dump() if filters else None,
                "error": "Empty query"
            }
        
        try:
            if search_type == "bm25":
                raw_results = await self._search_bm25(query, filters, limit=limit)
                results = [
                    SearchHit(
                        document_id=r.id,
                        title=r.title,
                        content_preview=r.content_preview or r.content[:500] if r.content else None,
                        source_id=r.source_id or "unknown",
                        score=round(r.score, 4),
                        bm25_score=r.score,
                        metadata=r.metadata or {}
                    )
                    for idx, r in enumerate(raw_results[:limit])
                ]
                metadata = {"bm25_count": len(raw_results)}
                
            elif search_type == "vector":
                embedding = None
                if self.embedding_service:
                    try:
                        if hasattr(self.embedding_service, 'embed'):
                            embedding = await self.embedding_service.embed(query)
                        else:
                            embedding = self.embedding_service.embed(query)
                    except Exception as e:
                        logger.warning(f"Failed to generate embedding: {e}")
                
                if embedding:
                    raw_results = await self._search_vector(embedding, filters, limit=limit)
                else:
                    raw_results = []
                
                results = [
                    SearchHit(
                        document_id=r.id,
                        title=r.title,
                        content_preview=r.content_preview or r.content[:500] if r.content else None,
                        source_id=r.source_id or "unknown",
                        score=round(r.score, 4),
                        vector_score=r.score,
                        metadata=r.metadata or {}
                    )
                    for idx, r in enumerate(raw_results[:limit])
                ]
                metadata = {
                    "vector_count": len(raw_results),
                    "embedding_used": embedding is not None,
                    "vector_backend": self.vector_search_backend if embedding else None
                }
                
            elif search_type == "hybrid":
                results, metadata = await self._search_hybrid(
                    query, limit, filters
                )
                
            else:
                return {
                    "query": query,
                    "search_type": search_type,
                    "total_results": 0,
                    "results": [],
                    "took_ms": (time.time() - start_time) * 1000,
                    "filters_applied": filters.model_dump() if filters else None,
                    "error": f"Unknown search type: {search_type}"
                }
            
            took_ms = (time.time() - start_time) * 1000
            
            return {
                "query": query,
                "search_type": search_type,
                "total_results": len(results),
                "results": [r.model_dump() for r in results],
                "took_ms": round(took_ms, 2),
                "filters_applied": filters.model_dump() if filters else None,
                **metadata
            }
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return {
                "query": query,
                "search_type": search_type,
                "total_results": 0,
                "results": [],
                "took_ms": (time.time() - start_time) * 1000,
                "filters_applied": filters.model_dump() if filters else None,
                "error": str(e)
            }

    # =============================================================================
    # API Service Methods
    # =============================================================================
    
    async def search_api(self, request: SearchRequest) -> SearchResponse:
        """Execute search for API request (SearchRequest/SearchResponse format).
        
        Args:
            request: SearchRequest with query and parameters
            
        Returns:
            SearchResponse with results
        """
        start_time = time.time()
        
        # Determine weights
        weights = request.hybrid_weights or {
            "bm25": self.bm25_weight,
            "vector": self.vector_weight,
        }
        
        # Execute hybrid search
        results, _ = await self._search_hybrid(
            query=request.query,
            limit=request.limit,
            sources=request.sources,
            additional_filters=request.filters,
            hybrid_weights=weights
        )
        
        took_ms = (time.time() - start_time) * 1000
        
        return SearchResponse(
            query=request.query,
            total=len(results),
            took_ms=round(took_ms, 2),
            hits=results,
        )
    
    async def health_check(self) -> HealthResponse:
        """Check health of search indices.
        
        Returns:
            HealthResponse with status of indices
        """
        import time
        
        start_time = time.time()
        indices = []
        overall_status = "healthy"
        
        if not self.es_client:
            return HealthResponse(
                status="unhealthy",
                indices=[],
                took_ms=0.0
            )
        
        try:
            # Check cluster health
            cluster_health = await self.es_client.cluster.health()
            cluster_status = cluster_health.get("status", "red")
            
            if cluster_status == "red":
                overall_status = "unhealthy"
            elif cluster_status == "yellow":
                overall_status = "degraded"
            
            # Get index stats
            chunks_index = f"{self.index_name}_chunks"
            for index_name in [self.index_name, chunks_index]:
                try:
                    stats = await self.es_client.indices.stats(index=index_name)
                    index_stats = stats["indices"].get(index_name, {})
                    
                    docs = index_stats.get("total", {}).get("docs", {})
                    store = index_stats.get("total", {}).get("store", {})
                    
                    indices.append(IndexHealth(
                        index=index_name,
                        status=cluster_status,
                        docs_count=docs.get("count", 0),
                        size_mb=round(store.get("size_in_bytes", 0) / (1024 * 1024), 2),
                    ))
                except Exception as e:
                    logger.warning(f"Error getting stats for index {index_name}: {e}")
                    indices.append(IndexHealth(
                        index=index_name,
                        status="red",
                        docs_count=0,
                        size_mb=0.0,
                    ))
                    overall_status = "degraded"
                    
        except Exception as e:
            logger.error(f"Health check error: {e}")
            overall_status = "unhealthy"
            indices = [
                IndexHealth(
                    index=self.index_name,
                    status="red",
                    docs_count=0,
                    size_mb=0.0,
                )
            ]
        
        took_ms = (time.time() - start_time) * 1000
        
        return HealthResponse(
            status=overall_status,
            indices=indices,
            took_ms=round(took_ms, 2),
        )
