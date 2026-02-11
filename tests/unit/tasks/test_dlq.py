"""Tests for DLQ tasks.

Verifica tasks de gerenciamento da Dead Letter Queue.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gabi.models.dlq import DLQStatus
from gabi.tasks.dlq import (
    _get_dlq_stats,
    _get_message,
    _process_dlq_message,
    _process_pending_messages,
    _resolve_message,
    _retry_document_processing,
    _retry_fetch,
    _retry_parse,
    _retry_sync_failed,
    _update_dlq_failure,
    get_dlq_stats_task,
    process_pending_dlq_task,
    resolve_dlq_task,
    retry_dlq_task,
)


class TestRetryDLQTask:
    """Test suite para retry_dlq_task."""
    
    def test_task_registered(self):
        """Task deve estar registrada no Celery."""
        from gabi.worker import celery_app
        
        assert "gabi.tasks.dlq.retry_dlq_task" in celery_app.tasks
    
    def test_task_configuration(self):
        """Verifica configuração da task."""
        task = retry_dlq_task
        
        assert task.name == "gabi.tasks.dlq.retry_dlq_task"
        assert task.queue == "gabi.dlq"
        assert task.max_retries == 0  # DLQ tem sua própria lógica
        assert task.time_limit == 1800  # 30 minutos
    
    @patch("gabi.tasks.dlq._process_dlq_message")
    def test_retry_success(self, mock_process):
        """Retry bem-sucedido."""
        mock_process.return_value = {
            "message_id": "test-uuid",
            "status": "success",
        }
        
        result = retry_dlq_task.run("test-uuid")
        
        assert result["status"] == "success"
        mock_process.assert_called_once_with("test-uuid")
    
    @patch("gabi.tasks.dlq._update_dlq_failure")
    @patch("gabi.tasks.dlq._process_dlq_message")
    def test_retry_failure_updates_dlq(self, mock_process, mock_update):
        """Falha de retry atualiza DLQ."""
        mock_process.side_effect = Exception("Processing failed")
        mock_update.return_value = None
        
        with pytest.raises(Exception):
            retry_dlq_task.run("test-uuid")
        
        mock_update.assert_called_once()


class TestProcessPendingDLQTask:
    """Test suite para process_pending_dlq_task."""
    
    def test_task_registered(self):
        """Task deve estar registrada."""
        from gabi.worker import celery_app
        
        assert "gabi.tasks.dlq.process_pending_dlq_task" in celery_app.tasks
    
    def test_task_configuration(self):
        """Verifica configuração."""
        task = process_pending_dlq_task
        
        assert task.name == "gabi.tasks.dlq.process_pending_dlq_task"
        assert task.queue == "gabi.dlq"
    
    @patch("gabi.tasks.dlq._process_pending_messages")
    def test_process_batch(self, mock_process):
        """Processa batch de mensagens."""
        mock_process.return_value = {
            "total_checked": 10,
            "processed": 5,
            "succeeded": 4,
            "failed": 1,
        }
        
        result = process_pending_dlq_task.run(max_messages=100)
        
        assert result["total_checked"] == 10
        assert result["succeeded"] == 4
    
    def test_with_source_filter(self):
        """Filtra por source_id."""
        with patch("gabi.tasks.dlq._process_pending_messages") as mock_process:
            mock_process.return_value = {"total_checked": 0}
            
            process_pending_dlq_task.run(max_messages=50, source_id="tcu_acordaos")
            
            mock_process.assert_called_once_with(50, "tcu_acordaos")


class TestResolveDLQTask:
    """Test suite para resolve_dlq_task."""
    
    def test_task_registered(self):
        """Task deve estar registrada."""
        from gabi.worker import celery_app
        
        assert "gabi.tasks.dlq.resolve_dlq_task" in celery_app.tasks
    
    @patch("gabi.tasks.dlq._resolve_message")
    def test_resolve_success(self, mock_resolve):
        """Resolução bem-sucedida."""
        mock_resolve.return_value = {
            "message_id": "test-uuid",
            "status": "resolved",
            "resolved_by": "admin",
        }
        
        result = resolve_dlq_task.run("test-uuid", "admin", "Fixed manually")
        
        assert result["status"] == "resolved"
        mock_resolve.assert_called_once_with("test-uuid", "admin", "Fixed manually")


class TestGetDLQStatsTask:
    """Test suite para get_dlq_stats_task."""
    
    def test_task_registered(self):
        """Task deve estar registrada."""
        from gabi.worker import celery_app
        
        assert "gabi.tasks.dlq.get_dlq_stats_task" in celery_app.tasks
    
    @patch("gabi.tasks.dlq._get_dlq_stats")
    def test_get_stats(self, mock_stats):
        """Retorna estatísticas."""
        mock_stats.return_value = {
            "total": 100,
            "by_status": {"pending": 10, "exhausted": 5},
        }
        
        result = get_dlq_stats_task.run()
        
        assert result["total"] == 100
        assert result["by_status"]["pending"] == 10


class TestGetMessage:
    """Test suite para _get_message."""
    
    @pytest.mark.asyncio
    async def test_get_message_found(self):
        """Deve retornar mensagem quando existe."""
        from gabi.models.dlq import DLQMessage
        
        message_id = str(uuid.uuid4())
        mock_message = DLQMessage(
            id=uuid.UUID(message_id),
            source_id="test_source",
            url="https://example.com",
            error_type="test_error",
            error_message="Test error",
        )
        
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_message
        mock_session.execute.return_value = mock_result
        
        result = await _get_message(mock_session, message_id)
        
        assert result is not None
        assert str(result.id) == message_id
    
    @pytest.mark.asyncio
    async def test_get_message_not_found(self):
        """Deve retornar None quando não existe."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        
        result = await _get_message(mock_session, str(uuid.uuid4()))
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_get_message_invalid_uuid(self):
        """Deve retornar None para UUID inválido."""
        mock_session = AsyncMock()
        
        result = await _get_message(mock_session, "invalid-uuid")
        
        assert result is None
        mock_session.execute.assert_not_called()


class TestProcessDLQMessage:
    """Test suite para _process_dlq_message."""
    
    @pytest.mark.asyncio
    async def test_message_not_found(self):
        """Deve lançar erro quando mensagem não existe."""
        with patch("gabi.tasks.dlq._get_message") as mock_get, \
             patch("gabi.tasks.dlq.get_session") as mock_get_session:
            mock_get.return_value = None
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)
            
            with pytest.raises(ValueError, match="not found"):
                await _process_dlq_message("nonexistent")
    
    @pytest.mark.asyncio
    async def test_message_cannot_retry(self):
        """Deve lançar erro quando mensagem não pode ser reprocessada."""
        from gabi.models.dlq import DLQMessage
        
        mock_message = MagicMock()
        mock_message.can_retry = False
        mock_message.status = DLQStatus.EXHAUSTED
        mock_message.retry_count = 5
        mock_message.max_retries = 5
        
        with patch("gabi.tasks.dlq._get_message") as mock_get, \
             patch("gabi.tasks.dlq.get_session") as mock_get_session:
            mock_get.return_value = mock_message
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)
            
            with pytest.raises(ValueError, match="cannot be retried"):
                await _process_dlq_message(str(uuid.uuid4()))


class TestUpdateDLQFailure:
    """Test suite para _update_dlq_failure."""
    
    @pytest.mark.asyncio
    async def test_update_failure(self):
        """Deve atualizar mensagem com erro."""
        from gabi.models.dlq import DLQMessage
        
        mock_message = MagicMock()
        mock_message.can_retry = True
        mock_message.error_message = "Original error"
        
        with patch("gabi.tasks.dlq._get_message") as mock_get, \
             patch("gabi.tasks.dlq.get_session") as mock_get_session:
            
            mock_get.return_value = mock_message
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)
            
            await _update_dlq_failure(str(uuid.uuid4()), "New error")
            
            assert "New error" in mock_message.error_message
            mock_session.commit.assert_called_once()


class TestResolveMessage:
    """Test suite para _resolve_message."""
    
    @pytest.mark.asyncio
    async def test_resolve_success(self):
        """Deve marcar mensagem como resolvida."""
        from gabi.models.dlq import DLQMessage
        
        mock_message = MagicMock()
        mock_message.resolve = MagicMock()
        mock_message.resolved_at = datetime.now(timezone.utc)
        
        with patch("gabi.tasks.dlq._get_message") as mock_get, \
             patch("gabi.tasks.dlq.get_session") as mock_get_session:
            
            mock_get.return_value = mock_message
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await _resolve_message(
                str(uuid.uuid4()),
                "admin",
                "Fixed the issue",
            )
            
            assert result["status"] == "resolved"
            mock_message.resolve.assert_called_once_with("admin", "Fixed the issue")


class TestProcessPendingMessages:
    """Test suite para _process_pending_messages."""
    
    @pytest.mark.asyncio
    async def test_no_pending_messages(self):
        """Deve retornar stats vazio quando não há mensagens."""
        with patch("gabi.tasks.dlq.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_session.execute.return_value = mock_result
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await _process_pending_messages(100)
            
            assert result["total_checked"] == 0
    
    @pytest.mark.asyncio
    async def test_skip_non_retryable(self):
        """Deve pular mensagens que não podem ser reprocessadas."""
        from gabi.models.dlq import DLQMessage
        
        mock_message = MagicMock()
        mock_message.can_retry = False
        mock_message.id = uuid.uuid4()
        
        with patch("gabi.tasks.dlq.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [mock_message]
            mock_session.execute.return_value = mock_result
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await _process_pending_messages(100)
            
            assert result["skipped"] == 1


class TestRetryHandlers:
    """Test suite para handlers de retry."""
    
    @pytest.mark.asyncio
    async def test_retry_sync_failed(self):
        """Deve retriggerar sync para erro de sync."""
        from gabi.models.dlq import DLQMessage
        from gabi.tasks.sync import sync_source_task
        
        mock_message = MagicMock()
        mock_message.payload = {"task_id": "task_123"}
        mock_message.source_id = "test_source"
        
        with patch.object(sync_source_task, "delay") as mock_delay:
            mock_result = MagicMock()
            mock_result.id = "new_task_123"
            mock_delay.return_value = mock_result
            
            result = await _retry_sync_failed(AsyncMock(), mock_message)
            
            assert result["status"] == "success"
            assert result["action"] == "retriggered_sync"
    
    @pytest.mark.asyncio
    async def test_retry_document_processing(self):
        """Deve retornar manual resolution required."""
        from gabi.models.dlq import DLQMessage
        
        mock_message = MagicMock()
        mock_message.payload = {"document_id": "doc_123"}
        mock_message.document_id = "doc_123"
        
        result = await _retry_document_processing(AsyncMock(), mock_message)
        
        assert result["status"] == "manual_resolution_required"
    
    @pytest.mark.asyncio
    async def test_retry_fetch(self):
        """Deve tentar refetch da URL."""
        from gabi.models.dlq import DLQMessage
        from gabi.pipeline.contracts import FetchMetadata, FetchedContent
        
        mock_message = MagicMock()
        mock_message.url = "https://example.com/data.csv"
        mock_message.source_id = "test_source"
        
        with patch("gabi.tasks.dlq.ContentFetcher") as MockFetcher:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch = AsyncMock(return_value=FetchedContent(
                url="https://example.com/data.csv",
                content=b"test",
                metadata=FetchMetadata(url="https://example.com/data.csv"),
            ))
            mock_fetcher.close = AsyncMock()
            MockFetcher.return_value = mock_fetcher
            
            result = await _retry_fetch(AsyncMock(), mock_message)
            
            assert result["status"] == "success"
            assert result["action"] == "refetched"
    
    @pytest.mark.asyncio
    async def test_retry_parse(self):
        """Deve retornar manual resolution required."""
        result = await _retry_parse(AsyncMock(), MagicMock())
        
        assert result["status"] == "manual_resolution_required"


class TestGetDLQStats:
    """Test suite para _get_dlq_stats."""
    
    @pytest.mark.asyncio
    async def test_empty_stats(self):
        """Stats vazio quando não há mensagens."""
        with patch("gabi.tasks.dlq.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_session.execute.return_value = mock_result
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await _get_dlq_stats()
            
            assert result["total"] == 0
            assert result["ready_for_retry"] == 0
    
    @pytest.mark.asyncio
    async def test_stats_by_status(self):
        """Deve agrupar por status."""
        from gabi.models.dlq import DLQMessage, DLQStatus
        
        mock_msg_pending = MagicMock()
        mock_msg_pending.status = DLQStatus.PENDING
        mock_msg_pending.error_type = "test"
        mock_msg_pending.can_retry = True
        mock_msg_pending.next_retry_at = None
        
        mock_msg_exhausted = MagicMock()
        mock_msg_exhausted.status = DLQStatus.EXHAUSTED
        mock_msg_exhausted.error_type = "test"
        mock_msg_exhausted.can_retry = False
        mock_msg_exhausted.next_retry_at = None
        
        with patch("gabi.tasks.dlq.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [
                mock_msg_pending,
                mock_msg_exhausted,
            ]
            mock_session.execute.return_value = mock_result
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await _get_dlq_stats()
            
            assert result["total"] == 2
            assert result["by_status"]["pending"] == 1
            assert result["by_status"]["exhausted"] == 1
