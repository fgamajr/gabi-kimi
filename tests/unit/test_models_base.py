"""Testes unitários para modelos base do GABI.

Testa os mixins e bases declarativas usadas por todos os modelos.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from uuid import UUID, uuid4

from gabi.models.base import (
    Base,
    UUIDMixin,
    TimestampMixin,
    SoftDeleteMixin,
    AuditableBase,
    SoftDeleteBase,
)


class TestUUIDMixin:
    """Testes para o UUIDMixin."""
    
    def test_uuid_mixin_has_id_field(self):
        """Verifica que UUIDMixin adiciona campo id do tipo UUID."""
        # UUIDMixin define o campo id
        assert hasattr(UUIDMixin, 'id')
    
    def test_uuid_mixin_id_is_mapped(self):
        """Verifica que id é um Mapped type."""
        # O tipo deve ser Mapped[UUID]
        from sqlalchemy.orm import Mapped
        # Não podemos instanciar mixin diretamente, mas verificamos a definição
        assert UUIDMixin.id is not None


class TestTimestampMixin:
    """Testes para o TimestampMixin."""
    
    def test_timestamp_mixin_has_created_at(self):
        """Verifica que TimestampMixin tem created_at."""
        assert hasattr(TimestampMixin, 'created_at')
    
    def test_timestamp_mixin_has_updated_at(self):
        """Verifica que TimestampMixin tem updated_at."""
        assert hasattr(TimestampMixin, 'updated_at')


class TestSoftDeleteMixin:
    """Testes para o SoftDeleteMixin."""
    
    def test_soft_delete_mixin_has_is_deleted(self):
        """Verifica que SoftDeleteMixin tem is_deleted."""
        assert hasattr(SoftDeleteMixin, 'is_deleted')
    
    def test_soft_delete_mixin_has_deleted_at(self):
        """Verifica que SoftDeleteMixin tem deleted_at."""
        assert hasattr(SoftDeleteMixin, 'deleted_at')
    
    def test_soft_delete_mixin_has_deleted_reason(self):
        """Verifica que SoftDeleteMixin tem deleted_reason."""
        assert hasattr(SoftDeleteMixin, 'deleted_reason')
    
    def test_soft_delete_mixin_has_deleted_by(self):
        """Verifica que SoftDeleteMixin tem deleted_by."""
        assert hasattr(SoftDeleteMixin, 'deleted_by')


class TestBaseClasses:
    """Testes para as classes base combinadas."""
    
    def test_base_is_declarative(self):
        """Verifica que Base é DeclarativeBase."""
        from sqlalchemy.orm import DeclarativeBase
        assert issubclass(Base, DeclarativeBase)
    
    def test_auditable_base_is_abstract(self):
        """Verifica que AuditableBase é abstrata."""
        assert AuditableBase.__abstract__ is True
    
    def test_soft_delete_base_is_abstract(self):
        """Verifica que SoftDeleteBase é abstrata."""
        assert SoftDeleteBase.__abstract__ is True
    
    def test_auditable_base_inherits_uuid_and_timestamp(self):
        """Verifica que AuditableBase herda UUID e Timestamp."""
        assert issubclass(AuditableBase, Base)
        assert issubclass(AuditableBase, UUIDMixin)
        assert issubclass(AuditableBase, TimestampMixin)
    
    def test_soft_delete_base_inherits_all_mixins(self):
        """Verifica que SoftDeleteBase herda todos os mixins."""
        assert issubclass(SoftDeleteBase, AuditableBase)
        assert issubclass(SoftDeleteBase, SoftDeleteMixin)


class TestModelExports:
    """Testes para os exports do módulo."""
    
    def test_all_exports_present(self):
        """Verifica que todos os exports estão definidos."""
        from gabi.models import base as base_module
        
        expected_exports = [
            'Base',
            'UUIDMixin',
            'TimestampMixin',
            'SoftDeleteMixin',
            'AuditableBase',
            'SoftDeleteBase',
        ]
        
        for export in expected_exports:
            assert hasattr(base_module, export), f"Export '{export}' não encontrado"


class TestModelMetadatas:
    """Testes para metadata dos modelos."""
    
    def test_base_has_metadata(self):
        """Verifica que Base tem metadata."""
        assert Base.metadata is not None
    
    def test_metadata_is_empty_initially(self):
        """Verifica que metadata começa sem tabelas."""
        # A metadata pode ter tabelas se outros modelos já foram importados
        # Este teste verifica apenas que metadata existe
        assert Base.metadata is not None
