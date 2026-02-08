"""Services - Lógica de negócio e serviços do GABI.

Implementa serviços de alto nível para:
- Busca híbrida (BM25 + Vetorial)
- Geração de embeddings
- Indexação de documentos
- Descoberta de fontes

Example:
    >>> from gabi.services.search_service import SearchService
    >>> from gabi.services.embedding_service import EmbeddingService
    >>> service = SearchService()
    >>> results = await service.search("query", "hybrid")
"""

from gabi.services.search_service import SearchService
from gabi.services.embedding_service import (
    EmbeddingService,
    CacheConfig,
    EmbeddingMetrics,
    EmbeddingBackend,
    LocalEmbeddingBackend,
)

__all__ = [
    # Search
    "SearchService",
    # Embeddings
    "EmbeddingService",
    "CacheConfig",
    "EmbeddingMetrics",
    "EmbeddingBackend",
    "LocalEmbeddingBackend",
]
