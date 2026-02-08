"""Modelo ChangeDetectionCache - Cache de detecção de mudanças do GABI.

Este módulo define o modelo de dados para cache de detecção de mudanças,
utilizado pelo pipeline de ingestão para detectar alterações em recursos
remotos (URLs) através de headers HTTP (ETag, Last-Modified) e hash de conteúdo.

Baseado em GABI_SPECS_FINAL_v1.md Seção 2.7 (change_detection_cache).

Invariantes:
    - Detecção de mudança obrigatória via ETag ou Last-Modified
    - Referência à sources com ON DELETE CASCADE
    - Contadores de verificação e mudança para estatísticas
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from gabi.models.base import Base


class ChangeDetectionCache(Base):
    """Modelo para cache de detecção de mudanças em recursos remotos.
    
    Este modelo armazena informações de cache HTTP (ETag, Last-Modified) e
    hashes de conteúdo para detectar quando um recurso remoto foi modificado,
    evitando reprocessamento desnecessário de documentos não alterados.
    
    Invariante de Detecção:
        Pelo menos um dos mecanismos de detecção deve estar presente:
        - ETag: Header HTTP para validação de cache
        - Last-Modified: Header HTTP com timestamp da última modificação
        - Content Hash: Hash SHA-256 do conteúdo (fallback)
    
    Attributes:
        id: Identificador único UUID
        source_id: Referência à fonte na sources
        url: URL do recurso monitorado (único por fonte)
        etag: Header ETag HTTP para validação de cache
        last_modified: Header Last-Modified HTTP
        content_length: Tamanho do conteúdo em bytes
        content_hash: Hash SHA-256 do conteúdo
        last_checked_at: Timestamp da última verificação
        last_changed_at: Timestamp da última mudança detectada
        check_count: Número total de verificações
        change_count: Número total de mudanças detectadas
    """
    
    __tablename__ = "change_detection_cache"
    
    # ==========================================================================
    # Identificação
    # ==========================================================================
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
        comment="Identificador único UUID do cache"
    )
    
    # ==========================================================================
    # Relacionamento
    # ==========================================================================
    source_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        comment="Referência à fonte na sources"
    )
    
    # ==========================================================================
    # URL do Recurso
    # ==========================================================================
    url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="URL completa do recurso monitorado"
    )
    
    # ==========================================================================
    # Headers HTTP para Detecção de Mudança (Obrigatório: ETag ou Last-Modified)
    # ==========================================================================
    etag: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Header ETag HTTP para validação de cache"
    )
    
    last_modified: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Header Last-Modified HTTP (formato RFC 7232)"
    )
    
    # ==========================================================================
    # Hash do Conteúdo (Fallback para detecção)
    # ==========================================================================
    content_hash: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Hash SHA-256 do conteúdo para detecção de mudança"
    )
    
    content_length: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Tamanho do conteúdo em bytes"
    )
    
    # ==========================================================================
    # Estado e Estatísticas
    # ==========================================================================
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp da última verificação do recurso"
    )
    
    last_changed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp da última mudança detectada"
    )
    
    check_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Número total de verificações realizadas"
    )
    
    change_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Número total de mudanças detectadas"
    )
    
    # ==========================================================================
    # Índices
    # ==========================================================================
    __table_args__ = (
        # Índice para busca por fonte
        Index("idx_change_detection_source", "source_id"),
        # Índice para busca por timestamp de verificação (para polling)
        Index("idx_change_detection_checked", "last_checked_at"),
        # Índice único para evitar duplicatas de URL por fonte
        Index("idx_change_detection_url_source", "source_id", "url", unique=True),
    )
    
    # ==========================================================================
    # Inicialização
    # ==========================================================================
    def __init__(self, **kwargs):
        # Set defaults before calling super().__init__
        if 'check_count' not in kwargs:
            kwargs['check_count'] = 0
        if 'change_count' not in kwargs:
            kwargs['change_count'] = 0
        super().__init__(**kwargs)
    
    # ==========================================================================
    # Propriedades
    # ==========================================================================
    @property
    def has_change_detection(self) -> bool:
        """Verifica se há mecanismo de detecção de mudança configurado.
        
        Invariante: Pelo menos um dos mecanismos deve estar presente.
        
        Returns:
            True se há ETag, Last-Modified ou content_hash
        """
        return bool(self.etag or self.last_modified or self.content_hash)
    
    @property
    def is_fresh(self) -> bool:
        """Verifica se o cache foi verificado recentemente.
        
        Returns:
            True se last_checked_at existe e é recente (menos de 1 hora)
        """
        if not self.last_checked_at:
            return False
        age = datetime.now(timezone.utc) - self.last_checked_at
        return age.total_seconds() < 3600  # 1 hora
    
    @property
    def change_rate(self) -> float:
        """Calcula a taxa de mudança (mudanças / verificações).
        
        Returns:
            Taxa entre 0.0 e 1.0, ou 0.0 se nunca verificado
        """
        if self.check_count == 0:
            return 0.0
        return self.change_count / self.check_count
    
    @property
    def detection_method(self) -> str:
        """Retorna o método de detecção utilizado.
        
        Returns:
            'etag', 'last_modified', 'content_hash' ou 'none'
        """
        if self.etag:
            return "etag"
        if self.last_modified:
            return "last_modified"
        if self.content_hash:
            return "content_hash"
        return "none"
    
    # ==========================================================================
    # Métodos
    # ==========================================================================
    def record_check(self, changed: bool = False) -> None:
        """Registra uma verificação do recurso.
        
        Args:
            changed: True se uma mudança foi detectada
        """
        now = datetime.now(timezone.utc)
        self.last_checked_at = now
        self.check_count += 1
        
        if changed:
            self.last_changed_at = now
            self.change_count += 1
    
    def update_etag(self, etag: str) -> None:
        """Atualiza o ETag do recurso.
        
        Args:
            etag: Novo valor do header ETag
        """
        self.etag = etag
    
    def update_last_modified(self, last_modified: str) -> None:
        """Atualiza o Last-Modified do recurso.
        
        Args:
            last_modified: Novo valor do header Last-Modified
        """
        self.last_modified = last_modified
    
    def update_content_hash(self, content_hash: str, content_length: int) -> None:
        """Atualiza o hash e tamanho do conteúdo.
        
        Args:
            content_hash: Hash SHA-256 do conteúdo
            content_length: Tamanho em bytes
        """
        self.content_hash = content_hash
        self.content_length = content_length
    
    def has_changed_from(
        self,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
        content_hash: Optional[str] = None
    ) -> bool:
        """Verifica se o recurso mudou comparando com valores atuais.
        
        Implementa a lógica de detecção de mudança:
        1. Compara ETag (se disponível)
        2. Compara Last-Modified (se ETag não disponível)
        3. Compara content_hash (fallback)
        
        Args:
            etag: ETag atual do recurso remoto
            last_modified: Last-Modified atual do recurso remoto
            content_hash: Hash atual do conteúdo
            
        Returns:
            True se detectada mudança, False caso contrário
        """
        # Prioridade 1: ETag (mais confiável)
        if self.etag and etag is not None:
            return self.etag != etag
        
        # Prioridade 2: Last-Modified
        if self.last_modified and last_modified is not None:
            return self.last_modified != last_modified
        
        # Prioridade 3: Content Hash (fallback)
        if self.content_hash and content_hash is not None:
            return self.content_hash != content_hash
        
        # Sem mecanismo de comparação disponível = assumir mudança
        return True
