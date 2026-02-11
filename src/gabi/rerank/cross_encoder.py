"""
Cross-Encoder Reranking Implementation for GABI

This module implements cross-encoder reranking to improve search result relevance.
The cross-encoder takes the top-K candidates from initial retrieval (BM25 + vector search)
and rescores them by processing the query-document pair together through a transformer.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import numpy as np

from gabi.config import settings
from gabi.types import SearchType

logger = logging.getLogger(__name__)


@dataclass
class RerankResult:
    """Result of reranking operation."""
    document_id: str
    title: str
    content_preview: str
    source_id: str
    metadata: Dict[str, Any]
    initial_score: float
    reranked_score: float
    rank_before: int
    rank_after: int


class CrossEncoderReranker:
    """
    Cross-Encoder Reranker for improving search result relevance.
    
    The cross-encoder reranks top-K candidates by processing query-document pairs
    together, capturing fine-grained interactions that bi-encoder models miss.
    """
    
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-12-v2"):
        """
        Initialize the cross-encoder reranker.
        
        Args:
            model_name: Name of the cross-encoder model to use
        """
        self.model_name = model_name
        self.tokenizer = None
        self.model = None
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        # Maximum number of candidate pairs to process at once
        self.batch_size = 16
        self.max_length = 512
        
    async def initialize(self):
        """Initialize the cross-encoder model asynchronously."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._load_model)
        
    def _load_model(self):
        """Load the cross-encoder model (runs in thread pool)."""
        logger.info(f"Loading cross-encoder model: {self.model_name}")
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
        self.model.eval()
        self.model.to(self.device)
        logger.info(f"Cross-encoder model loaded on {self.device}")
        
    async def rerank(
        self, 
        query: str, 
        candidates: List[Dict[str, Any]], 
        top_k: int = 50
    ) -> List[RerankResult]:
        """
        Rerank candidate documents using cross-encoder.
        
        Args:
            query: The search query
            candidates: List of candidate documents with initial scores
            top_k: Number of top candidates to rerank
            
        Returns:
            List of reranked results with updated scores
        """
        if not candidates:
            return []
        
        # Take top K candidates based on initial scores
        sorted_candidates = sorted(
            candidates, 
            key=lambda x: x.get('score', 0.0), 
            reverse=True
        )[:top_k]
        
        if not self.model or not self.tokenizer:
            # If model not loaded, return original results with rank info
            results = []
            for i, candidate in enumerate(sorted_candidates):
                results.append(RerankResult(
                    document_id=candidate.get('document_id', ''),
                    title=candidate.get('title', ''),
                    content_preview=candidate.get('content_preview', '')[:200],
                    source_id=candidate.get('source_id', ''),
                    metadata=candidate.get('metadata', {}),
                    initial_score=candidate.get('score', 0.0),
                    reranked_score=candidate.get('score', 0.0),
                    rank_before=i+1,
                    rank_after=i+1
                ))
            return results
        
        # Prepare query-document pairs for reranking
        query_doc_pairs = []
        for candidate in sorted_candidates:
            content = candidate.get('content_preview', '') or candidate.get('content', '') or ''
            query_doc_pairs.append((query, content[:500]))  # Limit content length
        
        # Rerank in batches
        all_scores = []
        for i in range(0, len(query_doc_pairs), self.batch_size):
            batch = query_doc_pairs[i:i+self.batch_size]
            batch_scores = await self._rerank_batch(batch)
            all_scores.extend(batch_scores)
        
        # Create reranked results
        reranked_pairs = list(zip(sorted_candidates, all_scores))
        reranked_pairs.sort(key=lambda x: x[1], reverse=True)
        
        results = []
        for rank_after, ((candidate, score), rank_before) in enumerate(
            zip(reranked_pairs, range(1, len(reranked_pairs)+1)), 1
        ):
            orig_candidate, cross_score = candidate
            results.append(RerankResult(
                document_id=orig_candidate.get('document_id', ''),
                title=orig_candidate.get('title', ''),
                content_preview=orig_candidate.get('content_preview', '')[:200],
                source_id=orig_candidate.get('source_id', ''),
                metadata=orig_candidate.get('metadata', {}),
                initial_score=orig_candidate.get('score', 0.0),
                reranked_score=float(cross_score),
                rank_before=orig_candidate.get('rank', rank_before),  # Use existing rank if available
                rank_after=rank_after
            ))
        
        return results
    
    async def _rerank_batch(self, query_doc_pairs: List[Tuple[str, str]]) -> List[float]:
        """Rerank a batch of query-document pairs."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, 
            self._rerank_batch_sync, 
            query_doc_pairs
        )
    
    def _rerank_batch_sync(self, query_doc_pairs: List[Tuple[str, str]]) -> List[float]:
        """Synchronous reranking of a batch (runs in thread pool)."""
        # Tokenize the batch
        texts = [(pair[0], pair[1]) for pair in query_doc_pairs]
        inputs = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            return_tensors="pt",
            max_length=self.max_length
        ).to(self.device)
        
        # Get predictions
        with torch.no_grad():
            outputs = self.model(**inputs)
            scores = torch.nn.functional.softmax(outputs.logits, dim=1)[:, 1]  # Get positive class probabilities
        
        return scores.cpu().numpy().tolist()


# Global instance
_cross_encoder_reranker: Optional[CrossEncoderReranker] = None


async def get_cross_encoder_reranker() -> CrossEncoderReranker:
    """Get singleton instance of cross-encoder reranker."""
    global _cross_encoder_reranker
    if _cross_encoder_reranker is None:
        _cross_encoder_reranker = CrossEncoderReranker()
        await _cross_encoder_reranker.initialize()
    return _cross_encoder_reranker


async def apply_cross_encoder_reranking(
    query: str,
    search_results: List[Dict[str, Any]],
    top_k: int = 50
) -> List[Dict[str, Any]]:
    """
    Apply cross-encoder reranking to search results.
    
    Args:
        query: The search query
        search_results: Initial search results to rerank
        top_k: Number of top results to rerank
        
    Returns:
        Reranked results with updated scores
    """
    reranker = await get_cross_encoder_reranker()
    reranked_results = await reranker.rerank(query, search_results, top_k)
    
    # Convert back to dictionary format for compatibility
    final_results = []
    for result in reranked_results:
        final_results.append({
            "document_id": result.document_id,
            "title": result.title,
            "content_preview": result.content_preview,
            "source_id": result.source_id,
            "metadata": result.metadata,
            "score": result.reranked_score,
            "initial_score": result.initial_score,
            "rank_before": result.rank_before,
            "rank_after": result.rank_after
        })
    
    return final_results