"""Admin schemas for GABI API."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from uuid import UUID


class ExecutionStatus(str, Enum):
    """Status da execução."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DLQStatus(str, Enum):
    """Status da mensagem DLQ."""
    PENDING = "pending"
    RETRYING = "retrying"
    EXHAUSTED = "exhausted"
    RESOLVED = "resolved"
    ARCHIVED = "archived"


class ExecutionStats(BaseModel):
    """Estatísticas de uma execução."""
    urls_discovered: Optional[int] = Field(None, description="URLs descobertas")
    documents_indexed: Optional[int] = Field(None, description="Documentos indexados")
    documents_updated: Optional[int] = Field(None, description="Documentos atualizados")
    documents_failed: Optional[int] = Field(None, description="Documentos com falha")
    chunks_created: Optional[int] = Field(None, description="Chunks criados")
    embeddings_generated: Optional[int] = Field(None, description="Embeddings gerados")
    bytes_processed: Optional[int] = Field(None, description="Bytes processados")
    duration_seconds: Optional[float] = Field(None, description="Duração")


class ExecutionListItem(BaseModel):
    """Item de execução na listagem."""
    run_id: UUID = Field(..., description="ID da execução")
    source_id: str = Field(..., description="ID da fonte")
    status: ExecutionStatus = Field(..., description="Status")
    trigger: str = Field(..., description="Gatilho (scheduled/manual/api/retry)")
    triggered_by: Optional[str] = Field(None, description="Quem iniciou")
    started_at: datetime = Field(..., description="Início")
    completed_at: Optional[datetime] = Field(None, description="Conclusão")
    duration_seconds: Optional[float] = Field(None, description="Duração")
    stats_summary: Optional[ExecutionStats] = Field(None, description="Resumo de stats")
    error_message: Optional[str] = Field(None, description="Mensagem de erro")


class ExecutionDetail(BaseModel):
    """Detalhe completo da execução."""
    run_id: UUID = Field(..., description="ID da execução")
    source_id: str = Field(..., description="ID da fonte")
    status: ExecutionStatus = Field(..., description="Status")
    trigger: str = Field(..., description="Gatilho")
    triggered_by: Optional[str] = Field(None, description="Quem iniciou")
    started_at: datetime = Field(..., description="Início")
    completed_at: Optional[datetime] = Field(None, description="Conclusão")
    duration_seconds: Optional[float] = Field(None, description="Duração")
    stats: ExecutionStats = Field(default_factory=ExecutionStats, description="Estatísticas")
    checkpoint: Optional[Dict[str, Any]] = Field(None, description="Checkpoint para resume")
    error_message: Optional[str] = Field(None, description="Mensagem de erro")
    error_traceback: Optional[str] = Field(None, description="Stack trace")
    logs: Optional[List[str]] = Field(None, description="Logs da execução")


class ExecutionListResponse(BaseModel):
    """Resposta da listagem de execuções."""
    total: int = Field(..., description="Total de execuções")
    page: int = Field(..., description="Página atual")
    page_size: int = Field(..., description="Tamanho da página")
    executions: List[ExecutionListItem] = Field(default_factory=list)


class DLQMessageItem(BaseModel):
    """Item de mensagem DLQ."""
    id: UUID = Field(..., description="ID da mensagem")
    source_id: str = Field(..., description="ID da fonte")
    run_id: Optional[UUID] = Field(None, description="ID da execução")
    url: str = Field(..., description="URL que falhou")
    document_id: Optional[str] = Field(None, description="ID do documento")
    error_type: str = Field(..., description="Tipo do erro")
    error_message: str = Field(..., description="Mensagem de erro")
    error_hash: Optional[str] = Field(None, description="Hash do erro")
    status: DLQStatus = Field(..., description="Status")
    retry_count: int = Field(..., description="Retries realizados")
    max_retries: int = Field(..., description="Máximo de retries")
    next_retry_at: Optional[datetime] = Field(None, description="Próximo retry")
    last_retry_at: Optional[datetime] = Field(None, description="Último retry")
    resolved_at: Optional[datetime] = Field(None, description="Data de resolução")
    resolved_by: Optional[str] = Field(None, description="Quem resolveu")
    created_at: datetime = Field(..., description="Criação")
    updated_at: datetime = Field(..., description="Atualização")


class DLQListResponse(BaseModel):
    """Resposta da listagem de DLQ."""
    total: int = Field(..., description="Total de mensagens")
    by_status: Dict[str, int] = Field(default_factory=dict, description="Por status")
    page: int = Field(..., description="Página atual")
    page_size: int = Field(..., description="Tamanho da página")
    messages: List[DLQMessageItem] = Field(default_factory=list)


class DLQRetryRequest(BaseModel):
    """Request para retry de DLQ."""
    force: bool = Field(default=False, description="Força retry mesmo se exhausted")
    priority: bool = Field(default=False, description="Alta prioridade")


class DLQRetryResponse(BaseModel):
    """Resposta do retry de DLQ."""
    success: bool = Field(..., description="Sucesso")
    message_id: UUID = Field(..., description="ID da mensagem")
    message: str = Field(..., description="Mensagem descritiva")
    retry_scheduled_at: Optional[datetime] = Field(None, description="Retry agendado para")
    retried_at: datetime = Field(default_factory=datetime.utcnow)


class DLQResolveRequest(BaseModel):
    """Request para resolver mensagem DLQ manualmente."""
    resolution_notes: Optional[str] = Field(None, description="Notas da resolução")
    resolved_by: str = Field(..., description="Quem está resolvendo")


class DLQResolveResponse(BaseModel):
    """Resposta da resolução de DLQ."""
    success: bool = Field(..., description="Sucesso")
    message_id: UUID = Field(..., description="ID da mensagem")
    message: str = Field(..., description="Mensagem")
    resolved_at: datetime = Field(default_factory=datetime.utcnow)


class SystemStats(BaseModel):
    """Estatísticas do sistema."""
    total_documents: int = Field(..., description="Total de documentos")
    total_sources: int = Field(..., description="Total de fontes")
    total_chunks: int = Field(..., description="Total de chunks")
    active_sources: int = Field(..., description="Fontes ativas")
    sources_in_error: int = Field(..., description="Fontes com erro")
    dlq_pending: int = Field(..., description="DLQ pendentes")
    dlq_exhausted: int = Field(..., description="DLQ exhausted")
    executions_today: int = Field(..., description="Execuções hoje")
    executions_failed_today: int = Field(..., description="Falhas hoje")


class SystemStatsResponse(BaseModel):
    """Resposta das estatísticas do sistema."""
    stats: SystemStats = Field(..., description="Estatísticas")
    computed_at: datetime = Field(default_factory=datetime.utcnow)
