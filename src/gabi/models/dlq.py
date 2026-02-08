"""Modelo DLQ (Dead Letter Queue) para o GABI.

Este módulo define o modelo SQLAlchemy para mensagens da fila de morte,
responsável por armazenar falhas de processamento com retry exponencial.
Baseado em GABI_SPECS_FINAL_v1.md Seção 2.7.1 (dlq_messages).
"""

from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from gabi.models.base import Base
from gabi.types import DLQStatus


# =============================================================================
# Modelo DLQMessage
# =============================================================================

class DLQMessage(Base):
    """Mensagem da Dead Letter Queue.
    
    Armazena falhas de processamento do pipeline de ingestão,
    permitindo retry com exponential backoff e resolução manual.
    
    Campos:
        id: UUID único da mensagem (PK)
        source_id: FK para sources (CASCADE)
        run_id: FK para execution_manifests (SET NULL)
        url: URL que falhou no processamento
        document_id: ID do documento relacionado (se aplicável)
        error_type: Tipo/classificação do erro
        error_message: Mensagem de erro
        error_traceback: Stack trace completo
        error_hash: Hash para agrupar erros similares
        status: Status atual na DLQ
        retry_count: Quantidade de retries realizados
        max_retries: Máximo de retries permitidos
        retry_strategy: Estratégia de retry (exponential_backoff)
        next_retry_at: Timestamp do próximo retry agendado
        last_retry_at: Timestamp do último retry
        resolved_at: Timestamp da resolução
        resolved_by: Quem resolveu o problema
        resolution_notes: Notas sobre a resolução
        payload: Dados do contexto da falha (JSONB)
        created_at: Timestamp de criação
        updated_at: Timestamp de atualização
        archived_at: Timestamp de arquivamento
    """
    
    __tablename__ = "dlq_messages"
    
    # =======================================================================
    # Identificação
    # =======================================================================
    
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
        nullable=False,
    )
    
    source_id: Mapped[str] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    run_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("execution_manifests.run_id", ondelete="SET NULL"),
        nullable=True,
    )
    
    # =======================================================================
    # Identificação do Recurso
    # =======================================================================
    
    url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    
    document_id: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # =======================================================================
    # Informações de Erro
    # =======================================================================
    
    error_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    
    error_message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    
    error_traceback: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    error_hash: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # =======================================================================
    # Retry com Exponential Backoff
    # =======================================================================
    
    status: Mapped[str] = mapped_column(
        String(20),
        default=DLQStatus.PENDING.value,
        server_default=DLQStatus.PENDING.value,
        nullable=False,
    )
    
    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    
    max_retries: Mapped[int] = mapped_column(
        Integer,
        default=5,
        server_default="5",
        nullable=False,
    )
    
    retry_strategy: Mapped[str] = mapped_column(
        Text,
        default="exponential_backoff",
        server_default="exponential_backoff",
        nullable=False,
    )
    
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
    )
    
    last_retry_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
    )
    
    # =======================================================================
    # Resolução
    # =======================================================================
    
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
    )
    
    resolved_by: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    resolution_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # =======================================================================
    # Payload e Timestamps
    # =======================================================================
    
    payload: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=func.now(),
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
    )
    
    # =======================================================================
    # Índices Otimizados
    # =======================================================================
    
    __table_args__ = (
        # Índice para queries de retry pendentes
        Index(
            "idx_dlq_status_retry",
            "status",
            "next_retry_at",
            postgresql_where=status.in_([DLQStatus.PENDING, DLQStatus.RETRYING])
        ),
        
        # Índice para queries por fonte
        Index(
            "idx_dlq_source",
            "source_id",
            created_at.desc(),
        ),
        
        # Índice para agrupamento por hash de erro
        Index(
            "idx_dlq_error_hash",
            "error_hash",
            postgresql_where=error_hash.isnot(None)
        ),
        
        # Índice para limpeza de mensagens exhausted
        Index(
            "idx_dlq_created",
            "created_at",
            postgresql_where=status == DLQStatus.EXHAUSTED
        ),
        
        # Comentário da tabela
        {"comment": "Mensagens da Dead Letter Queue para falhas de processamento"}
    )
    
    # =======================================================================
    # Métodos
    # =======================================================================
    
    def __init__(self, **kwargs):
        """Inicializa DLQMessage com valores padrão."""
        # Aplicar defaults antes de passar para o pai
        if 'status' not in kwargs:
            kwargs['status'] = DLQStatus.PENDING
        if 'retry_count' not in kwargs:
            kwargs['retry_count'] = 0
        if 'max_retries' not in kwargs:
            kwargs['max_retries'] = 5
        if 'retry_strategy' not in kwargs:
            kwargs['retry_strategy'] = 'exponential_backoff'
        if 'payload' not in kwargs:
            kwargs['payload'] = {}
        super().__init__(**kwargs)
    
    def __repr__(self) -> str:
        return (
            f"<DLQMessage("
            f"id={self.id}, "
            f"source_id={self.source_id}, "
            f"status={self.status.value}, "
            f"retry_count={self.retry_count}/{self.max_retries}"
            f")>"
        )
    
    @property
    def can_retry(self) -> bool:
        """Verifica se a mensagem ainda pode ser reprocessada.
        
        Returns:
            True se retry_count < max_retries e status permitir retry
        """
        return (
            self.retry_count < self.max_retries
            and self.status in (DLQStatus.PENDING, DLQStatus.RETRYING)
        )
    
    @property
    def is_resolved(self) -> bool:
        """Verifica se a mensagem foi resolvida.
        
        Returns:
            True se status é RESOLVED ou ARCHIVED
        """
        return self.status in (DLQStatus.RESOLVED, DLQStatus.ARCHIVED)
    
    def schedule_next_retry(self, base_delay_seconds: int = 60) -> None:
        """Calcula e agenda o próximo retry com exponential backoff.
        
        Fórmula: delay = base_delay * (2 ^ retry_count)
        
        Args:
            base_delay_seconds: Delay base em segundos (padrão: 60s)
        """
        if not self.can_retry:
            self.status = DLQStatus.EXHAUSTED
            return
        
        # Exponential backoff: 60s, 120s, 240s, 480s, 960s...
        delay = base_delay_seconds * (2 ** self.retry_count)
        self.next_retry_at = datetime.now() + timedelta(seconds=delay)
        self.status = DLQStatus.RETRYING
    
    def mark_retry_attempt(self) -> None:
        """Registra uma tentativa de retry."""
        self.retry_count += 1
        self.last_retry_at = datetime.now()
        
        if self.retry_count >= self.max_retries:
            self.status = DLQStatus.EXHAUSTED
            self.next_retry_at = None
    
    def resolve(
        self,
        resolved_by: str,
        notes: Optional[str] = None
    ) -> None:
        """Marca a mensagem como resolvida manualmente.
        
        Args:
            resolved_by: Identificador de quem resolveu
            notes: Notas opcionais sobre a resolução
        """
        self.status = DLQStatus.RESOLVED
        self.resolved_at = datetime.now()
        self.resolved_by = resolved_by
        self.resolution_notes = notes
        self.next_retry_at = None
    
    def archive(self) -> None:
        """Arquiva a mensagem resolvida."""
        if self.status == DLQStatus.RESOLVED:
            self.status = DLQStatus.ARCHIVED
            self.archived_at = datetime.now()


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "DLQMessage",
]
