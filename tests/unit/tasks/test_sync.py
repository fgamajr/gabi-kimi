"""Tests for sync tasks.

Verifica tasks de sincronização de fontes.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gabi.tasks.sync import (
    _add_document_to_dlq,
    _add_to_dlq,
    _build_error_summary,
    _check_duplicate,
    _classify_runtime_error,
    _get_source,
    _index_document,
    _run_discovery,
    _run_fetch,
    _run_parse,
    process_document_task,
    sync_source_task,
)


class TestSyncSourceTask:
    """Test suite para sync_source_task."""
    
    def test_task_registered(self):
        """Task deve estar registrada no Celery."""
        from gabi.worker import celery_app
        
        assert "gabi.tasks.sync.sync_source_task" in celery_app.tasks
    
    def test_task_configuration(self):
        """Verifica configuração da task."""
        task = sync_source_task
        
        assert task.name == "gabi.tasks.sync.sync_source_task"
        assert task.queue == "gabi.sync"
        assert task.max_retries == 3
        assert task.default_retry_delay == 60
        assert task.time_limit == 3600 * 6  # 6 horas
    
    @patch("gabi.tasks.sync._run_sync_pipeline")
    @patch("gabi.tasks.sync._add_to_dlq")
    def test_sync_success(self, mock_add_dlq, mock_pipeline):
        """Sync bem-sucedido retorna resultado correto."""
        mock_pipeline.return_value = {
            "urls_discovered": 10,
            "documents_indexed": 5,
        }
        
        result = sync_source_task.run("tcu_acordaos")
        
        assert result["status"] == "success"
        assert result["source_id"] == "tcu_acordaos"
        assert "run_id" in result
        assert "duration_seconds" in result
        assert result["urls_discovered"] == 10
        assert result["documents_indexed"] == 5
    
    @patch("gabi.tasks.sync._run_sync_pipeline")
    @patch("gabi.tasks.sync._add_to_dlq")
    def test_sync_failure_triggers_dlq(self, mock_add_dlq, mock_pipeline):
        """Falha de sync adiciona à DLQ."""
        mock_pipeline.side_effect = Exception("Pipeline error")
        mock_add_dlq.return_value = None
        
        with pytest.raises(Exception, match="Pipeline error"):
            sync_source_task.run("tcu_acordaos")
        
        mock_add_dlq.assert_called_once()


class TestRunDiscovery:
    """Test suite para _run_discovery."""
    
    @pytest.fixture
    async def mock_discovery_result(self):
        """Fixture para resultado de discovery."""
        from gabi.pipeline.contracts import DiscoveredURL, DiscoveryResult
        
        return DiscoveryResult(
            urls=[
                DiscoveredURL(
                    url="https://example.com/data.csv",
                    source_id="test_source",
                ),
            ],
            total_found=1,
            filtered_out=0,
            duration_seconds=0.5,
        )
    
    @pytest.mark.asyncio
    async def test_run_discovery(self, mock_discovery_result):
        """Discovery deve retornar URLs descobertas."""
        with patch(
            "gabi.tasks.sync.DiscoveryEngine.discover",
            return_value=mock_discovery_result,
        ):
            result = await _run_discovery("test_source", {"discovery": {}})
            
            assert result.total_found == 1
            assert len(result.urls) == 1
            assert result.urls[0].url == "https://example.com/data.csv"


class TestRunFetch:
    """Test suite para _run_fetch."""
    
    @pytest.mark.asyncio
    async def test_run_fetch(self):
        """Fetch deve baixar conteúdo."""
        from gabi.pipeline.contracts import DiscoveredURL, FetchMetadata, FetchedContent
        
        discovered = DiscoveredURL(
            url="https://example.com/test.csv",
            source_id="test_source",
        )
        
        mock_content = FetchedContent(
            url="https://example.com/test.csv",
            content=b"id,name\n1,test",
            metadata=FetchMetadata(
                url="https://example.com/test.csv",
                status_code=200,
                content_type="text/csv",
            ),
            fingerprint="abc123",
        )
        
        mock_fetcher = MagicMock()
        mock_fetcher.fetch = AsyncMock(return_value=mock_content)
        
        result = await _run_fetch(mock_fetcher, discovered, {"method": "GET"})
        
        assert result.url == "https://example.com/test.csv"
        assert result.content == b"id,name\n1,test"
        mock_fetcher.fetch.assert_called_once_with(
            url="https://example.com/test.csv",
            source_id="test_source",
            method="GET",
            headers=None,
        )


class TestRunParse:
    """Test suite para _run_parse."""
    
    @pytest.mark.asyncio
    async def test_run_parse_csv(self):
        """Parse CSV deve extrair documentos."""
        from gabi.pipeline.contracts import FetchMetadata, FetchedContent, ParseResult
        
        fetched = FetchedContent(
            url="https://example.com/data.csv",
            content=b"KEY,NAME\n1,Test",
            metadata=FetchMetadata(
                url="https://example.com/data.csv",
                content_type="text/csv",
            ),
        )
        
        with patch("gabi.tasks.sync.get_parser") as mock_get_parser:
            mock_parser = MagicMock()
            mock_parser.parse = AsyncMock(return_value=ParseResult(
                documents=[],
                raw_content_size=20,
                parsed_content_size=10,
            ))
            mock_get_parser.return_value = mock_parser
            
            result = await _run_parse(fetched, "test_source")
            
            assert result.raw_content_size == 20
            mock_get_parser.assert_called_once_with("csv")


class TestCheckDuplicate:
    """Test suite para _check_duplicate."""
    
    @pytest.mark.asyncio
    async def test_is_duplicate(self):
        """Deve detectar duplicata."""
        from gabi.pipeline.contracts import DuplicateCheckResult
        
        mock_dedup = MagicMock()
        mock_dedup.check_duplicate = AsyncMock(return_value=DuplicateCheckResult(
            is_duplicate=True,
            existing_document_id="doc_123",
            fingerprint="abc123",
        ))
        
        result = await _check_duplicate(mock_dedup, "abc123")
        
        assert result is True
        mock_dedup.check_duplicate.assert_called_once_with("abc123")
    
    @pytest.mark.asyncio
    async def test_is_not_duplicate(self):
        """Deve permitir documento novo."""
        from gabi.pipeline.contracts import DuplicateCheckResult
        
        mock_dedup = MagicMock()
        mock_dedup.check_duplicate = AsyncMock(return_value=DuplicateCheckResult(
            is_duplicate=False,
            fingerprint="abc123",
        ))
        
        result = await _check_duplicate(mock_dedup, "abc123")
        
        assert result is False


class TestIndexDocument:
    """Test suite para _index_document."""
    
    @pytest.mark.asyncio
    async def test_index_document(self):
        """Deve indexar documento no PostgreSQL."""
        from gabi.pipeline.contracts import ParsedDocument
        from gabi.pipeline.chunker import ChunkingResult
        
        mock_session = AsyncMock()
        
        parsed_doc = ParsedDocument(
            document_id="doc_123",
            source_id="test_source",
            title="Test Document",
            content="Test content",
            content_hash="hash123",
        )
        
        chunking_result = ChunkingResult(
            chunks=[],
            document_id="doc_123",
        )
        
        await _index_document(
            mock_session,
            parsed_doc,
            chunking_result,
            "test_source",
            str(uuid.uuid4()),
        )
        
        assert mock_session.merge.call_count + mock_session.add.call_count >= 1
        mock_session.commit.assert_called_once()


class TestAddToDLQ:
    """Test suite para funções de DLQ."""
    
    @pytest.mark.asyncio
    async def test_add_to_dlq(self):
        """Deve adicionar mensagem à DLQ."""
        mock_session = AsyncMock()
        
        with patch("gabi.tasks.sync.get_session") as mock_get_session:
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)
            
            await _add_to_dlq("test_source", str(uuid.uuid4()), "Error message", "task_123")
            
            mock_session.add.assert_called_once()
            mock_session.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_add_document_to_dlq(self):
        """Deve adicionar erro de documento à DLQ."""
        mock_session = AsyncMock()
        
        await _add_document_to_dlq(
            mock_session,
            "test_source",
            str(uuid.uuid4()),
            "doc_123",
            "Processing error",
            "https://example.com/doc",
        )
        
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()


class TestProcessDocumentTask:
    """Test suite para process_document_task."""
    
    def test_task_registered(self):
        """Task deve estar registrada."""
        from gabi.worker import celery_app
        
        assert "gabi.tasks.sync.process_document_task" in celery_app.tasks
    
    def test_task_configuration(self):
        """Verifica configuração da task."""
        task = process_document_task
        
        assert task.name == "gabi.tasks.sync.process_document_task"
        assert task.queue == "gabi.sync"


class TestGetSource:
    """Test suite para _get_source."""
    
    @pytest.mark.asyncio
    async def test_get_source_found(self):
        """Deve retornar fonte quando existe."""
        from gabi.models.source import SourceRegistry, SourceStatus, SourceType
        
        mock_source = SourceRegistry(
            id="test_source",
            name="Test Source",
            type=SourceType.API,
            status=SourceStatus.ACTIVE,
            config_hash="hash123",
            config_json={},
            owner_email="test@example.com",
        )
        
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_source
        mock_session.execute.return_value = mock_result
        
        result = await _get_source(mock_session, "test_source")
        
        assert result is not None
        assert result.id == "test_source"
    
    @pytest.mark.asyncio
    async def test_get_source_not_found(self):
        """Deve retornar None quando não existe."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        
        result = await _get_source(mock_session, "nonexistent")
        
        assert result is None


class TestErrorClassification:
    """Testes para classificação de erros do relatório."""

    def test_classifies_external_unreachable(self):
        classification = _classify_runtime_error(
            "Max retries exceeded: Network error: [Errno -5] No address associated with hostname",
            "https://api.stf.jus.br/decisoes.csv",
        )
        assert classification == "source_unreachable_external"

    def test_classifies_embedding_backend_unavailable(self):
        classification = _classify_runtime_error(
            "embedding_failed: Failed to connect to TEI after 4 attempts"
        )
        assert classification == "embedding_backend_unavailable"

    def test_build_error_summary(self):
        summary = _build_error_summary(
            [
                {
                    "error": "embedding_failed: Failed to connect to TEI after 4 attempts",
                },
                {
                    "error": "Max retries exceeded: Network error: [Errno -5] No address associated with hostname",
                    "url": "https://api.stj.jus.br/acordaos/2020.csv",
                },
            ]
        )
        assert summary["embedding_backend_unavailable"] == 1
        assert summary["source_unreachable_external"] == 1
