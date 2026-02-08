"""Modelo SourceRegistry - Registro de fontes de dados do GABI.

Este módulo define o modelo de dados para o registro de fontes,
que serve como fonte única de verdade para as configurações de fontes
de dados do sistema (referenciando sources.yaml).

Baseado em GABI_SPECS_FINAL_v1.md Seção 2.7.1 (source_registry).
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from gabi.models.base import Base
from gabi.types import SensitivityLevel, SourceStatus, SourceType

if TYPE_CHECKING:
    from gabi.models.document import Document


class SourceRegistry(Base):
    """Modelo para registro de fontes de dados.
    
    Cada instância representa uma fonte de dados configurada no sources.yaml,
    mantendo estatísticas de ingestão, status de sincronização e metadados
    de governança.
    
    Attributes:
        id: Identificador único da fonte (ex: 'tcu_acordaos')
        name: Nome human-readable da fonte
        description: Descrição detalhada da fonte
        type: Tipo de fonte (api, web, file, crawler)
        status: Status atual da fonte (active, paused, error, disabled)
        config_hash: Hash da configuração para detecção de mudanças
        config_json: Configuração completa da fonte em JSON
        document_count: Número atual de documentos ativos
        total_documents_ingested: Total acumulado de documentos processados
        last_document_at: Timestamp do último documento ingerido
        last_sync_at: Timestamp da última tentativa de sync
        last_success_at: Timestamp do último sync bem-sucedido
        next_scheduled_sync: Próximo sync agendado
        consecutive_errors: Contador de erros consecutivos
        last_error_message: Última mensagem de erro
        last_error_at: Timestamp do último erro
        owner_email: Email do responsável pela fonte
        sensitivity: Nível de sensibilidade dos dados
        retention_days: Dias de retenção dos documentos
        created_at: Timestamp de criação do registro
        updated_at: Timestamp da última atualização
        deleted_at: Timestamp de soft delete (null se ativo)
    """
    
    __tablename__ = "source_registry"
    
    # ==========================================================================
    # Identificação
    # ==========================================================================
    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        comment="Identificador único da fonte (ex: 'tcu_acordaos')"
    )
    
    name: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="Nome human-readable da fonte"
    )
    
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Descrição detalhada da fonte"
    )
    
    # ==========================================================================
    # Tipo e Status
    # ==========================================================================
    type: Mapped[SourceType] = mapped_column(
        String,
        nullable=False,
        comment="Tipo de fonte (api, web, file, crawler)"
    )
    
    status: Mapped[SourceStatus] = mapped_column(
        String,
        nullable=False,
        default=SourceStatus.ACTIVE,
        comment="Status atual da fonte"
    )
    
    # ==========================================================================
    # Configuração
    # ==========================================================================
    config_hash: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="Hash SHA-256 da configuração para detecção de mudanças"
    )
    
    config_json: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Configuração completa da fonte serializada em JSON"
    )
    
    # ==========================================================================
    # Estatísticas de Documentos
    # ==========================================================================
    document_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Número atual de documentos ativos desta fonte"
    )
    
    total_documents_ingested: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Total acumulado de documentos processados (histórico)"
    )
    
    last_document_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
        comment="Timestamp do último documento ingerido com sucesso"
    )
    
    # ==========================================================================
    # Execução e Agendamento
    # ==========================================================================
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
        comment="Timestamp da última tentativa de sincronização"
    )
    
    last_success_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
        comment="Timestamp do último sync completado com sucesso"
    )
    
    next_scheduled_sync: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
        comment="Timestamp do próximo sync agendado"
    )
    
    # ==========================================================================
    # Error Tracking
    # ==========================================================================
    consecutive_errors: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Número de erros consecutivos na sincronização"
    )
    
    last_error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Mensagem do último erro ocorrido"
    )
    
    last_error_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
        comment="Timestamp do último erro"
    )
    
    # ==========================================================================
    # Governança
    # ==========================================================================
    owner_email: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="Email do responsável/proprietário da fonte"
    )
    
    sensitivity: Mapped[SensitivityLevel] = mapped_column(
        String,
        nullable=False,
        default=SensitivityLevel.INTERNAL,
        comment="Nível de sensibilidade dos dados da fonte"
    )
    
    retention_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=2555,  # ~7 anos
        comment="Dias de retenção para documentos desta fonte"
    )
    
    # ==========================================================================
    # Timestamps
    # ==========================================================================
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=datetime.now(timezone.utc),
        comment="Timestamp de criação do registro"
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=datetime.now(timezone.utc),
        comment="Timestamp da última atualização"
    )
    
    # ==========================================================================
    # Soft Delete (SoftDeleteMixin inline)
    # ==========================================================================
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
        comment="Timestamp de soft delete (null se registro ativo)"
    )
    
    deleted_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Motivo da exclusão"
    )
    
    deleted_by: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
        comment="Identificador de quem realizou o soft delete"
    )
    
    # ==========================================================================
    # Índices
    # ==========================================================================
    __table_args__ = (
        # Índice para busca de fontes ativas
        Index("idx_source_status", "status"),
        Index("idx_source_next_sync", "next_scheduled_sync"),
    )
    
    # ==========================================================================
    # Propriedades
    # ==========================================================================
    @property
    def is_deleted(self) -> bool:
        """Retorna True se o registro foi deletado (soft delete)."""
        return self.deleted_at is not None
    
    @property
    def is_active(self) -> bool:
        """Retorna True se a fonte está ativa e não foi deletada."""
        return self.status == SourceStatus.ACTIVE and not self.is_deleted
    
    @property
    def is_healthy(self) -> bool:
        """Retorna True se a fonte está saudável (ativa sem erros consecutivos)."""
        return (
            self.status == SourceStatus.ACTIVE
            and not self.is_deleted
            and self.consecutive_errors < 3
        )
    
    @property
    def success_rate(self) -> float:
        """Calcula a taxa de sucesso baseada em documentos processados."""
        if self.total_documents_ingested == 0:
            return 1.0
        return self.document_count / max(self.total_documents_ingested, 1)
    
    # ==========================================================================
    # Métodos
    # ==========================================================================
    def soft_delete(self, reason: Optional[str] = None, deleted_by: Optional[str] = None) -> None:
        """Soft delete with audit info.
        
        Args:
            reason: Motivo da exclusão
            deleted_by: Identificador de quem está deletando
        """
        self.deleted_at = datetime.now(timezone.utc)
        self.deleted_reason = reason
        self.deleted_by = deleted_by
        self.status = SourceStatus.DISABLED
    
    def restore(self) -> None:
        """Restore from soft delete."""
        self.deleted_at = None
        self.deleted_reason = None
        self.deleted_by = None
        self.status = SourceStatus.ACTIVE
    
    def record_success(self) -> None:
        """Registra uma sincronização bem-sucedida."""
        now = datetime.now(timezone.utc)
        self.last_sync_at = now
        self.last_success_at = now
        self.consecutive_errors = 0
        self.status = SourceStatus.ACTIVE
    
    def record_error(self, error_message: str) -> None:
        """Registra um erro de sincronização.
        
        Args:
            error_message: Mensagem descritiva do erro
        """
        now = datetime.now(timezone.utc)
        self.last_sync_at = now
        self.last_error_at = now
        self.last_error_message = error_message
        self.consecutive_errors += 1
        
        # Auto-pausa após 5 erros consecutivos
        if self.consecutive_errors >= 5:
            self.status = SourceStatus.ERROR
    
    def increment_document_count(self, count: int = 1) -> None:
        """Incrementa contadores de documentos.
        
        Args:
            count: Número de documentos a adicionar (default: 1)
        """
        self.document_count += count
        self.total_documents_ingested += count
        self.last_document_at = datetime.now(timezone.utc)
    
    # ==========================================================================
    # Relacionamentos
    # ==========================================================================
    # Nota: Relacionamento com Document removido temporariamente devido a
    # problemas de inicialização do mapper. Use queries diretas.
