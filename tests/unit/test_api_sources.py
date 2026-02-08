"""Testes unitários para API de fontes.

Testa endpoints de fontes da API REST.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from gabi.api.sources import (
    list_sources,
    get_source,
    sync_source,
    get_source_status,
)
from gabi.schemas.sources import (
    SourceListResponse,
    SourceDetail,
    SourceSyncRequest,
    SourceSyncResponse,
    SourceStatusResponse,
)
from gabi.models.source import SourceRegistry
from gabi.types import SourceType, SourceStatus, SensitivityLevel


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_source():
    """Fonte de exemplo."""
    return SourceRegistry(
        id="test_source",
        name="Test Source",
        type=SourceType.API,
        status=SourceStatus.ACTIVE,
        config_hash="abc123",
        config_json={},
        owner_email="admin@tcu.gov.br",
        sensitivity=SensitivityLevel.INTERNAL,
        document_count=100,
        total_documents_ingested=150,
        consecutive_errors=0,
        retention_days=365,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def mock_db_session():
    """Mock de sessão do banco."""
    session = AsyncMock(spec=AsyncSession)
    return session


# =============================================================================
# List Sources Tests
# =============================================================================

class TestListSources:
    """Testes para list_sources."""
    
    @pytest.mark.asyncio
    async def test_list_sources_returns_response(self, mock_db_session):
        """Verifica que list_sources retorna SourceListResponse."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar_one_or_none.return_value = 0
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        response = await list_sources(db=mock_db_session)
        
        assert isinstance(response, SourceListResponse)
        assert response.total == 0
        assert response.sources == []
    
    @pytest.mark.asyncio
    async def test_list_sources_with_status_filter(self, mock_db_session, sample_source):
        """Verifica que list_sources filtra por status."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_source]
        mock_result.scalar_one_or_none.return_value = 1
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        response = await list_sources(
            status=SourceStatus.ACTIVE,
            db=mock_db_session,
        )
        
        assert response.total == 1
        assert response.sources[0].id == "test_source"
    
    @pytest.mark.asyncio
    async def test_list_sources_excludes_deleted(self, mock_db_session, sample_source):
        """Verifica que list_sources exclui deletados por padrão."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_source]
        mock_result.scalar_one_or_none.return_value = 1
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        response = await list_sources(db=mock_db_session)
        
        assert response.total == 1


# =============================================================================
# Get Source Tests
# =============================================================================

class TestGetSource:
    """Testes para get_source."""
    
    @pytest.mark.asyncio
    async def test_get_source_returns_detail(self, mock_db_session, sample_source):
        """Verifica que get_source retorna SourceDetail."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_source
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        response = await get_source(
            source_id="test_source",
            db=mock_db_session,
        )
        
        assert isinstance(response, SourceDetail)
        assert response.id == "test_source"
        assert response.name == "Test Source"
    
    @pytest.mark.asyncio
    async def test_get_source_not_found_raises_404(self, mock_db_session):
        """Verifica que get_source levanta 404 quando não encontrado."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        with pytest.raises(HTTPException) as exc_info:
            await get_source(source_id="NOT-EXISTENT", db=mock_db_session)
        
        assert exc_info.value.status_code == 404


# =============================================================================
# Sync Source Tests
# =============================================================================

class TestSyncSource:
    """Testes para sync_source."""
    
    @pytest.mark.asyncio
    async def test_sync_source_success(self, mock_db_session, sample_source):
        """Verifica que sync_source inicia sincronização."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_source
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        request = SourceSyncRequest(
            mode="full",
            force=False,
        )
        
        response = await sync_source(
            source_id="test_source",
            request=request,
            db=mock_db_session,
        )
        
        assert isinstance(response, SourceSyncResponse)
        assert response.success is True
        assert response.source_id == "test_source"
        mock_db_session.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_sync_source_not_found_raises_404(self, mock_db_session):
        """Verifica que sync_source levanta 404 quando fonte não existe."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        request = SourceSyncRequest(mode="full")
        
        with pytest.raises(HTTPException) as exc_info:
            await sync_source(
                source_id="NOT-EXISTENT",
                request=request,
                db=mock_db_session,
            )
        
        assert exc_info.value.status_code == 404
    
    @pytest.mark.asyncio
    async def test_sync_disabled_source_raises_400(self, mock_db_session, sample_source):
        """Verifica que sync_source levanta 400 para fonte desabilitada."""
        sample_source.status = SourceStatus.DISABLED
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_source
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        request = SourceSyncRequest(mode="full")
        
        with pytest.raises(HTTPException) as exc_info:
            await sync_source(
                source_id="test_source",
                request=request,
                db=mock_db_session,
            )
        
        assert exc_info.value.status_code == 400
    
    @pytest.mark.asyncio
    async def test_sync_deleted_source_raises_400(self, mock_db_session, sample_source):
        """Verifica que sync_source levanta 400 para fonte deletada."""
        sample_source.deleted_at = datetime.now(timezone.utc)
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_source
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        request = SourceSyncRequest(mode="full")
        
        with pytest.raises(HTTPException) as exc_info:
            await sync_source(
                source_id="test_source",
                request=request,
                db=mock_db_session,
            )
        
        assert exc_info.value.status_code == 400


# =============================================================================
# Get Source Status Tests
# =============================================================================

class TestGetSourceStatus:
    """Testes para get_source_status."""
    
    @pytest.mark.asyncio
    async def test_get_source_status_returns_response(self, mock_db_session, sample_source):
        """Verifica que get_source_status retorna SourceStatusResponse."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_source
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        response = await get_source_status(
            source_id="test_source",
            db=mock_db_session,
        )
        
        assert isinstance(response, SourceStatusResponse)
        assert response.source_id == "test_source"
        assert response.is_healthy is True
        assert response.document_count == 100
    
    @pytest.mark.asyncio
    async def test_get_source_status_unhealthy_source(self, mock_db_session, sample_source):
        """Verifica que get_source_status retorna is_healthy=False para fonte com erros."""
        sample_source.consecutive_errors = 5
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_source
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        response = await get_source_status(
            source_id="test_source",
            db=mock_db_session,
        )
        
        assert response.is_healthy is False
    
    @pytest.mark.asyncio
    async def test_get_source_status_not_found_raises_404(self, mock_db_session):
        """Verifica que get_source_status levanta 404 quando fonte não existe."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        with pytest.raises(HTTPException) as exc_info:
            await get_source_status(
                source_id="NOT-EXISTENT",
                db=mock_db_session,
            )
        
        assert exc_info.value.status_code == 404
