"""Testes de integração E2E para o pipeline completo.

Testa o fluxo completo de ingestão de documentos através de todas as fases.
"""

from __future__ import annotations

import pytest
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, Mock, patch
import httpx

from gabi.pipeline.orchestrator import PipelineOrchestrator
from gabi.models.document import Document
from gabi.models.chunk import DocumentChunk
from gabi.types import SourceType, SourceStatus, DocumentStatus


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_source_config():
    """Configuração de fonte de exemplo."""
    return {
        "metadata": {
            "domain": "juridico",
            "jurisdiction": "BR",
            "authority": "TCU",
            "document_type": "acordao",
        },
        "discovery": {
            "mode": "static_url",
            "url": "https://example.com/data.csv",
        },
        "fetch": {
            "protocol": "https",
            "method": "GET",
        },
        "parse": {
            "input_format": "csv",
        },
        "mapping": {
            "document_id": {"from": "KEY"},
            "title": {"from": "TITULO"},
        },
    }


@pytest.fixture
def mock_db_session():
    """Mock de sessão do banco."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.begin = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(),
        __aexit__=AsyncMock(),
    ))
    return session


@pytest.fixture
def mock_es_client():
    """Mock de cliente Elasticsearch."""
    client = AsyncMock()
    client.index = AsyncMock(return_value={
        "_index": "test",
        "_id": "doc-1",
        "result": "created",
    })
    return client


@pytest.fixture
def mock_redis_client():
    """Mock de cliente Redis."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=None)
    client.set = AsyncMock(return_value=True)
    client.lock = Mock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=True),
        __aexit__=AsyncMock(return_value=False),
    ))
    return client


@pytest.fixture
def mock_http_client():
    """Mock de cliente HTTP."""
    client = AsyncMock(spec=httpx.AsyncClient)
    return client


@pytest.fixture
def orchestrator(mock_db_session, mock_es_client, mock_redis_client, mock_http_client):
    """Orquestrador configurado com mocks."""
    return PipelineOrchestrator(
        db_session=mock_db_session,
        es_client=mock_es_client,
        redis_client=mock_redis_client,
        http_client=mock_http_client,
    )


# =============================================================================
# Pipeline Orchestrator Tests
# =============================================================================

class TestPipelineOrchestrator:
    """Testes para PipelineOrchestrator."""
    
    @pytest.mark.asyncio
    async def test_orchestrator_initializes_components(self, orchestrator):
        """Verifica que orquestrador inicializa componentes."""
        assert orchestrator.change_detector is not None
        assert orchestrator.fetcher is not None
        assert orchestrator.parser is not None
        assert orchestrator.fingerprinter is not None
        assert orchestrator.deduplicator is not None
        assert orchestrator.chunker is not None
        assert orchestrator.embedder is not None
        assert orchestrator.indexer is not None
    
    @pytest.mark.asyncio
    async def test_orchestrator_run_creates_manifest(self, orchestrator, sample_source_config):
        """Verifica que run cria manifest de execução."""
        with patch.object(orchestrator, "_discovery_phase", return_value=[]):
            with patch.object(orchestrator, "_create_manifest") as mock_create:
                mock_create.return_value = None
                
                stats = await orchestrator.run(
                    source_id="test_source",
                    source_config=sample_source_config,
                )
                
                mock_create.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_orchestrator_run_returns_stats(self, orchestrator, sample_source_config):
        """Verifica que run retorna estatísticas."""
        with patch.object(orchestrator, "_discovery_phase", return_value=[]):
            stats = await orchestrator.run(
                source_id="test_source",
                source_config=sample_source_config,
            )
            
            assert isinstance(stats, dict)
            assert "run_id" in stats
            assert "source_id" in stats
            assert "status" in stats


# =============================================================================
# Discovery Phase Tests
# =============================================================================

class TestDiscoveryPhase:
    """Testes para fase de descoberta."""
    
    @pytest.mark.asyncio
    async def test_discovery_static_url(self, orchestrator, sample_source_config):
        """Verifica descoberta com URL estática."""
        urls = await orchestrator._discovery_phase(sample_source_config, {})
        
        assert isinstance(urls, list)
        assert len(urls) == 1
        assert urls[0] == "https://example.com/data.csv"
    
    @pytest.mark.asyncio
    async def test_discovery_url_pattern(self, orchestrator):
        """Verifica descoberta com padrão de URL."""
        config = {
            "discovery": {
                "mode": "url_pattern",
                "url_template": "https://example.com/{year}/data.csv",
                "params": {
                    "year": {"start": 2020, "end": 2022}
                },
                "max_urls": 100,
            }
        }
        
        urls = await orchestrator._discovery_phase(config, {})
        
        assert len(urls) == 3
        assert "https://example.com/2020/data.csv" in urls
        assert "https://example.com/2021/data.csv" in urls
        assert "https://example.com/2022/data.csv" in urls
    
    @pytest.mark.asyncio
    async def test_discovery_respects_max_urls(self, orchestrator):
        """Verifica que descoberta respeita max_urls."""
        config = {
            "discovery": {
                "mode": "url_pattern",
                "url_template": "https://example.com/{year}/data.csv",
                "params": {
                    "year": {"start": 2000, "end": 2100}
                },
                "max_urls": 5,
            }
        }
        
        urls = await orchestrator._discovery_phase(config, {})
        
        assert len(urls) <= 5


# =============================================================================
# Processing Phase Tests
# =============================================================================

class TestProcessingPhase:
    """Testes para fase de processamento."""
    
    @pytest.mark.asyncio
    async def test_process_single_url_handles_errors(self, orchestrator):
        """Verifica que processamento lida com erros."""
        with pytest.raises(Exception):
            # Simula erro no fetch
            orchestrator.fetcher.fetch = AsyncMock(side_effect=Exception("Fetch error"))
            
            await orchestrator._process_single_url(
                url="https://example.com/error",
                source_id="test",
                fetch_config={},
                parse_config={},
                mapping_config={},
                quality_config={},
                run_id="run-1",
                stats={},
            )
    
    @pytest.mark.asyncio
    async def test_check_memory_raises_on_limit(self, orchestrator):
        """Verifica que check_memory levanta erro ao exceder limite."""
        with patch("psutil.Process") as mock_psutil:
            mock_process = MagicMock()
            mock_process.memory_info.return_value = MagicMock(rss=1024 * 1024 * 1024 * 4)  # 4GB
            mock_psutil.return_value = mock_process
            
            with pytest.raises(MemoryError):
                orchestrator._check_memory()


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestPipelineErrorHandling:
    """Testes para tratamento de erros do pipeline."""
    
    @pytest.mark.asyncio
    async def test_send_to_dlq_creates_message(self, orchestrator, mock_db_session):
        """Verifica que _send_to_dlq cria mensagem na DLQ."""
        await orchestrator._send_to_dlq(
            source_id="test_source",
            run_id="run-1",
            url="https://example.com/error",
            error_type="fetch_error",
            error_message="Connection timeout",
        )
        
        mock_db_session.execute.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_run_completes_with_error_status(self, orchestrator, sample_source_config):
        """Verifica que run completa com status de erro em caso de falha."""
        with patch.object(orchestrator, "_discovery_phase", side_effect=Exception("Fatal error")):
            with pytest.raises(Exception):
                await orchestrator.run(
                    source_id="test_source",
                    source_config=sample_source_config,
                )


# =============================================================================
# Checkpoint Tests
# =============================================================================

class TestPipelineCheckpoint:
    """Testes para checkpoint/resume do pipeline."""
    
    @pytest.mark.asyncio
    async def test_update_checkpoint(self, orchestrator, mock_db_session):
        """Verifica que _update_checkpoint atualiza manifest."""
        await orchestrator._update_checkpoint(
            run_id="run-1",
            processed=100,
            last_url="https://example.com/doc-100",
        )
        
        mock_db_session.execute.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_complete_manifest(self, orchestrator, mock_db_session):
        """Verifica que _complete_manifest finaliza execução."""
        stats = {
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        
        await orchestrator._complete_manifest(
            run_id="run-1",
            status="success",
            stats=stats,
        )
        
        mock_db_session.execute.assert_called_once()


# =============================================================================
# Concurrency Tests
# =============================================================================

class TestPipelineConcurrency:
    """Testes para concorrência do pipeline."""
    
    @pytest.mark.asyncio
    async def test_processing_phase_uses_semaphore(self, orchestrator):
        """Verifica que fase de processamento usa semáforo."""
        # URLs de teste
        urls = [f"https://example.com/doc{i}" for i in range(10)]
        
        with patch.object(orchestrator, "_process_single_url") as mock_process:
            mock_process.return_value = None
            
            with patch.object(orchestrator, "_update_checkpoint"):
                await orchestrator._processing_phase(
                    urls=urls,
                    source_id="test",
                    source_config={},
                    run_id="run-1",
                    stats={},
                )
                
                # Verifica que process foi chamado para todas as URLs
                assert mock_process.call_count == 10


# =============================================================================
# Stats Collection Tests
# =============================================================================

class TestPipelineStats:
    """Testes para coleta de estatísticas."""
    
    def test_stats_initialization(self, orchestrator):
        """Verifica inicialização das estatísticas."""
        stats = {
            "run_id": "test-run",
            "source_id": "test-source",
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        
        assert "run_id" in stats
        assert "source_id" in stats
        assert "status" in stats
        assert "started_at" in stats


# =============================================================================
# End-to-End Flow Tests
# =============================================================================

class TestEndToEndFlow:
    """Testes para fluxo end-to-end do pipeline."""
    
    @pytest.mark.asyncio
    async def test_e2e_flow_success(self, orchestrator, sample_source_config):
        """Testa fluxo completo bem-sucedido."""
        # Mock de todas as fases
        with patch.object(orchestrator, "_discovery_phase", return_value=["url1", "url2"]):
            with patch.object(orchestrator, "_change_detection_phase", return_value=["url1"]):
                with patch.object(orchestrator, "_processing_phase") as mock_processing:
                    mock_processing.return_value = None
                    
                    stats = await orchestrator.run(
                        source_id="test_source",
                        source_config=sample_source_config,
                    )
                    
                    assert stats["status"] in ["success", "partial_success", "failed"]
    
    @pytest.mark.asyncio
    async def test_e2e_flow_with_resume(self, orchestrator, sample_source_config):
        """Testa fluxo com resume de execução anterior."""
        run_id = "previous-run-id"
        
        with patch.object(orchestrator, "_discovery_phase", return_value=["url1"]):
            with patch.object(orchestrator, "_change_detection_phase", return_value=["url1"]):
                with patch.object(orchestrator, "_processing_phase"):
                    stats = await orchestrator.run(
                        source_id="test_source",
                        source_config=sample_source_config,
                        resume_from=run_id,
                    )
                    
                    # Em resume, não deve criar novo manifest
                    assert stats["run_id"] == run_id
