"""Testes de integração para deduplicação concorrente.

Testa distributed lock e comportamento em cenários de alta
concorrência com múltiplos workers simultâneos.

Baseado em GABI_SPECS_FINAL_v1.md §2.8.2 e critério:
test_concurrent_dedup (distributed lock funciona)
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from gabi.pipeline.deduplication import DedupConfig, Deduplicator
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
        self.meta = kwargs.get("metadata", {})
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
    return hashlib.sha256(b"concurrent test content").hexdigest()


@pytest.fixture
def concurrent_fingerprints() -> list[str]:
    """Lista de fingerprints para testes concorrentes."""
    return [
        hashlib.sha256(f"content_{i}".encode()).hexdigest()
        for i in range(10)
    ]


@pytest.fixture
async def redis_with_lock_mock() -> Mock:
    """Mock do Redis que simula comportamento de lock real."""
    client = Mock()
    locks: dict[str, bool] = {}
    
    class MockLock:
        def __init__(self, name: str, timeout: int = 30):
            self.name = name
            self.timeout = timeout
            self._acquired = False
        
        async def acquire(self, blocking_timeout: float = None) -> bool:
            if self.name in locks and locks[self.name]:
                return False  # Lock já adquirido
            locks[self.name] = True
            self._acquired = True
            return True
        
        async def release(self) -> None:
            if self._acquired and self.name in locks:
                locks[self.name] = False
                self._acquired = False
        
        async def __aenter__(self):
            await self.acquire()
            return self
        
        async def __aexit__(self, *args):
            await self.release()
    
    def create_lock(name: str, timeout: int = 30) -> MockLock:
        return MockLock(name, timeout)
    
    client.lock = Mock(side_effect=create_lock)
    
    return client


@pytest.fixture
async def redis_with_lock_contention() -> Mock:
    """Mock do Redis que simula alta contenção de locks."""
    client = Mock()
    locks: dict[str, asyncio.Lock] = {}
    acquire_order: list[str] = []
    
    class ContentionLock:
        def __init__(self, name: str, timeout: int = 30):
            self.name = name
            self.timeout = timeout
            if name not in locks:
                locks[name] = asyncio.Lock()
        
        async def acquire(self, blocking_timeout: float = None) -> bool:
            try:
                await asyncio.wait_for(
                    locks[self.name].acquire(),
                    timeout=blocking_timeout or 5.0
                )
                acquire_order.append(self.name)
                return True
            except asyncio.TimeoutError:
                return False
        
        async def release(self) -> None:
            if locks[self.name].locked():
                locks[self.name].release()
        
        async def __aenter__(self):
            await self.acquire()
            return self
        
        async def __aexit__(self, *args):
            await self.release()
    
    def create_lock(name: str, timeout: int = 30) -> ContentionLock:
        return ContentionLock(name, timeout)
    
    client.lock = Mock(side_effect=create_lock)
    client._acquire_order = acquire_order
    
    return client


# =============================================================================
# Testes de Concorrência
# =============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
class TestConcurrentDeduplication:
    """Testes para deduplicação em cenários concorrentes."""
    
    async def test_concurrent_dedup_same_fingerprint(
        self,
        redis_with_lock_contention: Mock,
        sample_fingerprint: str,
    ):
        """Múltiplos workers com mesmo fingerprint - apenas um deve processar.
        
        Critério: test_concurrent_dedup (distributed lock funciona)
        """
        # Arrange
        num_workers = 5
        results: list[bool] = []
        
        # Mock da sessão - nenhum documento existe inicialmente
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = Mock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        # Cria um Deduplicator compartilhado com cache compartilhado
        shared_dedup = Deduplicator(
            mock_session,
            redis_client=redis_with_lock_contention,
            config=DedupConfig(lock_blocking_timeout_seconds=2),
        )
        
        async def worker(worker_id: int) -> bool:
            """Worker que tenta processar o mesmo documento."""
            is_duplicate = await shared_dedup.check_and_lock(
                sample_fingerprint,
                f"DOC-WORKER-{worker_id}",
            )
            return is_duplicate
        
        # Act - inicia múltiplos workers simultaneamente
        tasks = [worker(i) for i in range(num_workers)]
        results = await asyncio.gather(*tasks)
        
        # Assert
        # Apenas um worker deve conseguir processar (não duplicado)
        # Os outros devem detectar como duplicado ou falhar no lock
        non_duplicates = sum(1 for r in results if not r)
        duplicates = sum(1 for r in results if r)
        
        assert non_duplicates == 1, (
            f"Esperado 1 não-duplicado, obtido {non_duplicates}. "
            f"Distribuição: {results}"
        )
        assert duplicates == num_workers - 1, (
            f"Esperado {num_workers - 1} duplicados, obtido {duplicates}"
        )
    
    async def test_concurrent_dedup_different_fingerprints(
        self,
        redis_with_lock_contention: Mock,
        concurrent_fingerprints: list[str],
    ):
        """Múltiplos workers com fingerprints diferentes - todos devem processar."""
        # Arrange
        results: list[bool] = []
        
        # Mock da sessão - nenhum documento existe
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = Mock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        async def worker(fingerprint: str, worker_id: int) -> bool:
            """Worker que processa fingerprint único."""
            dedup = Deduplicator(
                mock_session,
                redis_client=redis_with_lock_contention,
            )
            
            is_duplicate = await dedup.check_and_lock(
                fingerprint,
                f"DOC-WORKER-{worker_id}",
            )
            return is_duplicate
        
        # Act
        tasks = [
            worker(fp, i)
            for i, fp in enumerate(concurrent_fingerprints)
        ]
        results = await asyncio.gather(*tasks)
        
        # Assert - todos devem poder processar (fingerprints diferentes)
        assert all(not r for r in results), (
            f"Todos deveriam ser não-duplicados, mas obtido: {results}"
        )
    
    async def test_concurrent_dedup_with_existing_document(
        self,
        redis_with_lock_mock: Mock,
        sample_fingerprint: str,
    ):
        """Workers tentam processar documento já existente no banco."""
        # Arrange - mock do documento existente
        existing_doc = MockDocument(
            fingerprint=sample_fingerprint,
            document_id="EXISTING-DOC-001",
            status=DocumentStatus.ACTIVE,
            is_deleted=False,
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = Mock(return_value=existing_doc)
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        num_workers = 5
        
        async def worker(worker_id: int) -> bool:
            """Worker que tenta processar documento existente."""
            dedup = Deduplicator(
                mock_session,
                redis_client=redis_with_lock_mock,
            )
            
            return await dedup.check_and_lock(
                sample_fingerprint,
                f"DOC-WORKER-{worker_id}",
            )
        
        # Act
        tasks = [worker(i) for i in range(num_workers)]
        results = await asyncio.gather(*tasks)
        
        # Assert - todos devem detectar como duplicado
        assert all(results), f"Todos deveriam ser duplicados, mas obtido: {results}"
    
    async def test_concurrent_dedup_lock_release(
        self,
        redis_with_lock_contention: Mock,
        sample_fingerprint: str,
    ):
        """Lock deve ser liberado após processamento para permitir novas tentativas."""
        # Arrange
        mock_session = AsyncMock()
        
        # Mock inicial - nenhum documento existe
        mock_result_empty = MagicMock()
        mock_result_empty.scalar_one_or_none = Mock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_result_empty)
        
        dedup = Deduplicator(
            mock_session,
            redis_client=redis_with_lock_contention,
        )
        
        # Primeira tentativa - não é duplicado
        result1 = await dedup.check_and_lock(
            sample_fingerprint,
            "DOC-001",
        )
        
        # Adiciona ao cache simulando processamento
        await dedup.mark_processed(sample_fingerprint, "DOC-001")
        
        # Segunda tentativa - deve detectar como duplicado (do cache)
        result2 = await dedup.check_and_lock(
            sample_fingerprint,
            "DOC-002",
        )
        
        # Assert
        assert result1 is False  # Primeiro processou
        assert result2 is True   # Segundo detectou duplicata
    
    async def test_concurrent_dedup_lock_timeout(
        self,
        sample_fingerprint: str,
    ):
        """Lock com timeout deve permitir retry após expiração."""
        # Arrange - Redis que bloqueia indefinidamente
        mock_session = AsyncMock()
        redis_client = Mock()
        
        lock_instance = AsyncMock()
        lock_instance.acquire = AsyncMock(return_value=False)  # Sempre falha
        lock_instance.release = AsyncMock(return_value=None)
        
        redis_client.lock = Mock(return_value=lock_instance)
        
        dedup = Deduplicator(
            mock_session,
            redis_client=redis_client,
            config=DedupConfig(lock_blocking_timeout_seconds=0.1),
        )
        
        # Act
        result = await dedup.check_and_lock(
            sample_fingerprint,
            "DOC-001",
        )
        
        # Assert - quando não consegue lock, assume duplicado
        assert result is True


# =============================================================================
# Testes de Race Condition
# =============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
class TestRaceConditions:
    """Testes específicos para race conditions."""
    
    async def test_race_condition_check_then_insert(
        self,
        redis_with_lock_contention: Mock,
        sample_fingerprint: str,
    ):
        """Simula race condition entre check e insert.
        
        Este teste verifica que o distributed lock previne race condition
        onde dois workers verificam simultaneamente e ambos acham que
        não é duplicado.
        """
        # Arrange
        processed_by: list[str] = []
        lock = asyncio.Lock()
        
        # Mock inicial - nenhum documento existe
        mock_result_empty = MagicMock()
        mock_result_empty.scalar_one_or_none = Mock(return_value=None)
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result_empty)
        
        # Deduplicator compartilhado entre workers
        shared_dedup = Deduplicator(
            mock_session,
            redis_client=redis_with_lock_contention,
        )
        
        async def worker_race(worker_id: int) -> str:
            """Worker que simula check -> (race) -> insert."""
            # Tenta adquirir lock e verificar
            is_duplicate = await shared_dedup.check_and_lock(
                sample_fingerprint,
                f"DOC-WORKER-{worker_id}",
            )
            
            if not is_duplicate:
                # Seção crítica - apenas um worker deve chegar aqui
                async with lock:
                    processed_by.append(f"worker-{worker_id}")
                
                # Simula processamento
                await asyncio.sleep(0.01)
            
            return f"worker-{worker_id}"
        
        # Act - inicia workers simultaneamente
        num_workers = 10
        tasks = [worker_race(i) for i in range(num_workers)]
        await asyncio.gather(*tasks)
        
        # Assert - apenas um worker deve ter processado
        assert len(processed_by) == 1, (
            f"Apenas um worker deveria processar, mas {len(processed_by)} "
            f"processaram: {processed_by}"
        )
    
    async def test_race_condition_deleted_document_reingest(
        self,
        redis_with_lock_contention: Mock,
        sample_fingerprint: str,
    ):
        """Race condition ao re-ingestir documento deletado."""
        # Arrange
        # Mock retorna None (documento deletado não é encontrado)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = Mock(return_value=None)
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        # Deduplicator compartilhado
        shared_dedup = Deduplicator(
            mock_session,
            redis_client=redis_with_lock_contention,
        )
        
        reingested_by: list[str] = []
        lock = asyncio.Lock()
        
        async def worker_reingest(worker_id: int) -> bool:
            """Worker que tenta re-ingestir documento deletado."""
            dedup = shared_dedup
            
            # Verifica se pode re-ingestir
            is_duplicate = await dedup.check_and_lock(
                sample_fingerprint,
                f"DOC-REINGEST-{worker_id}",
            )
            
            if not is_duplicate:
                async with lock:
                    reingested_by.append(f"worker-{worker_id}")
                await asyncio.sleep(0.01)  # Simula processamento
            
            return is_duplicate
        
        # Act
        tasks = [worker_reingest(i) for i in range(5)]
        results = await asyncio.gather(*tasks)
        
        # Assert - apenas um deve re-ingestir
        assert len(reingested_by) == 1, (
            f"Apenas um worker deveria re-ingestir: {reingested_by}"
        )


# =============================================================================
# Testes de Performance
# =============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
class TestDedupPerformance:
    """Testes de performance para deduplicação."""
    
    async def test_concurrent_dedup_performance(
        self,
        redis_with_lock_contention: Mock,
        concurrent_fingerprints: list[str],
    ):
        """Testa performance com múltiplos workers simultâneos."""
        # Arrange
        num_workers = len(concurrent_fingerprints)
        
        # Mock da sessão
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = Mock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        async def worker(fingerprint: str, worker_id: int) -> float:
            """Worker que mede tempo de processamento."""
            import time
            
            start = time.time()
            dedup = Deduplicator(
                mock_session,
                redis_client=redis_with_lock_contention,
            )
            
            await dedup.check_and_lock(
                fingerprint,
                f"DOC-PERF-{worker_id}",
            )
            
            return time.time() - start
        
        # Act
        start_total = datetime.utcnow()
        tasks = [
            worker(fp, i)
            for i, fp in enumerate(concurrent_fingerprints)
        ]
        timings = await asyncio.gather(*tasks)
        total_time = (datetime.utcnow() - start_total).total_seconds()
        
        # Assert
        avg_time = sum(timings) / len(timings)
        max_time = max(timings)
        
        # Todas as operações devem completar em tempo razoável
        assert total_time < 5.0, (
            f"Processamento concorrente muito lento: {total_time:.2f}s"
        )
        
        # Log para análise
        print(f"\nPerformance: {num_workers} workers")
        print(f"  Tempo total: {total_time:.3f}s")
        print(f"  Tempo médio: {avg_time:.3f}s")
        print(f"  Tempo máximo: {max_time:.3f}s")
