"""Testes unitários para o Embedder.

Coverage:
- Embedder core functionality
- Circuit breaker states
- Retry com exponential backoff
- Validação de dimensionalidade (ADR-001)
- EmbeddingService com cache e fallback
"""

import asyncio
import json
import pytest
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import aiohttp
from aiohttp import web

from gabi.pipeline.embedder import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitBreakerState,
    DimensionalityError,
    Embedder,
    EmbeddingError,
    RetryConfig,
    TEIConnectionError,
    TEIResponseError,
)
from gabi.pipeline.contracts import Chunk, EmbeddedChunk, EmbeddingResult
from gabi.services.embedding_service import (
    CacheConfig,
    EmbeddingMetrics,
    EmbeddingService,
    LocalEmbeddingBackend,
)


# =============================================================================
# Fixtures
# =============================================================================

def create_async_context_manager_mock(return_value=None):
    """Create a mock that supports async context manager protocol.
    
    Returns a mock that can be used with 'async with' and returns
    the specified value when entered.
    """
    mock = MagicMock()
    mock.__aenter__ = AsyncMock(return_value=return_value if return_value is not None else mock)
    mock.__aexit__ = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def mock_session():
    """Mock de sessão aiohttp."""
    session = AsyncMock(spec=aiohttp.ClientSession)
    return session


@pytest.fixture
def mock_response():
    """Mock de response aiohttp."""
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock()
    return response


@pytest.fixture
def sample_embeddings():
    """Sample de embeddings 384-dimensionais."""
    return [
        [0.1] * 384,
        [0.2] * 384,
        [0.3] * 384,
    ]


@pytest.fixture
def sample_chunks():
    """Sample de chunks."""
    return [
        Chunk(text="Texto de teste 1", index=0, token_count=10, char_count=20),
        Chunk(text="Texto de teste 2", index=1, token_count=15, char_count=25),
    ]


@pytest.fixture
def embedder_config():
    """Configuração de embedder para testes."""
    return {
        "base_url": "http://localhost:8080",
        "model": "sentence-transformers/test-model",
        "batch_size": 8,
        "timeout": 30,
        "max_retries": 2,
    }


# =============================================================================
# Circuit Breaker Tests
# =============================================================================

class TestCircuitBreaker:
    """Testes para Circuit Breaker."""
    
    @pytest.mark.asyncio
    async def test_circuit_starts_closed(self):
        """Circuit breaker começa no estado fechado."""
        cb = CircuitBreaker()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.is_closed
        assert not cb.is_open
    
    @pytest.mark.asyncio
    async def test_successful_call_increments_success(self):
        """Call bem-sucedida incrementa contador."""
        cb = CircuitBreaker()
        
        async def success_func():
            return "success"
        
        result = await cb.call(success_func)
        assert result == "success"
        assert cb._success_count == 1
    
    @pytest.mark.asyncio
    async def test_failure_increments_failure_count(self):
        """Falha incrementa contador de falhas."""
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3))
        
        async def fail_func():
            raise ValueError("error")
        
        with pytest.raises(ValueError):
            await cb.call(fail_func)
        
        assert cb._failure_count == 1
    
    @pytest.mark.asyncio
    async def test_circuit_opens_after_threshold(self):
        """Circuito abre após threshold de falhas."""
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=2))
        
        async def fail_func():
            raise ValueError("error")
        
        # Primeiras 2 falhas
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(fail_func)
        
        # Circuito deve estar aberto
        assert cb.state == CircuitBreakerState.OPEN
        assert cb.is_open
        
        # Próxima call deve falhar com CircuitBreakerOpenError
        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(fail_func)
    
    @pytest.mark.asyncio
    async def test_half_open_after_timeout(self):
        """Circuito entra em half-open após timeout, falha retorna para open."""
        cb = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0.1)
        )
        
        async def fail_func():
            raise ValueError("error")
        
        async def success_func():
            return "success"
        
        # Abre o circuito
        with pytest.raises(ValueError):
            await cb.call(fail_func)
        
        assert cb.state == CircuitBreakerState.OPEN
        
        # Aguarda timeout de recovery
        await asyncio.sleep(0.15)
        
        # Chama função que falha - deve tentar half-open mas voltar para open
        with pytest.raises(ValueError):
            await cb.call(fail_func)
        
        # Falha em half-open retorna para OPEN
        assert cb.state == CircuitBreakerState.OPEN
    
    @pytest.mark.asyncio
    async def test_success_in_half_open_closes_circuit(self):
        """Sucesso em half-open fecha o circuito."""
        cb = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=1,
                recovery_timeout=0.1,
                half_open_max_calls=1,
            )
        )
        
        async def fail_func():
            raise ValueError("error")
        
        async def success_func():
            return "success"
        
        # Abre o circuito
        with pytest.raises(ValueError):
            await cb.call(fail_func)
        
        await asyncio.sleep(0.15)
        
        # Sucesso em half-open fecha o circuito
        result = await cb.call(success_func)
        assert result == "success"
        assert cb.state == CircuitBreakerState.CLOSED
    
    @pytest.mark.asyncio
    async def test_failure_in_half_open_reopens_circuit(self):
        """Falha em half-open reabre o circuito."""
        cb = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0.1)
        )
        
        async def fail_func():
            raise ValueError("error")
        
        # Abre o circuito
        with pytest.raises(ValueError):
            await cb.call(fail_func)
        
        await asyncio.sleep(0.15)
        
        # Força para half-open e falha novamente
        with pytest.raises(ValueError):
            await cb.call(fail_func)
        
        # Deve estar aberto novamente
        assert cb.state == CircuitBreakerState.OPEN
    
    @pytest.mark.asyncio
    async def test_get_stats_returns_dict(self):
        """get_stats retorna dicionário com informações."""
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=5))
        
        stats = cb.get_stats()
        
        assert "state" in stats
        assert "failure_count" in stats
        assert "success_count" in stats
        assert "config" in stats
        assert stats["config"]["failure_threshold"] == 5


# =============================================================================
# Embedder Tests
# =============================================================================

class TestEmbedder:
    """Testes para Embedder."""
    
    @pytest.mark.asyncio
    async def test_embedder_initialization(self, embedder_config):
        """Embedder inicializa corretamente."""
        embedder = Embedder(**embedder_config)
        
        assert embedder.base_url == embedder_config["base_url"]
        assert embedder.model == embedder_config["model"]
        assert embedder.batch_size == embedder_config["batch_size"]
        assert embedder.EMBEDDING_DIMENSIONS == 384
    
    @pytest.mark.asyncio
    async def test_embedder_uses_default_settings(self):
        """Embedder usa settings quando não especificado."""
        embedder = Embedder()
        
        assert embedder.base_url == "http://localhost:8080"
        assert "sentence-transformers" in embedder.model
        assert embedder.EMBEDDING_DIMENSIONS == 384
    
    @pytest.mark.asyncio
    async def test_dimensionality_invariant(self):
        """Dimensionalidade é sempre 384 (ADR-001)."""
        embedder = Embedder()
        
        # Não deve ser possível alterar
        assert embedder.EMBEDDING_DIMENSIONS == 384
        
        # Tentar atribuir deve falhar (atributo de classe)
        with pytest.raises(AttributeError):
            embedder.EMBEDDING_DIMENSIONS = 768
    
    @pytest.mark.asyncio
    async def test_validate_embeddings_checks_count(self):
        """Validação verifica número de embeddings."""
        embedder = Embedder()
        embeddings = [[0.1] * 384, [0.2] * 384]
        
        # Deve passar
        embedder._validate_embeddings(embeddings, 2)
        
        # Deve falhar com count errado
        with pytest.raises(TEIResponseError) as exc_info:
            embedder._validate_embeddings(embeddings, 3)
        assert "Expected 3 embeddings" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_validate_embeddings_checks_dimensions(self):
        """Validação verifica dimensionalidade 384."""
        embedder = Embedder()
        
        # Embedding com dimensão errada
        wrong_embeddings = [[0.1] * 768]
        
        with pytest.raises(DimensionalityError) as exc_info:
            embedder._validate_embeddings(wrong_embeddings, 1)
        
        assert "384" in str(exc_info.value)
        assert "ADR-001" in str(exc_info.value)
        assert "768" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_validate_embeddings_correct(self):
        """Validação passa com embeddings corretos."""
        embedder = Embedder()
        correct_embeddings = [[0.1] * 384, [0.2] * 384, [0.3] * 384]
        
        # Não deve lançar exceção
        embedder._validate_embeddings(correct_embeddings, 3)
    
    @pytest.mark.asyncio
    async def test_embed_batch_empty_list(self):
        """Batch vazio retorna lista vazia."""
        embedder = Embedder()
        result = await embedder.embed_batch([])
        assert result == []
    
    @pytest.mark.asyncio
    async def test_embed_batch_all_empty_strings(self):
        """Todos textos vazios retornam zeros."""
        embedder = Embedder()
        result = await embedder.embed_batch(["", "   ", ""])
        
        assert len(result) == 3
        assert all(len(emb) == 384 for emb in result)
        assert all(all(v == 0.0 for v in emb) for emb in result)
    
    @pytest.mark.asyncio
    async def test_embed_batch_mixed_empty(self):
        """Textos vazios e não-vazios são tratados corretamente."""
        session = AsyncMock()
        response = AsyncMock()
        response.status = 200
        response.json = AsyncMock(return_value=[[0.1] * 384, [0.2] * 384])
        
        # session.post needs to return an async context manager
        session.post = MagicMock(return_value=create_async_context_manager_mock(response))
        session.closed = False
        
        embedder = Embedder(session=session)
        
        result = await embedder.embed_batch(["texto 1", "", "texto 2"])
        
        assert len(result) == 3
        assert len(result[0]) == 384  # texto 1
        assert len(result[1]) == 384  # vazio (zeros)
        assert len(result[2]) == 384  # texto 2
        assert all(v == 0.0 for v in result[1])  # Deve ser zeros
    
    @pytest.mark.asyncio
    async def test_embed_single_string(self):
        """embed() com string única."""
        session = AsyncMock()
        response = AsyncMock()
        response.status = 200
        response.json = AsyncMock(return_value=[[0.1] * 384])
        
        # session.post needs to return an async context manager
        session.post = MagicMock(return_value=create_async_context_manager_mock(response))
        session.closed = False
        
        embedder = Embedder(session=session)
        result = await embedder.embed("texto de teste")
        
        assert len(result) == 384
    
    @pytest.mark.asyncio
    async def test_embed_list_of_strings(self):
        """embed() com lista de strings."""
        session = AsyncMock()
        response = AsyncMock()
        response.status = 200
        response.json = AsyncMock(return_value=[[0.1] * 384, [0.2] * 384])
        
        # session.post needs to return an async context manager
        session.post = MagicMock(return_value=create_async_context_manager_mock(response))
        session.closed = False
        
        embedder = Embedder(session=session)
        result = await embedder.embed(["texto 1", "texto 2"])
        
        assert len(result) == 2
        assert len(result[0]) == 384
        assert len(result[1]) == 384
    
    @pytest.mark.asyncio
    async def test_retry_with_exponential_backoff(self):
        """Retry implementa exponential backoff."""
        embedder = Embedder(max_retries=3)
        
        # Testa cálculo de delay
        delays = [embedder._calculate_delay(i) for i in range(3)]
        
        # Delays devem crescer exponencialmente (com jitter)
        assert delays[0] < delays[1] < delays[2]
        assert delays[0] >= 1.0  # Base delay
        assert delays[2] <= 60.0  # Max delay
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_protection(self):
        """Circuit breaker protege contra falhas."""
        session = AsyncMock()
        
        # Simula falhas de conexão - return context manager that raises on __aenter__
        def mock_post(*args, **kwargs):
            ctx = MagicMock()
            ctx.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("Connection refused"))
            ctx.__aexit__ = AsyncMock(return_value=None)
            return ctx
        
        session.post = mock_post
        session.closed = False
        
        embedder = Embedder(
            session=session,
            max_retries=0,  # Sem retry para testar CB rapidamente
        )
        
        # Força várias falhas para abrir circuito
        for _ in range(5):
            with pytest.raises(TEIConnectionError):
                await embedder.embed_batch(["test"])
        
        # Circuito deve estar aberto
        assert embedder.circuit_breaker.is_open
        
        # Próxima chamada deve falhar com CircuitBreakerOpenError
        with pytest.raises(CircuitBreakerOpenError):
            await embedder.embed_batch(["test"])
    
    @pytest.mark.asyncio
    async def test_get_cache_key_deterministic(self):
        """Cache key é determinística."""
        embedder = Embedder()
        
        key1 = embedder.get_cache_key("texto de teste")
        key2 = embedder.get_cache_key("texto de teste")
        key3 = embedder.get_cache_key("outro texto")
        
        assert key1 == key2
        assert key1 != key3
        assert len(key1) == 64  # SHA256 hex
    
    @pytest.mark.asyncio
    async def test_get_stats(self):
        """get_stats retorna informações do embedder."""
        embedder = Embedder()
        stats = embedder.get_stats()
        
        assert "model" in stats
        assert "dimensions" in stats
        assert stats["dimensions"] == 384
        assert "circuit_breaker" in stats
    
    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Embedder funciona como context manager."""
        session = AsyncMock()
        session.closed = False
        
        async with Embedder(session=session) as embedder:
            assert embedder is not None
        
        # Sessão deve ser fechada
        session.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_tei_response_error(self):
        """Erro na resposta do TEI lança TEIResponseError."""
        session = AsyncMock()
        response = AsyncMock()
        response.status = 500
        response.text = AsyncMock(return_value="Internal Server Error")
        
        # session.post needs to return an async context manager
        session.post = MagicMock(return_value=create_async_context_manager_mock(response))
        session.closed = False
        
        embedder = Embedder(session=session, max_retries=0)
        
        with pytest.raises(TEIResponseError) as exc_info:
            await embedder.embed_batch(["test"])
        
        assert "500" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_embed_chunks_integration(self, sample_chunks):
        """embed_chunks retorna EmbeddingResult correto."""
        session = AsyncMock()
        response = AsyncMock()
        response.status = 200
        response.json = AsyncMock(return_value=[[0.1] * 384, [0.2] * 384])
        
        # session.post needs to return an async context manager
        session.post = MagicMock(return_value=create_async_context_manager_mock(response))
        session.closed = False
        
        embedder = Embedder(session=session)
        result = await embedder.embed_chunks(sample_chunks, document_id="doc-123")
        
        assert isinstance(result, EmbeddingResult)
        assert result.document_id == "doc-123"
        assert len(result.chunks) == 2
        assert result.total_embeddings == 2
        assert all(isinstance(c, EmbeddedChunk) for c in result.chunks)
        assert all(len(c.embedding) == 384 for c in result.chunks)
    
    @pytest.mark.asyncio
    async def test_batching_respects_batch_size(self):
        """Batching respeita batch_size."""
        session = AsyncMock()
        response = AsyncMock()
        response.status = 200
        
        # Retorna embeddings conforme tamanho do batch
        async def mock_json():
            # Pega o payload da chamada
            call_args = session.post.call_args
            payload = call_args[1].get('json', {})
            inputs = payload.get('inputs', [])
            return [[0.1] * 384 for _ in inputs]
        
        response.json = mock_json
        
        # session.post needs to return an async context manager
        session.post = MagicMock(return_value=create_async_context_manager_mock(response))
        session.closed = False
        
        embedder = Embedder(session=session, batch_size=2)
        texts = ["texto 1", "texto 2", "texto 3", "texto 4", "texto 5"]
        
        await embedder.embed_batch(texts)
        
        # Deve fazer 3 chamadas (2+2+1)
        assert session.post.call_count == 3


# =============================================================================
# EmbeddingService Tests
# =============================================================================

class TestEmbeddingService:
    """Testes para EmbeddingService."""
    
    @pytest.mark.asyncio
    async def test_service_initialization(self):
        """Service inicializa corretamente."""
        service = EmbeddingService()
        
        assert service.embedder is not None
        assert service.cache_config.enabled is True
        assert service.metrics.total_requests == 0
    
    @pytest.mark.asyncio
    async def test_cache_hit(self):
        """Cache hit não chama embedder."""
        # Mock Redis
        redis_mock = AsyncMock()
        cached_embedding = json.dumps([0.1] * 384)
        redis_mock.get = AsyncMock(return_value=cached_embedding)
        
        # Mock Embedder
        embedder_mock = AsyncMock()
        embedder_mock.model = "test-model"
        embedder_mock.EMBEDDING_DIMENSIONS = 384
        
        service = EmbeddingService(
            embedder=embedder_mock,
            redis_client=redis_mock,
        )
        
        result = await service.embed_batch(["texto cached"])
        
        assert len(result) == 1
        assert len(result[0]) == 384
        assert service.metrics.cache_hits == 1
        assert service.metrics.cache_misses == 0
        # Embedder não deve ser chamado
        embedder_mock.embed_batch.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_cache_miss(self):
        """Cache miss chama embedder e cacheia."""
        # Mock Redis (miss)
        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value=None)
        
        # Mock Embedder
        embedder_mock = AsyncMock()
        embedder_mock.embed_batch = AsyncMock(return_value=[[0.1] * 384])
        embedder_mock.model = "test-model"
        embedder_mock.EMBEDDING_DIMENSIONS = 384
        
        service = EmbeddingService(
            embedder=embedder_mock,
            redis_client=redis_mock,
        )
        
        result = await service.embed_batch(["novo texto"])
        
        assert len(result) == 1
        assert service.metrics.cache_hits == 0
        assert service.metrics.cache_misses == 1
        # Deve chamar embedder
        embedder_mock.embed_batch.assert_called_once()
        # Deve salvar no cache
        redis_mock.setex.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_fallback_when_tei_unavailable(self):
        """Fallback é usado quando TEI indisponível."""
        # Mock Embedder (falha)
        embedder_mock = AsyncMock()
        embedder_mock.embed_batch = AsyncMock(
            side_effect=CircuitBreakerOpenError("TEI down")
        )
        embedder_mock.model = "test-model"
        embedder_mock.EMBEDDING_DIMENSIONS = 384
        
        # Mock Fallback
        fallback_mock = AsyncMock()
        fallback_mock.embed_batch = AsyncMock(return_value=[[0.1] * 384])
        
        service = EmbeddingService(
            embedder=embedder_mock,
            fallback_backend=fallback_mock,
            enable_fallback=True,
        )
        
        result = await service.embed_batch(["texto"])
        
        assert len(result) == 1
        assert service.metrics.fallback_requests == 1
        assert service.metrics.tei_requests == 0
    
    @pytest.mark.asyncio
    async def test_fallback_disabled(self):
        """Fallback pode ser desabilitado."""
        embedder_mock = AsyncMock()
        embedder_mock.embed_batch = AsyncMock(
            side_effect=CircuitBreakerOpenError("TEI down")
        )
        embedder_mock.model = "test-model"
        embedder_mock.EMBEDDING_DIMENSIONS = 384
        
        service = EmbeddingService(
            embedder=embedder_mock,
            enable_fallback=False,
        )
        
        with pytest.raises(EmbeddingError):
            await service.embed_batch(["texto"], use_fallback=False)
    
    @pytest.mark.asyncio
    async def test_cache_disabled(self):
        """Cache pode ser desabilitado."""
        embedder_mock = AsyncMock()
        embedder_mock.embed_batch = AsyncMock(return_value=[[0.1] * 384])
        embedder_mock.model = "test-model"
        embedder_mock.EMBEDDING_DIMENSIONS = 384
        
        service = EmbeddingService(
            embedder=embedder_mock,
            cache_config=CacheConfig(enabled=False),
        )
        
        result = await service.embed_batch(["texto"], use_cache=False)
        
        assert len(result) == 1
        assert service.metrics.cache_misses == 1
    
    @pytest.mark.asyncio
    async def test_embed_single_string(self):
        """embed() com string única."""
        embedder_mock = AsyncMock()
        embedder_mock.embed_batch = AsyncMock(return_value=[[0.1] * 384])
        embedder_mock.model = "test-model"
        embedder_mock.EMBEDDING_DIMENSIONS = 384
        
        service = EmbeddingService(embedder=embedder_mock)
        result = await service.embed("texto único")
        
        assert len(result) == 384
    
    @pytest.mark.asyncio
    async def test_get_metrics(self):
        """get_metrics retorna métricas."""
        service = EmbeddingService()
        
        # Simula algumas operações
        service.metrics.total_requests = 10
        service.metrics.cache_hits = 7
        service.metrics.cache_misses = 3
        
        metrics = service.get_metrics()
        
        assert metrics["total_requests"] == 10
        assert metrics["cache_hits"] == 7
        assert metrics["cache_misses"] == 3
        assert metrics["cache_hit_rate"] == 0.7
        assert metrics["dimensions"] == 384
    
    @pytest.mark.asyncio
    async def test_health_check(self):
        """health_check retorna status."""
        service = EmbeddingService()
        
        health = await service.health_check()
        
        assert health["service"] == "embedding"
        assert "status" in health
        assert "embedder" in health
        assert "cache" in health
        assert "fallback" in health
    
    @pytest.mark.asyncio
    async def test_invalidate_cache(self):
        """invalidate_cache remove do cache."""
        redis_mock = AsyncMock()
        redis_mock.delete = AsyncMock(return_value=1)
        
        service = EmbeddingService(redis_client=redis_mock)
        result = await service.invalidate_cache("texto")
        
        assert result is True
        redis_mock.delete.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_clear_cache(self):
        """clear_cache remove múltiplas chaves."""
        redis_mock = AsyncMock()
        redis_mock.keys = AsyncMock(return_value=["key1", "key2"])
        redis_mock.delete = AsyncMock(return_value=2)
        
        service = EmbeddingService(redis_client=redis_mock)
        result = await service.clear_cache()
        
        assert result == 2
    
    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Service funciona como context manager."""
        async with EmbeddingService() as service:
            assert service is not None


# =============================================================================
# RetryConfig Tests
# =============================================================================

class TestRetryConfig:
    """Testes para RetryConfig."""
    
    def test_default_values(self):
        """Valores padrão corretos."""
        config = RetryConfig()
        assert config.max_retries == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0
        assert config.exponential_base == 2.0
    
    def test_custom_values(self):
        """Valores customizáveis."""
        config = RetryConfig(
            max_retries=5,
            base_delay=2.0,
            max_delay=30.0,
            exponential_base=3.0,
        )
        assert config.max_retries == 5
        assert config.base_delay == 2.0
        assert config.max_delay == 30.0
        assert config.exponential_base == 3.0


# =============================================================================
# CacheConfig Tests
# =============================================================================

class TestCacheConfig:
    """Testes para CacheConfig."""
    
    def test_default_values(self):
        """Valores padrão corretos."""
        config = CacheConfig()
        assert config.ttl_seconds == 86400
        assert config.prefix == "emb:"
        assert config.enabled is True
    
    def test_custom_values(self):
        """Valores customizáveis."""
        config = CacheConfig(
            ttl_seconds=3600,
            prefix="test:",
            enabled=False,
        )
        assert config.ttl_seconds == 3600
        assert config.prefix == "test:"
        assert config.enabled is False


# =============================================================================
# EmbeddingMetrics Tests
# =============================================================================

class TestEmbeddingMetrics:
    """Testes para EmbeddingMetrics."""
    
    def test_initial_values(self):
        """Valores iniciais zero."""
        metrics = EmbeddingMetrics()
        assert metrics.total_requests == 0
        assert metrics.cache_hits == 0
        assert metrics.cache_misses == 0
        assert metrics.errors == 0
    
    def test_cache_hit_rate_zero(self):
        """Cache hit rate é 0 quando não há operações."""
        metrics = EmbeddingMetrics()
        assert metrics.cache_hit_rate == 0.0
    
    def test_cache_hit_rate_calculation(self):
        """Cache hit rate calculado corretamente."""
        metrics = EmbeddingMetrics()
        metrics.cache_hits = 75
        metrics.cache_misses = 25
        assert metrics.cache_hit_rate == 0.75
    
    def test_average_latency_zero(self):
        """Latência média é 0 quando não há requests."""
        metrics = EmbeddingMetrics()
        assert metrics.average_latency_ms == 0.0
    
    def test_average_latency_calculation(self):
        """Latência média calculada corretamente."""
        metrics = EmbeddingMetrics()
        metrics.total_requests = 10
        metrics.total_duration_ms = 500.0
        assert metrics.average_latency_ms == 50.0


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Testes de integração."""
    
    @pytest.mark.asyncio
    async def test_full_pipeline_with_cache(self):
        """Pipeline completo com cache."""
        # Mock Redis
        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value=None)  # Primeira vez: miss
        
        # Mock Embedder
        embedder_mock = AsyncMock()
        embedder_mock.embed_batch = AsyncMock(return_value=[[0.1] * 384])
        embedder_mock.model = "test-model"
        embedder_mock.EMBEDDING_DIMENSIONS = 384
        
        service = EmbeddingService(
            embedder=embedder_mock,
            redis_client=redis_mock,
        )
        
        # Primeira chamada - miss
        result1 = await service.embed_batch(["texto"])
        assert service.metrics.cache_misses == 1
        
        # Simula cache hit na segunda chamada
        redis_mock.get = AsyncMock(return_value=json.dumps([0.1] * 384))
        result2 = await service.embed_batch(["texto"])
        assert service.metrics.cache_hits == 1
        
        # Resultados devem ser iguais
        assert result1 == result2
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_failures(self):
        """Circuit breaker abre após falhas consecutivas."""
        session = AsyncMock()
        session.post = MagicMock(side_effect=aiohttp.ClientError("Timeout"))
        session.closed = False
        
        embedder = Embedder(
            session=session,
            max_retries=0,
        )
        
        # Falhas até abrir circuito
        for _ in range(5):
            with pytest.raises(TEIConnectionError):
                await embedder.embed_batch(["test"])
        
        # Circuito aberto
        assert embedder.circuit_breaker.is_open
        
        # Nova chamada deve falhar imediatamente
        with pytest.raises(CircuitBreakerOpenError):
            await embedder.embed_batch(["test"])
    
    @pytest.mark.asyncio
    async def test_dimensionality_enforcement(self):
        """Dimensionalidade 384 é estritamente aplicada."""
        session = AsyncMock()
        response = AsyncMock()
        response.status = 200
        
        # TEI retorna embedding com dimensão errada
        response.json = AsyncMock(return_value=[[0.1] * 768])
        
        # session.post needs to return an async context manager
        session.post = MagicMock(return_value=create_async_context_manager_mock(response))
        session.closed = False
        
        embedder = Embedder(session=session, max_retries=0)
        
        with pytest.raises(DimensionalityError) as exc_info:
            await embedder.embed_batch(["test"])
        
        assert "384" in str(exc_info.value)
        assert "768" in str(exc_info.value)


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Testes de casos edge."""
    
    @pytest.mark.asyncio
    async def test_very_long_text(self):
        """Texto muito longo é processado."""
        embedder = Embedder()
        long_text = "palavra " * 10000
        
        session = AsyncMock()
        response = AsyncMock()
        response.status = 200
        response.json = AsyncMock(return_value=[[0.1] * 384])
        
        # session.post needs to return an async context manager
        session.post = MagicMock(return_value=create_async_context_manager_mock(response))
        session.closed = False
        
        embedder._session = session
        
        result = await embedder.embed_batch([long_text])
        assert len(result) == 1
        assert len(result[0]) == 384
    
    @pytest.mark.asyncio
    async def test_unicode_text(self):
        """Texto unicode é processado corretamente."""
        session = AsyncMock()
        response = AsyncMock()
        response.status = 200
        
        # Retorna embeddings conforme tamanho do batch
        async def mock_json():
            call_args = session.post.call_args
            payload = call_args[1].get('json', {})
            inputs = payload.get('inputs', [])
            return [[0.1] * 384 for _ in inputs]
        
        response.json = mock_json
        
        # session.post needs to return an async context manager
        session.post = MagicMock(return_value=create_async_context_manager_mock(response))
        session.closed = False
        
        embedder = Embedder(session=session)
        
        unicode_texts = [
            "Texto com acentuação: é à ã ô",
            "Emojis: 🎉 🚀 💻",
            "Chinês: 你好世界",
            "Árabe: مرحبا",
        ]
        
        result = await embedder.embed_batch(unicode_texts)
        assert len(result) == 4
    
    @pytest.mark.asyncio
    async def test_special_characters(self):
        """Caracteres especiais são processados."""
        session = AsyncMock()
        response = AsyncMock()
        response.status = 200
        
        # Retorna embeddings conforme tamanho do batch
        async def mock_json():
            call_args = session.post.call_args
            payload = call_args[1].get('json', {})
            inputs = payload.get('inputs', [])
            return [[0.1] * 384 for _ in inputs]
        
        response.json = mock_json
        
        # session.post needs to return an async context manager
        session.post = MagicMock(return_value=create_async_context_manager_mock(response))
        session.closed = False
        
        embedder = Embedder(session=session)
        
        special_texts = [
            "<html>tags</html>",
            "Código: `function() {}`",
            "Quebra\nlinha\ttab",
            'Aspas: "simples" \'duplas\'',
        ]
        
        result = await embedder.embed_batch(special_texts)
        assert len(result) == 4
    
    @pytest.mark.asyncio
    async def test_concurrent_requests(self):
        """Requests concorrentes são tratadas."""
        session = AsyncMock()
        response = AsyncMock()
        response.status = 200
        response.json = AsyncMock(return_value=[[0.1] * 384])
        
        # session.post needs to return an async context manager
        session.post = MagicMock(return_value=create_async_context_manager_mock(response))
        session.closed = False
        
        embedder = Embedder(session=session)
        
        # Múltiplas requisições concorrentes
        tasks = [
            embedder.embed_batch([f"texto {i}"])
            for i in range(10)
        ]
        
        results = await asyncio.gather(*tasks)
        assert len(results) == 10
        assert all(len(r[0]) == 384 for r in results)
    
    @pytest.mark.asyncio
    async def test_retry_on_timeout(self):
        """Retry em timeout."""
        session = AsyncMock()
        
        # Primeira chamada timeout, segunda sucesso
        call_count = 0
        
        def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            response = AsyncMock()
            if call_count == 1:
                # Return a context manager that raises TimeoutError on __aenter__
                ctx = MagicMock()
                ctx.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError("Timeout"))
                ctx.__aexit__ = AsyncMock(return_value=None)
                return ctx
            response.status = 200
            response.json = AsyncMock(return_value=[[0.1] * 384])
            return create_async_context_manager_mock(response)
        
        session.post = mock_post
        session.closed = False
        
        embedder = Embedder(session=session, max_retries=1)
        
        result = await embedder.embed_batch(["test"])
        
        assert len(result) == 1
        assert call_count == 2  # Retry funcionou
