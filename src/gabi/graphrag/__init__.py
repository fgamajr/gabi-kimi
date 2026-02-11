"""GraphRAG module for GABI - Graph-based Retrieval Augmented Generation.

This module provides knowledge graph capabilities for the GABI legal document
search system, enabling relationship-aware search through citations, revocations,
precedents, and normative chains.

Example:
    >>> from gabi.graphrag import GraphRAGSearchService
    >>> service = GraphRAGSearchService(...)
    >>> results = await service.search("licitação direta")
"""

from gabi.graphrag.extractor import (
    LegalEntityExtractor,
    ExtractedEntity,
    ExtractedRelation,
)
from gabi.graphrag.pipeline import (
    GraphConstructionPipeline,
    GraphUpdateResult,
)
from gabi.graphrag.search import (
    GraphRAGSearchService,
    GraphSearchResult,
)

__all__ = [
    "LegalEntityExtractor",
    "ExtractedEntity",
    "ExtractedRelation",
    "GraphConstructionPipeline",
    "GraphUpdateResult",
    "GraphRAGSearchService",
    "GraphSearchResult",
]
