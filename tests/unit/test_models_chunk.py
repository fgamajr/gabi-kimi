"""Testes unitários para o modelo DocumentChunk.

Testa propriedades, métodos e comportamentos do modelo de chunks.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from uuid import uuid4

from gabi.models.chunk import DocumentChunk


class TestDocumentChunkCreation:
    """Testes para criação de DocumentChunk."""
    
    def test_chunk_creation_with_required_fields(self):
        """Verifica criação com campos obrigatórios."""
        chunk = DocumentChunk(
            document_id="TCU-TEST-001",
            chunk_index=0,
            chunk_text="Texto do chunk",
            token_count=10,
            char_count=14,
        )
        assert chunk.document_id == "TCU-TEST-001"
        assert chunk.chunk_index == 0
        assert chunk.chunk_text == "Texto do chunk"
    
    def test_chunk_defaults_metadata_to_empty_dict(self):
        """Verifica que metadata padrão é dict vazio."""
        chunk = DocumentChunk(
            document_id="TCU-TEST-001",
            chunk_index=0,
            chunk_text="Texto",
            token_count=5,
            char_count=5,
            chunk_metadata={},
        )
        assert chunk.chunk_metadata == {}


class TestDocumentChunkEmbedding:
    """Testes para embeddings de DocumentChunk."""
    
    def test_embedding_defaults_to_none(self):
        """Verifica que embedding padrão é None."""
        chunk = DocumentChunk(
            document_id="TCU-TEST-001",
            chunk_index=0,
            chunk_text="Texto",
            token_count=5,
            char_count=5,
        )
        assert chunk.embedding is None
    
    def test_embedding_dimensions_must_be_384(self):
        """Verifica que embedding deve ter 384 dimensões."""
        # O modelo aceita Vector(384)
        from pgvector.sqlalchemy import Vector
        # Verificamos que o tipo é Vector(384)
        assert isinstance(DocumentChunk.embedding.property.columns[0].type, Vector)
        assert DocumentChunk.embedding.property.columns[0].type.dim == 384
    
    def test_embedding_model_stores_model_name(self):
        """Verifica que embedding_model armazena nome do modelo."""
        chunk = DocumentChunk(
            document_id="TCU-TEST-001",
            chunk_index=0,
            chunk_text="Texto",
            token_count=5,
            char_count=5,
            embedding_model="sentence-transformers/test-model",
        )
        assert chunk.embedding_model == "sentence-transformers/test-model"


class TestDocumentChunkToDict:
    """Testes para método to_dict de DocumentChunk."""
    
    def test_to_dict_returns_dict(self):
        """Verifica que to_dict retorna um dicionário."""
        chunk = DocumentChunk(
            document_id="TCU-TEST-001",
            chunk_index=0,
            chunk_text="Texto do chunk",
            token_count=10,
            char_count=14,
        )
        result = chunk.to_dict()
        assert isinstance(result, dict)
    
    def test_to_dict_contains_required_fields(self):
        """Verifica que to_dict contém campos obrigatórios."""
        chunk = DocumentChunk(
            document_id="TCU-TEST-001",
            chunk_index=0,
            chunk_text="Texto do chunk",
            token_count=10,
            char_count=14,
        )
        result = chunk.to_dict()
        assert "id" in result
        assert "document_id" in result
        assert "chunk_index" in result
        assert "chunk_text" in result
        assert "token_count" in result
        assert "char_count" in result
    
    def test_to_dict_contains_has_embedding(self):
        """Verifica que to_dict contém has_embedding."""
        chunk = DocumentChunk(
            document_id="TCU-TEST-001",
            chunk_index=0,
            chunk_text="Texto",
            token_count=5,
            char_count=5,
        )
        result = chunk.to_dict()
        assert "has_embedding" in result
        assert result["has_embedding"] is False
    
    def test_to_dict_does_not_contain_actual_embedding(self):
        """Verifica que to_dict não contém o embedding vetorial."""
        chunk = DocumentChunk(
            document_id="TCU-TEST-001",
            chunk_index=0,
            chunk_text="Texto",
            token_count=5,
            char_count=5,
        )
        result = chunk.to_dict()
        assert "embedding" not in result


class TestDocumentChunkConstraints:
    """Testes para constraints de DocumentChunk."""
    
    def test_unique_constraint_document_chunk_index(self):
        """Verifica que há constraint única para document_id + chunk_index."""
        from sqlalchemy import UniqueConstraint
        constraints = DocumentChunk.__table_args__
        assert any(
            isinstance(constraint, UniqueConstraint) and 
            any(col.name == "document_id" for col in constraint.columns) and
            any(col.name == "chunk_index" for col in constraint.columns)
            for constraint in constraints
        )
    
    def test_document_id_is_foreign_key(self):
        """Verifica que document_id é foreign key."""
        from sqlalchemy import ForeignKey
        fk = DocumentChunk.document_id.property.columns[0].foreign_keys
        assert len(fk) > 0


class TestDocumentChunkRepr:
    """Testes para representação string de DocumentChunk."""
    
    def test_repr_contains_document_id(self):
        """Verifica que repr contém document_id."""
        chunk = DocumentChunk(
            document_id="TCU-TEST-001",
            chunk_index=0,
            chunk_text="Texto",
            token_count=5,
            char_count=5,
        )
        repr_str = repr(chunk)
        assert "TCU-TEST-001" in repr_str
    
    def test_repr_contains_chunk_index(self):
        """Verifica que repr contém chunk_index."""
        chunk = DocumentChunk(
            document_id="TCU-TEST-001",
            chunk_index=5,
            chunk_text="Texto",
            token_count=5,
            char_count=5,
        )
        repr_str = repr(chunk)
        assert "chunk_index=5" in repr_str
    
    def test_repr_contains_has_embedding_status(self):
        """Verifica que repr indica se tem embedding."""
        chunk = DocumentChunk(
            document_id="TCU-TEST-001",
            chunk_index=0,
            chunk_text="Texto",
            token_count=5,
            char_count=5,
        )
        repr_str = repr(chunk)
        assert "has_embedding=False" in repr_str
