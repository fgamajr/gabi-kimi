"""Testes unitários para o modelo DLQMessage.

Testa propriedades, métodos e comportamentos do modelo de DLQ.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from gabi.models.dlq import DLQMessage, DLQStatus


class TestDLQMessageCreation:
    """Testes para criação de DLQMessage."""
    
    def test_dlq_creation_with_required_fields(self):
        """Verifica criação com campos obrigatórios."""
        msg = DLQMessage(
            source_id="test_source",
            url="https://example.com/doc.pdf",
            error_type="connection_error",
            error_message="Connection timeout",
        )
        assert msg.source_id == "test_source"
        assert msg.url == "https://example.com/doc.pdf"
        assert msg.error_type == "connection_error"
    
    def test_dlq_default_status_is_pending(self):
        """Verifica que status padrão é PENDING."""
        msg = DLQMessage(
            source_id="test_source",
            url="https://example.com/doc.pdf",
            error_type="error",
            error_message="Error",
        )
        assert msg.status == DLQStatus.PENDING
    
    def test_dlq_default_retry_count_is_zero(self):
        """Verifica que retry_count padrão é 0."""
        msg = DLQMessage(
            source_id="test_source",
            url="https://example.com/doc.pdf",
            error_type="error",
            error_message="Error",
        )
        assert msg.retry_count == 0
    
    def test_dlq_default_max_retries_is_five(self):
        """Verifica que max_retries padrão é 5."""
        msg = DLQMessage(
            source_id="test_source",
            url="https://example.com/doc.pdf",
            error_type="error",
            error_message="Error",
        )
        assert msg.max_retries == 5
    
    def test_dlq_default_payload_is_empty_dict(self):
        """Verifica que payload padrão é dict vazio."""
        msg = DLQMessage(
            source_id="test_source",
            url="https://example.com/doc.pdf",
            error_type="error",
            error_message="Error",
        )
        assert msg.payload == {}


class TestDLQMessageProperties:
    """Testes para propriedades de DLQMessage."""
    
    def test_can_retry_returns_true_when_pending_and_under_limit(self):
        """Verifica que can_retry retorna True quando PENDING e abaixo do limite."""
        msg = DLQMessage(
            source_id="test_source",
            url="https://example.com/doc.pdf",
            error_type="error",
            error_message="Error",
            status=DLQStatus.PENDING,
            retry_count=2,
            max_retries=5,
        )
        assert msg.can_retry is True
    
    def test_can_retry_returns_false_when_exhausted(self):
        """Verifica que can_retry retorna False quando retry_count >= max_retries."""
        msg = DLQMessage(
            source_id="test_source",
            url="https://example.com/doc.pdf",
            error_type="error",
            error_message="Error",
            status=DLQStatus.PENDING,
            retry_count=5,
            max_retries=5,
        )
        assert msg.can_retry is False
    
    def test_can_retry_returns_false_when_resolved(self):
        """Verifica que can_retry retorna False quando RESOLVED."""
        msg = DLQMessage(
            source_id="test_source",
            url="https://example.com/doc.pdf",
            error_type="error",
            error_message="Error",
            status=DLQStatus.RESOLVED,
            retry_count=0,
            max_retries=5,
        )
        assert msg.can_retry is False
    
    def test_is_resolved_returns_true_when_resolved(self):
        """Verifica que is_resolved retorna True quando RESOLVED."""
        msg = DLQMessage(
            source_id="test_source",
            url="https://example.com/doc.pdf",
            error_type="error",
            error_message="Error",
            status=DLQStatus.RESOLVED,
        )
        assert msg.is_resolved is True
    
    def test_is_resolved_returns_true_when_archived(self):
        """Verifica que is_resolved retorna True quando ARCHIVED."""
        msg = DLQMessage(
            source_id="test_source",
            url="https://example.com/doc.pdf",
            error_type="error",
            error_message="Error",
            status=DLQStatus.ARCHIVED,
        )
        assert msg.is_resolved is True
    
    def test_is_resolved_returns_false_when_pending(self):
        """Verifica que is_resolved retorna False quando PENDING."""
        msg = DLQMessage(
            source_id="test_source",
            url="https://example.com/doc.pdf",
            error_type="error",
            error_message="Error",
            status=DLQStatus.PENDING,
        )
        assert msg.is_resolved is False


class TestDLQMessageMethods:
    """Testes para métodos de DLQMessage."""
    
    def test_schedule_next_retry_sets_status_to_retrying(self):
        """Verifica que schedule_next_retry define status como RETRYING."""
        msg = DLQMessage(
            source_id="test_source",
            url="https://example.com/doc.pdf",
            error_type="error",
            error_message="Error",
            status=DLQStatus.PENDING,
            retry_count=1,
            max_retries=5,
        )
        msg.schedule_next_retry(base_delay_seconds=60)
        assert msg.status == DLQStatus.RETRYING
    
    def test_schedule_next_retry_sets_next_retry_at(self):
        """Verifica que schedule_next_retry define next_retry_at."""
        msg = DLQMessage(
            source_id="test_source",
            url="https://example.com/doc.pdf",
            error_type="error",
            error_message="Error",
            retry_count=0,
            max_retries=5,
        )
        msg.schedule_next_retry(base_delay_seconds=60)
        assert msg.next_retry_at is not None
        # Verifica que é no futuro (exponential backoff: 60s * 2^0 = 60s)
        assert msg.next_retry_at > datetime.now()
    
    def test_schedule_next_retry_sets_exhausted_when_over_limit(self):
        """Verifica que schedule_next_retry define EXHAUSTED quando acima do limite."""
        msg = DLQMessage(
            source_id="test_source",
            url="https://example.com/doc.pdf",
            error_type="error",
            error_message="Error",
            retry_count=5,
            max_retries=5,
        )
        msg.schedule_next_retry()
        assert msg.status == DLQStatus.EXHAUSTED
    
    def test_mark_retry_attempt_increments_count(self):
        """Verifica que mark_retry_attempt incrementa retry_count."""
        msg = DLQMessage(
            source_id="test_source",
            url="https://example.com/doc.pdf",
            error_type="error",
            error_message="Error",
            retry_count=0,
        )
        msg.mark_retry_attempt()
        assert msg.retry_count == 1
        assert msg.last_retry_at is not None
    
    def test_mark_retry_attempt_sets_exhausted_at_limit(self):
        """Verifica que mark_retry_attempt define EXHAUSTED no limite."""
        msg = DLQMessage(
            source_id="test_source",
            url="https://example.com/doc.pdf",
            error_type="error",
            error_message="Error",
            retry_count=4,
            max_retries=5,
        )
        msg.mark_retry_attempt()
        assert msg.status == DLQStatus.EXHAUSTED
    
    def test_resolve_sets_resolved_status(self):
        """Verifica que resolve define status como RESOLVED."""
        msg = DLQMessage(
            source_id="test_source",
            url="https://example.com/doc.pdf",
            error_type="error",
            error_message="Error",
            status=DLQStatus.PENDING,
        )
        msg.resolve("admin@tcu.gov.br")
        assert msg.status == DLQStatus.RESOLVED
        assert msg.resolved_by == "admin@tcu.gov.br"
        assert msg.resolved_at is not None
    
    def test_resolve_accepts_notes(self):
        """Verifica que resolve aceita notas."""
        msg = DLQMessage(
            source_id="test_source",
            url="https://example.com/doc.pdf",
            error_type="error",
            error_message="Error",
        )
        msg.resolve("admin@tcu.gov.br", notes="Problema corrigido na fonte")
        assert msg.resolution_notes == "Problema corrigido na fonte"
    
    def test_archive_changes_status_to_archived(self):
        """Verifica que archive muda status para ARCHIVED."""
        msg = DLQMessage(
            source_id="test_source",
            url="https://example.com/doc.pdf",
            error_type="error",
            error_message="Error",
            status=DLQStatus.RESOLVED,
        )
        msg.archive()
        assert msg.status == DLQStatus.ARCHIVED
        assert msg.archived_at is not None


class TestDLQStatusEnum:
    """Testes para enum DLQStatus."""
    
    def test_status_values(self):
        """Verifica valores do enum."""
        assert DLQStatus.PENDING.value == "pending"
        assert DLQStatus.RETRYING.value == "retrying"
        assert DLQStatus.EXHAUSTED.value == "exhausted"
        assert DLQStatus.RESOLVED.value == "resolved"
        assert DLQStatus.ARCHIVED.value == "archived"


class TestDLQMessageRepr:
    """Testes para representação string de DLQMessage."""
    
    def test_repr_contains_source_id(self):
        """Verifica que repr contém source_id."""
        msg = DLQMessage(
            source_id="my_source",
            url="https://example.com/doc.pdf",
            error_type="error",
            error_message="Error",
        )
        repr_str = repr(msg)
        assert "my_source" in repr_str
    
    def test_repr_contains_retry_count(self):
        """Verifica que repr contém retry_count."""
        msg = DLQMessage(
            source_id="test_source",
            url="https://example.com/doc.pdf",
            error_type="error",
            error_message="Error",
            retry_count=2,
            max_retries=5,
        )
        repr_str = repr(msg)
        assert "retry_count=2/5" in repr_str
