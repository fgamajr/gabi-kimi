"""Modelo ExecutionManifest para o GABI.

Este módulo define o modelo para tracking de execuções de ingestão,
com suporte a checkpoint para resume e estatísticas de processamento.
Baseado em GABI_SPECS_FINAL_v1.md Seção 2.7.1 (execution_manifests).
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID, uuid4

from sqlalchemy import ARRAY, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sqlalchemy import Index

from gabi.models.base import Base
from gabi.types import ExecutionStatus


# =============================================================================
# Modelo ExecutionManifest
# =============================================================================

class ExecutionManifest(Base):
    """Manifesto de execução de ingestão de dados.
    
    Registra todas as execuções de ingestão, incluindo status, estatísticas,
    checkpoint para resume, logs e informações de erro.
    
    Campos:
        run_id: UUID único da execução (chave primária)
        source_id: Referência para a fonte de dados
        status: Status atual da execução
        trigger: Tipo de gatilho ('scheduled', 'manual', 'api', 'retry')
        triggered_by: Identificador de quem iniciou (user_id ou 'system')
        started_at: Timestamp de início da execução
        completed_at: Timestamp de conclusão (None se em andamento)
        stats: Estatísticas JSONB (urls_discovered, documents_indexed, etc.)
        checkpoint: Dados de checkpoint para resume de execução
        duration_seconds: Duração total da execução em segundos
        error_message: Mensagem de erro (se houver falha)
        error_traceback: Stack trace completo do erro
        logs: Array de logs da execução
    """
    
    __tablename__ = "execution_manifests"
    
    # Identificação
    run_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_registry.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    # Status
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=ExecutionStatus.PENDING.value,
    )
    trigger: Mapped[str] = mapped_column(
        nullable=False,
    )
    triggered_by: Mapped[Optional[str]] = mapped_column(
        nullable=True,
    )
    
    # Timestamps
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Estatísticas JSONB
    stats: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    
    # Checkpoint para resume
    checkpoint: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    
    # Duração
    duration_seconds: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    
    # Error tracking
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    error_traceback: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Logs
    logs: Mapped[Optional[List[str]]] = mapped_column(
        ARRAY(Text),
        nullable=True,
    )
    
    # ==========================================================================
    # Índices
    # ==========================================================================
    __table_args__ = (
        # Índice para busca por fonte e ordenação por data
        Index("idx_executions_source", "source_id", "started_at"),
        # Índice parcial para execuções ativas (pending/running)
        Index("idx_executions_status", "status"),
        # Índice para ordenação por data de início
        Index("idx_executions_date", "started_at"),
    )
    
    # ==========================================================================
    # Inicialização
    # ==========================================================================
    def __init__(self, **kwargs):
        # Set defaults before calling super().__init__
        if 'status' not in kwargs:
            kwargs['status'] = ExecutionStatus.PENDING.value
        if 'stats' not in kwargs:
            kwargs['stats'] = {}
        super().__init__(**kwargs)
    
    def __repr__(self) -> str:
        # Handle both string and enum values
        status_val = self.status.value if hasattr(self.status, 'value') else self.status
        return (
            f"<ExecutionManifest("
            f"run_id={self.run_id}, "
            f"source_id={self.source_id}, "
            f"status={status_val}, "
            f"trigger={self.trigger}"
            f")>"
        )
    
    @property
    def is_active(self) -> bool:
        """Retorna True se a execução está em andamento."""
        return self.status in (ExecutionStatus.PENDING, ExecutionStatus.RUNNING)
    
    @property
    def is_success(self) -> bool:
        """Retorna True se a execução foi bem-sucedida."""
        return self.status in (ExecutionStatus.SUCCESS, ExecutionStatus.PARTIAL_SUCCESS)
    
    @property
    def has_error(self) -> bool:
        """Retorna True se a execução falhou ou foi cancelada."""
        return self.status in (ExecutionStatus.FAILED, ExecutionStatus.CANCELLED)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "ExecutionManifest",
]
