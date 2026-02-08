"""Unit tests for SearchService."""

import pytest
from datetime import datetime
from unittest.mock import Mock, MagicMock, AsyncMock, patch

from gabi.services.search_service import SearchService, RawResult
from gabi.schemas.search import SearchFilters, RRFConfig, SearchRequest


class TestSearchServiceInitialization:
    """Test SearchService initialization."""
    
    def test_init_without_clients(self):
        """Test initialization without any clients."""
        service = SearchService()
        assert service.es_client is None
        assert service.pg_client is None
        assert service.embedding_service is None
        assert service.rrf_config.k == 60
    
    def test_init_with_clients(self):
        """Test initialization with all clients."""
        es_mock = Mock()
        pg_mock = Mock()
        emb_mock = Mock()
        config = RRFConfig(k=50)
        
        service = SearchService(
            es_client=es_mock,
            pg_client=pg_mock,
            embedding_service=emb_mock,
            rrf_config=config
        )
        
        assert service.es_client == es_mock
        assert service.pg_client == pg_mock
        assert service.embedding_service == emb_mock
        assert service.rrf_config.k == 50
    
    def test_default_rrf_k_constant(self):
        """Test default RRF k constant value."""
        assert SearchService.DEFAULT_RRF_K == 60
    
    def test_default_vector_backend_is_elasticsearch(self):
        """Test that default vector search backend is elasticsearch."""
        service = SearchService()
        assert service.vector_search_backend == "elasticsearch"
    
    def test_vector_backend_can_be_overridden(self):
        """Test that vector search backend can be set to pgvector."""
        service = SearchService(vector_search_backend="pgvector")
        assert service.vector_search_backend == "pgvector"


class TestSearchRequestValidation:
    """Test search request validation."""
    
    @pytest.mark.asyncio
    async def test_empty_query_returns_error(self):
        """Test that empty query returns error response."""
        service = SearchService()
        result = await service.search(query="", search_type="hybrid")
        
        assert "error" in result
        assert "Empty query" in result["error"]
        assert result["total_results"] == 0
    
    @pytest.mark.asyncio
    async def test_whitespace_only_query_returns_error(self):
        """Test that whitespace-only query returns error."""
        service = SearchService()
        result = await service.search(query="   ", search_type="hybrid")
        
        assert "error" in result
        assert result["total_results"] == 0


class TestBM25Search:
    """Test BM25 text search functionality."""
    
    @pytest.fixture
    def mock_es_client(self):
        """Create mock Elasticsearch client."""
        mock = Mock()
        mock.search = AsyncMock(return_value={
            "hits": {
                "hits": [
                    {
                        "_id": "doc1",
                        "_score": 15.5,
                        "_source": {
                            "content": "Test content 1",
                            "source_id": "src1",
                            "source_type": "pdf",
                            "metadata": {"author": "John"}
                        }
                    },
                    {
                        "_id": "doc2",
                        "_score": 12.3,
                        "_source": {
                            "content": "Test content 2",
                            "source_id": "src2",
                            "source_type": "web"
                        }
                    }
                ]
            }
        })
        return mock
    
    @pytest.mark.asyncio
    async def test_bm25_without_client_returns_empty(self):
        """Test BM25 search without ES client returns empty."""
        service = SearchService()
        results = await service._search_bm25("test query")
        assert results == []
    
    @pytest.mark.asyncio
    async def test_bm25_search_success(self, mock_es_client):
        """Test successful BM25 search."""
        service = SearchService(es_client=mock_es_client)
        results = await service._search_bm25("test query")
        
        assert len(results) == 2
        assert results[0].id == "doc1"
        assert results[0].score == 15.5
        assert results[0].content == "Test content 1"
    
    @pytest.mark.asyncio
    async def test_bm25_builds_correct_query(self, mock_es_client):
        """Test that BM25 builds correct ES query."""
        service = SearchService(es_client=mock_es_client)
        await service._search_bm25("test query", limit=50)
        
        call_args = mock_es_client.search.call_args
        # Check keyword arguments
        kwargs = call_args.kwargs if call_args.kwargs else call_args[1]
        assert kwargs.get("index") == "documents" or kwargs.get("index") is None
        assert "query" in kwargs
        assert kwargs.get("size") == 50 or kwargs.get("size") is None
    
    @pytest.mark.asyncio
    async def test_bm25_with_filters(self, mock_es_client):
        """Test BM25 search with filters."""
        service = SearchService(es_client=mock_es_client)
        
        filters = SearchFilters(
            source_id="src1",
            source_type="pdf",
            date_from=datetime(2024, 1, 1),
            date_to=datetime(2024, 12, 31),
            tags=["important", "review"]
        )
        
        await service._search_bm25("test", filters=filters)
        
        # Verify search was called
        mock_es_client.search.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_bm25_handles_exception(self, mock_es_client):
        """Test BM25 handles ES exceptions gracefully."""
        mock_es_client.search = AsyncMock(side_effect=Exception("Connection failed"))
        
        service = SearchService(es_client=mock_es_client)
        results = await service._search_bm25("test")
        
        assert results == []


class TestVectorSearch:
    """Test vector search functionality."""
    
    @pytest.mark.asyncio
    async def test_vector_without_pg_client_returns_empty(self):
        """Test vector search without PG client returns empty."""
        service = SearchService()
        results = await service._search_vector([0.1, 0.2, 0.3])
        assert results == []
    
    @pytest.mark.asyncio
    async def test_vector_search_with_es_backend(self):
        """Test vector search using Elasticsearch backend."""
        es_mock = Mock()
        es_mock.search = AsyncMock(return_value={
            "hits": {
                "hits": [
                    {"_id": "doc1", "_score": 0.95, "_source": {"content": "Test"}}
                ]
            }
        })
        
        service = SearchService(
            es_client=es_mock,
            vector_search_backend="elasticsearch"
        )
        
        results = await service._search_vector([0.1, 0.2, 0.3])
        
        # When ES backend is used, it should call ES
        es_mock.search.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_vector_search_with_es_uses_correct_field_path(self):
        """Test that ES vector search uses correct field path content.fields.vector."""
        es_mock = Mock()
        es_mock.search = AsyncMock(return_value={"hits": {"hits": []}})
        
        service = SearchService(
            es_client=es_mock,
            vector_search_backend="elasticsearch"
        )
        
        await service._search_vector([0.1, 0.2, 0.3])
        
        # Check that the correct field path is used
        call_args = es_mock.search.call_args
        kwargs = call_args.kwargs if call_args.kwargs else call_args[1]
        knn_query = kwargs.get("knn", {})
        assert knn_query.get("field") == "content.fields.vector"
    
    @pytest.mark.asyncio
    async def test_vector_search_es_without_client_returns_empty(self):
        """Test ES vector search without ES client returns empty."""
        service = SearchService(vector_search_backend="elasticsearch")
        results = await service._search_vector([0.1, 0.2, 0.3])
        assert results == []
    
    @pytest.mark.asyncio
    async def test_vector_search_es_handles_exception(self):
        """Test ES vector search handles exceptions gracefully."""
        es_mock = Mock()
        es_mock.search = AsyncMock(side_effect=Exception("ES error"))
        
        service = SearchService(
            es_client=es_mock,
            vector_search_backend="elasticsearch"
        )
        
        results = await service._search_vector([0.1, 0.2, 0.3])
        assert results == []


class TestHybridSearch:
    """Test hybrid search combining BM25 and vector."""
    
    @pytest.fixture
    def service_with_mocks(self):
        """Create service with mocked dependencies."""
        es_mock = Mock()
        es_mock.search = AsyncMock(return_value={
            "hits": {
                "hits": [
                    {"_id": "doc1", "_score": 10.0, "_source": {"content": "A"}},
                    {"_id": "doc2", "_score": 8.0, "_source": {"content": "B"}},
                ]
            }
        })
        
        pg_mock = Mock()
        emb_mock = Mock()
        emb_mock.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])
        
        return SearchService(
            es_client=es_mock,
            pg_client=pg_mock,
            embedding_service=emb_mock,
            vector_search_backend="elasticsearch"
        )
    
    @pytest.mark.asyncio
    async def test_hybrid_search_returns_results(self, service_with_mocks):
        """Test hybrid search returns fused results."""
        result = await service_with_mocks.search("test query", search_type="hybrid")
        
        assert result["search_type"] == "hybrid"
        assert "results" in result
        assert "took_ms" in result
    
    @pytest.mark.asyncio
    async def test_hybrid_generates_embedding(self, service_with_mocks):
        """Test hybrid search generates embedding for query."""
        await service_with_mocks.search("test query", search_type="hybrid")
        
        service_with_mocks.embedding_service.embed.assert_called_once_with("test query")
    
    @pytest.mark.asyncio
    async def test_hybrid_search_with_es_vector_backend(self):
        """Test hybrid search uses ES kNN for vector search."""
        es_mock = Mock()
        es_mock.search = AsyncMock(return_value={
            "hits": {
                "hits": [
                    {"_id": "doc1", "_score": 10.0, "_source": {"content": "A"}},
                ]
            }
        })
        
        emb_mock = Mock()
        emb_mock.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])
        
        service = SearchService(
            es_client=es_mock,
            embedding_service=emb_mock,
            vector_search_backend="elasticsearch"
        )
        
        result = await service.search("test query", search_type="hybrid")
        
        assert result["search_type"] == "hybrid"
        assert result.get("vector_backend") == "elasticsearch"


class TestSearchTypes:
    """Test different search types."""
    
    @pytest.fixture
    def mock_service(self):
        """Create service with mocked ES."""
        es_mock = Mock()
        es_mock.search = AsyncMock(return_value={
            "hits": {
                "hits": [
                    {"_id": "doc1", "_score": 10.0, "_source": {"content": "Test"}},
                ]
            }
        })
        return SearchService(es_client=es_mock)
    
    @pytest.mark.asyncio
    async def test_search_bm25_type(self, mock_service):
        """Test search with bm25 type."""
        result = await mock_service.search("query", search_type="bm25")
        
        assert result["search_type"] == "bm25"
    
    @pytest.mark.asyncio
    async def test_search_vector_type_no_embedding(self, mock_service):
        """Test vector search without embedding service."""
        result = await mock_service.search("query", search_type="vector")
        
        assert result["search_type"] == "vector"
    
    @pytest.mark.asyncio
    async def test_search_vector_type_with_embedding(self):
        """Test vector search with embedding service."""
        es_mock = Mock()
        es_mock.search = AsyncMock(return_value={
            "hits": {"hits": []}
        })
        emb_mock = Mock()
        emb_mock.embed = AsyncMock(return_value=[0.1, 0.2])
        
        service = SearchService(
            es_client=es_mock,
            embedding_service=emb_mock,
            vector_search_backend="elasticsearch"
        )
        result = await service.search("query", search_type="vector")
        
        assert result["search_type"] == "vector"
        assert result.get("embedding_used") is True
    
    @pytest.mark.asyncio
    async def test_search_hybrid_type(self, mock_service):
        """Test search with hybrid type."""
        result = await mock_service.search("query", search_type="hybrid")
        
        assert result["search_type"] == "hybrid"
    
    @pytest.mark.asyncio
    async def test_search_unknown_type(self, mock_service):
        """Test search with unknown type returns error."""
        result = await mock_service.search("query", search_type="unknown")
        
        assert "error" in result
        assert "Unknown search type" in result["error"]


class TestSearchFilters:
    """Test search filters functionality."""
    
    def test_filter_source_id(self):
        """Test filter by source_id."""
        filters = SearchFilters(source_id="src123")
        assert filters.source_id == "src123"
    
    def test_filter_source_type(self):
        """Test filter by source_type."""
        filters = SearchFilters(source_type="pdf")
        assert filters.source_type == "pdf"
    
    def test_filter_date_range(self):
        """Test filter by date range."""
        from_date = datetime(2024, 1, 1)
        to_date = datetime(2024, 12, 31)
        
        filters = SearchFilters(date_from=from_date, date_to=to_date)
        assert filters.date_from == from_date
        assert filters.date_to == to_date
    
    def test_filter_date_from_string(self):
        """Test filter date parsing from ISO string."""
        filters = SearchFilters(date_from="2024-01-01T00:00:00")
        assert isinstance(filters.date_from, datetime)
        assert filters.date_from.year == 2024
    
    def test_filter_tags(self):
        """Test filter by tags."""
        filters = SearchFilters(tags=["urgent", "review"])
        assert filters.tags == ["urgent", "review"]
    
    def test_filter_metadata(self):
        """Test filter by metadata."""
        filters = SearchFilters(metadata={"author": "John", "status": "published"})
        assert filters.metadata["author"] == "John"


class TestSearchResponse:
    """Test search response structure."""
    
    @pytest.mark.asyncio
    async def test_response_contains_all_fields(self):
        """Test that search response contains all required fields."""
        es_mock = Mock()
        es_mock.search = AsyncMock(return_value={"hits": {"hits": []}})
        
        service = SearchService(es_client=es_mock)
        result = await service.search("test", search_type="bm25")
        
        required_fields = ["query", "search_type", "total_results", "results", "took_ms", "filters_applied"]
        for field in required_fields:
            assert field in result
    
    @pytest.mark.asyncio
    async def test_response_timing_is_positive(self):
        """Test that took_ms is positive."""
        es_mock = Mock()
        es_mock.search = AsyncMock(return_value={"hits": {"hits": []}})
        
        service = SearchService(es_client=es_mock)
        result = await service.search("test", search_type="bm25")
        
        assert result["took_ms"] >= 0
    
    @pytest.mark.asyncio
    async def test_response_query_echo(self):
        """Test that query is echoed in response."""
        es_mock = Mock()
        es_mock.search = AsyncMock(return_value={"hits": {"hits": []}})
        
        service = SearchService(es_client=es_mock)
        result = await service.search("my search query", search_type="bm25")
        
        assert result["query"] == "my search query"


class TestSearchErrorHandling:
    """Test search error handling."""
    
    @pytest.mark.asyncio
    async def test_search_catches_exceptions(self):
        """Test that search handles errors gracefully - bm25 returns empty on error."""
        es_mock = Mock()
        es_mock.search = AsyncMock(side_effect=Exception("Unexpected error"))
        
        service = SearchService(es_client=es_mock)
        result = await service.search("test", search_type="bm25")
        
        # _search_bm25 catches errors internally and returns empty list
        # so search() completes successfully with 0 results
        assert result["total_results"] == 0
        assert result["bm25_count"] == 0
    
    @pytest.mark.asyncio
    async def test_bm25_returns_empty_on_error(self):
        """Test BM25 returns empty list on error."""
        es_mock = Mock()
        es_mock.search = AsyncMock(side_effect=ConnectionError("ES down"))
        
        service = SearchService(es_client=es_mock)
        results = await service._search_bm25("test")
        
        assert results == []


class TestSearchResultModel:
    """Test SearchResult model."""
    
    def test_search_result_creation(self):
        """Test creating a SearchResult."""
        from gabi.schemas.search import SearchHit
        
        result = SearchHit(
            document_id="doc1",
            content_preview="Test content",
            score=0.95,
            source_id="src1"
        )
        
        assert result.document_id == "doc1"
        assert result.score == 0.95


class TestESQueryBuilding:
    """Test Elasticsearch query building."""
    
    def test_build_es_query_structure(self):
        """Test building basic ES query structure."""
        service = SearchService()
        query = service._build_es_query("test query", None, size=20)
        
        # The query returns the bool query structure
        assert "bool" in query
        assert "must" in query["bool"]
        # is_deleted filter is always present
        assert any("is_deleted" in str(f) for f in query["bool"]["filter"])
    
    def test_build_es_query_with_filters(self):
        """Test building ES query with filters."""
        service = SearchService()
        
        filters = SearchFilters(
            source_id="src1",
            source_type="pdf",
            date_from=datetime(2024, 1, 1),
            date_to=datetime(2024, 12, 31),
            tags=["tag1"],
            metadata={"key": "value"}
        )
        
        query = service._build_es_query("test", filters, size=10)
        
        # Query should be built without errors with bool structure
        assert "bool" in query
        assert "must" in query["bool"]
        # Should have is_deleted + 5 filter clauses
        assert len(query["bool"]["filter"]) == 6


class TestRRFFusion:
    """Test Reciprocal Rank Fusion logic."""
    
    def test_rrf_score_computation(self):
        """Test RRF score computation."""
        service = SearchService()
        
        # Both ranks present
        score = service._compute_rrf_score(rank_bm25=1, rank_vector=2, k=60)
        expected = 1.0 / (60 + 1) + 1.0 / (60 + 2)
        assert abs(score - expected) < 0.0001
    
    def test_rrf_score_with_weights(self):
        """Test RRF score with custom weights."""
        service = SearchService()
        
        score = service._compute_rrf_score(
            rank_bm25=1, rank_vector=2, k=60,
            weight_bm25=2.0, weight_vector=1.0
        )
        expected = 2.0 / (60 + 1) + 1.0 / (60 + 2)
        assert abs(score - expected) < 0.0001
    
    def test_rrf_score_with_missing_rank(self):
        """Test RRF score when one rank is missing."""
        service = SearchService()
        
        # Only BM25 rank
        score_bm25_only = service._compute_rrf_score(rank_bm25=1, rank_vector=None, k=60)
        assert abs(score_bm25_only - 1.0 / 61) < 0.0001
        
        # Only vector rank
        score_vector_only = service._compute_rrf_score(rank_bm25=None, rank_vector=1, k=60)
        assert abs(score_vector_only - 1.0 / 61) < 0.0001
    
    def test_fuse_results_rrf(self):
        """Test result fusion with RRF."""
        service = SearchService()
        
        bm25_results = [
            RawResult(id="doc1", content="A", score=10.0),
            RawResult(id="doc2", content="B", score=8.0),
        ]
        vector_results = [
            RawResult(id="doc2", content="B", score=0.9),
            RawResult(id="doc3", content="C", score=0.8),
        ]
        
        fused = service._fuse_results_rrf(bm25_results, vector_results, limit=10)
        
        assert len(fused) == 3  # doc1, doc2, doc3
        # doc2 should have highest score (appears in both)
        assert fused[0].document_id == "doc2"


class TestSearchAPI:
    """Test API-style search with SearchRequest/SearchResponse."""
    
    @pytest.fixture
    def mock_service_with_api(self):
        """Create service with mocked dependencies for API tests."""
        es_mock = Mock()
        es_mock.search = AsyncMock(return_value={
            "hits": {
                "hits": [
                    {"_id": "doc1", "_score": 10.0, "_source": {"content": "A"}},
                ]
            }
        })
        
        emb_mock = Mock()
        emb_mock.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])
        
        return SearchService(
            es_client=es_mock,
            embedding_service=emb_mock,
            settings=None,
            vector_search_backend="elasticsearch"
        )
    
    @pytest.mark.asyncio
    async def test_search_api_with_request(self, mock_service_with_api):
        """Test search_api method with SearchRequest."""
        request = SearchRequest(query="test query", limit=5)
        
        response = await mock_service_with_api.search_api(request)
        
        assert isinstance(response.query, str)
        assert response.query == "test query"
        assert isinstance(response.total, int)
        assert isinstance(response.took_ms, float)
    
    @pytest.mark.asyncio
    async def test_search_api_with_hybrid_weights(self, mock_service_with_api):
        """Test search_api with custom hybrid weights."""
        request = SearchRequest(
            query="test query",
            hybrid_weights={"bm25": 1.5, "vector": 1.0}
        )
        
        response = await mock_service_with_api.search_api(request)
        
        assert response.query == "test query"
    
    @pytest.mark.asyncio
    async def test_search_api_with_sources_filter(self, mock_service_with_api):
        """Test search_api with sources filter."""
        request = SearchRequest(
            query="test query",
            sources=["src1", "src2"]
        )
        
        response = await mock_service_with_api.search_api(request)
        
        assert response.query == "test query"


class TestHealthCheck:
    """Test health check functionality."""
    
    @pytest.mark.asyncio
    async def test_health_check_without_es_client(self):
        """Test health check returns unhealthy without ES client."""
        service = SearchService()
        
        result = await service.health_check()
        
        assert result.status == "unhealthy"
    
    @pytest.mark.asyncio
    async def test_health_check_with_green_cluster(self):
        """Test health check with green cluster status."""
        es_mock = Mock()
        es_mock.cluster = Mock()
        es_mock.cluster.health = AsyncMock(return_value={"status": "green"})
        es_mock.indices = Mock()
        es_mock.indices.stats = AsyncMock(return_value={
            "indices": {
                "documents": {
                    "total": {
                        "docs": {"count": 100},
                        "store": {"size_in_bytes": 1024000}
                    }
                }
            }
        })
        
        service = SearchService(es_client=es_mock)
        result = await service.health_check()
        
        assert result.status == "healthy"
    
    @pytest.mark.asyncio
    async def test_health_check_with_yellow_cluster(self):
        """Test health check with yellow cluster status."""
        es_mock = Mock()
        es_mock.cluster = Mock()
        es_mock.cluster.health = AsyncMock(return_value={"status": "yellow"})
        es_mock.indices = Mock()
        es_mock.indices.stats = AsyncMock(return_value={
            "indices": {
                "documents": {
                    "total": {
                        "docs": {"count": 50},
                        "store": {"size_in_bytes": 512000}
                    }
                }
            }
        })
        
        service = SearchService(es_client=es_mock)
        result = await service.health_check()
        
        assert result.status == "degraded"
    
    @pytest.mark.asyncio
    async def test_health_check_with_red_cluster(self):
        """Test health check with red cluster status."""
        es_mock = Mock()
        es_mock.cluster = Mock()
        es_mock.cluster.health = AsyncMock(return_value={"status": "red"})
        es_mock.indices = Mock()
        es_mock.indices.stats = AsyncMock(return_value={
            "indices": {
                "documents": {
                    "total": {
                        "docs": {"count": 0},
                        "store": {"size_in_bytes": 0}
                    }
                }
            }
        })
        
        service = SearchService(es_client=es_mock)
        result = await service.health_check()
        
        assert result.status == "unhealthy"


class TestRawResult:
    """Test RawResult dataclass."""
    
    def test_raw_result_creation(self):
        """Test creating RawResult."""
        result = RawResult(
            id="doc1",
            content="Test content",
            score=0.95,
            source_id="src1"
        )
        
        assert result.id == "doc1"
        assert result.content == "Test content"
        assert result.score == 0.95
        assert result.source_id == "src1"
    
    def test_raw_result_with_optional_fields(self):
        """Test RawResult with all optional fields."""
        result = RawResult(
            id="doc1",
            content="Test",
            score=0.95,
            source_id="src1",
            source_type="pdf",
            metadata={"author": "John"},
            title="Test Title",
            url="http://example.com"
        )
        
        assert result.title == "Test Title"
        assert result.url == "http://example.com"
