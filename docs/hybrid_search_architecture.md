# GABI Hybrid Search Architecture

## Executive Summary

This document outlines the comprehensive hybrid search architecture for GABI (Gabinete de Busca Inteligente), a legal document search system for TCU (Tribunal de Contas da União). The architecture combines Elasticsearch (BM25) for exact match search with pgvector/ES kNN for semantic search, using Reciprocal Rank Fusion (RRF) for result combination.

**Key Goals:**
- High-precision exact match for legal citations and document numbers
- Semantic understanding for conceptual queries
- Configurable fusion with domain-specific weighting
- Sub-100ms response times for 95th percentile
- Horizontal scalability for millions of documents

---

## 1. Class Architecture for HybridSearchService

### 1.1 Core Class Hierarchy

```
┌─────────────────────────────────────────────────────────────────┐
│                    HybridSearchService                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ ExactMatch   │  │ Semantic     │  │ RRF Fusion Engine    │  │
│  │ Component    │  │ Component    │  │                      │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Query Router │  │ Cache Layer  │  │ Metrics Collector    │  │
│  │              │  │              │  │                      │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 Proposed Implementation

```python
# File: src/gabi/services/hybrid_search_service.py

"""Enhanced Hybrid Search Service with RRF Fusion for TCU Legal Documents.

This module provides a production-ready hybrid search implementation combining:
- Exact match search (Elasticsearch BM25) for citations and identifiers
- Semantic search (pgvector/ES kNN) for conceptual queries  
- Reciprocal Rank Fusion (RRF) for result combination
- Intelligent query routing based on query type detection
- Multi-layer caching for performance optimization
"""

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, Generic, List, Optional, Protocol, Set, Tuple, TypeVar, Union
from collections import defaultdict

from gabi.config import Settings, settings
from gabi.schemas.search import (
    SearchFilters, SearchHit, SearchRequest, SearchResponse,
    RRFConfig, IndexHealth, HealthResponse
)

logger = logging.getLogger(__name__)


# ============================================================================
# Enums and Types
# ============================================================================

class QueryType(Enum):
    """Classification of search query types for routing decisions."""
    EXACT_MATCH = auto()      # Citations, document numbers, specific terms
    SEMANTIC = auto()         # Conceptual, descriptive queries
    HYBRID = auto()           # Mixed queries benefiting from both
    UNKNOWN = auto()          # Default fallback


class SearchBackend(Enum):
    """Available search backends for vector search."""
    PGVECTOR = "pgvector"
    ELASTICSEARCH = "elasticsearch"


# ============================================================================
# Data Classes
# ============================================================================

@dataclass(frozen=True)
class SearchQuery:
    """Normalized search query with metadata."""
    raw_query: str
    normalized_query: str
    query_type: QueryType
    detected_entities: Dict[str, List[str]] = field(default_factory=dict)
    
    def __hash__(self) -> int:
        return hash((self.normalized_query, self.query_type))


@dataclass
class SearchResult:
    """Internal search result representation."""
    document_id: str
    content: str
    title: Optional[str]
    score: float
    source_id: str
    source_type: Optional[str]
    metadata: Dict[str, Any]
    rank: int = 0
    url: Optional[str] = None
    content_preview: Optional[str] = None


@dataclass  
class FusionResult:
    """Result of RRF fusion with provenance tracking."""
    document_id: str
    rrf_score: float
    bm25_rank: Optional[int]
    bm25_score: Optional[float]
    vector_rank: Optional[int]
    vector_score: Optional[float]
    result: SearchResult


@dataclass
class SearchMetrics:
    """Performance and quality metrics for search operations."""
    query_type: QueryType
    backend_used: str
    bm25_results: int
    vector_results: int
    fused_results: int
    took_ms: float
    cache_hit: bool
    embedding_time_ms: Optional[float] = None
    bm25_time_ms: Optional[float] = None
    vector_time_ms: Optional[float] = None


# ============================================================================
# Protocols (Interfaces)
# ============================================================================

class ExactMatchSearchable(Protocol):
    """Protocol for exact match search implementations."""
    
    async def search(
        self,
        query: str,
        filters: Optional[SearchFilters] = None,
        limit: int = 100,
        fields: Optional[List[str]] = None
    ) -> List[SearchResult]:
        """Execute exact match search."""
        ...
    
    async def search_by_field(
        self,
        field: str,
        value: str,
        limit: int = 100
    ) -> List[SearchResult]:
        """Search by specific field (e.g., numero, ano, orgao)."""
        ...
    
    async def health_check(self) -> bool:
        """Check backend health."""
        ...


class SemanticSearchable(Protocol):
    """Protocol for semantic/vector search implementations."""
    
    async def search(
        self,
        embedding: List[float],
        filters: Optional[SearchFilters] = None,
        limit: int = 100,
        min_score: float = 0.0
    ) -> List[SearchResult]:
        """Execute semantic search with embedding."""
        ...
    
    async def health_check(self) -> bool:
        """Check backend health."""
        ...


class CacheBackend(Protocol):
    """Protocol for cache implementations."""
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        ...
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int = 300
    ) -> bool:
        """Set value in cache with TTL."""
        ...
    
    async def delete(self, key: str) -> bool:
        """Delete key from cache."""
        ...
    
    async def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate keys matching pattern."""
        ...


# ============================================================================
# Query Router
# ============================================================================

class QueryRouter:
    """Intelligent query router for selecting optimal search strategy.
    
    Analyzes queries to determine whether they benefit more from:
    - Exact match (citations, numbers, specific terms)
    - Semantic search (concepts, descriptions)
    - Hybrid approach (mixed queries)
    
    TCU-Specific Patterns:
    - Acórdão numbers: "1234/2024", "AC 1234/2024"
    - Process numbers: "TC-123.456/2024"
    - Norm citations: "Lei 8.666/93", "IN TCU 65/2013"
    """
    
    # TCU-specific regex patterns
    ACORDAO_PATTERN = r'(?:AC|Ac[óo]rd[ãa]o)\s*(\d{1,5}/\d{4})'
    PROCESS_PATTERN = r'(?:TC-)?(\d{3}\.\d{3}/\d{4})'
    LEI_PATTERN = r'Lei\s+(\d{1,5}(?:\.\d{3})*/\d{2,4})'
    IN_PATTERN = r'IN\s+(?:TCU\s+)?(\d{1,4}/\d{4})'
    SUMULA_PATTERN = r'S[úu]mula\s*(?:TCU\s*)?(\d{1,3})'
    YEAR_PATTERN = r'\b(19|20)\d{2}\b'
    QUOTED_PATTERN = r'"([^"]+)"'
    
    # Semantic indicators (conceptual terms)
    SEMANTIC_INDICATORS = [
        'sobre', 'relativo a', 'referente a', 'trata de',
        'diz respeito', 'conceito de', 'definição de',
        'como funciona', 'qual é', 'explique'
    ]
    
    def __init__(self):
        self.patterns = {
            'acordao': re.compile(self.ACORDAO_PATTERN, re.IGNORECASE),
            'processo': re.compile(self.PROCESS_PATTERN, re.IGNORECASE),
            'lei': re.compile(self.LEI_PATTERN, re.IGNORECASE),
            'instrucao_normativa': re.compile(self.IN_PATTERN, re.IGNORECASE),
            'sumula': re.compile(self.SUMULA_PATTERN, re.IGNORECASE),
            'ano': re.compile(self.YEAR_PATTERN),
            'quoted': re.compile(self.QUOTED_PATTERN),
        }
    
    def analyze(self, query: str) -> SearchQuery:
        """Analyze query and determine optimal search strategy.
        
        Args:
            query: Raw user query
            
        Returns:
            SearchQuery with type classification and entities
        """
        normalized = self._normalize(query)
        entities = self._extract_entities(normalized)
        query_type = self._classify(normalized, entities)
        
        return SearchQuery(
            raw_query=query,
            normalized_query=normalized,
            query_type=query_type,
            detected_entities=entities
        )
    
    def _normalize(self, query: str) -> str:
        """Normalize query text."""
        # Remove extra whitespace
        normalized = ' '.join(query.split())
        # Convert to lowercase for analysis
        return normalized.lower()
    
    def _extract_entities(self, query: str) -> Dict[str, List[str]]:
        """Extract legal entities from query."""
        entities = defaultdict(list)
        
        for entity_type, pattern in self.patterns.items():
            matches = pattern.findall(query)
            if matches:
                entities[entity_type] = matches
        
        return dict(entities)
    
    def _classify(
        self,
        query: str,
        entities: Dict[str, List[str]]
    ) -> QueryType:
        """Classify query type based on content analysis."""
        
        # Check for exact match indicators
        has_citation = any(entities.get(k) for k in 
                          ['acordao', 'processo', 'lei', 'instrucao_normativa', 'sumula'])
        has_quotes = bool(entities.get('quoted'))
        
        # Check for semantic indicators
        has_semantic_terms = any(indicator in query 
                                for indicator in self.SEMANTIC_INDICATORS)
        
        # Decision logic
        if has_citation or has_quotes:
            # Citations and quoted phrases favor exact match
            if has_semantic_terms:
                return QueryType.HYBRID
            return QueryType.EXACT_MATCH
        
        if has_semantic_terms:
            return QueryType.SEMANTIC
        
        # Default to hybrid for unknown queries
        return QueryType.HYBRID
    
    def get_optimal_weights(self, query_type: QueryType) -> Dict[str, float]:
        """Get optimal RRF weights for query type.
        
        Returns:
            Dict with 'bm25' and 'vector' weights
        """
        weights = {
            QueryType.EXACT_MATCH: {'bm25': 1.5, 'vector': 0.5},
            QueryType.SEMANTIC: {'bm25': 0.5, 'vector': 1.5},
            QueryType.HYBRID: {'bm25': 1.0, 'vector': 1.0},
            QueryType.UNKNOWN: {'bm25': 1.0, 'vector': 1.0},
        }
        return weights.get(query_type, weights[QueryType.UNKNOWN])


# ============================================================================
# RRF Fusion Engine
# ============================================================================

class RRFFusionEngine:
    """Reciprocal Rank Fusion engine for combining search results.
    
    RRF Formula: score = Σ weight_i / (k + rank_i)
    where k=60 (industry standard) reduces impact of high rankings
    
    Reference: Cormack, Clarke & Buettcher (2009)
    """
    
    DEFAULT_K = 60
    MIN_K = 1
    MAX_K = 1000
    
    def __init__(self, k: int = DEFAULT_K):
        """Initialize RRF engine.
        
        Args:
            k: RRF constant (default 60)
        """
        self.k = max(self.MIN_K, min(k, self.MAX_K))
    
    def fuse(
        self,
        bm25_results: List[SearchResult],
        vector_results: List[SearchResult],
        limit: int = 10,
        weights: Optional[Dict[str, float]] = None
    ) -> List[FusionResult]:
        """Fuse results from BM25 and vector search using RRF.
        
        Args:
            bm25_results: Results from BM25 search (ranked by score)
            vector_results: Results from vector search (ranked by similarity)
            limit: Maximum number of results to return
            weights: Optional weights dict with 'bm25' and 'vector' keys
            
        Returns:
            List of FusionResult sorted by RRF score
        """
        weights = weights or {'bm25': 1.0, 'vector': 1.0}
        w_bm25 = weights.get('bm25', 1.0)
        w_vector = weights.get('vector', 1.0)
        
        # Create rank mappings (1-indexed)
        bm25_ranks = {r.document_id: (idx + 1, r.score) 
                     for idx, r in enumerate(bm25_results)}
        vector_ranks = {r.document_id: (idx + 1, r.score) 
                       for idx, r in enumerate(vector_results)}
        
        # Combine all document IDs
        all_ids = set(bm25_ranks.keys()) | set(vector_ranks.keys())
        
        # Create result lookup
        all_results = {r.document_id: r for r in bm25_results + vector_results}
        
        # Compute RRF scores
        fused = []
        for doc_id in all_ids:
            bm25_rank, bm25_score = bm25_ranks.get(doc_id, (None, None))
            vector_rank, vector_score = vector_ranks.get(doc_id, (None, None))
            
            rrf_score = 0.0
            if bm25_rank:
                rrf_score += w_bm25 / (self.k + bm25_rank)
            if vector_rank:
                rrf_score += w_vector / (self.k + vector_rank)
            
            fused.append(FusionResult(
                document_id=doc_id,
                rrf_score=rrf_score,
                bm25_rank=bm25_rank,
                bm25_score=bm25_score,
                vector_rank=vector_rank,
                vector_score=vector_score,
                result=all_results[doc_id]
            ))
        
        # Sort by RRF score descending
        fused.sort(key=lambda x: x.rrf_score, reverse=True)
        
        # Update ranks
        for i, item in enumerate(fused[:limit]):
            item.result.rank = i + 1
        
        return fused[:limit]
    
    def fuse_multi(
        self,
        result_sets: List[Tuple[str, List[SearchResult]]],
        limit: int = 10,
        weights: Optional[Dict[str, float]] = None
    ) -> List[FusionResult]:
        """Fuse results from multiple search backends.
        
        Args:
            result_sets: List of (name, results) tuples
            limit: Maximum results to return
            weights: Optional weights for each backend
            
        Returns:
            Fused and ranked results
        """
        weights = weights or {name: 1.0 for name, _ in result_sets}
        
        # Create rank mappings for each backend
        all_ranks = {}
        all_results = {}
        
        for name, results in result_sets:
            all_ranks[name] = {r.document_id: (idx + 1, r.score) 
                              for idx, r in enumerate(results)}
            for r in results:
                if r.document_id not in all_results:
                    all_results[r.document_id] = r
        
        # Get all unique IDs
        all_ids = set()
        for ranks in all_ranks.values():
            all_ids.update(ranks.keys())
        
        # Compute RRF scores
        fused = []
        for doc_id in all_ids:
            rrf_score = 0.0
            rank_info = {}
            
            for name, ranks in all_ranks.items():
                rank, score = ranks.get(doc_id, (None, None))
                if rank:
                    weight = weights.get(name, 1.0)
                    rrf_score += weight / (self.k + rank)
                    rank_info[f"{name}_rank"] = rank
                    rank_info[f"{name}_score"] = score
            
            fused.append(FusionResult(
                document_id=doc_id,
                rrf_score=rrf_score,
                bm25_rank=rank_info.get('bm25_rank'),
                bm25_score=rank_info.get('bm25_score'),
                vector_rank=rank_info.get('vector_rank'),
                vector_score=rank_info.get('vector_score'),
                result=all_results[doc_id]
            ))
        
        fused.sort(key=lambda x: x.rrf_score, reverse=True)
        return fused[:limit]


# ============================================================================
# Enhanced Hybrid Search Service
# ============================================================================

class HybridSearchService:
    """Production-grade hybrid search service for TCU legal documents.
    
    Features:
    - Intelligent query routing
    - Parallel search execution
    - Multi-layer caching
    - Configurable RRF fusion
    - Comprehensive metrics
    - Graceful degradation
    """
    
    def __init__(
        self,
        es_client: Optional[Any] = None,
        pg_client: Optional[Any] = None,
        embedding_service: Optional[Any] = None,
        cache_backend: Optional[CacheBackend] = None,
        settings: Optional[Settings] = None,
        vector_search_backend: SearchBackend = SearchBackend.ELASTICSEARCH
    ):
        """Initialize hybrid search service.
        
        Args:
            es_client: Elasticsearch client
            pg_client: PostgreSQL client (for pgvector)
            embedding_service: Service for generating embeddings
            cache_backend: Cache implementation
            settings: Application settings
            vector_search_backend: Backend for vector search
        """
        self.es_client = es_client
        self.pg_client = pg_client
        self.embedding_service = embedding_service
        self.cache = cache_backend
        self.vector_search_backend = vector_search_backend
        
        # Configuration
        settings = settings or Settings()
        self.index_name = settings.elasticsearch_index
        self.rrf_k = settings.search_rrf_k
        self.default_limit = settings.search_default_limit
        self.max_limit = settings.search_max_limit
        self.timeout_ms = settings.search_timeout_ms
        
        # Components
        self.router = QueryRouter()
        self.fusion_engine = RRFFusionEngine(k=self.rrf_k)
        
        # Metrics
        self._metrics: List[SearchMetrics] = []
        self._total_queries = 0
        self._cache_hits = 0
        
    # =======================================================================
    # Public API
    # =======================================================================
    
    async def search(
        self,
        request: SearchRequest,
        use_cache: bool = True
    ) -> SearchResponse:
        """Execute hybrid search with intelligent routing.
        
        Args:
            request: Search request with query and parameters
            use_cache: Whether to use result caching
            
        Returns:
            SearchResponse with fused results
        """
        start_time = time.time()
        
        # Analyze query for routing
        query_analysis = self.router.analyze(request.query)
        
        # Check cache
        if use_cache and self.cache:
            cached = await self._get_cached_result(request, query_analysis)
            if cached:
                self._cache_hits += 1
                cached.took_ms = (time.time() - start_time) * 1000
                return cached
        
        # Execute search based on query type
        results, metadata = await self._execute_search(
            request, query_analysis
        )
        
        # Build response
        response = SearchResponse(
            query=request.query,
            total=len(results),
            took_ms=round((time.time() - start_time) * 1000, 2),
            hits=results,
        )
        
        # Cache result
        if use_cache and self.cache:
            await self._cache_result(request, query_analysis, response)
        
        # Record metrics
        self._record_metrics(query_analysis, metadata, start_time)
        
        return response
    
    async def search_exact(
        self,
        query: str,
        filters: Optional[SearchFilters] = None,
        limit: int = 10,
        fields: Optional[List[str]] = None
    ) -> List[SearchHit]:
        """Execute exact match search only.
        
        Args:
            query: Search query
            filters: Optional filters
            limit: Maximum results
            fields: Fields to search
            
        Returns:
            List of SearchHit results
        """
        results = await self._search_bm25(query, filters, limit, fields)
        return self._to_search_hits(results, 'bm25')
    
    async def search_semantic(
        self,
        query: str,
        filters: Optional[SearchFilters] = None,
        limit: int = 10
    ) -> List[SearchHit]:
        """Execute semantic search only.
        
        Args:
            query: Search query
            filters: Optional filters
            limit: Maximum results
            
        Returns:
            List of SearchHit results
        """
        embedding = await self._get_embedding(query)
        if not embedding:
            return []
        
        results = await self._search_vector(embedding, filters, limit)
        return self._to_search_hits(results, 'vector')
    
    async def explain(
        self,
        request: SearchRequest
    ) -> Dict[str, Any]:
        """Explain search results with scoring details.
        
        Args:
            request: Search request
            
        Returns:
            Dict with query analysis, scores, and fusion details
        """
        query_analysis = self.router.analyze(request.query)
        
        # Execute both searches for explanation
        bm25_results = await self._search_bm25(
            request.query, limit=request.limit * 3
        )
        
        embedding = await self._get_embedding(request.query)
        vector_results = await self._search_vector(
            embedding, limit=request.limit * 3
        ) if embedding else []
        
        # Fuse with full provenance
        weights = self.router.get_optimal_weights(query_analysis.query_type)
        fused = self.fusion_engine.fuse(
            bm25_results, vector_results, request.limit, weights
        )
        
        return {
            'query_analysis': {
                'type': query_analysis.query_type.name,
                'normalized': query_analysis.normalized_query,
                'entities': query_analysis.detected_entities,
            },
            'weights': weights,
            'rrf_k': self.rrf_k,
            'bm25_count': len(bm25_results),
            'vector_count': len(vector_results),
            'fused': [
                {
                    'document_id': f.document_id,
                    'rrf_score': f.rrf_score,
                    'bm25_rank': f.bm25_rank,
                    'bm25_score': f.bm25_score,
                    'vector_rank': f.vector_rank,
                    'vector_score': f.vector_score,
                }
                for f in fused
            ]
        }
    
    # =======================================================================
    # Internal Methods
    # =======================================================================
    
    async def _execute_search(
        self,
        request: SearchRequest,
        query_analysis: SearchQuery
    ) -> Tuple[List[SearchHit], Dict[str, Any]]:
        """Execute search based on query type."""
        
        query_type = query_analysis.query_type
        
        if query_type == QueryType.EXACT_MATCH:
            return await self._search_exact_match(request)
        elif query_type == QueryType.SEMANTIC:
            return await self._search_semantic_only(request)
        else:
            return await self._search_hybrid_full(request, query_analysis)
    
    async def _search_exact_match(
        self,
        request: SearchRequest
    ) -> Tuple[List[SearchHit], Dict[str, Any]]:
        """Execute exact match search."""
        results = await self._search_bm25(
            request.query,
            filters=None,
            sources=request.sources,
            limit=request.limit
        )
        
        hits = self._to_search_hits(results, 'bm25')
        metadata = {'query_type': 'exact_match', 'bm25_count': len(results)}
        return hits, metadata
    
    async def _search_semantic_only(
        self,
        request: SearchRequest
    ) -> Tuple[List[SearchHit], Dict[str, Any]]:
        """Execute semantic search only."""
        embedding = await self._get_embedding(request.query)
        
        if not embedding:
            return [], {'error': 'embedding_failed'}
        
        results = await self._search_vector(
            embedding,
            filters=None,
            sources=request.sources,
            limit=request.limit
        )
        
        hits = self._to_search_hits(results, 'vector')
        metadata = {'query_type': 'semantic', 'vector_count': len(results)}
        return hits, metadata
    
    async def _search_hybrid_full(
        self,
        request: SearchRequest,
        query_analysis: SearchQuery
    ) -> Tuple[List[SearchHit], Dict[str, Any]]:
        """Execute full hybrid search with RRF fusion."""
        
        # Get embedding first (needed before parallel search)
        embedding = await self._get_embedding(request.query)
        
        # Execute searches in parallel
        bm25_task = self._search_bm25(
            request.query,
            filters=None,
            sources=request.sources,
            limit=request.limit * 3
        )
        
        tasks: List[asyncio.Task] = [asyncio.create_task(bm25_task)]
        
        if embedding:
            vector_task = self._search_vector(
                embedding,
                filters=None,
                sources=request.sources,
                limit=request.limit * 3
            )
            tasks.append(asyncio.create_task(vector_task))
        
        # Wait for results
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        bm25_results = results[0] if results and not isinstance(results[0], Exception) else []
        vector_results = results[1] if len(results) > 1 and not isinstance(results[1], Exception) else []
        
        # Fuse results
        weights = request.hybrid_weights or self.router.get_optimal_weights(
            query_analysis.query_type
        )
        
        fused = self.fusion_engine.fuse(
            bm25_results,
            vector_results,
            limit=request.limit,
            weights=weights
        )
        
        # Convert to SearchHit
        hits = [
            SearchHit(
                document_id=f.document_id,
                title=f.result.title,
                content_preview=f.result.content_preview,
                source_id=f.result.source_id,
                source_type=f.result.source_type,
                score=round(f.rrf_score, 4),
                bm25_score=f.bm25_score,
                vector_score=f.vector_score,
                rank_bm25=f.bm25_rank,
                rank_vector=f.vector_rank,
                metadata=f.result.metadata,
                url=f.result.url
            )
            for f in fused
        ]
        
        metadata = {
            'query_type': 'hybrid',
            'bm25_count': len(bm25_results),
            'vector_count': len(vector_results),
            'fused_count': len(fused),
            'weights': weights,
            'rrf_k': self.rrf_k,
        }
        
        return hits, metadata
    
    async def _search_bm25(
        self,
        query: str,
        filters: Optional[SearchFilters] = None,
        sources: Optional[List[str]] = None,
        limit: int = 100
    ) -> List[SearchResult]:
        """Execute BM25 search via Elasticsearch."""
        if not self.es_client:
            return []
        
        try:
            es_query = {
                "bool": {
                    "must": [{
                        "multi_match": {
                            "query": query,
                            "fields": [
                                "title^3",
                                "content^2",
                                "content_preview",
                                "metadata.*"
                            ],
                            "type": "best_fields",
                            "fuzziness": "AUTO"
                        }
                    }],
                    "filter": [{"term": {"is_deleted": False}}]
                }
            }
            
            # Add source filter
            if sources:
                es_query["bool"]["filter"].append(
                    {"terms": {"source_id": sources}}
                )
            
            response = await self.es_client.search(
                index=self.index_name,
                query=es_query,
                size=min(limit, self.max_limit),
                timeout=f"{self.timeout_ms}ms"
            )
            
            return [
                SearchResult(
                    document_id=hit["_id"],
                    content=hit["_source"].get("content", ""),
                    title=hit["_source"].get("title"),
                    score=hit["_score"],
                    source_id=hit["_source"].get("source_id", "unknown"),
                    source_type=hit["_source"].get("source_type"),
                    metadata=hit["_source"].get("metadata", {}),
                    content_preview=hit["_source"].get("content_preview"),
                    url=hit["_source"].get("url")
                )
                for hit in response.get("hits", {}).get("hits", [])
            ]
            
        except Exception as e:
            logger.error(f"BM25 search failed: {e}")
            return []
    
    async def _search_vector(
        self,
        embedding: List[float],
        filters: Optional[SearchFilters] = None,
        sources: Optional[List[str]] = None,
        limit: int = 100
    ) -> List[SearchResult]:
        """Execute vector search."""
        if self.vector_search_backend == SearchBackend.PGVECTOR:
            return await self._search_vector_pg(embedding, filters, limit)
        else:
            return await self._search_vector_es(embedding, sources, limit)
    
    async def _search_vector_es(
        self,
        embedding: List[float],
        sources: Optional[List[str]] = None,
        limit: int = 100
    ) -> List[SearchResult]:
        """Execute vector search via Elasticsearch kNN."""
        if not self.es_client:
            return []
        
        try:
            knn_query = {
                "field": "content_vector",
                "query_vector": embedding,
                "k": min(limit * 2, self.max_limit),
                "num_candidates": 100,
                "filter": {"term": {"is_deleted": False}}
            }
            
            if sources:
                knn_query["filter"] = {
                    "bool": {
                        "filter": [
                            {"term": {"is_deleted": False}},
                            {"terms": {"source_id": sources}}
                        ]
                    }
                }
            
            response = await self.es_client.search(
                index=self.index_name,
                knn=knn_query,
                size=limit,
                timeout=f"{self.timeout_ms}ms"
            )
            
            return [
                SearchResult(
                    document_id=hit["_id"],
                    content=hit["_source"].get("content", ""),
                    title=hit["_source"].get("title"),
                    score=hit["_score"],
                    source_id=hit["_source"].get("source_id", "unknown"),
                    source_type=hit["_source"].get("source_type"),
                    metadata=hit["_source"].get("metadata", {}),
                    content_preview=hit["_source"].get("content_preview"),
                    url=hit["_source"].get("url")
                )
                for hit in response.get("hits", {}).get("hits", [])
            ]
            
        except Exception as e:
            logger.error(f"Vector search (ES) failed: {e}")
            return []
    
    async def _search_vector_pg(
        self,
        embedding: List[float],
        filters: Optional[SearchFilters] = None,
        limit: int = 100
    ) -> List[SearchResult]:
        """Execute vector search via pgvector."""
        try:
            from gabi.db import get_session_no_commit
            from gabi.models.chunk import DocumentChunk
            from gabi.models.document import Document
            from sqlalchemy import select
            
            query = (
                select(
                    DocumentChunk.document_id,
                    DocumentChunk.chunk_text,
                    DocumentChunk.chunk_metadata,
                    DocumentChunk.embedding.cosine_distance(embedding).label("distance"),
                    Document.title,
                    Document.content_preview,
                    Document.source_id,
                    Document.doc_metadata,
                    Document.url,
                )
                .join(Document, DocumentChunk.document_id == Document.document_id)
                .where(DocumentChunk.embedding.isnot(None))
                .where(Document.is_deleted == False)
                .order_by("distance")
                .limit(limit * 3)
            )
            
            async with get_session_no_commit() as session:
                result = await session.execute(query)
                rows = result.all()
            
            # Deduplicate by document_id
            seen = set()
            results = []
            for row in rows:
                if row.document_id in seen:
                    continue
                seen.add(row.document_id)
                
                similarity = 1.0 - float(row.distance)
                results.append(SearchResult(
                    document_id=str(row.document_id),
                    content=row.chunk_text or "",
                    title=row.title,
                    score=similarity,
                    source_id=row.source_id,
                    source_type=None,
                    metadata=row.doc_metadata or {},
                    content_preview=row.content_preview,
                    url=row.url
                ))
                
                if len(results) >= limit:
                    break
            
            return results
            
        except Exception as e:
            logger.error(f"Vector search (pgvector) failed: {e}")
            return []
    
    async def _get_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding for text."""
        if not self.embedding_service:
            return None
        
        try:
            if hasattr(self.embedding_service, 'embed'):
                return await self.embedding_service.embed(text)
            else:
                return self.embedding_service.embed(text)
        except Exception as e:
            logger.warning(f"Failed to generate embedding: {e}")
            return None
    
    def _to_search_hits(
        self,
        results: List[SearchResult],
        search_type: str
    ) -> List[SearchHit]:
        """Convert SearchResults to SearchHits."""
        return [
            SearchHit(
                document_id=r.document_id,
                title=r.title,
                content_preview=r.content_preview or r.content[:500] if r.content else None,
                source_id=r.source_id,
                source_type=r.source_type,
                score=round(r.score, 4),
                bm25_score=r.score if search_type == 'bm25' else None,
                vector_score=r.score if search_type == 'vector' else None,
                metadata=r.metadata,
                url=r.url
            )
            for r in results
        ]
    
    # =======================================================================
    # Caching
    # =======================================================================
    
    def _get_cache_key(
        self,
        request: SearchRequest,
        query_analysis: SearchQuery
    ) -> str:
        """Generate cache key for search request."""
        key_data = {
            'query': query_analysis.normalized_query,
            'type': query_analysis.query_type.name,
            'sources': sorted(request.sources) if request.sources else None,
            'filters': request.filters,
            'limit': request.limit,
            'weights': request.hybrid_weights,
        }
        key_str = json.dumps(key_data, sort_keys=True)
        hash_val = hashlib.sha256(key_str.encode()).hexdigest()[:16]
        return f"search:{query_analysis.query_type.name.lower()}:{hash_val}"
    
    async def _get_cached_result(
        self,
        request: SearchRequest,
        query_analysis: SearchQuery
    ) -> Optional[SearchResponse]:
        """Get cached search result."""
        if not self.cache:
            return None
        
        key = self._get_cache_key(request, query_analysis)
        cached = await self.cache.get(key)
        
        if cached:
            try:
                return SearchResponse.model_validate(cached)
            except Exception:
                pass
        return None
    
    async def _cache_result(
        self,
        request: SearchRequest,
        query_analysis: SearchQuery,
        response: SearchResponse
    ) -> None:
        """Cache search result."""
        if not self.cache:
            return
        
        # Cache exact matches longer, semantic shorter
        if query_analysis.query_type == QueryType.EXACT_MATCH:
            ttl = 600  # 10 minutes
        elif query_analysis.query_type == QueryType.SEMANTIC:
            ttl = 180  # 3 minutes
        else:
            ttl = 300  # 5 minutes
        
        key = self._get_cache_key(request, query_analysis)
        await self.cache.set(key, response.model_dump(), ttl)
    
    # =======================================================================
    # Metrics
    # =======================================================================
    
    def _record_metrics(
        self,
        query_analysis: SearchQuery,
        metadata: Dict[str, Any],
        start_time: float
    ) -> None:
        """Record search metrics."""
        self._total_queries += 1
        
        metrics = SearchMetrics(
            query_type=query_analysis.query_type,
            backend_used=self.vector_search_backend.value,
            bm25_results=metadata.get('bm25_count', 0),
            vector_results=metadata.get('vector_count', 0),
            fused_results=metadata.get('fused_count', 0),
            took_ms=(time.time() - start_time) * 1000,
            cache_hit=False
        )
        
        self._metrics.append(metrics)
        
        # Keep only last 1000 metrics
        if len(self._metrics) > 1000:
            self._metrics = self._metrics[-1000:]
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get aggregated metrics."""
        if not self._metrics:
            return {}
        
        total = len(self._metrics)
        cache_hit_rate = self._cache_hits / max(self._total_queries, 1)
        
        by_type = defaultdict(lambda: {'count': 0, 'avg_time': 0})
        for m in self._metrics:
            by_type[m.query_type.name]['count'] += 1
            by_type[m.query_type.name]['avg_time'] += m.took_ms
        
        for t in by_type.values():
            t['avg_time'] /= max(t['count'], 1)
        
        return {
            'total_queries': self._total_queries,
            'cache_hit_rate': cache_hit_rate,
            'by_query_type': dict(by_type),
            'avg_response_time_ms': sum(m.took_ms for m in self._metrics) / total,
        }
    
    # =======================================================================
    # Health Check
    # =======================================================================
    
    async def health_check(self) -> HealthResponse:
        """Check health of all search backends."""
        start_time = time.time()
        
        indices = []
        es_healthy = False
        
        if self.es_client:
            try:
                cluster_health = await self.es_client.cluster.health()
                status = cluster_health.get("status", "red")
                es_healthy = status in ("green", "yellow")
                
                indices.append(IndexHealth(
                    index=self.index_name,
                    status=status,
                    docs_count=cluster_health.get("indices", {}).get(self.index_name, {}).get("docs", {}).get("count", 0),
                    size_mb=0.0
                ))
            except Exception as e:
                logger.error(f"ES health check failed: {e}")
        
        overall = "healthy" if es_healthy else "unhealthy"
        
        return HealthResponse(
            status=overall,
            indices=indices,
            took_ms=round((time.time() - start_time) * 1000, 2)
        )
```

---

## 2. RRF Algorithm Implementation

### 2.1 Mathematical Foundation

**Reciprocal Rank Fusion (RRF)** combines ranked lists from multiple sources:

```
RRF_score(d) = Σᵢ (wᵢ / (k + rᵢ(d)))

Where:
- d: document
- i: search method (BM25, vector, etc.)
- wᵢ: weight for method i
- k: constant (default 60) to reduce high-rank impact
- rᵢ(d): rank of document d in method i (1-indexed)
```

### 2.2 Key Properties

| Property | Value | Rationale |
|----------|-------|-----------|
| k constant | 60 | Industry standard, balances top vs deep results |
| Rank scaling | 1-indexed | Mathematical convention |
| Score range | (0, Σwᵢ/k] | Theoretically unbounded, practically limited |
| Normalization | None | RRF scores are comparable within query only |

### 2.3 Implementation Details

```python
class RRFFusionEngine:
    def fuse(self, results_a, results_b, k=60, weights=None):
        """
        Algorithm:
        1. Assign ranks (1-indexed) to each result list
        2. For each unique document:
           - Calculate contribution from each source: weight / (k + rank)
           - Sum contributions for final RRF score
        3. Sort by RRF score descending
        4. Return top N results
        """
        
        # Example calculation:
        # Doc X: BM25 rank=1, Vector rank=3, k=60, weights={bm25:1, vector:1}
        # RRF = 1/(60+1) + 1/(60+3) = 0.0164 + 0.0159 = 0.0323
        
        # Doc Y: BM25 rank=5, Vector rank=1
        # RRF = 1/(60+5) + 1/(60+1) = 0.0154 + 0.0164 = 0.0318
        
        # Doc X ranks higher despite not being #1 in either list
```

### 2.4 Weight Tuning for TCU Domain

| Query Type | BM25 Weight | Vector Weight | Rationale |
|------------|-------------|---------------|-----------|
| Citation search (AC 1234/2024) | 1.5 | 0.5 | Prioritize exact matches |
| Conceptual query | 0.5 | 1.5 | Prioritize semantic similarity |
| Mixed query | 1.0 | 1.0 | Balanced approach |
| Quoted phrase | 1.3 | 0.7 | Phrases need exact match boost |

---

## 3. Query Routing Logic

### 3.1 Query Classification

```
┌──────────────────────────────────────────────────────────────────────┐
│                        QUERY ROUTING FLOW                            │
└──────────────────────────────────────────────────────────────────────┘

User Query
    │
    ▼
┌─────────────────┐
│  Preprocessing  │ → Normalize, tokenize, lowercase
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Entity Extraction│ → Extract: acórdãos, processos, leis, súmulas
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌───────────────┐
│ Pattern Matching │ ──→│ Has Citation? │──Yes──→ EXACT_MATCH
└────────┬────────┘     └───────────────┘
         │                           No
         │                              │
         ▼                              ▼
┌─────────────────┐              ┌───────────────┐
│ Semantic Terms? │──Yes────────→│ Has Mixed?    │──Yes──→ HYBRID
└────────┬────────┘              └───────────────┘
         │ No                              No
         │                                  │
         ▼                                  ▼
    SEMANTIC                          SEMANTIC
```

### 3.2 TCU-Specific Patterns

```python
# Acórdão patterns
"AC 1234/2024"          → EXACT_MATCH (document number)
"Acórdão 1234/2024"     → EXACT_MATCH
"1234/2024"             → EXACT_MATCH (year suffix)

# Process patterns  
"TC-123.456/2024"       → EXACT_MATCH
"processo 123456/2024"  → EXACT_MATCH

# Norm patterns
"Lei 8.666/93"          → EXACT_MATCH
"IN TCU 65/2013"        → EXACT_MATCH
"Súmula 123"            → EXACT_MATCH

# Conceptual patterns
"licitação pregão"      → SEMANTIC
"direito adquirido"     → SEMANTIC
"""enunciado 123"""    → HYBRID (quoted phrase)

# Mixed patterns
"Ac 1234/2024 sobre licitação"  → HYBRID
```

### 3.3 Routing Decision Matrix

| Detected Pattern | Routing | BM25 Weight | Vector Weight |
|------------------|---------|-------------|---------------|
| citation + semantic_terms | HYBRID | 1.0 | 1.0 |
| citation only | EXACT_MATCH | 1.5 | 0.5 |
| quoted_phrase | HYBRID | 1.3 | 0.7 |
| semantic_terms only | SEMANTIC | 0.5 | 1.5 |
| year + keywords | HYBRID | 1.0 | 1.0 |
| default | HYBRID | 1.0 | 1.0 |

---

## 4. Caching Layer Design

### 4.1 Multi-Layer Cache Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CACHE LAYERS                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────┐   │
│  │   L1: In-Memory  │  │   L2: Redis      │  │   L3: Persistent│   │
│  │   (Application)  │  │   (Distributed)  │  │   (Optional)    │   │
│  │                  │  │                  │  │                 │   │
│  │  TTL: 60s        │  │  TTL: 300s       │  │  TTL: 1h        │   │
│  │  Size: 1000      │  │  Size: 10000     │  │  Size: 100000   │   │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬────────┘   │
│           │                     │                     │            │
│           └─────────────────────┼─────────────────────┘            │
│                                 │                                  │
│                                 ▼                                  │
│                    ┌─────────────────────────┐                     │
│                    │   Search Execution      │                     │
│                    └─────────────────────────┘                     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 Cache Key Strategy

```python
def generate_cache_key(request, query_analysis):
    """
    Cache key format: search:{type}:{hash}
    
    Components hashed:
    - Normalized query string
    - Query type
    - Sorted sources list
    - Filters (normalized)
    - Limit
    - Hybrid weights
    
    Example keys:
    - search:exact:a3f7b2d8e1c4
    - search:semantic:9e5c2a1b7f3d
    - search:hybrid:2d8e4c6a9b1f
    """
    key_data = {
        'query': query_analysis.normalized_query,
        'type': query_analysis.query_type.name,
        'sources': sorted(request.sources) if request.sources else None,
        'filters': normalize_filters(request.filters),
        'limit': request.limit,
        'weights': request.hybrid_weights,
    }
    hash_val = sha256(json.dumps(key_data, sort_keys=True)).hex()[:12]
    return f"search:{query_analysis.query_type.name.lower()}:{hash_val}"
```

### 4.3 TTL Strategy by Query Type

| Query Type | TTL | Rationale |
|------------|-----|-----------|
| EXACT_MATCH | 10 min | Citations rarely change, high reuse |
| SEMANTIC | 3 min | Conceptual results may evolve |
| HYBRID | 5 min | Balanced approach |
| Health Check | 30 sec | Status changes quickly |

### 4.4 Cache Invalidation

```python
class CacheManager:
    """Cache invalidation strategies."""
    
    async def invalidate_document(self, document_id: str):
        """Invalidate all cache entries containing document."""
        # Pattern: search:*:{hash}
        # Invalidate by document ID requires tracking reverse index
        pass
    
    async def invalidate_source(self, source_id: str):
        """Invalidate all cache entries for a source."""
        # Invalidate all keys with matching source
        pass
    
    async def invalidate_query_type(self, query_type: QueryType):
        """Invalidate by query type (e.g., after model update)."""
        pattern = f"search:{query_type.name.lower()}:*"
        await self.cache.delete_pattern(pattern)
```

---

## 5. Performance Benchmarks and Optimization

### 5.1 Target Performance Metrics

| Metric | Target | P95 | P99 |
|--------|--------|-----|-----|
| End-to-end latency | <50ms | <100ms | <200ms |
| BM25 only | <20ms | <30ms | <50ms |
| Vector only | <30ms | <50ms | <100ms |
| Hybrid (parallel) | <50ms | <100ms | <200ms |
| Embedding generation | <100ms | <150ms | <300ms |
| Cache hit latency | <5ms | <10ms | <20ms |

### 5.2 Optimization Strategies

#### 5.2.1 Elasticsearch Optimizations

```python
# Index settings for legal documents
INDEX_SETTINGS = {
    "number_of_shards": 3,           # Scale with data volume
    "number_of_replicas": 1,          # High availability
    "refresh_interval": "5s",         # Near real-time
    "index.store.preload": ["nvd", "dvd"],  # Warm filesystem cache
    
    "analysis": {
        "analyzer": {
            "pt_br_legal": {
                "type": "custom",
                "tokenizer": "standard",
                "filter": [
                    "lowercase",
                    "brazilian_stop",
                    "brazilian_stemmer",
                    "legal_synonyms"     # TCU-specific synonyms
                ]
            }
        }
    }
}

# Query optimizations
- Use `constant_score` for exact matches
- Limit `size` to required results
- Use `terminate_after` for early termination
- Enable `track_total_hits: false` for pagination
```

#### 5.2.2 Vector Search Optimizations

```python
# pgvector optimizations
"""
-- HNSW index for approximate nearest neighbors
CREATE INDEX ON document_chunks 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- Query with ef parameter for recall vs speed trade-off
SET hnsw.ef_search = 100;  -- Higher = better recall, slower
"""

# Elasticsearch kNN optimizations
knn_query = {
    "field": "content_vector",
    "query_vector": embedding,
    "k": 100,
    "num_candidates": 1000,  # Higher = better recall
    "filter": {...}  # Pre-filter to reduce candidates
}
```

#### 5.2.3 Parallel Execution

```python
async def execute_parallel_search(
    bm25_query: dict,
    vector_query: dict
) -> Tuple[List, List]:
    """Execute both searches concurrently."""
    
    bm25_task = asyncio.create_task(
        es.search(**bm25_query)
    )
    vector_task = asyncio.create_task(
        es.search(knn=vector_query)
    )
    
    # Wait with timeout
    done, pending = await asyncio.wait(
        [bm25_task, vector_task],
        timeout=timeout_ms / 1000,
        return_when=asyncio.ALL_COMPLETED
    )
    
    # Cancel pending if timeout
    for task in pending:
        task.cancel()
    
    return bm25_task.result(), vector_task.result()
```

#### 5.2.4 Embedding Optimizations

```python
# Request coalescing
pending_embeddings: Dict[str, asyncio.Future] = {}

async def embed_with_coalescing(text: str) -> List[float]:
    """Coalesce duplicate embedding requests."""
    if text in pending_embeddings:
        return await pending_embeddings[text]
    
    future = asyncio.Future()
    pending_embeddings[text] = future
    
    try:
        embedding = await generate_embedding(text)
        future.set_result(embedding)
        return embedding
    finally:
        del pending_embeddings[text]

# Batch embedding
async def embed_batch(texts: List[str]) -> List[List[float]]:
    """Embed multiple texts efficiently."""
    # Process in optimal batch size
    batch_size = 32
    results = []
    
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        embeddings = await embedder.embed_batch(batch)
        results.extend(embeddings)
    
    return results
```

### 5.3 Benchmarking Framework

```python
# benchmarks/search_benchmark.py

import asyncio
import time
from dataclasses import dataclass
from typing import List
import statistics

@dataclass
class BenchmarkResult:
    query_type: str
    query: str
    latency_ms: float
    bm25_results: int
    vector_results: int
    fused_results: int
    cache_hit: bool

class SearchBenchmark:
    """Benchmark suite for hybrid search."""
    
    TEST_QUERIES = {
        'exact_match': [
            "AC 1234/2024",
            "Lei 8.666/93",
            "IN TCU 65/2013",
        ],
        'semantic': [
            "licitação pregão eletrônico",
            "direito adquirido servidor",
            "responsabilidade fiscal",
        ],
        'hybrid': [
            "Acórdão 1234/2024 sobre licitação",
            "Súmula 123 aplicada ao caso",
        ]
    }
    
    async def run_benchmark(
        self,
        iterations: int = 100
    ) -> Dict[str, List[BenchmarkResult]]:
        """Run comprehensive benchmark."""
        results = defaultdict(list)
        
        for query_type, queries in self.TEST_QUERIES.items():
            for query in queries:
                for _ in range(iterations):
                    start = time.time()
                    response = await self.service.search(
                        SearchRequest(query=query)
                    )
                    latency = (time.time() - start) * 1000
                    
                    results[query_type].append(BenchmarkResult(
                        query_type=query_type,
                        query=query,
                        latency_ms=latency,
                        bm25_results=response.metadata.get('bm25_count', 0),
                        vector_results=response.metadata.get('vector_count', 0),
                        fused_results=len(response.hits),
                        cache_hit=response.metadata.get('cache_hit', False)
                    ))
        
        return results
    
    def generate_report(
        self,
        results: Dict[str, List[BenchmarkResult]]
    ) -> str:
        """Generate benchmark report."""
        report = ["# Search Benchmark Report\n"]
        
        for query_type, results_list in results.items():
            latencies = [r.latency_ms for r in results_list]
            
            report.append(f"\n## {query_type.upper()}")
            report.append(f"- Count: {len(results_list)}")
            report.append(f"- Mean: {statistics.mean(latencies):.2f}ms")
            report.append(f"- Median: {statistics.median(latencies):.2f}ms")
            report.append(f"- P95: {self._percentile(latencies, 95):.2f}ms")
            report.append(f"- P99: {self._percentile(latencies, 99):.2f}ms")
            report.append(f"- Min: {min(latencies):.2f}ms")
            report.append(f"- Max: {max(latencies):.2f}ms")
        
        return '\n'.join(report)
```

### 5.4 Capacity Planning

| Documents | Index Size | Shards | Memory | Concurrent Users | QPS |
|-----------|------------|--------|--------|------------------|-----|
| 100K | 10GB | 1 | 4GB | 10 | 50 |
| 1M | 100GB | 3 | 16GB | 50 | 200 |
| 10M | 1TB | 10 | 64GB | 200 | 1000 |
| 100M | 10TB | 50 | 256GB | 1000 | 5000 |

---

## 6. Integration Points

### 6.1 Service Integration

```python
# FastAPI dependency injection
async def get_hybrid_search_service(
    es_client: AsyncElasticsearch = Depends(get_es_client),
    redis_client: Redis = Depends(get_redis_client),
) -> HybridSearchService:
    """Factory for HybridSearchService."""
    
    embedder = EmbeddingService()
    cache = RedisCacheBackend(redis_client)
    
    return HybridSearchService(
        es_client=es_client,
        embedding_service=embedder,
        cache_backend=cache,
        vector_search_backend=SearchBackend.ELASTICSEARCH
    )

# API endpoint
@router.post("/search", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    service: HybridSearchService = Depends(get_hybrid_search_service)
):
    """Execute hybrid search."""
    return await service.search(request)
```

### 6.2 Configuration

```yaml
# config/search.yaml
search:
  rrf:
    k: 60
    weights:
      exact_match:
        bm25: 1.5
        vector: 0.5
      semantic:
        bm25: 0.5
        vector: 1.5
      hybrid:
        bm25: 1.0
        vector: 1.0
  
  cache:
    enabled: true
    ttl_seconds:
      exact_match: 600
      semantic: 180
      hybrid: 300
  
  vector_search:
    backend: elasticsearch  # or pgvector
    top_k: 100
    min_score: 0.7
  
  elasticsearch:
    index_name: gabi_documents_v1
    timeout_ms: 5000
    max_results: 100
    
  performance:
    parallel_search: true
    request_timeout_ms: 10000
    max_concurrent_requests: 100
```

---

## 7. Monitoring and Observability

### 7.1 Metrics to Track

```python
# Key metrics
METRICS = {
    # Latency
    'search_latency_ms': Histogram,
    'bm25_latency_ms': Histogram,
    'vector_latency_ms': Histogram,
    'embedding_latency_ms': Histogram,
    
    # Throughput
    'search_requests_total': Counter,
    'search_requests_by_type': Counter,
    
    # Quality
    'cache_hit_rate': Gauge,
    'rrf_fusion_ratio': Gauge,  # BM25-only vs Vector-only results
    
    # Errors
    'search_errors_total': Counter,
    'embedding_failures_total': Counter,
    
    # System
    'es_index_size_bytes': Gauge,
    'pgvector_index_size_bytes': Gauge,
}
```

### 7.2 Alerting Rules

```yaml
# alerts/search_alerts.yaml
alerts:
  - name: HighSearchLatency
    condition: search_latency_p95 > 200ms
    duration: 5m
    severity: warning
    
  - name: SearchErrors
    condition: rate(search_errors_total[5m]) > 0.01
    duration: 2m
    severity: critical
    
  - name: LowCacheHitRate
    condition: cache_hit_rate < 0.5
    duration: 10m
    severity: warning
    
  - name: EmbeddingServiceDown
    condition: embedding_failures_total > 10
    duration: 1m
    severity: critical
```

---

## 8. Conclusion

This hybrid search architecture provides:

1. **Intelligent Query Routing**: Automatically detects query types and optimizes search strategy
2. **Production-Ready RRF**: Configurable fusion with TCU-specific weighting
3. **Multi-Layer Caching**: Redis-based caching with TTL strategies by query type
4. **Performance Optimized**: Parallel execution, request coalescing, and optimized indices
5. **Observable**: Comprehensive metrics and alerting for production monitoring

### Next Steps

1. Implement `HybridSearchService` class
2. Add query router with TCU-specific patterns
3. Set up Redis cache layer
4. Create benchmark suite
5. Deploy with feature flags for gradual rollout
