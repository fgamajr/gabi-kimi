"""Modelo AuditLog para o GABI.

Este módulo define o modelo SQLAlchemy para logs de auditoria,
implementando hash chain para integridade e garantindo imutabilidade.

Baseado em GABI_SPECS_FINAL_v1.md Seção 2.7.1 (audit_log).

INVARIANTES:
    - IMUTÁVEL: Nunca atualizar ou deletar registros
    - Hash chain para integridade (previous_hash -> event_hash)
    - Todos os eventos são registrados com timestamp UTC
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from gabi.models.base import Base
from gabi.types import AuditEventType, AuditSeverity

if TYPE_CHECKING:
    pass


class AuditLog(Base):
    """Modelo de log de auditoria imutável.
    
    Registra todos os eventos significativos do sistema com garantia
    de integridade via hash chain. Este modelo é IMUTÁVEL - uma vez
    criado, o registro nunca deve ser modificado ou deletado.
    
    Attributes:
        id: UUID interno (PK)
        timestamp: Momento exato do evento (UTC)
        event_type: Tipo do evento auditado (enum)
        severity: Nível de severidade (debug, info, warning, error, critical)
        user_id: Identificador do usuário (se aplicável)
        user_email: Email do usuário (se aplicável)
        session_id: ID da sessão (se aplicável)
        ip_address: Endereço IP do cliente (INET)
        user_agent: User agent do cliente
        resource_type: Tipo do recurso afetado
        resource_id: Identificador do recurso afetado
        action_details: Detalhes da ação em JSONB
        before_state: Estado anterior do recurso em JSONB
        after_state: Estado posterior do recurso em JSONB
        previous_hash: Hash do evento anterior na cadeia
        event_hash: Hash deste evento (calculado automaticamente)
        request_id: ID da requisição HTTP
        correlation_id: ID para rastreamento distribuído
    
    Example:
        >>> log = AuditLog(
        ...     event_type=AuditEventType.DOCUMENT_CREATED,
        ...     severity=AuditSeverity.INFO,
        ...     user_id="user-123",
        ...     resource_type="document",
        ...     resource_id="doc-456",
        ...     action_details={"source": "api", "method": "POST"},
        ... )
    """
    
    __tablename__ = "audit_log"
    
    # ===================================================================
    # Identificação
    # ===================================================================
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
        nullable=False,
        comment="UUID do evento de auditoria (PK)"
    )
    
    # ===================================================================
    # Timestamp
    # ===================================================================
    
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Momento exato do evento (UTC)"
    )
    
    # ===================================================================
    # Evento
    # ===================================================================
    
    event_type: Mapped[AuditEventType] = mapped_column(
        String,
        nullable=False,
        comment="Tipo do evento auditado"
    )
    
    severity: Mapped[AuditSeverity] = mapped_column(
        String,
        default=AuditSeverity.INFO,
        server_default="info",
        nullable=False,
        comment="Nível de severidade (debug, info, warning, error, critical)"
    )
    
    def __init__(self, **kwargs):
        """Initialize with default severity if not provided."""
        if 'severity' not in kwargs or kwargs['severity'] is None:
            kwargs['severity'] = AuditSeverity.INFO
        super().__init__(**kwargs)
    
    # ===================================================================
    # Usuário
    # ===================================================================
    
    user_id: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
        comment="Identificador do usuário"
    )
    
    user_email: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
        comment="Email do usuário"
    )
    
    session_id: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
        comment="ID da sessão"
    )
    
    ip_address: Mapped[Optional[str]] = mapped_column(
        INET,
        nullable=True,
        comment="Endereço IP do cliente"
    )
    
    user_agent: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="User agent do cliente"
    )
    
    # ===================================================================
    # Recurso
    # ===================================================================
    
    resource_type: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
        comment="Tipo do recurso afetado (document, source, config, etc)"
    )
    
    resource_id: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
        comment="Identificador do recurso afetado"
    )
    
    # ===================================================================
    # Detalhes
    # ===================================================================
    
    action_details: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Detalhes da ação em JSONB"
    )
    
    before_state: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Estado anterior do recurso em JSONB"
    )
    
    after_state: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Estado posterior do recurso em JSONB"
    )
    
    # ===================================================================
    # Integridade (Hash Chain)
    # ===================================================================
    
    previous_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="Hash SHA-256 do evento anterior na cadeia"
    )
    
    event_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Hash SHA-256 deste evento (calculado automaticamente)"
    )
    
    # ===================================================================
    # Request Tracing
    # ===================================================================
    
    request_id: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
        comment="ID da requisição HTTP"
    )
    
    correlation_id: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
        comment="ID para rastreamento distribuído"
    )
    
    # ===================================================================
    # Índices
    # ===================================================================
    
    __table_args__ = (
        # Índice por timestamp (mais recentes primeiro)
        Index(
            "idx_audit_timestamp",
            timestamp.desc(),
            postgresql_using="btree"
        ),
        
        # Índice por usuário e timestamp (filtrado)
        Index(
            "idx_audit_user",
            user_id,
            timestamp.desc(),
            postgresql_where=user_id.is_not(None),
            postgresql_using="btree"
        ),
        
        # Índice por tipo de recurso e ID
        Index(
            "idx_audit_resource",
            resource_type,
            resource_id,
            postgresql_using="btree"
        ),
        
        # Índice por tipo de evento e timestamp
        Index(
            "idx_audit_event_type",
            event_type,
            timestamp.desc(),
            postgresql_using="btree"
        ),
        
        # Índice por request_id (filtrado)
        Index(
            "idx_audit_request",
            request_id,
            postgresql_where=request_id.is_not(None),
            postgresql_using="btree"
        ),
        
        # Comentário da tabela
        {"comment": "Log de auditoria imutável com hash chain para integridade"},
    )
    
    def __repr__(self) -> str:
        """Representação string do log de auditoria."""
        event_type_val = self.event_type.value if self.event_type else None
        severity_val = self.severity.value if self.severity else None
        timestamp_val = self.timestamp.isoformat() if self.timestamp else None
        return (
            f"<AuditLog("
            f"id={self.id}, "
            f"event_type={event_type_val}, "
            f"severity={severity_val}, "
            f"resource_type={self.resource_type}, "
            f"timestamp={timestamp_val}"
            f")>"
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte o log para dicionário.
        
        Returns:
            Dict com todos os campos do log.
        """
        return {
            "id": str(self.id),
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "event_type": self.event_type.value if self.event_type else None,
            "severity": self.severity.value if self.severity else None,
            "user_id": self.user_id,
            "user_email": self.user_email,
            "session_id": self.session_id,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "action_details": self.action_details,
            "before_state": self.before_state,
            "after_state": self.after_state,
            "previous_hash": self.previous_hash,
            "event_hash": self.event_hash,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
        }


# =============================================================================
# Exports
# =============================================================================

__all__ = ["AuditLog"]
