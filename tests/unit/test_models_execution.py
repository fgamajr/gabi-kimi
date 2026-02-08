"""Testes unitários para o modelo ExecutionManifest.

Testa propriedades, métodos e comportamentos do modelo de execuções.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from uuid import uuid4

from gabi.models.execution import ExecutionManifest, ExecutionStatus


class TestExecutionManifestCreation:
    """Testes para criação de ExecutionManifest."""
    
    def test_execution_creation_with_required_fields(self):
        """Verifica criação com campos obrigatórios."""
        run_id = uuid4()
        exec = ExecutionManifest(
            run_id=run_id,
            source_id="test_source",
            status=ExecutionStatus.PENDING,
            trigger="scheduled",
        )
        assert exec.run_id == run_id
        assert exec.source_id == "test_source"
        assert exec.trigger == "scheduled"
    
    def test_execution_default_status_is_pending(self):
        """Verifica que status padrão é PENDING."""
        exec = ExecutionManifest(
            run_id=uuid4(),
            source_id="test_source",
            trigger="scheduled",
        )
        assert exec.status == ExecutionStatus.PENDING
    
    def test_execution_stats_defaults_to_empty_dict(self):
        """Verifica que stats padrão é dict vazio."""
        exec = ExecutionManifest(
            run_id=uuid4(),
            source_id="test_source",
            trigger="scheduled",
        )
        assert exec.stats == {}


class TestExecutionManifestProperties:
    """Testes para propriedades de ExecutionManifest."""
    
    def test_is_active_returns_true_when_pending(self):
        """Verifica que is_active retorna True quando PENDING."""
        exec = ExecutionManifest(
            run_id=uuid4(),
            source_id="test_source",
            status=ExecutionStatus.PENDING,
            trigger="scheduled",
        )
        assert exec.is_active is True
    
    def test_is_active_returns_true_when_running(self):
        """Verifica que is_active retorna True quando RUNNING."""
        exec = ExecutionManifest(
            run_id=uuid4(),
            source_id="test_source",
            status=ExecutionStatus.RUNNING,
            trigger="scheduled",
        )
        assert exec.is_active is True
    
    def test_is_active_returns_false_when_success(self):
        """Verifica que is_active retorna False quando SUCCESS."""
        exec = ExecutionManifest(
            run_id=uuid4(),
            source_id="test_source",
            status=ExecutionStatus.SUCCESS,
            trigger="scheduled",
        )
        assert exec.is_active is False
    
    def test_is_success_returns_true_when_success(self):
        """Verifica que is_success retorna True quando SUCCESS."""
        exec = ExecutionManifest(
            run_id=uuid4(),
            source_id="test_source",
            status=ExecutionStatus.SUCCESS,
            trigger="scheduled",
        )
        assert exec.is_success is True
    
    def test_is_success_returns_true_when_partial_success(self):
        """Verifica que is_success retorna True quando PARTIAL_SUCCESS."""
        exec = ExecutionManifest(
            run_id=uuid4(),
            source_id="test_source",
            status=ExecutionStatus.PARTIAL_SUCCESS,
            trigger="scheduled",
        )
        assert exec.is_success is True
    
    def test_is_success_returns_false_when_failed(self):
        """Verifica que is_success retorna False quando FAILED."""
        exec = ExecutionManifest(
            run_id=uuid4(),
            source_id="test_source",
            status=ExecutionStatus.FAILED,
            trigger="scheduled",
        )
        assert exec.is_success is False
    
    def test_has_error_returns_true_when_failed(self):
        """Verifica que has_error retorna True quando FAILED."""
        exec = ExecutionManifest(
            run_id=uuid4(),
            source_id="test_source",
            status=ExecutionStatus.FAILED,
            trigger="scheduled",
        )
        assert exec.has_error is True
    
    def test_has_error_returns_true_when_cancelled(self):
        """Verifica que has_error retorna True quando CANCELLED."""
        exec = ExecutionManifest(
            run_id=uuid4(),
            source_id="test_source",
            status=ExecutionStatus.CANCELLED,
            trigger="scheduled",
        )
        assert exec.has_error is True
    
    def test_has_error_returns_false_when_success(self):
        """Verifica que has_error retorna False quando SUCCESS."""
        exec = ExecutionManifest(
            run_id=uuid4(),
            source_id="test_source",
            status=ExecutionStatus.SUCCESS,
            trigger="scheduled",
        )
        assert exec.has_error is False


class TestExecutionStatusEnum:
    """Testes para enum ExecutionStatus."""
    
    def test_status_values(self):
        """Verifica valores do enum."""
        assert ExecutionStatus.PENDING.value == "pending"
        assert ExecutionStatus.RUNNING.value == "running"
        assert ExecutionStatus.SUCCESS.value == "success"
        assert ExecutionStatus.PARTIAL_SUCCESS.value == "partial_success"
        assert ExecutionStatus.FAILED.value == "failed"
        assert ExecutionStatus.CANCELLED.value == "cancelled"


class TestExecutionManifestRepr:
    """Testes para representação string de ExecutionManifest."""
    
    def test_repr_contains_run_id(self):
        """Verifica que repr contém run_id."""
        run_id = uuid4()
        exec = ExecutionManifest(
            run_id=run_id,
            source_id="test_source",
            status=ExecutionStatus.PENDING,
            trigger="scheduled",
        )
        repr_str = repr(exec)
        assert str(run_id) in repr_str
    
    def test_repr_contains_source_id(self):
        """Verifica que repr contém source_id."""
        exec = ExecutionManifest(
            run_id=uuid4(),
            source_id="my_source",
            status=ExecutionStatus.PENDING,
            trigger="scheduled",
        )
        repr_str = repr(exec)
        assert "my_source" in repr_str
    
    def test_repr_contains_status(self):
        """Verifica que repr contém status."""
        exec = ExecutionManifest(
            run_id=uuid4(),
            source_id="test_source",
            status=ExecutionStatus.RUNNING,
            trigger="scheduled",
        )
        repr_str = repr(exec)
        assert "running" in repr_str
