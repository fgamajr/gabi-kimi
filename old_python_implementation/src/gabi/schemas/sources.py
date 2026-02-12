"""Source schemas for GABI API."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class SourceType(str, Enum):
    """Tipo de fonte de dados."""
    API = "api"
    WEB = "web"
    FILE = "file"
    CRAWLER = "crawler"


class SourceStatus(str, Enum):
    """Status da fonte."""
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    DISABLED = "disabled"


class SensitivityLevel(str, Enum):
    """Nível de sensibilidade dos dados."""
    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    CONFIDENTIAL = "confidential"


class SourceListItem(BaseModel):
    """Item de fonte na listagem."""
    id: str = Field(..., description="Identificador único da fonte")
    name: str = Field(..., description="Nome human-readable")
    description: Optional[str] = Field(None, description="Descrição detalhada")
    type: SourceType = Field(..., description="Tipo de fonte")
    status: SourceStatus = Field(..., description="Status atual")
    document_count: int = Field(..., description="Número de documentos ativos")
    total_documents_ingested: int = Field(..., description="Total histórico")
    last_success_at: Optional[datetime] = Field(None, description="Último sync bem-sucedido")
    next_scheduled_sync: Optional[datetime] = Field(None, description="Próximo sync agendado")
    consecutive_errors: int = Field(..., description="Erros consecutivos")
    is_healthy: bool = Field(..., description="Se está saudável")
    owner_email: str = Field(..., description="Email do responsável")
    sensitivity: SensitivityLevel = Field(..., description="Nível de sensibilidade")
    created_at: datetime = Field(..., description="Data de criação")
    updated_at: datetime = Field(..., description="Última atualização")


class SourceDetail(BaseModel):
    """Detalhe completo da fonte."""
    id: str = Field(..., description="Identificador único")
    name: str = Field(..., description="Nome")
    description: Optional[str] = Field(None, description="Descrição")
    type: SourceType = Field(..., description="Tipo")
    status: SourceStatus = Field(..., description="Status")
    config_hash: str = Field(..., description="Hash da configuração")
    config_json: Dict[str, Any] = Field(default_factory=dict, description="Configuração completa")
    document_count: int = Field(..., description="Documentos ativos")
    total_documents_ingested: int = Field(..., description="Total histórico")
    last_document_at: Optional[datetime] = Field(None, description="Último documento ingerido")
    last_sync_at: Optional[datetime] = Field(None, description="Última tentativa de sync")
    last_success_at: Optional[datetime] = Field(None, description="Último sucesso")
    next_scheduled_sync: Optional[datetime] = Field(None, description="Próximo agendado")
    consecutive_errors: int = Field(..., description="Erros consecutivos")
    last_error_message: Optional[str] = Field(None, description="Última mensagem de erro")
    last_error_at: Optional[datetime] = Field(None, description="Data do último erro")
    owner_email: str = Field(..., description="Responsável")
    sensitivity: SensitivityLevel = Field(..., description="Sensibilidade")
    retention_days: int = Field(..., description="Dias de retenção")
    created_at: datetime = Field(..., description="Criação")
    updated_at: datetime = Field(..., description="Atualização")


class SourceSyncRequest(BaseModel):
    """Request para sincronizar fonte."""
    mode: str = Field(default="incremental", description="Modo: incremental ou full")
    force: bool = Field(default=False, description="Força sync mesmo se já estiver atualizado")
    triggered_by: Optional[str] = Field(None, description="Quem iniciou o sync")


class SourceSyncResponse(BaseModel):
    """Resposta do sync da fonte."""
    success: bool = Field(..., description="Se o sync foi iniciado")
    source_id: str = Field(..., description="ID da fonte")
    run_id: Optional[str] = Field(None, description="ID da execução")
    message: str = Field(..., description="Mensagem")
    started_at: datetime = Field(default_factory=datetime.utcnow)


class SourceStatusResponse(BaseModel):
    """Resposta do status da fonte."""
    source_id: str = Field(..., description="ID da fonte")
    status: SourceStatus = Field(..., description="Status")
    is_healthy: bool = Field(..., description="Está saudável")
    document_count: int = Field(..., description="Documentos ativos")
    last_success_at: Optional[datetime] = Field(None, description="Último sucesso")
    next_scheduled_sync: Optional[datetime] = Field(None, description="Próximo agendado")
    consecutive_errors: int = Field(..., description="Erros consecutivos")
    success_rate: float = Field(..., description="Taxa de sucesso (0-1)")
    checked_at: datetime = Field(default_factory=datetime.utcnow)


class SourceStats(BaseModel):
    """Estatísticas da fonte."""
    total_documents: int = Field(..., description="Total de documentos")
    documents_by_status: Dict[str, int] = Field(default_factory=dict, description="Por status")
    documents_by_year: Optional[Dict[str, int]] = Field(None, description="Por ano")
    avg_content_size: Optional[float] = Field(None, description="Tamanho médio")
    total_chunks: int = Field(..., description="Total de chunks")


class SourceListResponse(BaseModel):
    """Resposta da listagem de fontes."""
    total: int = Field(..., description="Total de fontes")
    sources: List[SourceListItem] = Field(default_factory=list)


class SourceStatsResponse(BaseModel):
    """Resposta das estatísticas da fonte."""
    source_id: str = Field(..., description="ID da fonte")
    stats: SourceStats = Field(..., description="Estatísticas")
    computed_at: datetime = Field(default_factory=datetime.utcnow)
