"""Tipos base e Enums do GABI.

Este módulo define todos os enums, tipos base e aliases de tipo utilizados
em todo o sistema. Baseado em CONTRACTS.md §1.

Example:
    >>> from gabi.types import Environment, SearchType, JsonDict
    >>> env = Environment.LOCAL
    >>> data: JsonDict = {"key": "value"}
"""

from enum import Enum, auto
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
from dataclasses import dataclass, field

from pydantic import SecretStr


# =============================================================================
# Type Aliases
# =============================================================================

JsonDict = Dict[str, Any]
"""Dicionário JSON genérico com valores de qualquer tipo."""

MetadataDict = Dict[str, Any]
"""Dicionário de metadados para documentos e chunks."""

FilterDict = Dict[str, Any]
"""Dicionário de filtros para queries."""

EmbeddingVector = List[float]
"""Vetor de embedding (lista de floats)."""

DocumentId = str
"""Identificador único de documento."""

SourceId = str
"""Identificador único de fonte de dados."""

ChunkId = Union[int, str]
"""Identificador de chunk (pode ser int ou str)."""

Score = float
"""Score de similaridade ou ranking."""

Timestamp = Union[datetime, str]
"""Timestamp que pode ser datetime ou string ISO."""


# =============================================================================
# Enums de Fontes
# =============================================================================

class SourceType(str, Enum):
    """Tipo de fonte de dados."""
    API = "api"
    WEB = "web"
    FILE = "file"
    CRAWLER = "crawler"
    URL_PATTERN = "url_pattern"
    STATIC_URL = "static_url"
    API_QUERY = "api_query"


class SourceStatus(str, Enum):
    """Status de uma fonte de dados."""
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    DISABLED = "disabled"


# =============================================================================
# Enums de Execução
# =============================================================================

class ExecutionStatus(str, Enum):
    """Status de execução do pipeline."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionTrigger(str, Enum):
    """Tipo de trigger para execução."""
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    API = "api"
    RETRY = "retry"


# =============================================================================
# Enums de Documentos
# =============================================================================

class DocumentStatus(str, Enum):
    """Status de um documento."""
    ACTIVE = "active"
    UPDATED = "updated"
    DELETED = "deleted"
    ERROR = "error"


class ContentType(str, Enum):
    """Tipos de conteúdo suportados."""
    PDF = "application/pdf"
    HTML = "text/html"
    CSV = "text/csv"
    JSON = "application/json"
    XML = "application/xml"
    TEXT = "text/plain"
    MARKDOWN = "text/markdown"


# =============================================================================
# Enums de Dead Letter Queue
# =============================================================================

class DLQStatus(str, Enum):
    """Status de uma mensagem na DLQ."""
    PENDING = "pending"
    RETRYING = "retrying"
    EXHAUSTED = "exhausted"
    RESOLVED = "resolved"
    ARCHIVED = "archived"


class RetryStrategy(str, Enum):
    """Estratégias de retry."""
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    FIXED_DELAY = "fixed_delay"
    LINEAR_BACKOFF = "linear_backoff"


# =============================================================================
# Enums de Governança e Segurança
# =============================================================================

class SensitivityLevel(str, Enum):
    """Nível de sensibilidade dos dados."""
    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    CONFIDENTIAL = "confidential"


class AuditEventType(str, Enum):
    """Tipos de eventos de auditoria."""
    # Documentos
    DOCUMENT_VIEWED = "document_viewed"
    DOCUMENT_SEARCHED = "document_searched"
    DOCUMENT_CREATED = "document_created"
    DOCUMENT_UPDATED = "document_updated"
    DOCUMENT_DELETED = "document_deleted"
    DOCUMENT_REINDEXED = "document_reindexed"
    
    # Sincronização
    SYNC_STARTED = "sync_started"
    SYNC_COMPLETED = "sync_completed"
    SYNC_FAILED = "sync_failed"
    SYNC_CANCELLED = "sync_cancelled"
    
    # Configuração e Segurança
    CONFIG_CHANGED = "config_changed"
    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    PERMISSION_CHANGED = "permission_changed"
    
    # Qualidade e DLQ
    DLQ_MESSAGE_CREATED = "dlq_message_created"
    DLQ_MESSAGE_RESOLVED = "dlq_message_resolved"
    QUALITY_CHECK_FAILED = "quality_check_failed"


class AuditSeverity(str, Enum):
    """Severidade de eventos de auditoria."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# =============================================================================
# Enums de Pipeline
# =============================================================================

class PipelinePhase(str, Enum):
    """Fases do pipeline de ingestão."""
    DISCOVERY = "discovery"
    CHANGE_DETECTION = "change_detection"
    FETCH = "fetch"
    PARSE = "parse"
    FINGERPRINT = "fingerprint"
    DEDUPLICATION = "deduplication"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"


class ChangeDetectionResult(str, Enum):
    """Resultado da detecção de mudanças."""
    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    ERROR = "error"


class SectionType(str, Enum):
    """Tipos de seção em documentos jurídicos."""
    EMENTA = "ementa"
    ARTIGO = "artigo"
    PARAGRAFO = "paragrafo"
    INCISO = "inciso"
    ALINEA = "alinea"
    ITEM = "item"
    ACORDAO = "acordao"
    VOTO = "voto"
    DECISAO = "decisao"
    RELATORIO = "relatorio"
    FUNDAMENTACAO = "fundamentacao"
    DISPOSITIVO = "dispositivo"
    GENERAL = "general"


# =============================================================================
# Enums de Busca
# =============================================================================

class SearchType(str, Enum):
    """Tipos de busca suportados."""
    TEXT = "text"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


# =============================================================================
# Enums de Ambiente
# =============================================================================

class Environment(str, Enum):
    """Ambientes de execução."""
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


# =============================================================================
# Enums de Lineage
# =============================================================================

class LineageNodeType(str, Enum):
    """Tipos de nós no grafo de lineage."""
    SOURCE = "source"
    TRANSFORM = "transform"
    DATASET = "dataset"
    DOCUMENT = "document"
    API = "api"


class LineageEdgeType(str, Enum):
    """Tipos de arestas no grafo de lineage."""
    PRODUCED = "produced"
    INPUT_TO = "input_to"
    OUTPUT_TO = "output_to"
    DERIVED_FROM = "derived_from"
    API_CALL = "api_call"


# =============================================================================
# Tipos de Dados Base
# =============================================================================

@dataclass
class Chunk:
    """Representa um chunk de texto."""
    text: str
    index: int
    token_count: int
    char_count: int
    section_type: Optional[SectionType] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EmbeddedChunk(Chunk):
    """Chunk com embedding vetorial."""
    embedding: List[float] = field(default_factory=list)
    embedding_model: str = ""
    embedded_at: Optional[datetime] = None


@dataclass
class ProcessingStats:
    """Estatísticas de processamento."""
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
