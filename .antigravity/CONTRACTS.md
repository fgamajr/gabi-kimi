# CONTRACTS.md — Contratos de Interface entre Módulos

**Status:** BINDING — Todos os agentes DEVEM usar estes tipos.  
**Regra:** Nenhum worker pode inventar estruturas de dados próprias. Se precisar de um tipo que não existe aqui, PARE e solicite ao coordenador.

---

## 1. Tipos Primitivos Compartilhados

```python
# src/gabi/types.py
"""Tipos compartilhados por todos os módulos. IMUTÁVEL após Gate 0."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# === Enums canônicos (espelham os ENUMs do PostgreSQL) ===

class SourceType(str, Enum):
    API = "api"
    WEB = "web"
    FILE = "file"
    CRAWLER = "crawler"

class SourceStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    DISABLED = "disabled"

class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    CANCELLED = "cancelled"

class DocumentStatus(str, Enum):
    ACTIVE = "active"
    UPDATED = "updated"
    DELETED = "deleted"
    ERROR = "error"

class DLQStatus(str, Enum):
    PENDING = "pending"
    RETRYING = "retrying"
    EXHAUSTED = "exhausted"
    RESOLVED = "resolved"
    ARCHIVED = "archived"

class SensitivityLevel(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    CONFIDENTIAL = "confidential"

class SearchType(str, Enum):
    TEXT = "text"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"
```

---

## 2. Contratos do Pipeline (fluxo Discovery → Index)

Cada fase do pipeline recebe uma estrutura e produz outra. Os tipos abaixo definem essas fronteiras com exatidão.

### 2.1 Discovery → Change Detection

```python
# src/gabi/pipeline/contracts.py

class DiscoveredURL(BaseModel):
    """Produzido por: DiscoveryEngine. Consumido por: ChangeDetector."""
    url: str
    source_id: str
    discovery_mode: str  # "url_pattern", "static_url", "crawler", "api_query"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # metadata pode conter: year, page_number, link_text, etc.

class DiscoveryResult(BaseModel):
    """Retorno do DiscoveryEngine.discover()."""
    source_id: str
    urls: List[DiscoveredURL]
    total_discovered: int
    errors: List[str] = Field(default_factory=list)
```

### 2.2 Change Detection → Fetcher

```python
class ChangeDetectionVerdict(BaseModel):
    """Produzido por: ChangeDetector. Consumido por: Fetcher."""
    url: str
    source_id: str
    changed: bool
    reason: str  # "new", "etag_changed", "last_modified_changed", "content_hash_changed", "forced", "unknown"
    cached_etag: Optional[str] = None
    cached_last_modified: Optional[str] = None
    cached_content_hash: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ChangeDetectionBatch(BaseModel):
    """Retorno do ChangeDetector.check_batch()."""
    to_process: List[ChangeDetectionVerdict]   # changed=True
    skipped: List[ChangeDetectionVerdict]       # changed=False
    errors: List[Dict[str, str]] = Field(default_factory=list)
```

### 2.3 Fetcher → Parser

```python
class FetchedContent(BaseModel):
    """Produzido por: Fetcher. Consumido por: Parser."""
    url: str
    source_id: str
    raw_bytes: bytes = Field(exclude=True)  # Conteúdo bruto (não serializado em JSON)
    content_type: str  # "text/csv", "application/pdf", "text/html"
    detected_format: str  # "csv", "pdf", "html" (via magic bytes)
    encoding: str = "utf-8"
    size_bytes: int
    http_status: int
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    content_hash: str  # SHA256 do raw_bytes
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True
```

### 2.4 Parser → Fingerprinter

```python
class ParsedDocument(BaseModel):
    """Produzido por: Parser. Consumido por: Fingerprinter.
    
    Este é o tipo CANÔNICO de documento no pipeline.
    Todos os campos de mapping do sources.yaml são resolvidos aqui.
    """
    # Identificação
    document_id: str              # Gerado via mapping.document_id ou document_id_template
    source_id: str
    url: Optional[str] = None
    
    # Conteúdo principal
    title: Optional[str] = None
    content: str                  # Texto completo normalizado
    content_preview: Optional[str] = None  # Primeiros 500 chars de content
    
    # Metadados estruturados (campos do mapping que não são content)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # Exemplos: year, number, type, colegiado, relator, date, 
    # process, situacao, assunto, ementa, vigente
    
    # Campos de texto completo separados (fontes com múltiplos campos de texto)
    text_fields: Dict[str, str] = Field(default_factory=dict)
    # Exemplos: text_relatorio, text_voto, text_acordao, text_decisao,
    # text_enunciado, text_excerto, text_norma
    
    # Técnicos
    content_type: str = "text/plain"
    language: str = "pt-BR"
    content_size_bytes: Optional[int] = None


class ParseResult(BaseModel):
    """Retorno do Parser.parse()."""
    documents: List[ParsedDocument]
    source_url: str
    parse_errors: List[str] = Field(default_factory=list)
```

### 2.5 Fingerprinter → Deduplicator

```python
class FingerprintedDocument(ParsedDocument):
    """Produzido por: Fingerprinter. Consumido por: Deduplicator.
    
    Herda ParsedDocument e adiciona campos de fingerprint.
    """
    fingerprint: str              # SHA256 hex, 64 chars
    fingerprint_algorithm: str = "sha256"
    content_hash: str             # SHA256 do content completo
```

### 2.6 Deduplicator → Chunker

```python
class DeduplicationVerdict(BaseModel):
    """Produzido por: Deduplicator."""
    document_id: str
    fingerprint: str
    is_duplicate: bool
    existing_version: Optional[int] = None
    action: str  # "index_new", "update_existing", "skip_identical"

# O Chunker recebe diretamente o FingerprintedDocument (somente os não-duplicados).
# O Deduplicator filtra, não transforma.
```

### 2.7 Chunker → Embedder

```python
class Chunk(BaseModel):
    """Produzido por: Chunker. Consumido por: Embedder e Indexer."""
    chunk_index: int
    chunk_text: str
    token_count: int
    char_count: int
    section_type: Optional[str] = None  # "artigo", "paragrafo", "ementa", "voto", etc.
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChunkingResult(BaseModel):
    """Retorno do Chunker.chunk()."""
    document_id: str
    chunks: List[Chunk]
    total_chunks: int
    total_tokens: int
    chunking_strategy: str  # "legal_hierarchical", "whole_document", "semantic_section"
```

### 2.8 Embedder → Indexer

```python
class EmbeddedChunk(Chunk):
    """Produzido por: Embedder. Consumido por: Indexer.
    
    Herda Chunk e adiciona embedding.
    """
    embedding: List[float]        # Exatamente 384 floats. IMUTÁVEL.
    embedding_model: str          # "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedded_at: datetime


class EmbeddingResult(BaseModel):
    """Retorno do Embedder.embed_batch()."""
    document_id: str
    chunks: List[EmbeddedChunk]
    total_embeddings: int
    embedding_dimensions: int = 384  # IMUTÁVEL
    processing_time_ms: float
```

### 2.9 Indexer (entrada e saída)

```python
class IndexingInput(BaseModel):
    """Entrada consolidada para o Indexer."""
    document: FingerprintedDocument
    chunks: List[EmbeddedChunk]
    source_id: str
    run_id: str


class IndexingResult(BaseModel):
    """Retorno do Indexer.index()."""
    document_id: str
    pg_indexed: bool
    es_indexed: bool
    chunks_indexed: int
    version: int
    errors: List[str] = Field(default_factory=list)
```

---

## 3. Contratos da API REST

### 3.1 Request Schemas

```python
# src/gabi/schemas/search.py

class SearchFilters(BaseModel):
    source_id: Optional[str] = None
    year: Optional[int] = None
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    type: Optional[str] = None
    relator: Optional[str] = None
    colegiado: Optional[str] = None

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)
    search_type: SearchType = SearchType.HYBRID
    limit: int = Field(default=10, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    filters: Optional[SearchFilters] = None
    highlight: bool = True
```

### 3.2 Response Schemas

```python
class SearchResultItem(BaseModel):
    document_id: str
    title: Optional[str]
    snippet: str
    source_id: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    score: float
    rank_bm25: Optional[int] = None
    rank_vector: Optional[int] = None
    match_sources: List[str]  # ["bm25"], ["vector"], ou ambos
    highlights: Dict[str, List[str]] = Field(default_factory=dict)

class SearchResponse(BaseModel):
    results: List[SearchResultItem]
    total: int
    query: str
    search_type: SearchType
    took_ms: Optional[float] = None
```

```python
# src/gabi/schemas/document.py

class DocumentResponse(BaseModel):
    document_id: str
    title: Optional[str]
    content_preview: Optional[str]
    metadata: Dict[str, Any]
    url: Optional[str]
    source_id: str
    status: DocumentStatus
    version: int
    ingested_at: datetime
    updated_at: datetime

class DocumentChunkResponse(BaseModel):
    chunk_index: int
    chunk_text: str
    token_count: int
    section_type: Optional[str]
    metadata: Dict[str, Any]
```

```python
# src/gabi/schemas/source.py

class SourceResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    type: SourceType
    status: SourceStatus
    document_count: int
    last_sync_at: Optional[datetime]
    last_success_at: Optional[datetime]
    next_scheduled_sync: Optional[datetime]
    consecutive_errors: int
    sensitivity: SensitivityLevel
```

```python
# src/gabi/schemas/health.py

class ServiceHealth(BaseModel):
    status: str  # "healthy", "degraded", "unhealthy"
    latency_ms: Optional[float] = None
    error: Optional[str] = None

class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    services: Dict[str, ServiceHealth]
```

```python
# src/gabi/schemas/admin.py

class ExecutionResponse(BaseModel):
    run_id: UUID
    source_id: str
    status: ExecutionStatus
    trigger: str
    triggered_by: Optional[str]
    started_at: datetime
    completed_at: Optional[datetime]
    duration_seconds: Optional[float]
    stats: Dict[str, Any]

class DLQMessageResponse(BaseModel):
    id: UUID
    source_id: str
    url: str
    error_type: str
    error_message: str
    status: DLQStatus
    retry_count: int
    max_retries: int
    next_retry_at: Optional[datetime]
    created_at: datetime

class SyncTriggerRequest(BaseModel):
    force: bool = False

class DLQResolveRequest(BaseModel):
    resolution_notes: str = Field(..., min_length=5)
```

---

## 4. Contratos Internos

### 4.1 EmbeddingService ↔ TEI

```python
class TEIRequest(BaseModel):
    inputs: List[str]  # Max 32 textos por batch

class TEIResponse(BaseModel):
    embeddings: List[List[float]]  # Cada inner list: 384 floats
```

### 4.2 QualityEngine

```python
class QualityCheckResult(BaseModel):
    valid: bool
    score: int = Field(ge=0, le=100)
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    checked_rules: int
    passed_rules: int
```

### 4.3 AuditLogger

```python
class AuditEntry(BaseModel):
    event_type: str
    severity: str = "info"
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    resource_type: str
    resource_id: Optional[str] = None
    action_details: Dict[str, Any] = Field(default_factory=dict)
    before_state: Optional[Dict[str, Any]] = None
    after_state: Optional[Dict[str, Any]] = None
    request_id: Optional[str] = None
    correlation_id: Optional[str] = None
```

### 4.4 DLQ Entry

```python
class DLQEntry(BaseModel):
    source_id: str
    run_id: str
    url: str
    document_id: Optional[str] = None
    error_type: str  # "fetch_error", "parse_error", "fingerprint_error", "index_error", "quality_error"
    error_message: str
    error_traceback: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
```

---

## 5. Contrato do sources.yaml

```python
# src/gabi/pipeline/source_config.py

class DiscoveryConfig(BaseModel):
    mode: str  # "url_pattern", "static_url", "crawler", "api_query"
    url_template: Optional[str] = None
    url: Optional[str] = None
    root_url: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    change_detection: Optional[Dict[str, str]] = None
    rules: Optional[Dict[str, Any]] = None
    driver: Optional[str] = None

class FetchConfig(BaseModel):
    protocol: str = "https"
    method: str = "GET"
    output: Dict[str, Any]

class ParseConfig(BaseModel):
    input_format: str  # "csv", "pdf", "html"
    strategy: str = "row_to_document"
    tool: Optional[str] = None
    rules: Optional[Dict[str, Any]] = None

class LifecycleConfig(BaseModel):
    sync: Dict[str, Any]
    resync: Optional[Dict[str, Any]] = None
    purge: Optional[Dict[str, Any]] = None
    validation: Optional[Dict[str, Any]] = None

class IndexingConfig(BaseModel):
    enabled: bool = True
    strategy: str = "hybrid"
    fields: Optional[List[str]] = None

class EmbeddingConfig(BaseModel):
    enabled: bool = True
    chunking: Optional[Dict[str, Any]] = None

class SourceMetadata(BaseModel):
    domain: str
    jurisdiction: str = "BR"
    authority: str
    document_type: str
    canonical_type: str
    description: Optional[str] = None

class SourceConfig(BaseModel):
    """Schema completo de uma fonte no sources.yaml."""
    enabled: bool = True
    metadata: SourceMetadata
    discovery: DiscoveryConfig
    fetch: FetchConfig
    parse: ParseConfig
    mapping: Dict[str, Any]
    lifecycle: LifecycleConfig
    indexing: IndexingConfig = IndexingConfig()
    embedding: EmbeddingConfig = EmbeddingConfig()
```

---

## 6. Transforms Disponíveis

```python
# src/gabi/pipeline/transforms.py
# Assinatura: (value: str) -> str
# Se valor de entrada for None, a transform NÃO é chamada.

AVAILABLE_TRANSFORMS = {
    "strip_quotes",
    "strip_quotes_and_html",
    "strip_html",
    "to_integer",
    "to_float",
    "to_date",
    "normalize_whitespace",
    "uppercase",
    "lowercase",
    "url_to_slug",
}
```

---

## 7. Regras de Uso

1. **Importação obrigatória:** Todo módulo que manipula dados do pipeline DEVE importar de `gabi.pipeline.contracts` ou `gabi.types`.
2. **Extensão proibida:** Nenhum worker pode adicionar campos sem aprovação do coordenador. Dados extras vão no campo `metadata`.
3. **Serialização:** Usar `.model_dump()` e `.model_dump_json()` para logging e persistência.
4. **Validação no boundary:** Cada componente DEVE validar input com o tipo esperado. Falhas de validação vão para a DLQ.
5. **Imutabilidade:** Após criar instância, não modificar atributos. Criar nova instância se necessário.
