"""
SPLADE (Sparse Learned Embeddings) Implementation for GABI

This module implements SPLADE embeddings which produce sparse representations
that capture semantic information in a format compatible with inverted indices,
potentially replacing the dual system (Elasticsearch + pgvector) with a single system.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import numpy as np
from scipy.sparse import csr_matrix
import torch
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModel
from sklearn.feature_extraction.text import TfidfVectorizer

from gabi.config import settings
from gabi.types import SearchType

logger = logging.getLogger(__name__)


@dataclass
class SPLADEResult:
    """Result of SPLADE embedding operation."""
    document_id: str
    sparse_embedding: csr_matrix
    token_weights: Dict[str, float]
    vocabulary: List[str]


class SPLADEEmbedder:
    """
    SPLADE Embedder for creating sparse embeddings.
    
    SPLADE produces sparse embeddings by learning term weights that capture
    semantic information in a format compatible with inverted indices.
    """
    
    def __init__(self, model_name: str = "naver/splade-cocondenser-ensembledistil"):
        """
        Initialize the SPLADE embedder.
        
        Args:
            model_name: Name of the SPLADE model to use
        """
        self.model_name = model_name
        self.tokenizer = None
        self.model = None
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        # Vocabulary for the model
        self.vocab = None
        
    async def initialize(self):
        """Initialize the SPLADE model asynchronously."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._load_model)
        
    def _load_model(self):
        """Load the SPLADE model (runs in thread pool)."""
        try:
            logger.info(f"Loading SPLADE model: {self.model_name}")
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModel.from_pretrained(self.model_name)
            self.model.eval()
            self.model.to(self.device)
            
            # Get vocabulary
            self.vocab = {v: k for k, v in self.tokenizer.get_vocab().items()}
            
            logger.info(f"SPLADE model loaded on {self.device}")
        except Exception as e:
            logger.warning(f"Could not load SPLADE model {self.model_name}: {e}")
            logger.info("Falling back to traditional TF-IDF approach")
            self.model = None
            self.tokenizer = None
            self.vocab = None
    
    async def embed(self, text: str) -> Optional[SPLADEResult]:
        """
        Create a SPLADE embedding for the given text.
        
        Args:
            text: Input text to embed
            
        Returns:
            SPLADEResult with sparse embedding and token weights
        """
        if self.model and self.tokenizer:
            # Use SPLADE model
            return await self._embed_with_splade(text)
        else:
            # Fallback to TF-IDF based sparse representation
            return await self._embed_with_tfidf(text)
    
    async def embed_batch(self, texts: List[str]) -> List[Optional[SPLADEResult]]:
        """
        Create SPLADE embeddings for a batch of texts.
        
        Args:
            texts: List of input texts to embed
            
        Returns:
            List of SPLADEResult objects
        """
        if self.model and self.tokenizer:
            # Use SPLADE model
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                self._embed_batch_with_splade_sync,
                texts
            )
        else:
            # Fallback to TF-IDF
            results = []
            for text in texts:
                results.append(await self._embed_with_tfidf(text))
            return results
    
    async def _embed_with_splade(self, text: str) -> Optional[SPLADEResult]:
        """Create SPLADE embedding using the trained model."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._embed_with_splade_sync,
            text
        )
    
    def _embed_with_splade_sync(self, text: str) -> Optional[SPLADEResult]:
        """Synchronous SPLADE embedding (runs in thread pool)."""
        # Tokenize input
        inputs = self.tokenizer(
            text,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=512
        ).to(self.device)
        
        # Get model outputs
        with torch.no_grad():
            outputs = self.model(**inputs)
            # For SPLADE, we typically use the CLS token representation
            # and apply log(1 + ReLU(logits)) to get term weights
            logits = outputs.last_hidden_state  # Shape: [batch_size, seq_len, vocab_size]
            
            # Apply activation to get term weights
            activated = F.relu(logits)  # ReLU activation
            log_activated = torch.log1p(activated)  # log(1 + x) activation
            
            # Sum over sequence dimension to get document-level term weights
            doc_weights = torch.sum(log_activated, dim=1)  # Shape: [batch_size, vocab_size]
            
            # Get the first (and only) document's weights
            weights = doc_weights[0].cpu().numpy()
        
        # Create sparse representation - only keep non-zero weights
        non_zero_indices = np.nonzero(weights)[0]
        non_zero_weights = weights[non_zero_indices]
        
        # Create sparse matrix (1 x vocab_size)
        sparse_embedding = csr_matrix(
            (non_zero_weights, (np.zeros_like(non_zero_indices), non_zero_indices)),
            shape=(1, len(self.vocab))
        )
        
        # Create token weights dictionary
        token_weights = {}
        for idx, weight in zip(non_zero_indices, non_zero_weights):
            if idx in self.vocab:
                token = self.vocab[idx]
                token_weights[token] = float(weight)
        
        return SPLADEResult(
            document_id=f"splade_{hash(text)}",  # Generate a document ID
            sparse_embedding=sparse_embedding,
            token_weights=token_weights,
            vocabulary=list(self.vocab.keys()) if self.vocab else []
        )
    
    def _embed_batch_with_splade_sync(self, texts: List[str]) -> List[Optional[SPLADEResult]]:
        """Synchronous batch SPLADE embedding (runs in thread pool)."""
        results = []
        for text in texts:
            result = self._embed_with_splade_sync(text)
            results.append(result)
        return results
    
    async def _embed_with_tfidf(self, text: str) -> Optional[SPLADEResult]:
        """Create sparse embedding using TF-IDF as fallback."""
        # This is a simplified TF-IDF approach for demonstration
        # In practice, you'd use a proper trained SPLADE model
        
        # Simple tokenization and weighting
        tokens = text.lower().split()
        
        # Count token frequencies
        token_counts = {}
        for token in tokens:
            # Remove punctuation
            clean_token = ''.join(c for c in token if c.isalnum())
            if clean_token:
                token_counts[clean_token] = token_counts.get(clean_token, 0) + 1
        
        # Normalize counts to create weights
        total_tokens = len(tokens)
        token_weights = {token: count/total_tokens for token, count in token_counts.items()}
        
        # For demo purposes, create a simple sparse matrix
        # In a real implementation, this would be much more sophisticated
        vocab_list = list(token_weights.keys())
        weights_array = list(token_weights.values())
        
        # Create a sparse matrix representation
        row_indices = [0] * len(weights_array)  # Single document
        col_indices = list(range(len(weights_array)))  # Token indices
        sparse_embedding = csr_matrix(
            (weights_array, (row_indices, col_indices)),
            shape=(1, len(vocab_list))
        )
        
        return SPLADEResult(
            document_id=f"tfidf_{hash(text)}",  # Generate a document ID
            sparse_embedding=sparse_embedding,
            token_weights=token_weights,
            vocabulary=vocab_list
        )
    
    async def compute_similarity(self, query_embedding: SPLADEResult, doc_embedding: SPLADEResult) -> float:
        """
        Compute similarity between two SPLADE embeddings.
        
        Args:
            query_embedding: SPLADE embedding for the query
            doc_embedding: SPLADE embedding for the document
            
        Returns:
            Similarity score (dot product of sparse vectors)
        """
        # Compute dot product of sparse vectors
        similarity = query_embedding.sparse_embedding.dot(doc_embedding.sparse_embedding.T).toarray()[0][0]
        return float(similarity)


# Global instance
_splade_embedder: Optional[SPLADEEmbedder] = None


async def get_splade_embedder() -> SPLADEEmbedder:
    """Get singleton instance of SPLADE embedder."""
    global _splade_embedder
    if _splade_embedder is None:
        _splade_embedder = SPLADEEmbedder()
        await _splade_embedder.initialize()
    return _splade_embedder


async def create_splade_embedding(text: str) -> Optional[SPLADEResult]:
    """
    Create a SPLADE embedding for the given text.
    
    Args:
        text: Input text to embed
        
    Returns:
        SPLADEResult with sparse embedding and token weights
    """
    embedder = await get_splade_embedder()
    return await embedder.embed(text)


async def create_splade_embeddings_batch(texts: List[str]) -> List[Optional[SPLADEResult]]:
    """
    Create SPLADE embeddings for a batch of texts.
    
    Args:
        texts: List of input texts to embed
        
    Returns:
        List of SPLADEResult objects
    """
    embedder = await get_splade_embedder()
    return await embedder.embed_batch(texts)


async def compute_splade_similarity(query_embedding: SPLADEResult, doc_embedding: SPLADEResult) -> float:
    """
    Compute similarity between two SPLADE embeddings.
    
    Args:
        query_embedding: SPLADE embedding for the query
        doc_embedding: SPLADE embedding for the document
        
    Returns:
        Similarity score
    """
    embedder = await get_splade_embedder()
    return await embedder.compute_similarity(query_embedding, doc_embedding)