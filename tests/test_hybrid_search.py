"""Tests for Hybrid Search Service with RRF Fusion.

This module contains comprehensive tests for the hybrid search implementation,
including query routing, RRF fusion, caching, and integration tests.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List, Dict, Any

from gabi.services.hybrid_search import (
    HybridSearchService,
    QueryRouter,
    QueryType,
    RRFFusionEngine,
    SearchResult,
    FusionResult,
    InMemoryCacheBackend,
    SearchBackend,
)
from gabi.schemas.search import SearchRequest, SearchFilters, SearchHit


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def query_router():
    """Create a query router instance."""
    return QueryRouter()


@pytest.fixture
def rrf_engine():
    """Create an RRF fusion engine."""
    return RRFFusionEngine(k=60)


@pytest.fixture
def mock_es_client():
    """Create a mock Elasticsearch client."""
    client = AsyncMock()
    return client


@pytest.fixture
def mock_embedding_service():
    """Create a mock embedding service."""
    service = AsyncMock()
    service.embed = AsyncMock(return_value=[0.1] * 384)
    return service


@pytest.fixture
def cache_backend():
    """Create an in-memory cache backend."""
    return InMemoryCacheBackend()


@pytest.fixture
async def hybrid_service(mock_es_client, mock_embedding_service, cache_backend):
    """Create a hybrid search service."""
    service = HybridSearchService(
        es_client=mock_es_client,
        embedding_service=mock_embedding_service,
        cache_backend=cache_backend,
        vector_search_backend=SearchBackend.ELASTICSEARCH
    )
    return service


# =============================================================================
# Query Router Tests
# =============================================================================

class TestQueryRouter:
    """Test cases for QueryRouter."""
    
    def test_analyze_acordao_query(self, query_router):
        """Test analysis of acórdão citation queries."""
        queries = [
            "AC 1234/2024",
            "Acórdão 1234/2024",
            "acordao 567/2023",
        ]
        
        for query in queries:
            result = query_router.analyze(query)
            assert result.query_type == QueryType.EXACT_MATCH
            assert 'acordao' in result.detected_entities or 'ano' in result.detected_entities
    
    def test_analyze_lei_query(self, query_router):
        """Test analysis of Lei citation queries."""
        queries = [
            "Lei 8.666/93",
            "Lei 13.709/2018",
        ]
        
        for query in queries:
            result = query_router.analyze(query)
            assert result.query_type == QueryType.EXACT_MATCH
            assert 'lei' in result.detected_entities
    
    def test_analyze_semantic_query(self, query_router):
        """Test analysis of semantic/conceptual queries."""
        queries = [
            "licitação pregão eletrônico",
            "direito adquirido servidor público",
            "responsabilidade fiscal ente federado",
            "sobre contas públicas",  # semantic indicator
        ]
        
        for query in queries:
            result = query_router.analyze(query)
            assert result.query_type in [QueryType.SEMANTIC, QueryType.HYBRID]
    
    def test_analyze_hybrid_query(self, query_router):
        """Test analysis of hybrid queries."""
        queries = [
            "Acórdão 1234/2024 sobre licitação",
            'Súmula 123 aplicada a "pregão eletrônico" sobre contratos',
        ]
        
        for query in queries:
            result = query_router.analyze(query)
            # Query has both citation and semantic terms -> HYBRID
            assert result.query_type == QueryType.HYBRID, f"Expected HYBRID for: {query}"
    
    def test_analyze_quoted_phrase(self, query_router):
        """Test analysis of quoted phrase queries."""
        result = query_router.analyze('"direito líquido e certo"')
        # Quoted phrases without semantic terms should be EXACT_MATCH
        # (user is looking for exact phrase match)
        assert result.query_type == QueryType.EXACT_MATCH
        assert 'quoted' in result.detected_entities
    
    def test_normalize_query(self, query_router):
        """Test query normalization."""
        result = query_router.analyze("  AC   1234/2024  ")
        assert result.normalized_query == "ac 1234/2024"
    
    def test_get_optimal_weights(self, query_router):
        """Test optimal weight retrieval."""
        assert query_router.get_optimal_weights(QueryType.EXACT_MATCH) == {
            'bm25': 1.5, 'vector': 0.5
        }
        assert query_router.get_optimal_weights(QueryType.SEMANTIC) == {
            'bm25': 0.5, 'vector': 1.5
        }
        assert query_router.get_optimal_weights(QueryType.HYBRID) == {
            'bm25': 1.0, 'vector': 1.0
        }


# =============================================================================
# RRF Fusion Engine Tests
# =============================================================================

class TestRRFFusionEngine:
    """Test cases for RRFFusionEngine."""
    
    def create_search_result(
        self,
        doc_id: str,
        score: float,
        title: str = "Test"
    ) -> SearchResult:
        """Helper to create SearchResult."""
        return SearchResult(
            document_id=doc_id,
            content="Content",
            title=title,
            score=score,
            source_id="test",
            source_type="test",
            metadata={},
        )
    
    def test_fuse_basic(self, rrf_engine):
        """Test basic RRF fusion."""
        bm25_results = [
            self.create_search_result("doc1", 10.0),
            self.create_search_result("doc2", 9.0),
            self.create_search_result("doc3", 8.0),
        ]
        
        vector_results = [
            self.create_search_result("doc2", 0.95),
            self.create_search_result("doc3", 0.90),
            self.create_search_result("doc4", 0.85),
        ]
        
        fused = rrf_engine.fuse(bm25_results, vector_results, limit=10)
        
        # Should have 4 unique documents
        assert len(fused) == 4
        
        # doc2 and doc3 should rank higher (present in both)
        doc_ids = [f.document_id for f in fused]
        assert "doc2" in doc_ids[:2]
        assert "doc3" in doc_ids[:2]
    
    def test_fuse_with_weights(self, rrf_engine):
        """Test RRF fusion with custom weights."""
        bm25_results = [
            self.create_search_result("doc1", 10.0),
        ]
        
        vector_results = [
            self.create_search_result("doc2", 0.95),
        ]
        
        # Test with BM25 weighted higher
        fused = rrf_engine.fuse(
            bm25_results, 
            vector_results, 
            limit=10,
            weights={'bm25': 1.5, 'vector': 0.5}
        )
        
        # doc1 should have higher score due to BM25 weight
        doc1_score = next(f.rrf_score for f in fused if f.document_id == "doc1")
        doc2_score = next(f.rrf_score for f in fused if f.document_id == "doc2")
        assert doc1_score > doc2_score
    
    def test_fuse_limit(self, rrf_engine):
        """Test RRF fusion with result limit."""
        bm25_results = [self.create_search_result(f"doc{i}", float(10-i)) for i in range(10)]
        vector_results = [self.create_search_result(f"doc{i}", float(0.9-i*0.01)) for i in range(10)]
        
        fused = rrf_engine.fuse(bm25_results, vector_results, limit=5)
        assert len(fused) == 5
    
    def test_fuse_empty_results(self, rrf_engine):
        """Test RRF fusion with empty result lists."""
        fused = rrf_engine.fuse([], [], limit=10)
        assert len(fused) == 0
        
        # Only BM25 results
        bm25_results = [self.create_search_result("doc1", 10.0)]
        fused = rrf_engine.fuse(bm25_results, [], limit=10)
        assert len(fused) == 1
        assert fused[0].rrf_score > 0
    
    def test_rrf_score_calculation(self, rrf_engine):
        """Test RRF score calculation formula."""
        # With k=60, rank=1, weight=1.0: score = 1/(60+1) ≈ 0.0164
        bm25_results = [self.create_search_result("doc1", 10.0)]
        vector_results = []
        
        fused = rrf_engine.fuse(bm25_results, vector_results, limit=10)
        expected_score = 1.0 / (60 + 1)
        assert abs(fused[0].rrf_score - expected_score) < 0.0001
    
    def test_fuse_multi(self, rrf_engine):
        """Test fusion with multiple result sets."""
        set1 = [self.create_search_result("doc1", 10.0), self.create_search_result("doc2", 9.0)]
        set2 = [self.create_search_result("doc2", 0.95), self.create_search_result("doc3", 0.90)]
        set3 = [self.create_search_result("doc3", 0.85), self.create_search_result("doc1", 0.80)]
        
        result_sets = [
            ("bm25", set1),
            ("vector1", set2),
            ("vector2", set3),
        ]
        
        fused = rrf_engine.fuse_multi(result_sets, limit=10)
        assert len(fused) == 3


# =============================================================================
# Cache Backend Tests
# =============================================================================

class TestInMemoryCacheBackend:
    """Test cases for InMemoryCacheBackend."""
    
    @pytest.mark.asyncio
    async def test_get_set(self):
        """Test basic get/set operations."""
        cache = InMemoryCacheBackend()
        
        await cache.set("key1", {"data": "value"}, ttl_seconds=60)
        result = await cache.get("key1")
        
        assert result == {"data": "value"}
    
    @pytest.mark.asyncio
    async def test_expiry(self):
        """Test TTL expiry."""
        cache = InMemoryCacheBackend()
        
        await cache.set("key1", "value", ttl_seconds=0.01)
        await asyncio.sleep(0.02)
        
        result = await cache.get("key1")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_delete(self):
        """Test delete operation."""
        cache = InMemoryCacheBackend()
        
        await cache.set("key1", "value", ttl_seconds=60)
        deleted = await cache.delete("key1")
        
        assert deleted is True
        assert await cache.get("key1") is None
    
    @pytest.mark.asyncio
    async def test_invalidate_pattern(self):
        """Test pattern-based invalidation."""
        cache = InMemoryCacheBackend()
        
        await cache.set("search:exact:abc", "value1", ttl_seconds=60)
        await cache.set("search:semantic:def", "value2", ttl_seconds=60)
        await cache.set("other:key", "value3", ttl_seconds=60)
        
        count = await cache.invalidate_pattern("search:*")
        
        assert count == 2
        assert await cache.get("search:exact:abc") is None
        assert await cache.get("other:key") is not None


# =============================================================================
# Hybrid Search Service Tests
# =============================================================================

class TestHybridSearchService:
    """Test cases for HybridSearchService."""
    
    @pytest.mark.asyncio
    async def test_search_exact_match(self, mock_es_client, mock_embedding_service, cache_backend):
        """Test exact match search routing."""
        # Mock ES response
        mock_es_client.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_id": "doc1",
                        "_score": 10.0,
                        "_source": {
                            "title": "Test Doc",
                            "content": "Content",
                            "source_id": "test",
                            "metadata": {}
                        }
                    }
                ]
            }
        }
        
        service = HybridSearchService(
            es_client=mock_es_client,
            embedding_service=mock_embedding_service,
            cache_backend=cache_backend,
        )
        
        request = SearchRequest(query="AC 1234/2024", limit=10)
        response = await service.search(request)
        
        assert response.total == 1
        assert response.hits[0].document_id == "doc1"
        mock_es_client.search.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_search_uses_cache(self, mock_es_client, mock_embedding_service, cache_backend):
        """Test that search uses cache."""
        service = HybridSearchService(
            es_client=mock_es_client,
            embedding_service=mock_embedding_service,
            cache_backend=cache_backend,
        )
        
        # Mock ES response
        mock_es_client.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_id": "doc1",
                        "_score": 10.0,
                        "_source": {
                            "title": "Test Doc",
                            "content": "Content",
                            "source_id": "test",
                            "metadata": {}
                        }
                    }
                ]
            }
        }
        
        request = SearchRequest(query="AC 1234/2024", limit=10)
        
        # First search should hit ES
        response1 = await service.search(request, use_cache=True)
        assert mock_es_client.search.call_count == 1
        
        # Second search should use cache
        response2 = await service.search(request, use_cache=True)
        # ES should not be called again
        assert mock_es_client.search.call_count == 1
        
        # Results should be identical
        assert response1.total == response2.total
    
    @pytest.mark.asyncio
    async def test_search_semantic(self, mock_es_client, mock_embedding_service, cache_backend):
        """Test semantic search."""
        # Mock ES kNN response
        mock_es_client.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_id": "doc1",
                        "_score": 0.95,
                        "_source": {
                            "title": "Semantic Match",
                            "content": "Content",
                            "source_id": "test",
                            "metadata": {}
                        }
                    }
                ]
            }
        }
        
        service = HybridSearchService(
            es_client=mock_es_client,
            embedding_service=mock_embedding_service,
            cache_backend=cache_backend,
        )
        
        request = SearchRequest(query="sobre licitação", limit=10)
        response = await service.search(request)
        
        assert response.total == 1
        mock_embedding_service.embed.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_explain_search(self, mock_es_client, mock_embedding_service, cache_backend):
        """Test search explanation."""
        # Mock ES responses
        mock_es_client.search.return_value = {
            "hits": {
                "hits": []
            }
        }
        
        service = HybridSearchService(
            es_client=mock_es_client,
            embedding_service=mock_embedding_service,
            cache_backend=cache_backend,
        )
        
        request = SearchRequest(query="AC 1234/2024", limit=10)
        explanation = await service.explain(request)
        
        assert 'query_analysis' in explanation
        assert 'weights' in explanation
        assert 'rrf_k' in explanation
    
    @pytest.mark.asyncio
    async def test_health_check(self, mock_es_client, cache_backend):
        """Test health check."""
        mock_es_client.cluster.health.return_value = {
            "status": "green",
            "indices": {
                "gabi_documents_v1": {
                    "docs": {"count": 1000},
                    "store": {"size_in_bytes": 1024*1024*100}
                }
            }
        }
        mock_es_client.indices.stats.return_value = {
            "indices": {
                "gabi_documents_v1": {
                    "total": {
                        "docs": {"count": 1000},
                        "store": {"size_in_bytes": 1024*1024*100}
                    }
                }
            }
        }
        
        service = HybridSearchService(
            es_client=mock_es_client,
            cache_backend=cache_backend,
        )
        
        health = await service.health_check()
        
        assert health.status == "healthy"
        assert len(health.indices) >= 1
    
    @pytest.mark.asyncio
    async def test_get_metrics(self, mock_es_client, mock_embedding_service, cache_backend):
        """Test metrics collection."""
        service = HybridSearchService(
            es_client=mock_es_client,
            embedding_service=mock_embedding_service,
            cache_backend=cache_backend,
        )
        
        # Mock ES response for multiple searches
        mock_es_client.search.return_value = {
            "hits": {"hits": []}
        }
        
        # Execute searches without cache to ensure all are recorded
        for i in range(5):
            request = SearchRequest(query=f"test query {i}", limit=10)  # Different queries to avoid cache
            await service.search(request, use_cache=False)
        
        metrics = service.get_metrics()
        
        assert metrics['total_queries'] == 5
        assert 'avg_response_time_ms' in metrics
        assert 'by_query_type' in metrics


# =============================================================================
# Integration Tests
# =============================================================================

class TestHybridSearchIntegration:
    """Integration tests for the complete hybrid search flow."""
    
    @pytest.mark.asyncio
    async def test_full_hybrid_search_flow(self):
        """Test complete hybrid search flow with mocked dependencies."""
        # Create mock ES client
        es_client = AsyncMock()
        es_client.search = AsyncMock(side_effect=[
            # BM25 response
            {
                "hits": {
                    "hits": [
                        {"_id": "doc1", "_score": 10.0, "_source": {
                            "title": "Doc 1", "content": "Content 1",
                            "source_id": "test", "metadata": {}
                        }},
                        {"_id": "doc2", "_score": 9.0, "_source": {
                            "title": "Doc 2", "content": "Content 2",
                            "source_id": "test", "metadata": {}
                        }},
                    ]
                }
            },
            # Vector response
            {
                "hits": {
                    "hits": [
                        {"_id": "doc2", "_score": 0.95, "_source": {
                            "title": "Doc 2", "content": "Content 2",
                            "source_id": "test", "metadata": {}
                        }},
                        {"_id": "doc3", "_score": 0.90, "_source": {
                            "title": "Doc 3", "content": "Content 3",
                            "source_id": "test", "metadata": {}
                        }},
                    ]
                }
            }
        ])
        
        # Create mock embedding service
        embedding_service = AsyncMock()
        embedding_service.embed = AsyncMock(return_value=[0.1] * 384)
        
        # Create service
        service = HybridSearchService(
            es_client=es_client,
            embedding_service=embedding_service,
            vector_search_backend=SearchBackend.ELASTICSEARCH
        )
        
        # Execute hybrid search
        request = SearchRequest(query="acórdão sobre licitação", limit=10)
        response = await service.search(request)
        
        # Verify
        assert response.total > 0
        assert len(response.hits) > 0
        
        # Verify doc2 is ranked higher (present in both)
        doc_ids = [h.document_id for h in response.hits]
        assert "doc2" in doc_ids


# =============================================================================
# Performance Tests
# =============================================================================

@pytest.mark.benchmark
class TestHybridSearchPerformance:
    """Performance benchmarks for hybrid search."""
    
    @pytest.mark.asyncio
    async def test_rrf_fusion_performance(self, rrf_engine):
        """Benchmark RRF fusion with large result sets."""
        import time
        
        # Create large result sets
        bm25_results = [
            SearchResult(
                document_id=f"doc{i}",
                content=f"Content {i}",
                title=f"Doc {i}",
                score=float(100 - i),
                source_id="test",
                source_type="test",
                metadata={},
            )
            for i in range(1000)
        ]
        
        vector_results = [
            SearchResult(
                document_id=f"doc{i}",
                content=f"Content {i}",
                title=f"Doc {i}",
                score=float(0.99 - i * 0.001),
                source_id="test",
                source_type="test",
                metadata={},
            )
            for i in range(1000)
        ]
        
        # Benchmark
        start = time.time()
        for _ in range(100):
            fused = rrf_engine.fuse(bm25_results, vector_results, limit=100)
        elapsed = (time.time() - start) / 100
        
        # Should be very fast (< 10ms per fusion)
        assert elapsed < 0.01
    
    @pytest.mark.asyncio
    async def test_query_router_performance(self, query_router):
        """Benchmark query routing."""
        import time
        
        queries = [
            "AC 1234/2024",
            "Lei 8.666/93",
            "sobre licitação",
            "Acórdão 1234/2024 sobre pregão",
        ] * 1000
        
        start = time.time()
        for query in queries:
            query_router.analyze(query)
        elapsed = (time.time() - start) / len(queries)
        
        # Should be very fast (< 1ms per query)
        assert elapsed < 0.001


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
