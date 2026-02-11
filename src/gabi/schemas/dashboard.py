"""Schemas Pydantic para os endpoints do dashboard.

Define contratos tipados para todas as respostas do dashboard,
usando enums canônicos de gabi.types conforme CONTRACTS.md §7.1.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from gabi.types import (
    AuditEventType,
    AuditSeverity,
    PipelinePhase,
    SourceStatus,
    SourceType,
)


# ---------------------------------------------------------------------------
# GET /dashboard/stats
# ---------------------------------------------------------------------------

class DashboardSourceSummary(BaseModel):
    """Resumo de uma fonte para o dashboard."""

    id: str = Field(..., description="ID da fonte (ex: tcu_acordaos)")
    name: str = Field(..., description="Nome legível da fonte")
    description: Optional[str] = Field(None, description="Descrição da fonte")
    source_type: SourceType = Field(..., description="Tipo da fonte")
    status: SourceStatus = Field(..., description="Status operacional")
    enabled: bool = Field(..., description="Derivado: status != disabled")
    document_count: int = Field(..., ge=0, description="Documentos associados")
    last_sync_at: Optional[datetime] = Field(None, description="Última sincronização")
    last_success_at: Optional[datetime] = Field(None, description="Última sync bem-sucedida")
    consecutive_errors: int = Field(0, ge=0, description="Erros consecutivos")


class DashboardStatsResponse(BaseModel):
    """Resposta do endpoint /dashboard/stats.

    Alimenta: MetricCard (4 cards) + SourcesTable.
    """

    sources: List[DashboardSourceSummary] = Field(
        default_factory=list, description="Lista de fontes com resumo"
    )
    total_documents: int = Field(..., ge=0, description="Documentos ativos (não deletados)")
    total_chunks: int = Field(..., ge=0, description="Total de chunks")
    total_indexed: int = Field(..., ge=0, description="Documentos indexados no ES")
    total_embeddings: int = Field(
        ..., ge=0, description="Chunks com embedding gerado"
    )
    active_sources: int = Field(..., ge=0, description="Fontes com status active")
    documents_last_24h: int = Field(
        ..., ge=0, description="Documentos ingeridos nas últimas 24h"
    )
    dlq_pending: int = Field(
        ..., ge=0, description="Mensagens DLQ pendentes ou em retry"
    )
    elasticsearch_available: bool = Field(
        ..., description="ES está acessível"
    )
    total_elastic_docs: Optional[int] = Field(
        None, ge=0, description="Total de docs no ES (null se offline)"
    )
    generated_at: datetime = Field(
        ..., description="Timestamp de geração da resposta"
    )


# ---------------------------------------------------------------------------
# GET /dashboard/pipeline
# ---------------------------------------------------------------------------

class PipelineStageInfo(BaseModel):
    """Informação de um estágio do pipeline.

    O GABI possui 9 fases reais (PipelinePhase enum).
    O frontend pode agrupar como quiser para renderização.
    """

    name: PipelinePhase = Field(..., description="Fase do pipeline")
    label: str = Field(..., description="Rótulo legível (pt-BR)")
    description: str = Field(..., description="Descrição da fase")
    count: int = Field(..., ge=0, description="Documentos que completaram esta fase")
    total: int = Field(..., ge=0, description="Total de documentos no sistema")
    failed: int = Field(0, ge=0, description="Falhas nesta fase")
    status: Literal["active", "idle", "error"] = Field(
        ..., description="active=atividade<2h, error=>10% falhas, idle=c.c."
    )
    last_activity: Optional[datetime] = Field(
        None, description="Última atividade nesta fase"
    )


class DashboardPipelineResponse(BaseModel):
    """Resposta do endpoint /dashboard/pipeline.

    Alimenta: PipelineOverview — sempre 9 estágios, em ordem do pipeline.
    """

    stages: List[PipelineStageInfo] = Field(
        ..., min_length=9, max_length=9, description="9 fases do pipeline"
    )
    overall_status: Literal["healthy", "degraded", "stalled"] = Field(
        ..., description="healthy=ok, degraded=parcial, stalled=parado"
    )
    generated_at: datetime = Field(
        ..., description="Timestamp de geração da resposta"
    )


# ---------------------------------------------------------------------------
# GET /dashboard/activity
# ---------------------------------------------------------------------------

class ActivityEvent(BaseModel):
    """Evento de atividade derivado do audit_log.

    Cada evento mapeia para um registro de AuditLog, com description
    gerado a partir de event_type + action_details.
    """

    id: str = Field(..., description="UUID do registro no audit_log")
    timestamp: datetime = Field(..., description="Momento do evento")
    event_type: AuditEventType = Field(..., description="Tipo do evento")
    severity: AuditSeverity = Field(..., description="Severidade")
    source_id: Optional[str] = Field(
        None,
        description="ID da fonte associada (extraído de resource_id quando resource_type=source)",
    )
    description: str = Field(
        ..., description="Texto legível do evento (gerado pelo backend)"
    )
    details: Optional[Dict[str, Any]] = Field(
        None, description="action_details do audit_log"
    )
    run_id: Optional[str] = Field(
        None, description="correlation_id do audit_log (link para execução)"
    )


class DashboardActivityResponse(BaseModel):
    """Resposta do endpoint /dashboard/activity.

    Alimenta: ActivityFeed — eventos recentes ordenados por timestamp desc.
    """

    events: List[ActivityEvent] = Field(
        default_factory=list, description="Eventos de atividade"
    )
    total: int = Field(..., ge=0, description="Total de eventos (com filtros)")
    has_more: bool = Field(..., description="Há mais eventos além do limit")
    generated_at: datetime = Field(
        ..., description="Timestamp de geração da resposta"
    )


# ---------------------------------------------------------------------------
# GET /dashboard/health
# ---------------------------------------------------------------------------

class ComponentHealth(BaseModel):
    """Status de saúde de um componente de infraestrutura."""

    name: str = Field(..., description="postgresql, elasticsearch, redis, tei")
    status: Literal["online", "degraded", "offline"] = Field(
        ..., description="Status do componente"
    )
    latency_ms: Optional[float] = Field(
        None, ge=0, description="Latência do probe em ms"
    )
    version: Optional[str] = Field(None, description="Versão do componente")
    details: Dict[str, Any] = Field(
        default_factory=dict, description="Métricas específicas do componente"
    )


class DashboardHealthResponse(BaseModel):
    """Resposta do endpoint /dashboard/health.

    Alimenta: SystemHealth — status de PG, ES, Redis, TEI.
    """

    status: Literal["healthy", "degraded", "unhealthy"] = Field(
        ...,
        description="healthy=tudo ok, degraded=N-1, unhealthy=PG ou ES offline",
    )
    uptime_seconds: float = Field(..., ge=0, description="Uptime do processo Python")
    components: List[ComponentHealth] = Field(
        ..., description="Status de cada componente"
    )
    generated_at: datetime = Field(
        ..., description="Timestamp de geração da resposta"
    )


# ---------------------------------------------------------------------------
# POST /dashboard/trigger-ingestion
# ---------------------------------------------------------------------------

class TriggerIngestionResponse(BaseModel):
    """Resposta do endpoint POST /dashboard/trigger-ingestion."""

    message: str = Field(..., description="Mensagem descritiva")
    source_id: str = Field(..., description="ID da fonte")
    source_name: str = Field(..., description="Nome da fonte")
    status: Literal["queued", "already_running"] = Field(
        ..., description="Status da operação"
    )
    timestamp: datetime = Field(..., description="Momento do trigger")


__all__ = [
    "DashboardSourceSummary",
    "DashboardStatsResponse",
    "PipelineStageInfo",
    "DashboardPipelineResponse",
    "ActivityEvent",
    "DashboardActivityResponse",
    "ComponentHealth",
    "DashboardHealthResponse",
    "TriggerIngestionResponse",
]
