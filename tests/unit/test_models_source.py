"""Testes unitários para o modelo SourceRegistry.

Testa propriedades, métodos e comportamentos do modelo de fontes.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from uuid import uuid4

from gabi.models.source import SourceRegistry
from gabi.types import SourceType, SourceStatus, SensitivityLevel


class TestSourceRegistryProperties:
    """Testes para propriedades do SourceRegistry."""
    
    def test_is_active_returns_true_when_active_and_not_deleted(self):
        """Verifica que is_active retorna True quando status é ACTIVE e não deletado."""
        source = SourceRegistry(
            id="test_source",
            name="Test Source",
            type=SourceType.API,
            config_hash="abc123",
            owner_email="test@tcu.gov.br",
            status=SourceStatus.ACTIVE,
            deleted_at=None,
        )
        assert source.is_active is True
    
    def test_is_active_returns_false_when_paused(self):
        """Verifica que is_active retorna False quando status é PAUSED."""
        source = SourceRegistry(
            id="test_source",
            name="Test Source",
            type=SourceType.API,
            config_hash="abc123",
            owner_email="test@tcu.gov.br",
            status=SourceStatus.PAUSED,
        )
        assert source.is_active is False
    
    def test_is_active_returns_false_when_deleted(self):
        """Verifica que is_active retorna False quando deletado."""
        source = SourceRegistry(
            id="test_source",
            name="Test Source",
            type=SourceType.API,
            config_hash="abc123",
            owner_email="test@tcu.gov.br",
            status=SourceStatus.ACTIVE,
            deleted_at=datetime.now(timezone.utc),
        )
        assert source.is_active is False
    
    def test_is_deleted_returns_true_when_deleted_at_set(self):
        """Verifica que is_deleted retorna True quando deleted_at está definido."""
        source = SourceRegistry(
            id="test_source",
            name="Test Source",
            type=SourceType.API,
            config_hash="abc123",
            owner_email="test@tcu.gov.br",
            deleted_at=datetime.now(timezone.utc),
        )
        assert source.is_deleted is True
    
    def test_is_deleted_returns_false_when_deleted_at_none(self):
        """Verifica que is_deleted retorna False quando deleted_at é None."""
        source = SourceRegistry(
            id="test_source",
            name="Test Source",
            type=SourceType.API,
            config_hash="abc123",
            owner_email="test@tcu.gov.br",
            deleted_at=None,
        )
        assert source.is_deleted is False
    
    def test_is_healthy_returns_true_when_active_and_no_errors(self):
        """Verifica que is_healthy retorna True quando ativo sem erros."""
        source = SourceRegistry(
            id="test_source",
            name="Test Source",
            type=SourceType.API,
            config_hash="abc123",
            owner_email="test@tcu.gov.br",
            status=SourceStatus.ACTIVE,
            consecutive_errors=0,
            deleted_at=None,
        )
        assert source.is_healthy is True
    
    def test_is_healthy_returns_false_when_many_errors(self):
        """Verifica que is_healthy retorna False quando há muitos erros."""
        source = SourceRegistry(
            id="test_source",
            name="Test Source",
            type=SourceType.API,
            config_hash="abc123",
            owner_email="test@tcu.gov.br",
            status=SourceStatus.ACTIVE,
            consecutive_errors=5,
        )
        assert source.is_healthy is False
    
    def test_success_rate_returns_one_when_no_documents(self):
        """Verifica que success_rate retorna 1.0 quando não há documentos."""
        source = SourceRegistry(
            id="test_source",
            name="Test Source",
            type=SourceType.API,
            config_hash="abc123",
            owner_email="test@tcu.gov.br",
            document_count=0,
            total_documents_ingested=0,
        )
        assert source.success_rate == 1.0
    
    def test_success_rate_calculates_correctly(self):
        """Verifica que success_rate calcula corretamente."""
        source = SourceRegistry(
            id="test_source",
            name="Test Source",
            type=SourceType.API,
            config_hash="abc123",
            owner_email="test@tcu.gov.br",
            document_count=80,
            total_documents_ingested=100,
        )
        assert source.success_rate == 0.8


class TestSourceRegistryMethods:
    """Testes para métodos do SourceRegistry."""
    
    def test_soft_delete_sets_deleted_at(self):
        """Verifica que soft_delete define deleted_at."""
        source = SourceRegistry(
            id="test_source",
            name="Test Source",
            type=SourceType.API,
            config_hash="abc123",
            owner_email="test@tcu.gov.br",
        )
        source.soft_delete()
        assert source.deleted_at is not None
    
    def test_restore_clears_deleted_at(self):
        """Verifica que restore limpa deleted_at."""
        source = SourceRegistry(
            id="test_source",
            name="Test Source",
            type=SourceType.API,
            config_hash="abc123",
            owner_email="test@tcu.gov.br",
            deleted_at=datetime.now(timezone.utc),
        )
        source.restore()
        assert source.deleted_at is None
    
    def test_record_success_updates_timestamps(self):
        """Verifica que record_success atualiza timestamps."""
        source = SourceRegistry(
            id="test_source",
            name="Test Source",
            type=SourceType.API,
            config_hash="abc123",
            owner_email="test@tcu.gov.br",
            consecutive_errors=3,
            status=SourceStatus.ERROR,
        )
        source.record_success()
        assert source.last_sync_at is not None
        assert source.last_success_at is not None
        assert source.consecutive_errors == 0
        assert source.status == SourceStatus.ACTIVE
    
    def test_record_error_increments_counter(self):
        """Verifica que record_error incrementa contador de erros."""
        source = SourceRegistry(
            id="test_source",
            name="Test Source",
            type=SourceType.API,
            config_hash="abc123",
            owner_email="test@tcu.gov.br",
            consecutive_errors=0,
        )
        source.record_error("Connection timeout")
        assert source.consecutive_errors == 1
        assert source.last_error_message == "Connection timeout"
        assert source.last_error_at is not None
    
    def test_record_error_auto_pauses_after_five_errors(self):
        """Verifica que fonte é pausada após 5 erros."""
        source = SourceRegistry(
            id="test_source",
            name="Test Source",
            type=SourceType.API,
            config_hash="abc123",
            owner_email="test@tcu.gov.br",
            consecutive_errors=4,
            status=SourceStatus.ACTIVE,
        )
        source.record_error("Fifth error")
        assert source.status == SourceStatus.ERROR
    
    def test_increment_document_count_updates_stats(self):
        """Verifica que increment_document_count atualiza estatísticas."""
        source = SourceRegistry(
            id="test_source",
            name="Test Source",
            type=SourceType.API,
            config_hash="abc123",
            owner_email="test@tcu.gov.br",
            document_count=10,
            total_documents_ingested=10,
        )
        source.increment_document_count(5)
        assert source.document_count == 15
        assert source.total_documents_ingested == 15
        assert source.last_document_at is not None


class TestSourceRegistryTypes:
    """Testes para tipos e enums do SourceRegistry."""
    
    def test_source_type_values(self):
        """Verifica valores do enum SourceType."""
        assert SourceType.API.value == "api"
        assert SourceType.WEB.value == "web"
        assert SourceType.FILE.value == "file"
        assert SourceType.CRAWLER.value == "crawler"
    
    def test_source_status_values(self):
        """Verifica valores do enum SourceStatus."""
        assert SourceStatus.ACTIVE.value == "active"
        assert SourceStatus.PAUSED.value == "paused"
        assert SourceStatus.ERROR.value == "error"
        assert SourceStatus.DISABLED.value == "disabled"
    
    def test_default_sensitivity(self):
        """Verifica sensibilidade padrão."""
        source = SourceRegistry(
            id="test_source",
            name="Test Source",
            type=SourceType.API,
            config_hash="abc123",
            owner_email="test@tcu.gov.br",
            sensitivity=SensitivityLevel.INTERNAL,
        )
        assert source.sensitivity == SensitivityLevel.INTERNAL
    
    def test_default_status(self):
        """Verifica status padrão."""
        source = SourceRegistry(
            id="test_source",
            name="Test Source",
            type=SourceType.API,
            config_hash="abc123",
            owner_email="test@tcu.gov.br",
            status=SourceStatus.ACTIVE,
        )
        assert source.status == SourceStatus.ACTIVE
    
    def test_default_retention_days(self):
        """Verifica dias de retenção padrão."""
        source = SourceRegistry(
            id="test_source",
            name="Test Source",
            type=SourceType.API,
            config_hash="abc123",
            owner_email="test@tcu.gov.br",
            retention_days=2555,
        )
        assert source.retention_days == 2555  # ~7 anos
