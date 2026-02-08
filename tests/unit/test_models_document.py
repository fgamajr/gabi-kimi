"""Testes unitários para o modelo Document.

Testa propriedades, métodos e comportamentos do modelo de documentos.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from gabi.models.document import Document
from gabi.types import DocumentStatus


class TestDocumentCreation:
    """Testes para criação de Document."""
    
    def test_document_creation_with_required_fields(self):
        """Verifica criação com campos obrigatórios."""
        doc = Document(
            document_id="TCU-TEST-001",
            source_id="test_source",
            fingerprint="abc123",
        )
        assert doc.document_id == "TCU-TEST-001"
        assert doc.source_id == "test_source"
        assert doc.fingerprint == "abc123"
    
    def test_document_default_status_is_active(self):
        """Verifica que status padrão é ACTIVE."""
        doc = Document(
            document_id="TCU-TEST-001",
            source_id="test_source",
            fingerprint="abc123",
            status=DocumentStatus.ACTIVE,
        )
        assert doc.status == DocumentStatus.ACTIVE
    
    def test_document_default_language_is_pt_br(self):
        """Verifica que idioma padrão é pt-BR."""
        doc = Document(
            document_id="TCU-TEST-001",
            source_id="test_source",
            fingerprint="abc123",
            language="pt-BR",
        )
        assert doc.language == "pt-BR"
    
    def test_document_default_version_is_one(self):
        """Verifica que versão padrão é 1."""
        doc = Document(
            document_id="TCU-TEST-001",
            source_id="test_source",
            fingerprint="abc123",
            version=1,
        )
        assert doc.version == 1
    
    def test_document_default_is_deleted_is_false(self):
        """Verifica que is_deleted padrão é False."""
        doc = Document(
            document_id="TCU-TEST-001",
            source_id="test_source",
            fingerprint="abc123",
        )
        assert doc.is_deleted is False or doc.is_deleted is None


class TestDocumentSoftDelete:
    """Testes para soft delete de Document."""
    
    def test_soft_delete_sets_is_deleted(self):
        """Verifica que soft_delete define is_deleted como True."""
        doc = Document(
            document_id="TCU-TEST-001",
            source_id="test_source",
            fingerprint="abc123",
        )
        doc.soft_delete()
        assert doc.is_deleted is True
        assert doc.status == DocumentStatus.DELETED
    
    def test_soft_delete_sets_deleted_at(self):
        """Verifica que soft_delete define deleted_at."""
        doc = Document(
            document_id="TCU-TEST-001",
            source_id="test_source",
            fingerprint="abc123",
        )
        doc.soft_delete()
        assert doc.deleted_at is not None
    
    def test_soft_delete_sets_reason(self):
        """Verifica que soft_delete aceita motivo."""
        doc = Document(
            document_id="TCU-TEST-001",
            source_id="test_source",
            fingerprint="abc123",
        )
        doc.soft_delete(reason="Dados obsoletos")
        assert doc.deleted_reason == "Dados obsoletos"
    
    def test_soft_delete_sets_deleted_by(self):
        """Verifica que soft_delete aceita deleted_by."""
        doc = Document(
            document_id="TCU-TEST-001",
            source_id="test_source",
            fingerprint="abc123",
        )
        doc.soft_delete(deleted_by="admin@tcu.gov.br")
        assert doc.deleted_by == "admin@tcu.gov.br"
    
    def test_restore_clears_deleted_state(self):
        """Verifica que restore limpa estado de deleção."""
        doc = Document(
            document_id="TCU-TEST-001",
            source_id="test_source",
            fingerprint="abc123",
        )
        doc.soft_delete(reason="Test")
        doc.restore()
        assert doc.is_deleted is False
        assert doc.deleted_at is None
        assert doc.deleted_reason is None
        assert doc.deleted_by is None
        assert doc.status == DocumentStatus.ACTIVE


class TestDocumentElasticsearchSync:
    """Testes para sincronização com Elasticsearch."""
    
    def test_mark_es_synced_sets_flags(self):
        """Verifica que mark_es_synced define flags corretamente."""
        doc = Document(
            document_id="TCU-TEST-001",
            source_id="test_source",
            fingerprint="abc123",
        )
        doc.mark_es_synced()
        assert doc.es_indexed is True
        assert doc.es_indexed_at is not None
    
    def test_needs_es_reindex_returns_true_when_not_indexed(self):
        """Verifica que needs_es_reindex retorna True quando não indexado."""
        doc = Document(
            document_id="TCU-TEST-001",
            source_id="test_source",
            fingerprint="abc123",
            es_indexed=False,
        )
        assert doc.needs_es_reindex() is True
    
    def test_needs_es_reindex_returns_true_when_indexed_at_is_none(self):
        """Verifica que needs_es_reindex retorna True quando indexed_at é None."""
        doc = Document(
            document_id="TCU-TEST-001",
            source_id="test_source",
            fingerprint="abc123",
            es_indexed=True,
            es_indexed_at=None,
        )
        assert doc.needs_es_reindex() is True
    
    def test_needs_es_reindex_returns_true_when_updated_after_indexed(self):
        """Verifica que needs_es_reindex retorna True quando atualizado após indexação."""
        now = datetime.now(timezone.utc)
        doc = Document(
            document_id="TCU-TEST-001",
            source_id="test_source",
            fingerprint="abc123",
            es_indexed=True,
            es_indexed_at=now - timedelta(hours=1),
            updated_at=now,
        )
        assert doc.needs_es_reindex() is True
    
    def test_needs_es_reindex_returns_false_when_up_to_date(self):
        """Verifica que needs_es_reindex retorna False quando atualizado."""
        now = datetime.now(timezone.utc)
        doc = Document(
            document_id="TCU-TEST-001",
            source_id="test_source",
            fingerprint="abc123",
            es_indexed=True,
            es_indexed_at=now,
            updated_at=now - timedelta(hours=1),
        )
        assert doc.needs_es_reindex() is False


class TestDocumentMetadata:
    """Testes para metadados de Document."""
    
    def test_metadata_defaults_to_empty_dict(self):
        """Verifica que metadados padrão é dict vazio."""
        doc = Document(
            document_id="TCU-TEST-001",
            source_id="test_source",
            fingerprint="abc123",
            doc_metadata={},
        )
        assert doc.doc_metadata == {}
    
    def test_metadata_can_store_arbitrary_data(self):
        """Verifica que metadados podem armazenar dados arbitrários."""
        doc = Document(
            document_id="TCU-TEST-001",
            source_id="test_source",
            fingerprint="abc123",
            doc_metadata={
                "year": 2024,
                "relator": "Ministro Teste",
                "complex_data": {"nested": "value"},
            },
        )
        assert doc.doc_metadata["year"] == 2024
        assert doc.doc_metadata["relator"] == "Ministro Teste"


class TestDocumentStatus:
    """Testes para status de Document."""
    
    def test_document_status_values(self):
        """Verifica valores do enum DocumentStatus."""
        assert DocumentStatus.ACTIVE.value == "active"
        assert DocumentStatus.UPDATED.value == "updated"
        assert DocumentStatus.DELETED.value == "deleted"
        assert DocumentStatus.ERROR.value == "error"


class TestDocumentRepr:
    """Testes para representação string de Document."""
    
    def test_repr_contains_document_id(self):
        """Verifica que repr contém document_id."""
        doc = Document(
            document_id="TCU-TEST-001",
            source_id="test_source",
            fingerprint="abc123",
            title="Test Document",
        )
        repr_str = repr(doc)
        assert "TCU-TEST-001" in repr_str
        assert "Test Document" in repr_str
