"""Modelo DocumentChunk para chunks de documentos vetorizados.

Este módulo define o modelo para armazenar chunks de documentos com seus
embeddings vetoriais (384 dimensões - ADR-001).
Baseado em GABI_SPECS_FINAL_v1.md Seção 2.7.1 (document_chunks).
"""

from datetime import datetime
from typing import Optional, Any
from uuid import UUID

from sqlalchemy import ForeignKey, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from gabi.models.base import SoftDeleteBase


class DocumentChunk(SoftDeleteBase):
    """Modelo para chunks de documentos com embeddings vetoriais.
    
    Cada chunk representa uma parte de um documento processado,
    com seu texto, metadados e embedding vetorial para busca semântica.
    
    Attributes:
        id: UUID primário gerado automaticamente
        document_id: FK para documents(document_id) com CASCADE
        chunk_index: Índice sequencial do chunk no documento
        chunk_text: Conteúdo textual do chunk
        token_count: Quantidade de tokens no chunk
        char_count: Quantidade de caracteres no chunk
        embedding: Vetor de 384 dimensões para busca semântica
        embedding_model: Nome do modelo usado para gerar o embedding
        embedded_at: Timestamp da geração do embedding
        metadata: Metadados adicionais em formato JSON
        section_type: Tipo da seção (artigo, paragrafo, ementa, etc)
    """
    
    __tablename__ = "document_chunks"
    
    # Constraints
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk_index"),
    )
    
    # Foreign Key
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Referência ao documento pai"
    )
    
    # Índice do chunk no documento
    chunk_index: Mapped[int] = mapped_column(
        nullable=False,
        comment="Índice sequencial do chunk no documento"
    )
    
    # Conteúdo
    chunk_text: Mapped[str] = mapped_column(
        nullable=False,
        comment="Texto do chunk"
    )
    
    token_count: Mapped[int] = mapped_column(
        nullable=False,
        comment="Quantidade de tokens no chunk"
    )
    
    char_count: Mapped[int] = mapped_column(
        nullable=False,
        comment="Quantidade de caracteres no chunk"
    )
    
    # Vetor (384 dimensões - IMUTÁVEL conforme ADR-001)
    embedding: Mapped[Optional[Vector]] = mapped_column(
        Vector(384),
        nullable=True,
        comment="Embedding vetorial de 384 dimensões para busca semântica"
    )
    
    embedding_model: Mapped[Optional[str]] = mapped_column(
        nullable=True,
        comment="Nome do modelo usado para gerar o embedding"
    )
    
    embedded_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="Timestamp da geração do embedding"
    )
    
    # Metadados
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
        comment="Metadados adicionais do chunk"
    )
    
    section_type: Mapped[Optional[str]] = mapped_column(
        nullable=True,
        index=True,
        comment="Tipo da seção (artigo, paragrafo, ementa, etc)"
    )
    
    # Nota: Relacionamento com Document removido temporariamente
    
    def __repr__(self) -> str:
        """Representação em string do DocumentChunk."""
        return (
            f"<DocumentChunk(id={self.id}, "
            f"document_id={self.document_id}, "
            f"chunk_index={self.chunk_index}, "
            f"has_embedding={self.embedding is not None})>"
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Converte o chunk para dicionário.
        
        Returns:
            Dicionário com os dados do chunk (sem o embedding vetorial)
        """
        return {
            "id": str(self.id),
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "chunk_text": self.chunk_text,
            "token_count": self.token_count,
            "char_count": self.char_count,
            "has_embedding": self.embedding is not None,
            "embedding_model": self.embedding_model,
            "embedded_at": self.embedded_at.isoformat() if self.embedded_at else None,
            "metadata": self.chunk_metadata,
            "section_type": self.section_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# Export
__all__ = ["DocumentChunk"]
