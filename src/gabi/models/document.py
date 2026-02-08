"""Modelo Document para o GABI.

Este módulo define o modelo SQLAlchemy para documentos jurídicos,
implementando soft delete, fingerprint canônico (SHA-256) e
sincronização com Elasticsearch.

Baseado em GABI_SPECS_FINAL_v1.md Seção 2.7.1 (documents).
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gabi.models.base import Base
from gabi.types import DocumentStatus

if TYPE_CHECKING:
    from gabi.models.source import SourceRegistry


class Document(Base):
    """Modelo de documento jurídico.
    
    Representa um documento processado pelo pipeline de ingestão,
    com suporte a soft delete e sincronização cross-store (PG + ES).
    
    Attributes:
        id: UUID interno (PK)
        document_id: Identificador externo único
        source_id: FK para sources
        fingerprint: Hash canônico SHA-256 do conteúdo
        title: Título do documento
        content_preview: Preview do conteúdo (primeiros N caracteres)
        metadata: Metadados extensíveis em JSONB
        status: Status do documento (active, updated, deleted, error)
        is_deleted: Flag de soft delete
        es_indexed: Flag de sincronização com Elasticsearch
        chunks_count: Quantidade de chunks associados
    """
    
    __tablename__ = "documents"
    
    # ========================================================================
    # Identificadores
    # ========================================================================
    
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
        comment="UUID interno do documento (PK)"
    )
    
    document_id: Mapped[str] = mapped_column(
        String,
        unique=True,
        nullable=False,
        index=True,
        comment="Identificador externo único do documento"
    )
    
    source_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("source_registry.id", ondelete="CASCADE"),
        nullable=False,
        comment="FK para fonte de origem"
    )
    
    # ========================================================================
    # Conteúdo e Fingerprint
    # ========================================================================
    
    fingerprint: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="Fingerprint canônico SHA-256 do conteúdo"
    )
    
    fingerprint_algorithm: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="sha256",
        comment="Algoritmo usado para o fingerprint"
    )
    
    title: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Título do documento"
    )
    
    content_preview: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Preview do conteúdo (primeiros N caracteres)"
    )
    
    content_hash: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
        comment="Hash do conteúdo completo"
    )
    
    content_size_bytes: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Tamanho do conteúdo em bytes"
    )
    
    # ========================================================================
    # Metadados
    # ========================================================================
    
    doc_metadata: Mapped[Dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        comment="Metadados extensíveis do documento"
    )
    
    url: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
        comment="URL de origem do documento"
    )
    
    content_type: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
        comment="Tipo de conteúdo (MIME type)"
    )
    
    language: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="pt-BR",
        comment="Idioma do documento (ISO 639-1)"
    )
    
    # ========================================================================
    # Status e Versionamento
    # ========================================================================
    
    status: Mapped[DocumentStatus] = mapped_column(
        String,
        nullable=False,
        default=DocumentStatus.ACTIVE,
        comment="Status do documento"
    )
    
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="Versão do documento (incrementado em updates)"
    )
    
    # ========================================================================
    # Soft Delete
    # ========================================================================
    
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Flag de soft delete"
    )
    
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp da exclusão lógica"
    )
    
    deleted_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Motivo da exclusão"
    )
    
    deleted_by: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
        comment="Usuário/sistema que executou a exclusão"
    )
    
    # ========================================================================
    # Timestamps
    # ========================================================================
    
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        comment="Timestamp de ingestão"
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
        comment="Timestamp da última atualização"
    )
    
    reindexed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp da última reindexação"
    )
    
    # ========================================================================
    # Elasticsearch Sync
    # ========================================================================
    
    es_indexed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Flag indicando se está indexado no ES"
    )
    
    es_indexed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp da última indexação no ES"
    )
    
    chunks_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Quantidade de chunks associados"
    )
    
    # ========================================================================
    # Relacionamentos
    # ========================================================================
    
    # Nota: Relacionamentos removidos temporariamente devido a 
    # incompatibilidade SQLModel vs SQLAlchemy. Use queries diretas.
    
    # ========================================================================
    # Índices Otimizados
    # ========================================================================
    
    __table_args__ = (
        # Índice para queries por fonte (apenas não deletados)
        Index(
            "idx_documents_source",
            "source_id",
            postgresql_where=is_deleted.is_(False)
        ),
        
        # Índice hash para fingerprint (deduplicação rápida)
        Index(
            "idx_documents_fingerprint",
            "fingerprint",
            postgresql_using="hash"
        ),
        
        # Índice para queries por status
        Index(
            "idx_documents_status",
            "status",
            postgresql_where=is_deleted.is_(False)
        ),
        
        # Índice para ordenação por data de ingestão
        Index(
            "idx_documents_ingested",
            ingested_at.desc(),
            postgresql_where=is_deleted.is_(False)
        ),
        
        # Índice GIN para metadados JSONB
        Index(
            "idx_documents_metadata",
            "metadata",
            postgresql_using="gin",
            postgresql_ops={"metadata": "jsonb_path_ops"}
        ),
        
        # Índice para sincronização ES (documentos pendentes ou desatualizados)
        Index(
            "idx_documents_es_sync",
            "es_indexed",
            "updated_at",
            postgresql_where=(es_indexed.is_(False)) | (es_indexed_at < updated_at)
        ),
        
        # Índice composto para queries comuns (source + status + data)
        Index(
            "idx_documents_source_active_date",
            "source_id",
            is_deleted,
            ingested_at.desc(),
            postgresql_where=is_deleted.is_(False)
        ),
        
        # Comentário da tabela
        {"comment": "Documentos jurídicos processados pelo pipeline GABI"}
    )
    
    # ========================================================================
    # Métodos
    # ========================================================================
    
    def soft_delete(self, reason: Optional[str] = None, deleted_by: Optional[str] = None) -> None:
        """Executa soft delete do documento.
        
        Args:
            reason: Motivo da exclusão
            deleted_by: Identificador do usuário/sistema
        """
        self.is_deleted = True
        self.deleted_at = datetime.now()
        self.deleted_reason = reason
        self.deleted_by = deleted_by
        self.status = DocumentStatus.DELETED
    
    def restore(self) -> None:
        """Restaura um documento soft-deleted."""
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_reason = None
        self.deleted_by = None
        self.status = DocumentStatus.ACTIVE
    
    def mark_es_synced(self) -> None:
        """Marca o documento como sincronizado com Elasticsearch."""
        self.es_indexed = True
        self.es_indexed_at = datetime.now()
    
    def needs_es_reindex(self) -> bool:
        """Verifica se o documento precisa ser reindexado no ES.
        
        Returns:
            True se necessita reindexação
        """
        if not self.es_indexed:
            return True
        if self.es_indexed_at is None:
            return True
        if self.updated_at and self.es_indexed_at < self.updated_at:
            return True
        return False
    
    def __repr__(self) -> str:
        return f"<Document(id={self.id}, document_id={self.document_id}, title={self.title!r})>"



