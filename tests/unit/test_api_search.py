"""Testes unitários para API de busca.

Testa endpoints de busca híbrida da API REST.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from gabi.api.search import router, get_search_service
from gabi.services.search_service import SearchService
from gabi.schemas.search import (
    SearchRequest,
    SearchHit,
    SearchResponse,
    IndexHealth,
    HealthResponse,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_es_client():
    """Mock de cliente Elasticsearch."""
    client = AsyncMock()
    return client


@pytest.fixture
def mock_settings():
    """Mock de settings."""
    settings = MagicMock()
    settings.elasticsearch_index = "test_index"
    settings.search_rrf_k = 60
    settings.search_default_limit = 10
    settings.search_max_limit = 100
    settings.search_bm25_weight = 1.0
    settings.search_vector_weight = 1.0
    settings.search_timeout_ms = 5000
    return settings


@pytest.fixture
def search_service(mock_es_client, mock_settings):
    """Serviço de busca configurado."""
    return SearchService(
        es_client=mock_es_client,
        settings=mock_settings,
        vector_search_backend="elasticsearch",
    )


@pytest.fixture
def sample_search_request():
    """Request de busca de exemplo."""
    return SearchRequest(
        query="licitação",
        limit=10,
        offset=0,
    )


# =============================================================================
# SearchRequest Tests
# =============================================================================

class TestSearchRequest:
    """Testes para SearchRequest."""
    
    def test_search_request_validates_query(self):
        """Verifica que query é validada."""
        with pytest.raises(ValueError):
            SearchRequest(query="")  # query vazia
        
        with pytest.raises(ValueError):
            SearchRequest(query="a" * 1001)  # query muito longa
    
    def test_search_request_validates_limit(self):
        """Verifica que limit é validado."""
        with pytest.raises(ValueError):
            SearchRequest(query="test", limit=0)
        
        with pytest.raises(ValueError):
            SearchRequest(query="test", limit=101)
    
    def test_search_request_validates_offset(self):
        """Verifica que offset é validado."""
        with pytest.raises(ValueError):
            SearchRequest(query="test", offset=-1)
        
        with pytest.raises(ValueError):
            SearchRequest(query="test", offset=10001)
    
    def test_search_request_validates_hybrid_weights(self):
        """Verifica que hybrid_weights é validado."""
        with pytest.raises(ValueError):
            SearchRequest(
                query="test",
                hybrid_weights={"invalid_key": 1.0}
            )
    
    def test_search_request_accepts_valid_hybrid_weights(self):
        """Verifica que hybrid_weights válido é aceito."""
        request = SearchRequest(
            query="test",
            hybrid_weights={"bm25": 1.0, "vector": 1.2}
        )
        assert request.hybrid_weights == {"bm25": 1.0, "vector": 1.2}


# =============================================================================
# SearchService Tests
# =============================================================================

class TestSearchService:
    """Testes para SearchService."""
    
    @pytest.mark.asyncio
    async def test_search_returns_search_response(
        self, search_service, mock_es_client, sample_search_request
    ):
        """Verifica que search_api retorna SearchResponse."""
        mock_es_client.search.return_value = {
            "hits": {
                "total": {"value": 0},
                "hits": []
            }
        }
        
        response = await search_service.search_api(sample_search_request)
        
        assert isinstance(response, SearchResponse)
        assert response.query == "licitação"
    
    @pytest.mark.asyncio
    async def test_search_calls_es_search(
        self, search_service, mock_es_client, sample_search_request
    ):
        """Verifica que search_api chama Elasticsearch search."""
        mock_es_client.search.return_value = {
            "hits": {
                "total": {"value": 0},
                "hits": []
            }
        }
        
        await search_service.search_api(sample_search_request)
        
        mock_es_client.search.assert_called_once()
        call_kwargs = mock_es_client.search.call_args.kwargs
        assert call_kwargs["index"] == "test_index"
    
    @pytest.mark.asyncio
    async def test_search_parses_hits(self, search_service, mock_es_client):
        """Verifica que search_api parseia hits corretamente."""
        mock_es_client.search.return_value = {
            "hits": {
                "total": {"value": 2},
                "hits": [
                    {
                        "_id": "doc-1",
                        "_score": 1.5,
                        "_source": {
                            "title": "Document 1",
                            "content_preview": "Preview...",
                            "source_id": "source1",
                            "metadata": {"year": 2024},
                        }
                    },
                    {
                        "_id": "doc-2",
                        "_score": 1.2,
                        "_source": {
                            "title": "Document 2",
                            "content_preview": "Preview 2...",
                            "source_id": "source2",
                        }
                    }
                ]
            }
        }
        
        request = SearchRequest(query="test")
        response = await search_service.search_api(request)
        
        assert len(response.hits) == 2
        assert response.hits[0].document_id == "doc-1"
        assert response.hits[0].title == "Document 1"
    
    @pytest.mark.asyncio
    async def test_search_applies_source_filter(self, search_service, mock_es_client):
        """Verifica que search_api aplica filtro de sources."""
        mock_es_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }
        
        request = SearchRequest(
            query="test",
            sources=["source1", "source2"]
        )
        await search_service.search_api(request)
        
        call_kwargs = mock_es_client.search.call_args.kwargs
        query = call_kwargs["query"]
        filter_clauses = query["bool"]["filter"]
        assert any(
            clause.get("terms", {}).get("source_id") == ["source1", "source2"]
            for clause in filter_clauses
        )
    
    @pytest.mark.asyncio
    async def test_search_excludes_deleted(self, search_service, mock_es_client):
        """Verifica que search_api exclui documentos deletados."""
        mock_es_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }
        
        request = SearchRequest(query="test")
        await search_service.search_api(request)
        
        call_kwargs = mock_es_client.search.call_args.kwargs
        query = call_kwargs["query"]
        filter_clauses = query["bool"]["filter"]
        assert any(
            clause == {"term": {"is_deleted": False}}
            for clause in filter_clauses
        )
    
    @pytest.mark.asyncio
    async def test_search_returns_empty_on_error(self, search_service, mock_es_client):
        """Verifica que search_api retorna lista vazia em caso de erro."""
        mock_es_client.search.side_effect = Exception("ES Error")
        
        request = SearchRequest(query="test")
        response = await search_service.search_api(request)
        
        assert response.hits == []


# =============================================================================
# Search RRF Tests
# =============================================================================

class TestSearchRRF:
    """Testes para RRF (Reciprocal Rank Fusion)."""
    
    def test_fuse_results_with_bm25_only(self, search_service):
        """Verifica que _fuse_results_rrf funciona com apenas BM25."""
        from gabi.services.search_service import RawResult
        
        bm25_results = [
            RawResult(id="doc-1", content="Doc 1", score=1.5, title="Doc 1"),
            RawResult(id="doc-2", content="Doc 2", score=1.2, title="Doc 2"),
        ]
        
        fused = search_service._fuse_results_rrf(
            bm25_results=bm25_results,
            vector_results=[],
            limit=10,
            weights={"bm25": 1.0, "vector": 0},
        )
        
        assert len(fused) == 2
        assert fused[0].document_id == "doc-1"
    
    def test_fuse_results_with_vector_only(self, search_service):
        """Verifica que _fuse_results_rrf funciona com apenas vetorial."""
        from gabi.services.search_service import RawResult
        
        vector_results = [
            RawResult(id="doc-1", content="Doc 1", score=0.95, title="Doc 1"),
            RawResult(id="doc-2", content="Doc 2", score=0.90, title="Doc 2"),
        ]
        
        fused = search_service._fuse_results_rrf(
            bm25_results=[],
            vector_results=vector_results,
            limit=10,
            weights={"bm25": 0, "vector": 1.0},
        )
        
        assert len(fused) == 2
        assert fused[0].document_id == "doc-1"
    
    def test_fuse_results_combines_scores(self, search_service):
        """Verifica que _fuse_results_rrf combina scores corretamente."""
        from gabi.services.search_service import RawResult
        
        bm25_results = [
            RawResult(id="doc-1", content="Doc 1", score=1.5, title="Doc 1"),
            RawResult(id="doc-2", content="Doc 2", score=1.2, title="Doc 2"),
        ]
        vector_results = [
            RawResult(id="doc-2", content="Doc 2", score=0.95, title="Doc 2"),
            RawResult(id="doc-1", content="Doc 1", score=0.90, title="Doc 1"),
        ]
        
        fused = search_service._fuse_results_rrf(
            bm25_results=bm25_results,
            vector_results=vector_results,
            limit=10,
            weights={"bm25": 1.0, "vector": 1.0},
        )
        
        # doc-1 e doc-2 devem estar no resultado
        doc_ids = [hit.document_id for hit in fused]
        assert "doc-1" in doc_ids
        assert "doc-2" in doc_ids


# =============================================================================
# Health Check Tests
# =============================================================================

class TestSearchHealthCheck:
    """Testes para health check de busca."""
    
    @pytest.mark.asyncio
    async def test_health_check_returns_healthy(self, search_service, mock_es_client):
        """Verifica que health_check retorna healthy quando ES está OK."""
        mock_es_client.cluster.health.return_value = {
            "status": "green"
        }
        mock_es_client.indices.stats.return_value = {
            "indices": {
                "test_index": {
                    "total": {
                        "docs": {"count": 100},
                        "store": {"size_in_bytes": 1024000}
                    }
                }
            }
        }
        
        response = await search_service.health_check()
        
        assert isinstance(response, HealthResponse)
        assert response.status == "healthy"
    
    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_on_yellow(
        self, search_service, mock_es_client
    ):
        """Verifica que health_check retorna degraded em status yellow."""
        mock_es_client.cluster.health.return_value = {
            "status": "yellow"
        }
        mock_es_client.indices.stats.return_value = {
            "indices": {}
        }
        
        response = await search_service.health_check()
        
        assert response.status == "degraded"
    
    @pytest.mark.asyncio
    async def test_health_check_returns_unhealthy_on_red(
        self, search_service, mock_es_client
    ):
        """Verifica que health_check retorna unhealthy em status red."""
        mock_es_client.cluster.health.return_value = {
            "status": "red"
        }
        mock_es_client.indices.stats.return_value = {
            "indices": {}
        }
        
        response = await search_service.health_check()
        
        assert response.status == "unhealthy"
    
    @pytest.mark.asyncio
    async def test_health_check_handles_error(self, search_service, mock_es_client):
        """Verifica que health_check lida com erro do ES."""
        mock_es_client.cluster.health.side_effect = Exception("ES Error")
        
        response = await search_service.health_check()
        
        assert response.status == "unhealthy"


# =============================================================================
# SearchHit Tests
# =============================================================================

class TestSearchHit:
    """Testes para SearchHit."""
    
    def test_search_hit_creation(self):
        """Verifica criação de SearchHit."""
        hit = SearchHit(
            document_id="doc-1",
            title="Test Document",
            content_preview="Preview...",
            source_id="source1",
            score=1.5,
        )
        
        assert hit.document_id == "doc-1"
        assert hit.title == "Test Document"
        assert hit.score == 1.5
    
    def test_search_hit_optional_fields(self):
        """Verifica campos opcionais de SearchHit."""
        hit = SearchHit(
            document_id="doc-1",
            source_id="source1",
            score=1.5,
            bm25_score=1.5,
            vector_score=0.9,
            metadata={"year": 2024},
            url="https://example.com/doc",
        )
        
        assert hit.bm25_score == 1.5
        assert hit.vector_score == 0.9
        assert hit.metadata == {"year": 2024}
        assert hit.url == "https://example.com/doc"


# =============================================================================
# IndexHealth Tests
# =============================================================================

class TestIndexHealth:
    """Testes para IndexHealth."""
    
    def test_index_health_creation(self):
        """Verifica criação de IndexHealth."""
        health = IndexHealth(
            index="test_index",
            status="green",
            docs_count=100,
            size_mb=10.5,
        )
        
        assert health.index == "test_index"
        assert health.status == "green"
        assert health.docs_count == 100
        assert health.size_mb == 10.5
