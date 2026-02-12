"""Pipeline - Processamento de documentos em estágios.

Pipeline modular com fases:
1. Discovery - Descoberta de URLs
2. Change Detection - Detecção de mudanças
3. Fetch - Download de conteúdo
4. Parse - Extração de texto
5. Fingerprint - Geração de fingerprints
6. Chunking - Divisão em chunks
7. Embedding - Geração de embeddings
8. Indexing - Indexação no PostgreSQL/ES
"""

from gabi.pipeline.contracts import (
    # Discovery
    DiscoveredURL,
    DiscoveryResult,
    # Change Detection
    ChangeCheckResult,
    ChangeDetectionSummary,
    # Fetch
    FetchMetadata,
    FetchedContent,
    # Parse
    ParsedDocument,
    ParseResult,
    # Fingerprint
    DocumentFingerprint,
    DuplicateCheckResult,
    # Chunk
    Chunk,
    ChunkingResult,
    # Embedding
    EmbeddedChunk,
    EmbeddingResult,
    # Index
    IndexDocument,
    IndexChunk,
    IndexingResult,
    # Execution
    ExecutionCheckpoint,
    ExecutionStats,
    PipelinePhaseResult,
    PipelineResult,
    # DLQ
    DLQMessage,
)

# Lazy imports to avoid side effects at import time
# Use: from gabi.pipeline.discovery import DiscoveryEngine
# Use: from gabi.pipeline.change_detection import ChangeDetector
# Use: from gabi.pipeline.fetcher import ContentFetcher
# Use: from gabi.pipeline.fingerprint import Fingerprinter, FingerprinterConfig

# Import orchestrator (lazy to avoid side effects)
from gabi.pipeline.orchestrator import (
    PipelineOrchestrator,
    PipelineConfig,
    PipelineManifest,
    PipelineStatus,
    PipelinePhase,
    run_pipeline,
)

__all__ = [
    # Orchestrator
    "PipelineOrchestrator",
    "PipelineConfig",
    "PipelineManifest",
    "PipelineStatus",
    "PipelinePhase",
    "run_pipeline",
    # Contracts
    "DiscoveredURL",
    "DiscoveryResult",
    "ChangeCheckResult",
    "ChangeDetectionSummary",
    "FetchMetadata",
    "FetchedContent",
    "ParsedDocument",
    "ParseResult",
    "DocumentFingerprint",
    "DuplicateCheckResult",
    "Chunk",
    "ChunkingResult",
    "EmbeddedChunk",
    "EmbeddingResult",
    "IndexDocument",
    "IndexChunk",
    "IndexingResult",
    "ExecutionCheckpoint",
    "ExecutionStats",
    "PipelinePhaseResult",
    "PipelineResult",
    "DLQMessage",
]
