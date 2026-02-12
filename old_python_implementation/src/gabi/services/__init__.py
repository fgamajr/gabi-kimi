"""Services - Lógica de negócio e serviços do GABI.

Implementa serviços de alto nível para:
- Busca híbrida (BM25 + Vetorial) com RRF
- Geração de embeddings
- Indexação de documentos
- Descoberta de fontes

Example:
    >>> from gabi.services.hybrid_search import HybridSearchService
    >>> from gabi.services.embedding_service import EmbeddingService
    >>> service = HybridSearchService()
    >>> results = await service.search(request)
"""

from gabi.services.search_service import SearchService
from gabi.services.hybrid_search import (
    HybridSearchService,
    QueryRouter,
    QueryType,
    RRFFusionEngine,
    SearchBackend,
    SearchQuery,
    SearchResult,
    FusionResult,
    RedisCacheBackend,
    InMemoryCacheBackend,
    CacheBackend,
)
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
    "HybridSearchService",
    "QueryRouter",
    "QueryType",
    "RRFFusionEngine",
    "SearchBackend",
    "SearchQuery",
    "SearchResult",
    "FusionResult",
    # Cache
    "RedisCacheBackend",
    "InMemoryCacheBackend",
    "CacheBackend",
    # Embeddings
    "EmbeddingService",
    "CacheConfig",
    "EmbeddingMetrics",
    "EmbeddingBackend",
    "LocalEmbeddingBackend",
]
