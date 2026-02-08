"""Testes unitários para API administrativa.

Testa endpoints administrativos da API REST.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from gabi.api.admin import (
    list_executions,
    get_execution,
    list_dlq,
    retry_dlq,
    get_system_stats,
)
from gabi.schemas.admin import (
    ExecutionListResponse,
    ExecutionDetail,
    DLQListResponse,
    DLQRetryRequest,
    DLQRetryResponse,
    SystemStatsResponse,
)
from gabi.models.execution import ExecutionManifest, ExecutionStatus
from gabi.models.dlq import DLQMessage, DLQStatus


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_execution():
    """Execução de exemplo."""
    return ExecutionManifest(
        run_id=uuid4(),
        source_id="test_source",
        status=ExecutionStatus.SUCCESS,
        trigger="scheduled",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        duration_seconds=120.5,
        stats={
            "urls_discovered": 10,
            "documents_indexed": 8,
            "documents_failed": 0,
        },
    )


@pytest.fixture
def sample_dlq_message():
    """Mensagem DLQ de exemplo."""
    return DLQMessage(
        id=uuid4(),
        source_id="test_source",
        url="https://example.com/doc.pdf",
        error_type="connection_error",
        error_message="Connection timeout",
        status=DLQStatus.PENDING,
        retry_count=0,
        max_retries=5,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def mock_db_session():
    """Mock de sessão do banco."""
    session = AsyncMock(spec=AsyncSession)
    return session


# =============================================================================
# List Executions Tests
# =============================================================================

class TestListExecutions:
    """Testes para list_executions."""
    
    @pytest.mark.asyncio
    async def test_list_executions_returns_response(self, mock_db_session):
        """Verifica que list_executions retorna ExecutionListResponse."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar_one_or_none.return_value = 0
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        response = await list_executions(db=mock_db_session, page=1, page_size=20)
        
        assert isinstance(response, ExecutionListResponse)
        assert response.total == 0
        assert response.executions == []
    
    @pytest.mark.asyncio
    async def test_list_executions_with_filters(self, mock_db_session, sample_execution):
        """Verifica que list_executions aplica filtros."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_execution]
        mock_result.scalar_one_or_none.return_value = 1
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        response = await list_executions(
            source_id="test_source",
            status=ExecutionStatus.SUCCESS,
            db=mock_db_session,
            page=1,
            page_size=20,
        )
        
        assert response.total == 1
        assert len(response.executions) == 1
        assert response.executions[0].source_id == "test_source"
    
    @pytest.mark.asyncio
    async def test_list_executions_pagination(self, mock_db_session):
        """Verifica que list_executions suporta paginação."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar_one_or_none.return_value = 0
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        response = await list_executions(
            page=2,
            page_size=10,
            db=mock_db_session,
        )
        
        assert response.page == 2
        assert response.page_size == 10


# =============================================================================
# Get Execution Tests
# =============================================================================

class TestGetExecution:
    """Testes para get_execution."""
    
    @pytest.mark.asyncio
    async def test_get_execution_returns_detail(self, mock_db_session, sample_execution):
        """Verifica que get_execution retorna ExecutionDetail."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_execution
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        response = await get_execution(
            run_id=sample_execution.run_id,
            db=mock_db_session,
        )
        
        assert isinstance(response, ExecutionDetail)
        assert response.run_id == sample_execution.run_id
        assert response.source_id == "test_source"
    
    @pytest.mark.asyncio
    async def test_get_execution_not_found_raises_404(self, mock_db_session):
        """Verifica que get_execution levanta 404 quando não encontrado."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        with pytest.raises(HTTPException) as exc_info:
            await get_execution(run_id=uuid4(), db=mock_db_session)
        
        assert exc_info.value.status_code == 404


# =============================================================================
# List DLQ Tests
# =============================================================================

class TestListDLQ:
    """Testes para list_dlq."""
    
    @pytest.mark.asyncio
    async def test_list_dlq_returns_response(self, mock_db_session):
        """Verifica que list_dlq retorna DLQListResponse."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar_one_or_none.return_value = 0
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        response = await list_dlq(db=mock_db_session, page=1, page_size=20)
        
        assert isinstance(response, DLQListResponse)
        assert response.total == 0
        assert response.messages == []
    
    @pytest.mark.asyncio
    async def test_list_dlq_with_status_filter(self, mock_db_session, sample_dlq_message):
        """Verifica que list_dlq filtra por status."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_dlq_message]
        mock_result.scalar_one_or_none.return_value = 1
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        response = await list_dlq(
            status=DLQStatus.PENDING,
            db=mock_db_session,
            page=1,
            page_size=20,
        )
        
        assert response.total == 1
    
    @pytest.mark.asyncio
    async def test_list_dlq_includes_status_counts(self, mock_db_session, sample_dlq_message):
        """Verifica que list_dlq inclui contagens por status."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_dlq_message]
        mock_result.scalar_one_or_none.return_value = 1
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        response = await list_dlq(db=mock_db_session, page=1, page_size=20)
        
        assert isinstance(response.by_status, dict)


# =============================================================================
# Retry DLQ Tests
# =============================================================================

class TestRetryDLQ:
    """Testes para retry_dlq."""
    
    @pytest.mark.asyncio
    async def test_retry_dlq_success(self, mock_db_session, sample_dlq_message):
        """Verifica que retry_dlq agenda retry."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_dlq_message
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        request = DLQRetryRequest(force=False, priority=True)
        
        response = await retry_dlq(
            message_id=sample_dlq_message.id,
            request=request,
            db=mock_db_session,
        )
        
        assert isinstance(response, DLQRetryResponse)
        assert response.success is True
        assert response.message_id == sample_dlq_message.id
        mock_db_session.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_retry_dlq_not_found_raises_404(self, mock_db_session):
        """Verifica que retry_dlq levanta 404 quando mensagem não existe."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        request = DLQRetryRequest()
        
        with pytest.raises(HTTPException) as exc_info:
            await retry_dlq(
                message_id=uuid4(),
                request=request,
                db=mock_db_session,
            )
        
        assert exc_info.value.status_code == 404
    
    @pytest.mark.asyncio
    async def test_retry_exhausted_without_force_raises_400(
        self, mock_db_session, sample_dlq_message
    ):
        """Verifica que retry_dlq levanta 400 para mensagem exhausted sem force."""
        sample_dlq_message.status = DLQStatus.EXHAUSTED
        sample_dlq_message.retry_count = 5
        sample_dlq_message.max_retries = 5
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_dlq_message
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        request = DLQRetryRequest(force=False)
        
        with pytest.raises(HTTPException) as exc_info:
            await retry_dlq(
                message_id=sample_dlq_message.id,
                request=request,
                db=mock_db_session,
            )
        
        assert exc_info.value.status_code == 400
    
    @pytest.mark.asyncio
    async def test_retry_resolved_raises_400(self, mock_db_session, sample_dlq_message):
        """Verifica que retry_dlq levanta 400 para mensagem resolvida."""
        sample_dlq_message.status = DLQStatus.RESOLVED
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_dlq_message
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        request = DLQRetryRequest()
        
        with pytest.raises(HTTPException) as exc_info:
            await retry_dlq(
                message_id=sample_dlq_message.id,
                request=request,
                db=mock_db_session,
            )
        
        assert exc_info.value.status_code == 400
    
    @pytest.mark.asyncio
    async def test_retry_with_force_ignores_exhausted(
        self, mock_db_session, sample_dlq_message
    ):
        """Verifica que retry_dlq ignora exhausted quando force=True."""
        sample_dlq_message.status = DLQStatus.EXHAUSTED
        sample_dlq_message.retry_count = 5
        sample_dlq_message.max_retries = 5
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_dlq_message
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        request = DLQRetryRequest(force=True)
        
        response = await retry_dlq(
            message_id=sample_dlq_message.id,
            request=request,
            db=mock_db_session,
        )
        
        assert response.success is True


# =============================================================================
# System Stats Tests
# =============================================================================

class TestSystemStats:
    """Testes para get_system_stats."""
    
    @pytest.mark.asyncio
    async def test_get_system_stats_returns_response(self, mock_db_session):
        """Verifica que get_system_stats retorna SystemStatsResponse."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = 0
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        response = await get_system_stats(db=mock_db_session)
        
        assert isinstance(response, SystemStatsResponse)
        assert response.stats.total_documents == 0
        assert response.stats.total_sources == 0
    
    @pytest.mark.asyncio
    async def test_get_system_stats_includes_all_metrics(self, mock_db_session):
        """Verifica que get_system_stats inclui todas as métricas."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = 0
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        response = await get_system_stats(db=mock_db_session)
        
        stats = response.stats
        assert hasattr(stats, 'total_documents')
        assert hasattr(stats, 'total_sources')
        assert hasattr(stats, 'total_chunks')
        assert hasattr(stats, 'active_sources')
        assert hasattr(stats, 'sources_in_error')
        assert hasattr(stats, 'dlq_pending')
        assert hasattr(stats, 'dlq_exhausted')
        assert hasattr(stats, 'executions_today')
        assert hasattr(stats, 'executions_failed_today')
