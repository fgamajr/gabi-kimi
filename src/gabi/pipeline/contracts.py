"""Contratos do pipeline de ingestão.

Define todas as estruturas de dados utilizadas no pipeline de ingestão,
desde a descoberta até a indexação.
Baseado em CONTRACTS.md §2.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from enum import Enum

from gabi.types import (
    ChangeDetectionResult,
    ContentType,
    DocumentStatus,
    ExecutionStatus,
    LineageEdgeType,
    LineageNodeType,
    SectionType,
    SourceType,
)


# =============================================================================
# Discovery Contracts
# =============================================================================

@dataclass
class DiscoveredURL:
    """URL descoberta durante a fase de discovery.
    
    Attributes:
        url: URL completa
        source_id: ID da fonte
        metadata: Metadados adicionais
        priority: Prioridade de processamento (maior = mais prioritário)
        discovered_at: Timestamp de descoberta
    """
    url: str
    source_id: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    discovered_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DiscoveryResult:
    """Resultado da fase de discovery.
    
    Attributes:
        urls: Lista de URLs descobertas
        total_found: Total de URLs encontradas
        filtered_out: URLs filtradas (duplicadas, excluídas, etc.)
        duration_seconds: Duração da fase
    """
    urls: List[DiscoveredURL] = field(default_factory=list)
    total_found: int = 0
    filtered_out: int = 0
    duration_seconds: float = 0.0


# =============================================================================
# Change Detection Contracts
# =============================================================================

@dataclass
class ChangeCheckResult:
    """Resultado da verificação de mudanças para uma URL.
    
    Attributes:
        url: URL verificada
        result: Tipo de resultado (new, changed, unchanged, error)
        etag: Header ETag atual
        last_modified: Header Last-Modified atual
        content_hash: Hash do conteúdo atual
        content_length: Tamanho do conteúdo em bytes
        previous_check: Timestamp da verificação anterior
        current_check: Timestamp desta verificação
    """
    url: str
    result: ChangeDetectionResult
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    content_hash: Optional[str] = None
    content_length: Optional[int] = None
    previous_check: Optional[datetime] = None
    current_check: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ChangeDetectionSummary:
    """Resumo da fase de change detection.
    
    Attributes:
        new_urls: URLs novas
        changed_urls: URLs modificadas
        unchanged_urls: URLs sem mudanças
        error_urls: URLs com erro na verificação
        total_checked: Total verificado
        duration_seconds: Duração da fase
    """
    new_urls: List[str] = field(default_factory=list)
    changed_urls: List[str] = field(default_factory=list)
    unchanged_urls: List[str] = field(default_factory=list)
    error_urls: List[str] = field(default_factory=list)
    total_checked: int = 0
    duration_seconds: float = 0.0


# =============================================================================
# Fetcher Contracts
# =============================================================================

@dataclass
class FetchMetadata:
    """Metadados de uma requisição fetch.
    
    Attributes:
        url: URL buscada
        method: Método HTTP
        status_code: Código de status HTTP
        content_type: Content-Type do response
        content_length: Tamanho do conteúdo em bytes
        encoding: Encoding detectado
        headers: Headers HTTP da resposta
        fetch_duration_ms: Tempo de download em ms
        timestamp: Timestamp do fetch
    """
    url: str
    method: str = "GET"
    status_code: int = 200
    content_type: Optional[str] = None
    content_length: Optional[int] = None
    encoding: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    fetch_duration_ms: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class FetchedContent:
    """Conteúdo buscado na fase de fetch.
    
    All content is kept in memory (diskless server — no temp files).
    The content_path field is kept for backward compatibility but is
    never populated in the current architecture.
    
    Attributes:
        url: URL de origem
        content: Conteúdo bruto em bytes (sempre presente)
        metadata: Metadados do fetch
        cache_path: Caminho no cache local (se aplicável)
        fingerprint: Hash do conteúdo para dedup
        content_path: DEPRECATED — sempre None em server diskless
        is_streamed: DEPRECATED — sempre False em server diskless
        size_bytes: Tamanho do conteúdo em bytes
    """
    url: str
    content: Optional[bytes] = None
    metadata: Optional[FetchMetadata] = None
    cache_path: Optional[str] = None
    fingerprint: Optional[str] = None
    content_path: Optional[str] = None  # DEPRECATED: diskless server
    is_streamed: bool = False  # DEPRECATED: always False
    size_bytes: int = 0
    
    def get_content(self) -> bytes:
        """Get content bytes.
        
        Content is always in memory. The file fallback is kept for
        backward compatibility but should never be hit on diskless servers.
        
        Returns:
            Content as bytes
            
        Raises:
            ValueError: If no content available
        """
        if self.content is not None:
            return self.content
        # Legacy fallback (should not happen on diskless server)
        if self.content_path:
            import os
            with open(self.content_path, 'rb') as f:
                return f.read()
        raise ValueError("No content available — content was not loaded into memory")
    
    def cleanup(self) -> None:
        """Noop on diskless server. Kept for backward compatibility.
        
        Safe to call multiple times.
        """
        # Legacy temp file cleanup (should not happen on diskless server)
        if self.content_path:
            import os
            try:
                if os.path.exists(self.content_path):
                    os.unlink(self.content_path)
            except OSError:
                pass
            self.content_path = None


# =============================================================================
# Parser Contracts
# =============================================================================

@dataclass
class ParsedDocument:
    """Documento parseado na fase de parsing.
    
    Attributes:
        document_id: ID único do documento
        source_id: ID da fonte
        title: Título do documento
        content: Conteúdo completo em texto
        content_preview: Preview do conteúdo (primeiros N caracteres)
        content_type: Tipo de conteúdo original
        content_hash: Hash do conteúdo
        url: URL de origem
        language: Idioma detectado (ex: 'pt-BR')
        metadata: Metadados estruturados
        parsed_at: Timestamp do parsing
        parsing_duration_ms: Duração do parsing em ms
    """
    document_id: str
    source_id: str
    title: Optional[str] = None
    content: str = ""
    content_preview: Optional[str] = None
    content_type: Optional[str] = None
    content_hash: Optional[str] = None
    url: Optional[str] = None
    language: str = "pt-BR"
    metadata: Dict[str, Any] = field(default_factory=dict)
    parsed_at: datetime = field(default_factory=datetime.utcnow)
    parsing_duration_ms: int = 0


@dataclass
class ParseResult:
    """Resultado da fase de parsing.
    
    Attributes:
        documents: Documentos extraídos
        errors: Erros encontrados durante parsing
        raw_content_size: Tamanho do conteúdo bruto
        parsed_content_size: Tamanho do conteúdo parseado
        duration_seconds: Duração da fase
    """
    documents: List[ParsedDocument] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    raw_content_size: int = 0
    parsed_content_size: int = 0
    duration_seconds: float = 0.0


# =============================================================================
# Fingerprint Contracts
# =============================================================================

@dataclass
class DocumentFingerprint:
    """Fingerprint de um documento para deduplicação.
    
    Attributes:
        fingerprint: Hash único do documento
        algorithm: Algoritmo utilizado (ex: 'sha256', 'simhash')
        document_id: ID do documento associado
        source_id: ID da fonte
        components: Componentes que compõem o fingerprint
        created_at: Timestamp de criação
    """
    fingerprint: str
    algorithm: str = "sha256"
    document_id: Optional[str] = None
    source_id: Optional[str] = None
    components: Dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DuplicateCheckResult:
    """Resultado da verificação de duplicatas.
    
    Attributes:
        is_duplicate: True se documento é duplicado
        existing_document_id: ID do documento existente (se duplicado)
        fingerprint: Fingerprint calculado
        confidence: Confiança da detecção (0.0 a 1.0)
        similarity_score: Score de similaridade (para detecção fuzzy)
    """
    is_duplicate: bool = False
    existing_document_id: Optional[str] = None
    fingerprint: Optional[str] = None
    confidence: float = 1.0
    similarity_score: Optional[float] = None


# =============================================================================
# Chunker Contracts
# =============================================================================

@dataclass
class Chunk:
    """Chunk de texto de um documento.
    
    Attributes:
        text: Texto do chunk
        index: Índice sequencial do chunk no documento
        token_count: Número de tokens
        char_count: Número de caracteres
        section_type: Tipo de seção (artigo, parágrafo, etc.)
        metadata: Metadados adicionais
        start_offset: Posição inicial no texto original
        end_offset: Posição final no texto original
    """
    text: str
    index: int
    token_count: int = 0
    char_count: int = 0
    section_type: Optional[SectionType] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    start_offset: int = 0
    end_offset: int = 0


@dataclass
class ChunkingResult:
    """Resultado da fase de chunking.
    
    Attributes:
        chunks: Chunks gerados
        document_id: ID do documento
        total_tokens: Total de tokens
        total_chars: Total de caracteres
        chunking_strategy: Estratégia utilizada
        duration_seconds: Duração da fase
    """
    chunks: List[Chunk] = field(default_factory=list)
    document_id: Optional[str] = None
    total_tokens: int = 0
    total_chars: int = 0
    chunking_strategy: str = "semantic"
    duration_seconds: float = 0.0


# =============================================================================
# Embedder Contracts
# =============================================================================

@dataclass
class EmbeddedChunk(Chunk):
    """Chunk com embedding vetorial.
    
    Attributes:
        embedding: Vetor de embeddings (384 dimensões)
        embedding_model: Modelo utilizado
        embedding_dimensions: Dimensionalidade do embedding
        embedded_at: Timestamp da geração
    """
    embedding: List[float] = field(default_factory=list)
    embedding_model: str = ""
    embedding_dimensions: int = 384
    embedded_at: Optional[datetime] = None


@dataclass
class EmbeddingResult:
    """Resultado da fase de embedding.
    
    Attributes:
        chunks: Chunks com embeddings
        document_id: ID do documento
        model: Modelo utilizado
        batch_size: Tamanho do batch
        total_embeddings: Total de embeddings gerados
        failed_embeddings: Embeddings que falharam
        duration_seconds: Duração da fase
        tokens_processed: Tokens processados
    """
    chunks: List[EmbeddedChunk] = field(default_factory=list)
    document_id: Optional[str] = None
    model: str = ""
    batch_size: int = 32
    total_embeddings: int = 0
    failed_embeddings: int = 0
    duration_seconds: float = 0.0
    tokens_processed: int = 0


# =============================================================================
# Indexer Contracts
# =============================================================================

@dataclass
class IndexDocument:
    """Documento pronto para indexação.
    
    Attributes:
        document_id: ID único do documento
        source_id: ID da fonte
        fingerprint: Fingerprint para dedup
        title: Título
        content: Conteúdo completo
        content_preview: Preview do conteúdo
        content_hash: Hash do conteúdo
        content_size_bytes: Tamanho em bytes
        metadata: Metadados estruturados
        url: URL de origem
        content_type: Tipo de conteúdo
        language: Idioma
        status: Status do documento
        version: Versão do documento
        chunks_count: Número de chunks
        embedding_model: Modelo de embedding utilizado
    """
    document_id: str
    source_id: str
    fingerprint: str
    title: Optional[str] = None
    content: Optional[str] = None
    content_preview: Optional[str] = None
    content_hash: Optional[str] = None
    content_size_bytes: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    url: Optional[str] = None
    content_type: Optional[str] = None
    language: str = "pt-BR"
    status: DocumentStatus = DocumentStatus.ACTIVE
    version: int = 1
    chunks_count: int = 0
    embedding_model: str = ""


@dataclass
class IndexChunk:
    """Chunk pronto para indexação no PostgreSQL.
    
    Attributes:
        id: ID único do chunk
        document_id: ID do documento pai
        chunk_index: Índice sequencial
        chunk_text: Texto do chunk
        token_count: Número de tokens
        char_count: Número de caracteres
        embedding: Vetor de embeddings (384 dimensões)
        embedding_model: Modelo utilizado
        section_type: Tipo de seção
        metadata: Metadados adicionais
    """
    id: str
    document_id: str
    chunk_index: int
    chunk_text: str
    token_count: int
    char_count: int
    embedding: List[float]
    embedding_model: str
    section_type: Optional[SectionType] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IndexingResult:
    """Resultado da fase de indexação.
    
    Attributes:
        document_id: ID do documento indexado
        postgres_success: Sucesso na indexação PostgreSQL
        elasticsearch_success: Sucesso na indexação Elasticsearch
        chunks_indexed: Número de chunks indexados
        errors: Erros encontrados
        duration_seconds: Duração da fase
        pg_duration_ms: Duração da indexação PG em ms
        es_duration_ms: Duração da indexação ES em ms
    """
    document_id: str
    postgres_success: bool = False
    elasticsearch_success: bool = False
    chunks_indexed: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0
    pg_duration_ms: int = 0
    es_duration_ms: int = 0


# =============================================================================
# Execution/Checkpoint Contracts
# =============================================================================

@dataclass
class ExecutionCheckpoint:
    """Checkpoint para resume de execução.
    
    Attributes:
        processed_count: Número de itens processados
        last_processed_url: Última URL processada
        last_processed_id: Último ID processado
        phase: Fase atual do pipeline
        stats: Estatísticas acumuladas
        timestamp: Timestamp do checkpoint
    """
    processed_count: int = 0
    last_processed_url: Optional[str] = None
    last_processed_id: Optional[str] = None
    phase: str = "discovery"
    stats: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ExecutionStats:
    """Estatísticas detalhadas de uma execução.
    
    Attributes:
        urls_discovered: URLs descobertas
        urls_new: URLs novas
        urls_updated: URLs atualizadas
        urls_skipped: URLs ignoradas
        urls_failed: URLs com falha
        documents_fetched: Documentos buscados
        documents_parsed: Documentos parseados
        documents_deduplicated: Documentos duplicados
        documents_indexed: Documentos indexados
        documents_failed: Documentos com falha
        chunks_created: Chunks criados
        embeddings_generated: Embeddings gerados
        bytes_processed: Bytes processados
        processing_time_ms: Tempo total em ms
        errors: Lista de erros
    """
    urls_discovered: int = 0
    urls_new: int = 0
    urls_updated: int = 0
    urls_skipped: int = 0
    urls_failed: int = 0
    documents_fetched: int = 0
    documents_parsed: int = 0
    documents_deduplicated: int = 0
    documents_indexed: int = 0
    documents_failed: int = 0
    chunks_created: int = 0
    embeddings_generated: int = 0
    bytes_processed: int = 0
    processing_time_ms: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)


# =============================================================================
# DLQ Contracts
# =============================================================================

@dataclass
class DLQMessage:
    """Mensagem na Dead Letter Queue.
    
    Attributes:
        id: ID único da mensagem
        source_id: ID da fonte
        run_id: ID da execução
        url: URL que falhou
        document_id: ID do documento (se aplicável)
        error_type: Tipo de erro
        error_message: Mensagem de erro
        error_traceback: Stack trace completo
        error_hash: Hash do erro para agrupamento
        payload: Payload original
        retry_count: Número de tentativas
        max_retries: Máximo de tentativas
        retry_strategy: Estratégia de retry
        next_retry_at: Próxima tentativa
        status: Status atual
        created_at: Timestamp de criação
        resolved_at: Timestamp de resolução
        resolved_by: Usuário que resolveu
        resolution_notes: Notas da resolução
    """
    id: str
    source_id: str
    url: str
    error_type: str
    error_message: str
    run_id: Optional[str] = None
    document_id: Optional[str] = None
    error_traceback: Optional[str] = None
    error_hash: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    max_retries: int = 5
    retry_strategy: str = "exponential_backoff"
    next_retry_at: Optional[datetime] = None
    status: str = "pending"
    created_at: datetime = field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    resolution_notes: Optional[str] = None


# =============================================================================
# Pipeline Result Contracts
# =============================================================================

@dataclass
class PipelinePhaseResult:
    """Resultado de uma fase do pipeline.
    
    Attributes:
        phase: Nome da fase
        success: Se a fase teve sucesso
        items_processed: Itens processados
        items_failed: Itens com falha
        errors: Erros encontrados
        duration_seconds: Duração da fase
    """
    phase: str
    success: bool = True
    items_processed: int = 0
    items_failed: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0


@dataclass
class PipelineResult:
    """Resultado completo do pipeline.
    
    Attributes:
        run_id: ID da execução
        source_id: ID da fonte
        status: Status final
        trigger: Tipo de trigger
        triggered_by: Quem acionou
        started_at: Início da execução
        completed_at: Fim da execução
        phase_results: Resultados de cada fase
        stats: Estatísticas consolidadas
        checkpoint: Checkpoint final
        errors: Erros gerais
    """
    run_id: str
    source_id: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    trigger: str = "scheduled"
    triggered_by: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    phase_results: List[PipelinePhaseResult] = field(default_factory=list)
    stats: ExecutionStats = field(default_factory=ExecutionStats)
    checkpoint: Optional[ExecutionCheckpoint] = None
    errors: List[Dict[str, Any]] = field(default_factory=list)
