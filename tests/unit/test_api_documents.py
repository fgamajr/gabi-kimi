"""Testes unitários para API de documentos.

Testa endpoints de documentos da API REST.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from gabi.api.documents import (
    list_documents,
    get_document,
    reindex_document,
    delete_document,
)
from gabi.schemas.documents import (
    DocumentReindexRequest,
    DocumentListResponse,
    DocumentDetailResponse,
)
from gabi.models.document import Document
from gabi.types import DocumentStatus


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_document():
    """Documento de exemplo."""
    return Document(
        id=str(uuid4()),
        document_id="TCU-TEST-001",
        source_id="test_source",
        fingerprint="abc123",
        title="Test Document",
        content_preview="Preview...",
        status=DocumentStatus.ACTIVE,
        is_deleted=False,
        version=1,
        chunks_count=5,
        es_indexed=True,
        doc_metadata={"year": 2024},
        ingested_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def mock_db_session():
    """Mock de sessão do banco."""
    session = AsyncMock(spec=AsyncSession)
    return session


# =============================================================================
# List Documents Tests
# =============================================================================

class TestListDocuments:
    """Testes para list_documents."""
    
    @pytest.mark.asyncio
    async def test_list_documents_returns_response(self, mock_db_session):
        """Verifica que list_documents retorna DocumentListResponse."""
        # Mock execute
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar_one.return_value = 0
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        response = await list_documents(db=mock_db_session)
        
        assert isinstance(response, DocumentListResponse)
        assert response.total == 0
        assert response.documents == []
    
    @pytest.mark.asyncio
    async def test_list_documents_with_filters(self, mock_db_session, sample_document):
        """Verifica que list_documents aplica filtros."""
        # Mock execute
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_document]
        mock_result.scalar_one.return_value = 1
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        response = await list_documents(
            source_id="test_source",
            status=DocumentStatus.ACTIVE,
            db=mock_db_session,
        )
        
        assert response.total == 1
        assert len(response.documents) == 1
        assert response.documents[0].document_id == "TCU-TEST-001"
    
    @pytest.mark.asyncio
    async def test_list_documents_pagination(self, mock_db_session):
        """Verifica que list_documents suporta paginação."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar_one.return_value = 0
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        response = await list_documents(
            page=2,
            page_size=10,
            db=mock_db_session,
        )
        
        assert response.page == 2
        assert response.page_size == 10


# =============================================================================
# Get Document Tests
# =============================================================================

class TestGetDocument:
    """Testes para get_document."""
    
    @pytest.mark.asyncio
    async def test_get_document_returns_detail(self, mock_db_session, sample_document):
        """Verifica que get_document retorna DocumentDetailResponse."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_document
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        response = await get_document(
            document_id="TCU-TEST-001",
            db=mock_db_session,
        )
        
        assert isinstance(response, DocumentDetailResponse)
        assert response.document.document_id == "TCU-TEST-001"
    
    @pytest.mark.asyncio
    async def test_get_document_not_found_raises_404(self, mock_db_session):
        """Verifica que get_document levanta 404 quando não encontrado."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        with pytest.raises(HTTPException) as exc_info:
            await get_document(document_id="NOT-EXISTENT", db=mock_db_session)
        
        assert exc_info.value.status_code == 404
    
    @pytest.mark.asyncio
    async def test_get_document_by_uuid(self, mock_db_session, sample_document):
        """Verifica que get_document aceita UUID."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_document
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        response = await get_document(
            document_id=sample_document.id,
            db=mock_db_session,
        )
        
        assert response.document.id == sample_document.id


# =============================================================================
# Reindex Document Tests
# =============================================================================

class TestReindexDocument:
    """Testes para reindex_document."""
    
    @pytest.mark.asyncio
    async def test_reindex_document_success(self, mock_db_session, sample_document):
        """Verifica que reindex_document marca para reindexação."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_document
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        request = DocumentReindexRequest(force=True)
        
        response = await reindex_document(
            document_id="TCU-TEST-001",
            request=request,
            db=mock_db_session,
        )
        
        assert response.success is True
        assert response.document_id == "TCU-TEST-001"
        mock_db_session.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_reindex_document_not_found_raises_404(self, mock_db_session):
        """Verifica que reindex_document levanta 404 quando não encontrado."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        request = DocumentReindexRequest(force=True)
        
        with pytest.raises(HTTPException) as exc_info:
            await reindex_document(
                document_id="NOT-EXISTENT",
                request=request,
                db=mock_db_session,
            )
        
        assert exc_info.value.status_code == 404
    
    @pytest.mark.asyncio
    async def test_reindex_deleted_document_raises_400(self, mock_db_session, sample_document):
        """Verifica que reindex_document levanta 400 para documento deletado."""
        sample_document.is_deleted = True
        sample_document.status = DocumentStatus.DELETED
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_document
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        request = DocumentReindexRequest(force=True)
        
        with pytest.raises(HTTPException) as exc_info:
            await reindex_document(
                document_id="TCU-TEST-001",
                request=request,
                db=mock_db_session,
            )
        
        assert exc_info.value.status_code == 400
    
    @pytest.mark.asyncio
    async def test_reindex_without_force_checks_needs_reindex(self, mock_db_session, sample_document):
        """Verifica que reindex sem force verifica se precisa reindexar."""
        sample_document.es_indexed = True
        sample_document.es_indexed_at = datetime.now(timezone.utc)
        sample_document.updated_at = sample_document.es_indexed_at
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_document
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        request = DocumentReindexRequest(force=False)
        
        response = await reindex_document(
            document_id="TCU-TEST-001",
            request=request,
            db=mock_db_session,
        )
        
        # Documento já está atualizado
        assert response.success is True


# =============================================================================
# Delete Document Tests
# =============================================================================

class TestDeleteDocument:
    """Testes para delete_document."""
    
    @pytest.mark.asyncio
    async def test_delete_document_success(self, mock_db_session, sample_document):
        """Verifica que delete_document executa soft delete."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_document
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        response = await delete_document(
            document_id="TCU-TEST-001",
            reason="Dados obsoletos",
            deleted_by="admin@tcu.gov.br",
            db=mock_db_session,
        )
        
        assert response.success is True
        assert response.document_id == "TCU-TEST-001"
        assert sample_document.is_deleted is True
        mock_db_session.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_delete_document_not_found_raises_404(self, mock_db_session):
        """Verifica que delete_document levanta 404 quando não encontrado."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        with pytest.raises(HTTPException) as exc_info:
            await delete_document(
                document_id="NOT-EXISTENT",
                db=mock_db_session,
            )
        
        assert exc_info.value.status_code == 404
    
    @pytest.mark.asyncio
    async def test_delete_already_deleted_raises_400(self, mock_db_session, sample_document):
        """Verifica que delete_document levanta 400 para documento já deletado."""
        sample_document.is_deleted = True
        sample_document.status = DocumentStatus.DELETED
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_document
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        with pytest.raises(HTTPException) as exc_info:
            await delete_document(
                document_id="TCU-TEST-001",
                db=mock_db_session,
            )
        
        assert exc_info.value.status_code == 400
