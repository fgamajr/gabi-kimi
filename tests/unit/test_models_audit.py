"""Testes unitários para o modelo AuditLog.

Testa propriedades, métodos e comportamentos do modelo de auditoria.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from uuid import uuid4

from gabi.models.audit import AuditLog
from gabi.types import AuditEventType, AuditSeverity


class TestAuditLogCreation:
    """Testes para criação de AuditLog."""
    
    def test_audit_log_creation_with_required_fields(self):
        """Verifica criação com campos obrigatórios."""
        log = AuditLog(
            event_type=AuditEventType.DOCUMENT_CREATED,
            severity=AuditSeverity.INFO,
            event_hash="abc123def456",
        )
        assert log.event_type == AuditEventType.DOCUMENT_CREATED
        assert log.severity == AuditSeverity.INFO
        assert log.event_hash == "abc123def456"
    
    def test_audit_log_default_severity_is_info(self):
        """Verifica que severity padrão é INFO."""
        log = AuditLog(
            event_type=AuditEventType.DOCUMENT_CREATED,
            event_hash="abc123",
        )
        assert log.severity == AuditSeverity.INFO


class TestAuditLogToDict:
    """Testes para método to_dict de AuditLog."""
    
    def test_to_dict_returns_dict(self):
        """Verifica que to_dict retorna um dicionário."""
        log = AuditLog(
            event_type=AuditEventType.DOCUMENT_CREATED,
            severity=AuditSeverity.INFO,
            event_hash="abc123",
        )
        result = log.to_dict()
        assert isinstance(result, dict)
    
    def test_to_dict_contains_required_fields(self):
        """Verifica que to_dict contém campos obrigatórios."""
        log = AuditLog(
            event_type=AuditEventType.DOCUMENT_CREATED,
            severity=AuditSeverity.INFO,
            event_hash="abc123",
        )
        result = log.to_dict()
        assert "id" in result
        assert "timestamp" in result
        assert "event_type" in result
        assert "severity" in result
        assert "event_hash" in result
    
    def test_to_dict_contains_user_fields(self):
        """Verifica que to_dict contém campos de usuário."""
        log = AuditLog(
            event_type=AuditEventType.DOCUMENT_CREATED,
            event_hash="abc123",
            user_id="user-123",
            user_email="user@tcu.gov.br",
        )
        result = log.to_dict()
        assert result["user_id"] == "user-123"
        assert result["user_email"] == "user@tcu.gov.br"
    
    def test_to_dict_contains_resource_fields(self):
        """Verifica que to_dict contém campos de recurso."""
        log = AuditLog(
            event_type=AuditEventType.DOCUMENT_CREATED,
            event_hash="abc123",
            resource_type="document",
            resource_id="doc-456",
        )
        result = log.to_dict()
        assert result["resource_type"] == "document"
        assert result["resource_id"] == "doc-456"
    
    def test_to_dict_contains_state_fields(self):
        """Verifica que to_dict contém campos de estado."""
        log = AuditLog(
            event_type=AuditEventType.DOCUMENT_UPDATED,
            event_hash="abc123",
            before_state={"title": "Old"},
            after_state={"title": "New"},
        )
        result = log.to_dict()
        assert result["before_state"] == {"title": "Old"}
        assert result["after_state"] == {"title": "New"}
    
    def test_to_dict_contains_hash_chain(self):
        """Verifica que to_dict contém hash chain."""
        log = AuditLog(
            event_type=AuditEventType.DOCUMENT_CREATED,
            event_hash="current_hash",
            previous_hash="previous_hash",
        )
        result = log.to_dict()
        assert result["previous_hash"] == "previous_hash"
        assert result["event_hash"] == "current_hash"


class TestAuditLogIndices:
    """Testes para índices de AuditLog."""
    
    def test_has_timestamp_index(self):
        """Verifica que há índice por timestamp."""
        from sqlalchemy import Index
        table_args = AuditLog.__table_args__
        assert any("idx_audit_timestamp" in str(arg) for arg in table_args)
    
    def test_has_user_index(self):
        """Verifica que há índice por usuário."""
        table_args = AuditLog.__table_args__
        assert any("idx_audit_user" in str(arg) for arg in table_args)
    
    def test_has_resource_index(self):
        """Verifica que há índice por recurso."""
        table_args = AuditLog.__table_args__
        assert any("idx_audit_resource" in str(arg) for arg in table_args)
    
    def test_has_event_type_index(self):
        """Verifica que há índice por tipo de evento."""
        table_args = AuditLog.__table_args__
        assert any("idx_audit_event_type" in str(arg) for arg in table_args)


class TestAuditLogTypes:
    """Testes para tipos e enums de AuditLog."""
    
    def test_audit_event_type_values(self):
        """Verifica valores de AuditEventType."""
        assert AuditEventType.DOCUMENT_VIEWED.value == "document_viewed"
        assert AuditEventType.DOCUMENT_CREATED.value == "document_created"
        assert AuditEventType.SYNC_STARTED.value == "sync_started"
        assert AuditEventType.SYNC_COMPLETED.value == "sync_completed"
    
    def test_audit_severity_values(self):
        """Verifica valores de AuditSeverity."""
        assert AuditSeverity.DEBUG.value == "debug"
        assert AuditSeverity.INFO.value == "info"
        assert AuditSeverity.WARNING.value == "warning"
        assert AuditSeverity.ERROR.value == "error"
        assert AuditSeverity.CRITICAL.value == "critical"


class TestAuditLogRepr:
    """Testes para representação string de AuditLog."""
    
    def test_repr_contains_event_type(self):
        """Verifica que repr contém event_type."""
        log = AuditLog(
            event_type=AuditEventType.DOCUMENT_CREATED,
            event_hash="abc123",
        )
        repr_str = repr(log)
        assert "document_created" in repr_str
    
    def test_repr_contains_severity(self):
        """Verifica que repr contém severity."""
        log = AuditLog(
            event_type=AuditEventType.DOCUMENT_CREATED,
            severity=AuditSeverity.ERROR,
            event_hash="abc123",
        )
        repr_str = repr(log)
        assert "error" in repr_str
    
    def test_repr_contains_resource_type(self):
        """Verifica que repr contém resource_type."""
        log = AuditLog(
            event_type=AuditEventType.DOCUMENT_CREATED,
            event_hash="abc123",
            resource_type="document",
        )
        repr_str = repr(log)
        assert "document" in repr_str
