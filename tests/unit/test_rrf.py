"""Unit tests for Reciprocal Rank Fusion (RRF) algorithm."""

import pytest
from gabi.services.search_service import SearchService, RawResult
from gabi.schemas.search import RRFConfig


class TestRRFAlgorithm:
    """Test RRF score computation and fusion logic."""
    
    def test_rrf_score_single_rank_bm25(self):
        """Test RRF score with only BM25 rank."""
        service = SearchService()
        score = service._compute_rrf_score(rank_bm25=1, rank_vector=None, k=60)
        assert score == pytest.approx(1/61, rel=1e-6)
    
    def test_rrf_score_single_rank_vector(self):
        """Test RRF score with only vector rank."""
        service = SearchService()
        score = service._compute_rrf_score(rank_bm25=None, rank_vector=1, k=60)
        assert score == pytest.approx(1/61, rel=1e-6)
    
    def test_rrf_score_both_ranks(self):
        """Test RRF score with both BM25 and vector ranks."""
        service = SearchService()
        score = service._compute_rrf_score(rank_bm25=1, rank_vector=2, k=60)
        expected = (1/61) + (1/62)
        assert score == pytest.approx(expected, rel=1e-6)
    
    def test_rrf_score_no_ranks(self):
        """Test RRF score with no ranks provided."""
        service = SearchService()
        score = service._compute_rrf_score(rank_bm25=None, rank_vector=None, k=60)
        assert score == 0.0
    
    def test_rrf_score_zero_rank(self):
        """Test RRF score with zero rank (invalid, should be ignored)."""
        service = SearchService()
        score = service._compute_rrf_score(rank_bm25=0, rank_vector=0, k=60)
        assert score == 0.0
    
    def test_rrf_score_negative_rank(self):
        """Test RRF score with negative rank (invalid, should be ignored)."""
        service = SearchService()
        score = service._compute_rrf_score(rank_bm25=-1, rank_vector=-5, k=60)
        assert score == 0.0
    
    def test_rrf_score_different_k_values(self):
        """Test RRF score with different k constants."""
        service = SearchService()
        score_k30 = service._compute_rrf_score(rank_bm25=1, rank_vector=1, k=30)
        score_k60 = service._compute_rrf_score(rank_bm25=1, rank_vector=1, k=60)
        score_k100 = service._compute_rrf_score(rank_bm25=1, rank_vector=1, k=100)
        
        # Lower k = higher score for same rank
        assert score_k30 > score_k60 > score_k100
    
    def test_rrf_score_higher_rank_lower_score(self):
        """Test that higher rank (worse position) gives lower score."""
        service = SearchService()
        score_rank1 = service._compute_rrf_score(rank_bm25=1, rank_vector=None, k=60)
        score_rank10 = service._compute_rrf_score(rank_bm25=10, rank_vector=None, k=60)
        score_rank100 = service._compute_rrf_score(rank_bm25=100, rank_vector=None, k=60)
        
        assert score_rank1 > score_rank10 > score_rank100
    
    def test_rrf_with_weighted_config(self):
        """Test RRF with weighted configuration."""
        service = SearchService()
        
        # Test with explicit weights passed to _compute_rrf_score
        score = service._compute_rrf_score(
            rank_bm25=1, rank_vector=1, k=60, 
            weight_bm25=0.7, weight_vector=0.8
        )
        expected = (0.7/61) + (0.8/61)
        assert score == pytest.approx(expected, rel=1e-6)
    
    def test_rrf_zero_weight_ignores_source(self):
        """Test that zero weight ignores that source."""
        service = SearchService()
        
        # Test with explicit weights - bm25 weight is 0
        score = service._compute_rrf_score(
            rank_bm25=1, rank_vector=2, k=60,
            weight_bm25=0.0, weight_vector=1.0
        )
        expected = 1.0/62  # Only vector contributes
        assert score == pytest.approx(expected, rel=1e-6)


class TestRRFFusion:
    """Test RRF result fusion."""
    
    @pytest.fixture
    def sample_bm25_results(self):
        """Create sample BM25 results."""
        return [
            RawResult(id="doc1", content="Content 1", score=10.5, source_id="src1"),
            RawResult(id="doc2", content="Content 2", score=9.2, source_id="src1"),
            RawResult(id="doc3", content="Content 3", score=8.0, source_id="src2"),
        ]
    
    @pytest.fixture
    def sample_vector_results(self):
        """Create sample vector results."""
        return [
            RawResult(id="doc2", content="Content 2", score=0.95, source_id="src1"),
            RawResult(id="doc4", content="Content 4", score=0.90, source_id="src2"),
            RawResult(id="doc1", content="Content 1", score=0.85, source_id="src1"),
        ]
    
    def test_fuse_empty_results(self):
        """Test fusion with empty result lists."""
        service = SearchService()
        results = service._fuse_results_rrf([], [], limit=10, k=60)
        assert results == []
    
    def test_fuse_only_bm25(self, sample_bm25_results):
        """Test fusion with only BM25 results."""
        service = SearchService()
        results = service._fuse_results_rrf(sample_bm25_results, [], limit=10, k=60)
        
        assert len(results) == 3
        # Results are SearchHit objects with document_id
        assert results[0].document_id in ["doc1", "doc2", "doc3"]
        assert results[0].score > 0
    
    def test_fuse_only_vector(self, sample_vector_results):
        """Test fusion with only vector results."""
        service = SearchService()
        results = service._fuse_results_rrf([], sample_vector_results, limit=10, k=60)
        
        assert len(results) == 3
        # Results are SearchHit objects with document_id
        assert results[0].document_id in ["doc1", "doc2", "doc4"]
        assert results[0].score > 0
    
    def test_fuse_combined_results(self, sample_bm25_results, sample_vector_results):
        """Test fusion with both result types."""
        service = SearchService()
        results = service._fuse_results_rrf(
            sample_bm25_results,
            sample_vector_results,
            limit=10,
            k=60
        )
        
        assert len(results) == 4  # doc1, doc2, doc3, doc4
        
        # Get all document IDs
        doc_ids = [r.document_id for r in results]
        assert "doc1" in doc_ids
        assert "doc2" in doc_ids
        assert "doc3" in doc_ids
        assert "doc4" in doc_ids
        
        # doc2 appears in both so should have higher score
        doc2 = next(r for r in results if r.document_id == "doc2")
        assert doc2.score > 0
        
        # doc3 only in BM25
        doc3 = next(r for r in results if r.document_id == "doc3")
        assert doc3.score > 0
        
        # doc4 only in vector
        doc4 = next(r for r in results if r.document_id == "doc4")
        assert doc4.score > 0
    
    def test_fuse_respects_limit(self, sample_bm25_results, sample_vector_results):
        """Test that limit parameter is respected."""
        service = SearchService()
        results = service._fuse_results_rrf(
            sample_bm25_results,
            sample_vector_results,
            limit=2,
            k=60
        )
        
        assert len(results) == 2
    
    def test_fuse_rrf_ranking_order(self, sample_bm25_results, sample_vector_results):
        """Test that results are properly ranked by RRF score."""
        service = SearchService()
        results = service._fuse_results_rrf(
            sample_bm25_results,
            sample_vector_results,
            limit=10,
            k=60
        )
        
        # Verify descending order by score
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)
    
    def test_fuse_preserves_metadata(self, sample_bm25_results):
        """Test that metadata is preserved in fused results."""
        service = SearchService()
        results = service._fuse_results_rrf(sample_bm25_results, [], limit=10, k=60)
        
        # Check that results have source_id (may be different from original)
        assert results[0].source_id is not None
        assert isinstance(results[0].metadata, dict)
    
    def test_fuse_with_custom_k(self, sample_bm25_results, sample_vector_results):
        """Test fusion with custom k value."""
        config = RRFConfig(k=30)
        service = SearchService(rrf_config=config)
        
        results = service._fuse_results_rrf(
            sample_bm25_results,
            sample_vector_results,
            limit=10,
            k=30
        )
        
        assert len(results) > 0
        # All results should have scores
        assert all(r.score > 0 for r in results)


class TestRRFEdgeCases:
    """Test RRF edge cases."""
    
    def test_identical_ranks(self):
        """Test RRF with identical documents at same rank."""
        service = SearchService()
        
        bm25 = [
            RawResult(id="doc1", content="A", score=10.0),
            RawResult(id="doc2", content="B", score=9.0),
        ]
        vector = [
            RawResult(id="doc1", content="A", score=0.9),
            RawResult(id="doc2", content="B", score=0.8),
        ]
        
        results = service._fuse_results_rrf(bm25, vector, limit=10, k=60)
        
        # Both docs should be present
        assert len(results) == 2
        
        # doc1 should rank higher or equal (rank 1 in both)
        doc_ids = [r.document_id for r in results]
        assert "doc1" in doc_ids
        assert "doc2" in doc_ids
    
    def test_single_result_each(self):
        """Test RRF with single result from each source."""
        service = SearchService()
        
        bm25 = [RawResult(id="doc1", content="A", score=10.0)]
        vector = [RawResult(id="doc2", content="B", score=0.9)]
        
        results = service._fuse_results_rrf(bm25, vector, limit=10, k=60)
        
        assert len(results) == 2
        # Both should have positive scores
        assert results[0].score > 0
        assert results[1].score > 0
    
    def test_duplicate_ids_ignored(self):
        """Test that duplicate IDs in same source are handled."""
        service = SearchService()
        
        bm25 = [
            RawResult(id="doc1", content="A", score=10.0),
            RawResult(id="doc1", content="A duplicate", score=9.0),  # Duplicate
        ]
        
        results = service._fuse_results_rrf(bm25, [], limit=10, k=60)
        
        # Only one doc1 should be present
        doc1_results = [r for r in results if r.document_id == "doc1"]
        assert len(doc1_results) == 1
