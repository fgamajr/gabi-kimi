"""Extended schemas for dashboard control panel.

These schemas supplement the existing dashboard.py schemas
for the frontend control panel requirements.

New endpoints covered:
- GET /dashboard/pipeline/summary (4-stage view)
- GET /dashboard/jobs (sync jobs by year, ES indexes)
- GET /dashboard/pipeline/state
- POST /dashboard/pipeline/{phase}/start
- POST /dashboard/pipeline/{phase}/stop
- POST /dashboard/pipeline/{phase}/restart
- POST /dashboard/pipeline/bulk-control
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# =============================================================================
# GET /dashboard/pipeline/summary (4-stage view for frontend)
# =============================================================================

class PipelineSummaryStage(BaseModel):
    """One of the 4 frontend-facing pipeline stages.
    
    Maps backend phases:
    - harvest: discovery + change_detection
    - sync: fetch + parse + fingerprint
    - ingest: deduplication + chunking + embedding
    - index: indexing
    """
    name: Literal["harvest", "sync", "ingest", "index"] = Field(
        ..., description="Stage identifier"
    )
    label: str = Field(..., description="Rótulo em português")
    description: str = Field(..., description="Descrição da etapa")
    count: int = Field(..., ge=0, description="Documentos na etapa")
    total: int = Field(..., ge=0, description="Total de documentos")
    progress_pct: float = Field(
        ..., ge=0.0, le=100.0, description="Porcentagem de progresso"
    )
    status: Literal["active", "idle", "error", "paused"] = Field(
        ..., description="Status da etapa"
    )
    last_activity: Optional[datetime] = Field(
        None, description="Última atividade nesta etapa"
    )
    substages: List[str] = Field(
        default_factory=list,
        description="Fases do backend incluídas nesta etapa"
    )


class PipelineSummaryResponse(BaseModel):
    """4-stage pipeline summary for frontend dashboard."""
    stages: List[PipelineSummaryStage] = Field(
        ..., min_length=4, max_length=4, description="4 etapas do pipeline"
    )
    overall_status: Literal["healthy", "degraded", "stalled", "paused"] = Field(
        ..., description="Status geral do pipeline"
    )
    active_source_count: int = Field(
        ..., ge=0, description="Fontes em processamento ativo"
    )
    queued_source_count: int = Field(
        ..., ge=0, description="Fontes na fila"
    )
    generated_at: datetime = Field(
        ..., description="Timestamp de geração da resposta"
    )


# =============================================================================
# GET /dashboard/jobs (Sync jobs and Elasticsearch indexes)
# =============================================================================

class SyncJobStatus(str, Enum):
    """Status of a synchronization job."""
    SYNCED = "synced"
    PENDING = "pending"
    FAILED = "failed"
    IN_PROGRESS = "in_progress"
    NOT_STARTED = "not_started"


class SyncJob(BaseModel):
    """Represents a synchronization job for a specific year."""
    source_id: str = Field(..., description="ID da fonte")
    source_name: str = Field(..., description="Nome legível da fonte")
    year: int = Field(..., description="Ano (ex: 2024)")
    status: SyncJobStatus = Field(..., description="Status da sincronização")
    document_count: int = Field(
        ..., ge=0, description="Documentos para este ano"
    )
    updated_at: Optional[datetime] = Field(
        None, description="Última atualização"
    )
    started_at: Optional[datetime] = Field(
        None, description="Quando a sync começou"
    )
    completed_at: Optional[datetime] = Field(
        None, description="Quando a sync terminou"
    )
    error_message: Optional[str] = Field(
        None, description="Mensagem de erro se falhou"
    )


class ElasticIndexHealth(str, Enum):
    """Elasticsearch index health status."""
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class ElasticIndexInfo(BaseModel):
    """Information about an Elasticsearch index."""
    name: str = Field(..., description="Nome do índice")
    alias: Optional[str] = Field(
        None, description="Alias do índice"
    )
    document_count: int = Field(
        ..., ge=0, description="Número de documentos"
    )
    size_bytes: int = Field(
        ..., ge=0, description="Tamanho do índice em bytes"
    )
    health: ElasticIndexHealth = Field(
        ..., description="Saúde do índice"
    )
    created_at: Optional[datetime] = Field(
        None, description="Data de criação do índice"
    )


class JobsResponse(BaseModel):
    """Response for jobs endpoint."""
    sync_jobs: List[SyncJob] = Field(
        default_factory=list, description="Sync jobs por ano"
    )
    elastic_indexes: List[ElasticIndexInfo] = Field(
        default_factory=list, description="Informações dos índices ES"
    )
    total_elastic_docs: int = Field(
        ..., ge=0, description="Total de documentos em todos os índices"
    )
    years_available: List[int] = Field(
        default_factory=list, description="Anos com dados disponíveis"
    )
    generated_at: datetime = Field(
        ..., description="Timestamp de geração"
    )


# =============================================================================
# Pipeline Control Schemas
# =============================================================================

class PipelineState(BaseModel):
    """Current state of the pipeline processing."""
    is_running: bool = Field(..., description="Se o pipeline está rodando")
    current_phase: Optional[str] = Field(
        None, description="Fase atual em execução"
    )
    active_sources: List[str] = Field(
        default_factory=list, description="Fontes em processamento"
    )
    queued_sources: List[str] = Field(
        default_factory=list, description="Fontes na fila"
    )
    paused_phases: List[str] = Field(
        default_factory=list, description="Fases pausadas"
    )
    rate_limit_docs_per_min: int = Field(
        default=0, ge=0, description="Limite de documentos por minuto"
    )


class PipelineStateResponse(BaseModel):
    """Response for pipeline state endpoint."""
    state: PipelineState
    generated_at: datetime


# Start Phase
class StartPhaseRequest(BaseModel):
    """Request to start a pipeline phase."""
    source_ids: Optional[List[str]] = Field(
        None, description="Fontes específicas (null = todas)"
    )
    resume_from: Optional[str] = Field(
        None, description="Run ID para resumir execução"
    )
    priority: Literal["normal", "high"] = Field(
        default="normal", description="Prioridade da execução"
    )
    rate_limit: Optional[int] = Field(
        None, ge=1, le=10000, description="Máximo de docs por minuto"
    )


class StartPhaseResponse(BaseModel):
    """Response from starting a phase."""
    success: bool
    run_id: Optional[str] = Field(None, description="ID da execução")
    phase: str = Field(..., description="Fase iniciada")
    sources_affected: List[str] = Field(
        default_factory=list, description="Fontes afetadas"
    )
    estimated_completion: Optional[datetime] = Field(
        None, description="Estimativa de término"
    )
    message: str
    started_at: datetime


# Stop Phase
class StopPhaseRequest(BaseModel):
    """Request to stop a pipeline phase."""
    graceful: bool = Field(
        default=True, description="Aguardar itens atuais"
    )
    timeout_seconds: int = Field(
        default=60, ge=0, le=300, description="Tempo máximo de espera"
    )
    reason: Optional[str] = Field(
        None, description="Motivo da parada"
    )


class StopPhaseResponse(BaseModel):
    """Response from stopping a phase."""
    success: bool
    phase: str = Field(..., description="Fase parada")
    items_in_progress: int = Field(
        ..., ge=0, description="Itens em processamento"
    )
    items_queued: int = Field(
        ..., ge=0, description="Itens restantes na fila"
    )
    stopped_at: datetime
    message: str


# Restart Phase
class RestartPhaseRequest(BaseModel):
    """Request to restart a pipeline phase."""
    source_ids: Optional[List[str]] = Field(
        None, description="Fontes específicas"
    )
    clear_errors: bool = Field(
        default=False, description="Limpar erros anteriores"
    )
    full_reprocess: bool = Field(
        default=False, description="Reprocessar todos os documentos"
    )
    reason: Optional[str] = Field(
        None, description="Motivo do restart"
    )


class RestartPhaseResponse(BaseModel):
    """Response from restarting a phase."""
    success: bool
    run_id: str = Field(..., description="ID da nova execução")
    phase: str = Field(..., description="Fase reiniciada")
    sources_affected: List[str] = Field(
        default_factory=list, description="Fontes afetadas"
    )
    cleared_errors: int = Field(
        ..., ge=0, description="Erros limpos (se clear_errors=true)"
    )
    message: str
    restarted_at: datetime


# Bulk Control
class BulkControlAction(str, Enum):
    """Available bulk control actions."""
    PAUSE_ALL = "pause_all"
    RESUME_ALL = "resume_all"
    STOP_ALL = "stop_all"
    RESTART_FAILED = "restart_failed"


class BulkControlRequest(BaseModel):
    """Request for bulk pipeline control."""
    action: BulkControlAction = Field(
        ..., description="Ação a executar"
    )
    source_ids: Optional[List[str]] = Field(
        None, description="Fontes específicas (null = todas)"
    )


class BulkControlResponse(BaseModel):
    """Response from bulk control operation."""
    success: bool
    action: BulkControlAction
    affected_phases: List[str] = Field(
        default_factory=list, description="Fases afetadas"
    )
    affected_sources: List[str] = Field(
        default_factory=list, description="Fontes afetadas"
    )
    message: str
    executed_at: datetime


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Pipeline Summary (4-stage)
    "PipelineSummaryStage",
    "PipelineSummaryResponse",
    # Jobs
    "SyncJobStatus",
    "SyncJob",
    "ElasticIndexHealth",
    "ElasticIndexInfo",
    "JobsResponse",
    # Pipeline Control
    "PipelineState",
    "PipelineStateResponse",
    "StartPhaseRequest",
    "StartPhaseResponse",
    "StopPhaseRequest",
    "StopPhaseResponse",
    "RestartPhaseRequest",
    "RestartPhaseResponse",
    "BulkControlAction",
    "BulkControlRequest",
    "BulkControlResponse",
]
