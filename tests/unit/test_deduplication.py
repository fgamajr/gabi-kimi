"""Testes unitários para o módulo de deduplicação.

Testa a lógica de deduplicação, cache in-memory e verificação
de duplicatas considerando soft delete.

Baseado em GABI_SPECS_FINAL_v1.md §2.8.2.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from gabi.exceptions import DeduplicationError
from gabi.pipeline.contracts import DuplicateCheckResult
from gabi.pipeline.deduplication import (
    DedupConfig,
    Deduplicator,
    InMemoryFingerprintCache,
)
from gabi.types import DocumentStatus


# Mock do modelo Document para evitar problemas com SQLAlchemy
class MockDocument:
    """Mock do modelo Document para testes."""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", str(uuid.uuid4()))
        self.document_id = kwargs.get("document_id", f"DOC-{self.id[:8]}")
        self.source_id = kwargs.get("source_id", "test_source")
        self.fingerprint = kwargs.get("fingerprint", "")
        self.fingerprint_algorithm = kwargs.get("fingerprint_algorithm", "sha256")
        self.title = kwargs.get("title", "Test Document")
        self.content_preview = kwargs.get("content_preview", "Preview...")
        self.content_hash = kwargs.get("content_hash", "")
        self.content_size_bytes = kwargs.get("content_size_bytes", 1000)
        self.meta = kwargs.get("metadata", {})  # 'metadata' é reservado no SQLAlchemy
        self.url = kwargs.get("url", "")
        self.content_type = kwargs.get("content_type", "text/html")
        self.language = kwargs.get("language", "pt-BR")
        self.status = kwargs.get("status", DocumentStatus.ACTIVE)
        self.version = kwargs.get("version", 1)
        self.is_deleted = kwargs.get("is_deleted", False)
        self.deleted_at = kwargs.get("deleted_at", None)
        self.deleted_reason = kwargs.get("deleted_reason", None)
        self.deleted_by = kwargs.get("deleted_by", None)
        self.ingested_at = kwargs.get("ingested_at", datetime.utcnow())
        self.updated_at = kwargs.get("updated_at", datetime.utcnow())
        self.reindexed_at = kwargs.get("reindexed_at", None)
        self.es_indexed = kwargs.get("es_indexed", False)
        self.es_indexed_at = kwargs.get("es_indexed_at", None)
        self.chunks_count = kwargs.get("chunks_count", 0)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_fingerprint() -> str:
    """Fingerprint de exemplo para testes."""
    return hashlib.sha256(b"test content for dedup").hexdigest()


@pytest.fixture
def another_fingerprint() -> str:
    """Outro fingerprint de exemplo."""
    return hashlib.sha256(b"different content").hexdigest()


@pytest.fixture
def dedup_config() -> DedupConfig:
    """Configuração de deduplicação para testes."""
    return DedupConfig(
        cache_ttl_seconds=60,
        cache_max_size=100,
        lock_timeout_seconds=10,
        lock_blocking_timeout_seconds=1,
        redis_key_prefix="test:dedup",
    )


@pytest.fixture
def mock_redis_client() -> Mock:
    """Mock do cliente Redis com suporte a locks."""
    client = Mock()
    
    # Mock do lock
    lock_mock = AsyncMock()
    lock_mock.acquire = AsyncMock(return_value=True)
    lock_mock.release = AsyncMock(return_value=None)
    lock_mock.__aenter__ = AsyncMock(return_value=True)
    lock_mock.__aexit__ = AsyncMock(return_value=False)
    
    client.lock = Mock(return_value=lock_mock)
    
    return client


@pytest.fixture
async def deduplicator(
    db_session: AsyncSession,
    mock_redis_client: Mock,
    dedup_config: DedupConfig,
) -> Deduplicator:
    """Deduplicator configurado para testes."""
    return Deduplicator(
        db_session=db_session,
        redis_client=mock_redis_client,
        config=dedup_config,
    )


# =============================================================================
# Testes de Cache In-Memory
# =============================================================================

class TestInMemoryFingerprintCache:
    """Testes para o cache LRU em memória."""
    
    def test_cache_get_nonexistent(self):
        """Cache retorna None para fingerprint inexistente."""
        cache = InMemoryFingerprintCache()
        
        result = cache.get("nonexistent_fingerprint")
        
        assert result is None
    
    def test_cache_set_and_get(self):
        """Cache armazena e recupera fingerprint corretamente."""
        cache = InMemoryFingerprintCache()
        fingerprint = "abc123"
        doc_id = "DOC-001"
        
        cache.set(fingerprint, doc_id)
        result = cache.get(fingerprint)
        
        assert result == doc_id
    
    def test_cache_ttl_expiration(self):
        """Cache invalida entradas expiradas."""
        cache = InMemoryFingerprintCache(ttl_seconds=0)  # TTL instantâneo
        fingerprint = "abc123"
        doc_id = "DOC-001"
        
        cache.set(fingerprint, doc_id)
        result = cache.get(fingerprint)
        
        assert result is None  # Deve expirar imediatamente
    
    def test_cache_lru_eviction(self):
        """Cache remove entradas mais antigas quando atinge limite."""
        cache = InMemoryFingerprintCache(max_size=3)
        
        # Adiciona 3 entradas
        cache.set("fp1", "DOC-001")
        cache.set("fp2", "DOC-002")
        cache.set("fp3", "DOC-003")
        
        # Acessa fp1 para atualizar ordem LRU
        cache.get("fp1")
        
        # Adiciona mais uma entrada (deve remover fp2)
        cache.set("fp4", "DOC-004")
        
        assert cache.get("fp1") == "DOC-001"  # Mantido (acessado recentemente)
        assert cache.get("fp2") is None  # Removido (mais antigo)
        assert cache.get("fp3") == "DOC-003"  # Mantido
        assert cache.get("fp4") == "DOC-004"  # Novo
    
    def test_cache_invalidate(self):
        """Cache invalida entrada específica corretamente."""
        cache = InMemoryFingerprintCache()
        
        cache.set("fp1", "DOC-001")
        cache.set("fp2", "DOC-002")
        
        cache.invalidate("fp1")
        
        assert cache.get("fp1") is None
        assert cache.get("fp2") == "DOC-002"
    
    def test_cache_clear(self):
        """Cache limpa todas as entradas corretamente."""
        cache = InMemoryFingerprintCache()
        
        cache.set("fp1", "DOC-001")
        cache.set("fp2", "DOC-002")
        
        cache.clear()
        
        assert cache.get("fp1") is None
        assert cache.get("fp2") is None
        assert len(cache) == 0
    
    def test_cache_updates_access_order(self):
        """Cache atualiza ordem de acesso corretamente."""
        cache = InMemoryFingerprintCache(max_size=3)
        
        cache.set("fp1", "DOC-001")
        cache.set("fp2", "DOC-002")
        cache.set("fp3", "DOC-003")
        
        # Acessa fp1 (agora é o mais recente)
        cache.get("fp1")
        
        # fp2 é o mais antigo, deve ser removido
        cache.set("fp4", "DOC-004")
        
        assert cache.get("fp1") is not None
        assert cache.get("fp2") is None


# =============================================================================
# Testes de Deduplicação
# =============================================================================

@pytest.mark.unit
class TestDeduplicator:
    """Testes para o Deduplicator."""
    
    async def test_check_new_document_not_duplicate(
        self,
        sample_fingerprint: str,
    ):
        """Documento novo não deve ser detectado como duplicado.
        
        Critério: test_check_new_document (não duplicado)
        """
        # Arrange
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = Mock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        dedup = Deduplicator(mock_session, redis_client=None)
        
        # Act
        result = await dedup.check_duplicate(sample_fingerprint)
        
        # Assert
        assert isinstance(result, DuplicateCheckResult)
        assert result.is_duplicate is False
        assert result.existing_document_id is None
        assert result.fingerprint == sample_fingerprint
        assert result.confidence == 1.0
    
    async def test_check_duplicate_fingerprint_exists(
        self,
        sample_fingerprint: str,
    ):
        """Fingerprint existente deve ser detectado como duplicado.
        
        Critério: test_check_duplicate (fingerprint existe)
        """
        # Arrange - mock do resultado do banco
        existing_doc = MockDocument(
            fingerprint=sample_fingerprint,
            document_id="EXISTING-DOC-001",
            status=DocumentStatus.ACTIVE,
            is_deleted=False,
        )
        
        # Mock da sessão para retornar documento existente
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = Mock(return_value=existing_doc)
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        dedup = Deduplicator(mock_session, redis_client=None)
        
        # Act
        result = await dedup.check_duplicate(sample_fingerprint)
        
        # Assert
        assert result.is_duplicate is True
        assert result.existing_document_id == "EXISTING-DOC-001"
        assert result.fingerprint == sample_fingerprint
    
    async def test_check_deleted_document_allows_reingest(
        self,
        sample_fingerprint: str,
    ):
        """Fingerprint de documento deletado deve permitir re-ingestão.
        
        Critério: test_check_deleted_document (fingerprint deletado → permitir)
        """
        # Arrange - mock retorna None (documento deletado não é considerado)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = Mock(return_value=None)
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        dedup = Deduplicator(mock_session, redis_client=None)
        
        # Act
        result = await dedup.check_duplicate(sample_fingerprint)
        
        # Assert - documento deletado não deve ser considerado duplicata
        assert result.is_duplicate is False
        assert result.existing_document_id is None
    
    async def test_check_duplicate_with_cache(
        self,
        sample_fingerprint: str,
    ):
        """Cache deve ser usado para verificação rápida."""
        # Arrange
        existing_doc = MockDocument(
            fingerprint=sample_fingerprint,
            document_id="CACHED-DOC-001",
            status=DocumentStatus.ACTIVE,
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = Mock(return_value=existing_doc)
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        dedup = Deduplicator(mock_session, redis_client=None)
        
        # Primeira chamada - busca no DB e popula cache
        result1 = await dedup.check_duplicate(sample_fingerprint, use_cache=True)
        assert result1.is_duplicate is True
        
        # Segunda chamada - deve vir do cache (não deve chamar execute novamente)
        result2 = await dedup.check_duplicate(sample_fingerprint, use_cache=True)
        assert result2.is_duplicate is True
        assert result2.existing_document_id == "CACHED-DOC-001"
        
        # Verifica que execute foi chamado apenas uma vez (primeira consulta)
        assert mock_session.execute.call_count == 1
    
    async def test_check_duplicate_without_cache(
        self,
        sample_fingerprint: str,
    ):
        """Verificação sem cache deve consultar banco de dados."""
        # Arrange
        existing_doc = MockDocument(
            fingerprint=sample_fingerprint,
            document_id="NO-CACHE-DOC-001",
            status=DocumentStatus.ACTIVE,
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = Mock(return_value=existing_doc)
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        dedup = Deduplicator(mock_session, redis_client=None)
        
        # Act - consulta direta no DB
        result = await dedup.check_duplicate(sample_fingerprint, use_cache=False)
        
        # Assert
        assert result.is_duplicate is True
        assert result.existing_document_id == "NO-CACHE-DOC-001"
    
    async def test_mark_processed_adds_to_cache(
        self,
        sample_fingerprint: str,
    ):
        """mark_processed deve adicionar fingerprint ao cache."""
        # Arrange
        mock_session = AsyncMock()
        dedup = Deduplicator(mock_session, redis_client=None)
        
        # Act
        await dedup.mark_processed(sample_fingerprint, "DOC-001")
        
        # Assert - próxima verificação deve encontrar no cache
        cached = dedup.cache.get(sample_fingerprint)
        assert cached == "DOC-001"
    
    async def test_invalidate_cache_specific(
        self,
        sample_fingerprint: str,
        another_fingerprint: str,
    ):
        """invalidate_cache deve remover fingerprint específico."""
        # Arrange
        mock_session = AsyncMock()
        dedup = Deduplicator(mock_session, redis_client=None)
        dedup.cache.set(sample_fingerprint, "DOC-001")
        dedup.cache.set(another_fingerprint, "DOC-002")
        
        # Act
        dedup.invalidate_cache(sample_fingerprint)
        
        # Assert
        assert dedup.cache.get(sample_fingerprint) is None
        assert dedup.cache.get(another_fingerprint) == "DOC-002"
    
    async def test_invalidate_cache_all(
        self,
        sample_fingerprint: str,
        another_fingerprint: str,
    ):
        """invalidate_cache sem argumento deve limpar todo o cache."""
        # Arrange
        mock_session = AsyncMock()
        dedup = Deduplicator(mock_session, redis_client=None)
        dedup.cache.set(sample_fingerprint, "DOC-001")
        dedup.cache.set(another_fingerprint, "DOC-002")
        
        # Act
        dedup.invalidate_cache()
        
        # Assert
        assert len(dedup.cache) == 0
    
    async def test_get_cache_stats(self):
        """get_cache_stats deve retornar estatísticas corretas."""
        # Arrange
        mock_session = AsyncMock()
        dedup = Deduplicator(
            mock_session,
            redis_client=None,
            config=DedupConfig(cache_max_size=500, cache_ttl_seconds=120),
        )
        dedup.cache.set("fp1", "DOC-001")
        dedup.cache.set("fp2", "DOC-002")
        
        # Act
        stats = dedup.get_cache_stats()
        
        # Assert
        assert stats["cache_size"] == 2
        assert stats["cache_max_size"] == 500
        assert stats["cache_ttl_seconds"] == 120


# =============================================================================
# Testes de Deduplicação com Lock
# =============================================================================

@pytest.mark.unit
class TestDeduplicatorWithLock:
    """Testes para deduplicação com distributed lock."""
    
    async def test_check_and_lock_without_redis(
        self,
        sample_fingerprint: str,
    ):
        """check_and_lock sem Redis deve usar check_duplicate simples."""
        # Arrange
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = Mock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        dedup = Deduplicator(mock_session, redis_client=None)
        
        # Act
        is_duplicate = await dedup.check_and_lock(
            sample_fingerprint, "DOC-001"
        )
        
        # Assert
        assert is_duplicate is False
    
    async def test_check_and_lock_acquires_lock(
        self,
        mock_redis_client: Mock,
        sample_fingerprint: str,
    ):
        """check_and_lock deve adquirir lock distribuído."""
        # Arrange
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = Mock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        dedup = Deduplicator(mock_session, redis_client=mock_redis_client)
        
        # Act
        is_duplicate = await dedup.check_and_lock(
            sample_fingerprint, "DOC-001"
        )
        
        # Assert
        mock_redis_client.lock.assert_called_once()
        assert is_duplicate is False
    
    async def test_check_and_lock_duplicate_detected(
        self,
        mock_redis_client: Mock,
        sample_fingerprint: str,
    ):
        """check_and_lock deve detectar duplicata com lock."""
        # Arrange
        existing_doc = MockDocument(
            fingerprint=sample_fingerprint,
            document_id="EXISTING-DOC-002",
            status=DocumentStatus.ACTIVE,
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = Mock(return_value=existing_doc)
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        dedup = Deduplicator(
            mock_session,
            redis_client=mock_redis_client,
        )
        
        # Act
        is_duplicate = await dedup.check_and_lock(
            sample_fingerprint, "DOC-NEW"
        )
        
        # Assert
        assert is_duplicate is True
    
    async def test_check_and_lock_lock_failure(
        self,
        sample_fingerprint: str,
    ):
        """check_and_lock deve retornar True se não conseguir adquirir lock."""
        # Arrange
        mock_session = AsyncMock()
        redis_client = Mock()
        lock_mock = AsyncMock()
        lock_mock.acquire = AsyncMock(return_value=False)  # Falha ao adquirir
        redis_client.lock = Mock(return_value=lock_mock)
        
        dedup = Deduplicator(mock_session, redis_client=redis_client)
        
        # Act
        is_duplicate = await dedup.check_and_lock(
            sample_fingerprint, "DOC-001"
        )
        
        # Assert - assume duplicado para evitar race condition
        assert is_duplicate is True
    
    async def test_check_and_lock_releases_lock(
        self,
        mock_redis_client: Mock,
        sample_fingerprint: str,
    ):
        """check_and_lock deve liberar lock após verificação."""
        # Arrange
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = Mock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        lock_mock = AsyncMock()
        lock_mock.acquire = AsyncMock(return_value=True)
        lock_mock.release = AsyncMock(return_value=None)
        mock_redis_client.lock = Mock(return_value=lock_mock)
        
        dedup = Deduplicator(mock_session, redis_client=mock_redis_client)
        
        # Act
        await dedup.check_and_lock(sample_fingerprint, "DOC-001")
        
        # Assert
        lock_mock.release.assert_called_once()


# =============================================================================
# Testes de Erro
# =============================================================================

@pytest.mark.unit
class TestDeduplicatorErrors:
    """Testes para tratamento de erros."""
    
    async def test_check_duplicate_error_handling(self):
        """Deve lançar DeduplicationError em caso de erro no DB."""
        # Arrange - cria sessão mock que falha
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("DB Error"))
        
        dedup = Deduplicator(mock_session, redis_client=None)
        
        # Act & Assert
        with pytest.raises(DeduplicationError) as exc_info:
            await dedup.check_duplicate("some_fingerprint")
        
        assert "Failed to check duplicate" in str(exc_info.value)
        assert exc_info.value.code == "DEDUPLICATION_ERROR"
    
    async def test_check_and_lock_error_handling(self):
        """Deve lançar DeduplicationError em caso de erro no lock."""
        # Arrange
        mock_session = AsyncMock()
        redis_client = Mock()
        redis_client.lock = Mock(side_effect=Exception("Redis Error"))
        
        dedup = Deduplicator(mock_session, redis_client=redis_client)
        
        # Act & Assert
        with pytest.raises(DeduplicationError) as exc_info:
            await dedup.check_and_lock("some_fingerprint", "DOC-001")
        
        assert "Failed to check and lock" in str(exc_info.value)
