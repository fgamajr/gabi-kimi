"""Testes de integração para o Indexer atômico.

Testa atomicidade PG + ES e Saga pattern para rollback.
Baseado nos requisitos da GABI_SPECS_FINAL_v1.md Seção P-001.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

# Models
from gabi.models.base import Base
from gabi.models.chunk import DocumentChunk
from gabi.models.document import Document
from gabi.models.dlq import DLQMessage, DLQStatus
from gabi.models.source import SourceRegistry
from gabi.models.execution import ExecutionManifest
from gabi.models.lineage import LineageNode, LineageEdge
from gabi.types import SensitivityLevel, SourceStatus, SourceType

# Pipeline
from gabi.pipeline.indexer import (
    ChunkData,
    DocumentVersionInfo,
    DuplicateDocumentError,
    ElasticsearchError,
    Indexer,
    IndexingDLQHandler,
    IndexingResult,
    IndexingStatus,
    PostgreSQLError,
    SagaError,
    VersionMismatchError,
    create_indexer,
)
from gabi.services.indexing_service import (
    DocumentContent,
    IndexingService,
    IndexingServiceConfig,
    ProcessingResult,
    ProcessingStage,
)

# DB
from gabi.db import close_db, get_session_no_commit, init_db_with_tables


# =============================================================================
# Fixtures
# =============================================================================

@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Cria sessão de banco para testes."""
    from gabi.db import init_db, get_engine
    
    # Reset DB
    try:
        await init_db()
    except RuntimeError:
        pass  # Already initialized
        
    engine = get_engine()
    async with engine.begin() as conn:
        # Drop all tables with CASCADE to handle views/dependencies
        await conn.execute(text("DO $$ DECLARE r RECORD; BEGIN FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE'; END LOOP; END $$;"))
        # Drop all enum types to ensure fresh definition
        await conn.execute(text("DO $$ DECLARE r RECORD; BEGIN FOR r IN (SELECT typname FROM pg_type JOIN pg_namespace ON pg_type.typnamespace = pg_namespace.oid WHERE nspname = 'public' AND typtype = 'e') LOOP EXECUTE 'DROP TYPE IF EXISTS ' || quote_ident(r.typname) || ' CASCADE'; END LOOP; END $$;"))
        await conn.run_sync(Base.metadata.create_all)
    
    # Setup required sources
    async with get_session_no_commit() as session:
        for source_id in ("test-source", "test", "concurrent-test", "source-456"):
            await session.merge(
                SourceRegistry(
                    id=source_id,
                    name=f"Test {source_id}",
                    type=SourceType.API,
                    status=SourceStatus.ACTIVE,
                    config_hash=hashlib.sha256(source_id.encode()).hexdigest(),
                    config_json={},
                    owner_email="test@example.com",
                    sensitivity=SensitivityLevel.INTERNAL,
                )
            )
        await session.commit()

    async with get_session_no_commit() as session:
        yield session
    
    await close_db()


@pytest.fixture
def mock_es_client() -> MagicMock:
    """Mock do cliente Elasticsearch."""
    client = MagicMock()
    client.index = AsyncMock(return_value={"_id": "test", "result": "created"})
    client.delete = AsyncMock(return_value={"_id": "test", "result": "deleted"})
    client.delete_by_query = AsyncMock(return_value={"deleted": 10})
    client.update = AsyncMock(return_value={"_id": "test", "result": "updated"})
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_bulk_success() -> AsyncMock:
    """Mock para async_bulk com sucesso."""
    async def bulk_success(es, actions, **kwargs):
        return (len(actions), [])  # success_count, errors
    return AsyncMock(side_effect=bulk_success)


@pytest.fixture
def mock_bulk_failure() -> AsyncMock:
    """Mock para async_bulk com falha."""
    async def bulk_failure(es, actions, **kwargs):
        errors = [{"index": {"_id": "1", "error": "some error"}}]
        return (0, errors)
    return AsyncMock(side_effect=bulk_failure)


@pytest.fixture
def sample_document() -> Document:
    """Cria um documento de exemplo."""
    doc_id = f"test-doc-{uuid.uuid4().hex[:8]}"
    return Document(
        document_id=doc_id,
        source_id="test-source",
        fingerprint=hashlib.sha256(b"test content").hexdigest(),
        fingerprint_algorithm="sha256",
        title="Documento de Teste",
        content_preview="Preview do conteúdo",
        doc_metadata={"tipo": "teste"},
        language="pt-BR",
        status="active",
        version=1,
    )


@pytest.fixture
def sample_chunks() -> List[ChunkData]:
    """Cria chunks de exemplo."""
    return [
        ChunkData(
            chunk_index=0,
            text="Primeiro chunk de teste",
            token_count=10,
            char_count=23,
            embedding=[0.1] * 384,
            metadata={"section": "body"},
            section_type="paragrafo",
        ),
        ChunkData(
            chunk_index=1,
            text="Segundo chunk de teste",
            token_count=10,
            char_count=22,
            embedding=[0.2] * 384,
            metadata={"section": "body"},
            section_type="paragrafo",
        ),
    ]


from typing import Generator

# ...

@pytest.fixture
def mock_session_factory(db_session):
    """Factory that returns the shared db_session context manager.
    
    This ensures Indexer uses the same session as the test, allowing it to see
    uncommitted data and participating in the same transaction scope.
    """
    @asynccontextmanager
    async def _mock_get_session():
        # Important: Don't close/commit the test session here
        # just yield it so Indexer can use it
        yield db_session
        
    return _mock_get_session

@pytest.fixture
def indexer(mock_es_client: MagicMock, mock_bulk_success, mock_session_factory) -> Generator[Indexer, None, None]:
    """Cria instância do Indexer com ES mockado e DB session compartilhada."""
    # Patch get_session_no_commit globalmente para este teste
    with patch("gabi.pipeline.indexer.get_session_no_commit", side_effect=mock_session_factory):
        yield Indexer(
            es_client=mock_es_client,
            es_index="test_gabi",
            enable_saga=True,
            bulk_fn=mock_bulk_success,
        )


# =============================================================================
# Testes de Atomicidade
# =============================================================================

@pytest.mark.asyncio
class TestAtomicIndexing:
    """Testes de indexação atômica PG + ES."""
    
    async def test_successful_atomic_indexing(
        self,
        db_session: AsyncSession,
        mock_es_client: MagicMock,
        mock_bulk_success,
        mock_session_factory,
        sample_document: Document,
        sample_chunks: List[ChunkData],
    ) -> None:
        """Testa indexação bem-sucedida em ambos os stores.
        
        Verifica:
        - Documento existe no PG
        - Chunks existem no PG
        - ES bulk foi chamado
        - Status é SUCCESS
        - es_indexed flag foi atualizada
        """
        with patch("elasticsearch.helpers.async_bulk", mock_bulk_success), \
             patch("gabi.pipeline.indexer.get_session_no_commit", side_effect=mock_session_factory):
            indexer = Indexer(es_client=mock_es_client, es_index="test")
            
            # Executa indexação
            result = await indexer.index_document(
                document=sample_document,
                chunks=sample_chunks,
                source_id="test-source",
            )
        
        # Verifica resultado
        assert result.status == IndexingStatus.SUCCESS
        assert result.pg_success is True
        assert result.es_success is True
        assert result.chunks_indexed == 2
        
        # Verifica PG - Documento
        stmt = select(Document).where(Document.document_id == sample_document.document_id)
        query_result = await db_session.execute(stmt)
        doc = query_result.scalar_one_or_none()
        assert doc is not None
        assert doc.document_id == sample_document.document_id
        assert doc.title == sample_document.title
        assert doc.es_indexed is True  # es_indexed flag atualizada
        assert doc.es_indexed_at is not None
        
        # Verifica PG - Chunks
        stmt = select(DocumentChunk).where(
            DocumentChunk.document_id == sample_document.document_id
        )
        query_result = await db_session.execute(stmt)
        chunks = query_result.scalars().all()
        assert len(chunks) == 2
        assert chunks[0].chunk_index == 0
        assert chunks[1].chunk_index == 1
        
    async def test_pg_failure_no_es_call(
        self,
        db_session: AsyncSession,
        mock_es_client: MagicMock,
        sample_document: Document,
        sample_chunks: List[ChunkData],
    ) -> None:
        """Testa que ES não é chamado se PG falhar.
        
        Simula falha no PostgreSQL e verifica que ES não recebe dados.
        """
        bulk_mock = AsyncMock()
        
        with patch("elasticsearch.helpers.async_bulk", bulk_mock):
            indexer = Indexer(es_client=mock_es_client, es_index="test")
            
            # Simula documento inválido (sem source_id obrigatório)
            invalid_doc = Document(
                document_id="test-invalid",
                source_id="",  # Inválido
                fingerprint="abc",
                fingerprint_algorithm="sha256",
                title="Invalid",
                doc_metadata={},
                language="pt-BR",
            )
            
            # Executa (deve falhar no PG)
            # Como já estamos mockando o session factory, podemos injetar a falha
            # de outra forma, mas para manter isolamento deste teste específico
            # vamos sobrescrever o patch
            mock_fail_factory = MagicMock()
            mock_session = AsyncMock()
            # O begin falha ao tentar iniciar transação
            mock_session.begin = MagicMock(side_effect=Exception("PG Error"))
            # Precisamos configurar o context manager do session
            mock_fail_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_fail_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("gabi.pipeline.indexer.get_session_no_commit", side_effect=mock_fail_factory):
                result = await indexer.index_document(
                    document=invalid_doc,
                    chunks=sample_chunks,
                    source_id="test-source",
                )
        
        # Verifica que ES bulk não foi chamado
        bulk_mock.assert_not_called()
        
    async def test_es_failure_triggers_saga_rollback(
        self,
        db_session: AsyncSession,
        mock_es_client: MagicMock,
        mock_bulk_failure,
        mock_session_factory,
        sample_document: Document,
        sample_chunks: List[ChunkData],
    ) -> None:
        """Testa que falha no ES dispara Saga rollback.
        
        Verifica:
        - PG foi atualizado
        - ES falhou
        - Saga executou rollback
        - Documento foi removido do PG
        """
        with patch("elasticsearch.helpers.async_bulk", mock_bulk_failure), \
             patch("gabi.pipeline.indexer.get_session_no_commit", side_effect=mock_session_factory):
            indexer = Indexer(
                es_client=mock_es_client,
                es_index="test",
                enable_saga=True,
            )
            
            # Executa indexação
            result = await indexer.index_document(
                document=sample_document,
                chunks=sample_chunks,
                source_id="test-source",
            )
        
        # Verifica resultado
        assert result.status == IndexingStatus.ROLLED_BACK
        assert result.pg_success is True  # Commitou antes do ES
        assert result.es_success is False  # Falhou
        assert result.saga_executed is True  # Saga foi executado
        
        # Verifica que documento foi removido do PG (rollback)
        stmt = select(Document).where(Document.document_id == sample_document.document_id)
        query_result = await db_session.execute(stmt)
        doc = query_result.scalar_one_or_none()
        assert doc is None  # Rollback removeu
        
        # Verifica que chunks também foram removidos
        stmt = select(DocumentChunk).where(
            DocumentChunk.document_id == sample_document.document_id
        )
        query_result = await db_session.execute(stmt)
        chunks = query_result.scalars().all()
        assert len(chunks) == 0

    async def test_es_failure_without_saga_leaves_pg_data(
        self,
        db_session: AsyncSession,
        mock_es_client: MagicMock,
        mock_bulk_failure,
        sample_document: Document,
        sample_chunks: List[ChunkData],
    ) -> None:
        """Testa que sem Saga, falha ES deixa dados no PG (inconsistência).
        
        Isso documenta o comportamento quando saga está desabilitado.
        """
        with patch("elasticsearch.helpers.async_bulk", mock_bulk_failure):
            # Indexer SEM saga
            indexer = Indexer(
                es_client=mock_es_client,
                es_index="test",
                enable_saga=False,
            )
            
            # Executa indexação
            result = await indexer.index_document(
                document=sample_document,
                chunks=sample_chunks,
                source_id="test-source",
            )
        
        # Verifica resultado
        assert result.status == IndexingStatus.PARTIAL
        assert result.pg_success is True
        assert result.es_success is False
        assert result.saga_executed is False  # Saga não executou
        
        # Documento PERMANECE no PG (inconsistência!)
        stmt = select(Document).where(Document.document_id == sample_document.document_id)
        query_result = await db_session.execute(stmt)
        doc = query_result.scalar_one_or_none()
        assert doc is not None  # Ainda existe


# =============================================================================
# Testes de Reindexação
# =============================================================================

@pytest.mark.asyncio
class TestReindexing:
    """Testes de reindexação de documentos existentes."""
    
    async def test_reindexing_replaces_old_chunks(
        self,
        db_session: AsyncSession,
        mock_es_client: MagicMock,
        mock_bulk_success,
        mock_session_factory,
        sample_document: Document,
        sample_chunks: List[ChunkData],
    ) -> None:
        """Testa que reindexação remove chunks antigos.
        
        Verifica:
        - Chunks antigos são removidos
        - Novos chunks são inseridos
        - Versão é incrementada
        """
        with patch("elasticsearch.helpers.async_bulk", mock_bulk_success), \
             patch("gabi.pipeline.indexer.get_session_no_commit", side_effect=mock_session_factory):
            indexer = Indexer(es_client=mock_es_client, es_index="test")
            
            # Primeira indexação
            await indexer.index_document(
                document=sample_document,
                chunks=sample_chunks,
                source_id="test-source",
            )
        
        # Verifica chunks iniciais
        stmt = select(DocumentChunk).where(
            DocumentChunk.document_id == sample_document.document_id
        )
        result = await db_session.execute(stmt)
        initial_chunks = result.scalars().all()
        assert len(initial_chunks) == 2
        initial_ids = {c.id for c in initial_chunks}
        
        # Novos chunks para reindexação
        new_chunks = [
            ChunkData(
                chunk_index=0,
                text="Novo chunk atualizado",
                token_count=5,
                char_count=21,
                embedding=[0.5] * 384,
            ),
        ]
        
        with patch("elasticsearch.helpers.async_bulk", mock_bulk_success), \
             patch("gabi.pipeline.indexer.get_session_no_commit", side_effect=mock_session_factory):
            # Reindexa
            result = await indexer.reindex_document(
                document_id=sample_document.document_id,
                chunks=new_chunks,
            )
        
        # Verifica
        assert result.status == IndexingStatus.SUCCESS
        
        stmt = select(DocumentChunk).where(
            DocumentChunk.document_id == sample_document.document_id
        )
        result = await db_session.execute(stmt)
        final_chunks = result.scalars().all()
        
        # Apenas 1 chunk novo
        assert len(final_chunks) == 1
        assert final_chunks[0].chunk_text == "Novo chunk atualizado"
        
        # IDs diferentes (old foram deletados)
        final_ids = {c.id for c in final_chunks}
        assert initial_ids.isdisjoint(final_ids)


# =============================================================================
# Testes de Deleção
# =============================================================================

@pytest.mark.asyncio
class TestDeletion:
    """Testes de deleção de documentos."""
    
    async def test_soft_delete(
        self,
        db_session: AsyncSession,
        mock_es_client: MagicMock,
        mock_bulk_success,
        mock_session_factory,
        sample_document: Document,
        sample_chunks: List[ChunkData],
    ) -> None:
        """Testa soft delete preserva dados no PG."""
        with patch("elasticsearch.helpers.async_bulk", mock_bulk_success), \
             patch("gabi.pipeline.indexer.get_session_no_commit", side_effect=mock_session_factory):
            indexer = Indexer(es_client=mock_es_client, es_index="test")
            
            # Indexa primeiro
            await indexer.index_document(
                document=sample_document,
                chunks=sample_chunks,
                source_id="test-source",
            )
        
            # Soft delete (still inside patch scope ideally, but let's re-patch or keep scope)
            success = await indexer.delete_document(
                document_id=sample_document.document_id,
                soft=True,
                deleted_by="tester",
            )
        
        assert success is True
        
        # Verifica documento marcado como deletado
        stmt = select(Document).where(Document.document_id == sample_document.document_id)
        result = await db_session.execute(stmt)
        doc = result.scalar_one()
        assert doc.is_deleted is True
        assert doc.deleted_at is not None
        assert doc.es_indexed is False  # ES sync flag reset
        
        # Verifica que ES foi atualizado
        mock_es_client.update.assert_called()
        
        # Verifica que chunks ES foram limpos
        mock_es_client.delete_by_query.assert_called()
        
    async def test_hard_delete_removes_all(
        self,
        db_session: AsyncSession,
        mock_es_client: MagicMock,
        mock_bulk_success,
        mock_session_factory,
        sample_document: Document,
        sample_chunks: List[ChunkData],
    ) -> None:
        """Testa hard delete remove tudo do PG."""
        with patch("elasticsearch.helpers.async_bulk", mock_bulk_success), \
             patch("gabi.pipeline.indexer.get_session_no_commit", side_effect=mock_session_factory):
            indexer = Indexer(es_client=mock_es_client, es_index="test")
            
            # Indexa primeiro
            await indexer.index_document(
                document=sample_document,
                chunks=sample_chunks,
                source_id="test-source",
            )
        
            # Hard delete
            success = await indexer.delete_document(
                document_id=sample_document.document_id,
                soft=False,
            )
        
        # Hard delete
        success = await indexer.delete_document(
            document_id=sample_document.document_id,
            soft=False,
        )
        
        assert success is True
        
        # Verifica documento removido
        stmt = select(Document).where(Document.document_id == sample_document.document_id)
        result = await db_session.execute(stmt)
        doc = result.scalar_one_or_none()
        assert doc is None
        
        # Verifica chunks removidos
        stmt = select(DocumentChunk).where(
            DocumentChunk.document_id == sample_document.document_id
        )
        result = await db_session.execute(stmt)
        chunks = result.scalars().all()
        assert len(chunks) == 0


# =============================================================================
# Testes de Idempotência
# =============================================================================

@pytest.mark.asyncio
class TestIdempotency:
    """Testes de idempotência e deduplicação."""
    
    async def test_duplicate_fingerprint_detection(
        self,
        db_session: AsyncSession,
        mock_es_client: MagicMock,
        mock_bulk_success,
        mock_session_factory,
        sample_document: Document,
        sample_chunks: List[ChunkData],
    ) -> None:
        """Testa que documentos com mesmo fingerprint são detectados como duplicatas."""
        with patch("elasticsearch.helpers.async_bulk", mock_bulk_success), \
             patch("gabi.pipeline.indexer.get_session_no_commit", side_effect=mock_session_factory):
            indexer = Indexer(es_client=mock_es_client, es_index="test")
            
            # Primeira indexação
            result1 = await indexer.index_document(
                document=sample_document,
                chunks=sample_chunks,
                source_id="test-source",
            )
            assert result1.status == IndexingStatus.SUCCESS
        
            # Cria documento diferente com MESMO fingerprint
            duplicate_doc = Document(
                document_id=f"different-id-{uuid.uuid4().hex[:8]}",
                source_id="test-source",
                fingerprint=sample_document.fingerprint,  # Mesmo fingerprint
                fingerprint_algorithm="sha256",
                title="Documento Duplicado",
                doc_metadata={},
                language="pt-BR",
            )
            
            # Tenta indexar duplicata
            result2 = await indexer.index_document(
                document=duplicate_doc,
                chunks=sample_chunks,
                source_id="test-source",
            )
            
            # Deve ser ignorado como duplicata
            assert result2.status == IndexingStatus.IGNORED
            assert "Duplicate fingerprint" in str(result2.errors)
        
        with patch("elasticsearch.helpers.async_bulk", mock_bulk_success):
            indexer2 = Indexer(es_client=mock_es_client, es_index="test")
            
            # Segunda indexação deve detectar duplicata
            result2 = await indexer2.index_document(
                document=duplicate_doc,
                chunks=sample_chunks,
                source_id="test-source",
            )
        
        assert result2.status == IndexingStatus.DUPLICATE
        assert result2.pg_success is False
        
    async def test_same_document_reindex_allowed(
        self,
        db_session: AsyncSession,
        mock_es_client: MagicMock,
        mock_bulk_success,
        mock_session_factory,
        sample_document: Document,
        sample_chunks: List[ChunkData],
    ) -> None:
        """Testa que reindexação do mesmo documento é permitida."""
        with patch("elasticsearch.helpers.async_bulk", mock_bulk_success), \
             patch("gabi.pipeline.indexer.get_session_no_commit", side_effect=mock_session_factory):
            indexer = Indexer(es_client=mock_es_client, es_index="test")
            
            # Primeira indexação
            result1 = await indexer.index_document(
                document=sample_document,
                chunks=sample_chunks,
                source_id="test-source",
            )
            assert result1.status == IndexingStatus.SUCCESS
            
            # Reindexação do mesmo documento deve ser permitida
            result2 = await indexer.index_document(
                document=sample_document,
                chunks=sample_chunks,
                source_id="test-source",
            )
            assert result2.status == IndexingStatus.SUCCESS


# =============================================================================
# Testes de Versionamento e Race Conditions
# =============================================================================

@pytest.mark.asyncio
class TestVersioning:
    """Testes de version checking para evitar race conditions."""
    
    async def test_saga_rollback_with_version_mismatch(
        self,
        db_session: AsyncSession,
        mock_es_client: MagicMock,
        mock_bulk_failure,
        mock_session_factory,
        sample_document: Document,
        sample_chunks: List[ChunkData],
    ) -> None:
        """Testa que Saga aborta rollback se versão mudou (race condition).
        
        Simula cenário onde outro processo modifica o documento entre
        o commit PG e a falha ES.
        """
        with patch("elasticsearch.helpers.async_bulk", mock_bulk_failure):
            indexer = Indexer(
                es_client=mock_es_client,
                es_index="test",
                enable_saga=True,
            )
            
            # Indexa documento
            await indexer.index_document(
                document=sample_document,
                chunks=sample_chunks,
                source_id="test-source",
            )
        
        # Capture fingerprint before doc becomes detached
        doc_fingerprint = sample_document.fingerprint
        doc_id = sample_document.document_id

        # Documento foi rolado back - vamos criar de novo para o teste
        async def bulk_success(es, actions, **kwargs):
            return (len(actions), [])
        bulk_success_mock = AsyncMock(side_effect=bulk_success)

        with patch("elasticsearch.helpers.async_bulk", bulk_success_mock), \
             patch("gabi.pipeline.indexer.get_session_no_commit", side_effect=mock_session_factory):
            indexer = Indexer(es_client=mock_es_client, es_index="test")
            result = await indexer.index_document(
                document=sample_document,
                chunks=sample_chunks,
                source_id="test-source",
            )
        
        # Atualiza versão do documento (simula outro processo)
        stmt = select(Document).where(Document.document_id == sample_document.document_id)
        query_result = await db_session.execute(stmt)
        doc = query_result.scalar_one()
        doc.version += 1
        await db_session.commit()

        # Tenta rollback com versão antiga
        version_info = DocumentVersionInfo(
            document_id=doc_id,
            version=1,  # Versão antiga
            fingerprint=doc_fingerprint,
            es_indexed=False,
        )
        
        with patch("elasticsearch.helpers.async_bulk", mock_bulk_failure), \
             patch("gabi.pipeline.indexer.get_session_no_commit", side_effect=mock_session_factory):
            rollback_success = await indexer._execute_saga_rollback(version_info)
        
        # Rollback deve falhar devido ao version mismatch
        assert rollback_success is False
        
        # Documento deve persistir no PG
        stmt = select(Document).where(Document.document_id == sample_document.document_id)
        query_result = await db_session.execute(stmt)
        doc = query_result.scalar_one_or_none()
        assert doc is not None
        assert doc.version == 2  # Versão preservada


# =============================================================================
# Testes de DLQ
# =============================================================================

@pytest.mark.asyncio
class TestDLQIntegration:
    """Testes de integração com DLQ."""
    
    async def test_dlq_handler_creates_message(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Testa que handler cria mensagem DLQ corretamente."""
        handler = IndexingDLQHandler()
        
        error = Exception("Test error")
        message = await handler.enqueue_failure(
            document_id="doc-123",
            source_id="source-456",
            error=error,
            run_id=None,
            payload={"content": "test"},
        )
        
        # Verifica mensagem
        assert message.document_id == "doc-123"
        assert message.source_id == "source-456"
        assert message.error_type == "Exception"
        assert message.error_message == "Test error"
        assert message.status == DLQStatus.PENDING
        
        # Verifica no banco
        stmt = select(DLQMessage).where(DLQMessage.id == message.id)
        result = await db_session.execute(stmt)
        stored = result.scalar_one_or_none()
        assert stored is not None
        assert stored.error_hash is not None


# =============================================================================
# Testes do IndexingService
# =============================================================================

@pytest.mark.asyncio
class TestIndexingService:
    """Testes do serviço de indexação de alto nível."""
    
    @pytest.fixture
    def mock_embedder(self) -> MagicMock:
        """Mock do embedder."""
        embedder = MagicMock()
        embedder.embed = AsyncMock(return_value=[[0.1] * 384] * 2)
        return embedder
    
    @pytest.fixture
    def indexing_service(
        self,
        mock_es_client: MagicMock,
        mock_embedder: MagicMock,
        mock_bulk_success,
        mock_session_factory,
    ) -> Generator[IndexingService, None, None]:
        """Cria serviço de indexação."""
        with patch("elasticsearch.helpers.async_bulk", mock_bulk_success), \
             patch("gabi.pipeline.indexer.get_session_no_commit", side_effect=mock_session_factory):
            indexer = Indexer(es_client=mock_es_client, es_index="test")
            config = IndexingServiceConfig(enable_dlq=False)
            
            yield IndexingService(
                indexer=indexer,
                embedder=mock_embedder,
                config=config,
                dlq_handler=None,
            )
    
    async def test_full_pipeline(
        self,
        db_session: AsyncSession,
        indexing_service: IndexingService,
    ) -> None:
        """Testa pipeline completo: chunking → embedding → indexação."""
        content = DocumentContent(
            document_id="full-pipeline-test",
            source_id="test-source",
            title="Teste Pipeline Completo",
            content="Primeiro parágrafo do documento. " * 20 + "\n\n" +
                   "Segundo parágrafo do documento. " * 20,
            url="http://test.com/doc",
        )
        
        result = await indexing_service.process_document(content)
        
        assert result.success is True
        assert result.stage == ProcessingStage.COMPLETED
        assert result.chunks_count > 0
        assert result.indexing_result is not None
        assert result.indexing_result.status == IndexingStatus.SUCCESS
        
        # Verifica no PG
        stmt = select(Document).where(Document.document_id == content.document_id)
        query_result = await db_session.execute(stmt)
        doc = query_result.scalar_one_or_none()
        assert doc is not None
        assert doc.title == content.title
        
        # Verifica que es_indexed foi atualizado
        assert doc.es_indexed is True
        assert doc.es_indexed_at is not None
        
    async def test_empty_content(
        self,
        indexing_service: IndexingService,
    ) -> None:
        """Testa comportamento com conteúdo vazio."""
        content = DocumentContent(
            document_id="empty-test",
            source_id="test-source",
            title="Documento Vazio",
            content="",
        )
        
        result = await indexing_service.process_document(content)
        
        # Deve completar sem erros, mas sem chunks
        assert result.success is True
        assert result.chunks_count == 0
        
    async def test_batch_processing(
        self,
        db_session: AsyncSession,
        mock_es_client: MagicMock,
        mock_embedder: MagicMock,
        mock_bulk_success,
    ) -> None:
        """Testa processamento em batch."""
        with patch("elasticsearch.helpers.async_bulk", mock_bulk_success):
            indexer = Indexer(es_client=mock_es_client, es_index="test")
        
            config = IndexingServiceConfig(enable_dlq=False)
            service = IndexingService(
                indexer=indexer,
                embedder=mock_embedder,
                config=config,
            )
            
            contents = [
                DocumentContent(
                    document_id=f"batch-test-{i}",
                    source_id="test-source",
                    title=f"Documento {i}",
                    content=f"Conteúdo do documento {i}. " * 50,
                )
                for i in range(5)
            ]
            
            result = await service.process_batch(contents)
        
        assert result.total == 5
        assert result.successful == 5
        assert result.failed == 0
        assert result.success_rate == 1.0
        
    async def test_batch_with_partial_failure(
        self,
        db_session: AsyncSession,
        mock_es_client: MagicMock,
        mock_embedder: MagicMock,
    ) -> None:
        """Testa batch com falha parcial."""
        # Configura ES para falhar no 3º documento
        call_count = 0
        async def es_bulk_side_effect(es, actions, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                return (0, [{"error": "ES Error"}])
            return (len(actions), [])
        
        with patch("elasticsearch.helpers.async_bulk", AsyncMock(side_effect=es_bulk_side_effect)):
            indexer = Indexer(es_client=mock_es_client, es_index="test", enable_saga=True)
            config = IndexingServiceConfig(enable_dlq=False)
            
            service = IndexingService(
                indexer=indexer,
                embedder=mock_embedder,
                config=config,
            )
            
            contents = [
                DocumentContent(
                    document_id=f"partial-test-{i}",
                    source_id="test-source",
                    title=f"Documento {i}",
                    content=f"Conteúdo do documento {i}. " * 50,
                )
                for i in range(5)
            ]
            
            result = await service.process_batch(contents)
        
        # 4 sucessos (3º falhou e foi rolado back)
        assert result.total == 5
        assert result.successful == 4
        assert result.failed == 1


# =============================================================================
# Testes de Performance
# =============================================================================

@pytest.mark.asyncio
class TestPerformance:
    """Testes de performance da indexação."""
    
    async def test_indexing_duration_tracking(
        self,
        mock_es_client: MagicMock,
        mock_bulk_success,
        sample_document: Document,
        sample_chunks: List[ChunkData],
    ) -> None:
        """Testa que duração é corretamente medida."""
        with patch("elasticsearch.helpers.async_bulk", mock_bulk_success):
            indexer = Indexer(es_client=mock_es_client, es_index="test")
            
            result = await indexer.index_document(
                document=sample_document,
                chunks=sample_chunks,
                source_id="test-source",
            )
        
        assert result.duration_ms is not None
        assert result.duration_ms >= 0
        # Deve ser razoavelmente rápido (< 5s para teste simples)
        assert result.duration_ms < 5000


# =============================================================================
# Testes de Concorrência
# =============================================================================

@pytest.mark.asyncio
class TestConcurrency:
    """Testes de concorrência e paralelismo."""
    
    async def test_concurrent_indexing(
        self,
        db_session: AsyncSession,
        mock_es_client: MagicMock,
    ) -> None:
        """Testa indexação concorrente de múltiplos documentos.
        
        Verifica que não há race conditions.
        NOTA: Não usamos a fixture 'indexer' aqui pois ela compartilha
        a mesma sessão de banco, o que falha com asyncio.gather.
        Usamos sessões reais independentes para cada task.
        """
        async def _mock_async_bulk(es, actions, **kwargs):
            return (len(actions), [])

        indexer = Indexer(
            es_client=mock_es_client,
            es_index="test_gabi",
            enable_saga=True,
            bulk_fn=_mock_async_bulk,
        )
        
        async def index_one(doc_id: str) -> IndexingResult:
            doc = Document(
                document_id=doc_id,
                source_id="concurrent-test",
                fingerprint=hashlib.sha256(doc_id.encode()).hexdigest(),
                fingerprint_algorithm="sha256",
                title=f"Doc {doc_id}",
                doc_metadata={},
                language="pt-BR",
            )
            chunks = [
                ChunkData(
                    chunk_index=0,
                    text=f"Content {doc_id}",
                    token_count=5,
                    char_count=20,
                    embedding=[0.1] * 384,
                )
            ]
            # Use shared indexer (stateless for this op)
            return await indexer.index_document(doc, chunks, "concurrent-test")
        
        # Executa 10 concorrentes
        doc_ids = [f"concurrent-{i}" for i in range(10)]
        results = await asyncio.gather(*[index_one(did) for did in doc_ids])
        
        # Todos devem ter sucesso
        assert all(r.status == IndexingStatus.SUCCESS for r in results)
        
        # Verifica no PG - todos devem existir
        for doc_id in doc_ids:
            stmt = select(Document).where(Document.document_id == doc_id)
            result = await db_session.execute(stmt)
            doc = result.scalar_one_or_none()
            assert doc is not None, f"Documento {doc_id} não encontrado"


# =============================================================================
# Testes de Edge Cases
# =============================================================================

@pytest.mark.asyncio
class TestEdgeCases:
    """Testes de casos extremos."""
    
    async def test_very_large_content(
        self,
        mock_es_client: MagicMock,
        mock_bulk_success,
        db_session: AsyncSession,
    ) -> None:
        """Testa indexação de conteúdo muito grande."""
        large_content = "A" * 1_000_000  # 1MB
        doc = Document(
            document_id="large-doc",
            source_id="test",
            fingerprint=hashlib.sha256(large_content.encode()).hexdigest(),
            fingerprint_algorithm="sha256",
            title="Large Document",
            content_preview=large_content[:1000],
            content_size_bytes=len(large_content.encode()),
            doc_metadata={},
            language="pt-BR",
        )
        
        # Muitos chunks
        chunks = [
            ChunkData(
                chunk_index=i,
                text=f"Chunk {i} " * 100,
                token_count=512,
                char_count=1024,
                embedding=[0.01] * 384,
            )
            for i in range(100)  # 100 chunks
        ]
        
        with patch("elasticsearch.helpers.async_bulk", mock_bulk_success):
            indexer = Indexer(es_client=mock_es_client, es_index="test")
            result = await indexer.index_document(doc, chunks, "test")
        
        assert result.status == IndexingStatus.SUCCESS
        assert result.chunks_indexed == 100
        
    async def test_special_characters_in_content(
        self,
        mock_es_client: MagicMock,
        mock_bulk_success,
        db_session: AsyncSession,
    ) -> None:
        """Testa conteúdo com caracteres especiais."""
        special_content = "Conteúdo com acentos: áéíóú ñ ç \n\t \\ \" ' <script>"
        doc = Document(
            document_id="special-chars",
            source_id="test",
            fingerprint=hashlib.sha256(special_content.encode()).hexdigest(),
            fingerprint_algorithm="sha256",
            title="Special Chars: <>&\"'",
            doc_metadata={"key": "value with spaces and \"quotes\""},
            language="pt-BR",
        )
        
        chunks = [ChunkData(
            chunk_index=0,
            text=special_content,
            token_count=10,
            char_count=len(special_content),
            embedding=[0.1] * 384,
        )]
        
        with patch("elasticsearch.helpers.async_bulk", mock_bulk_success):
            indexer = Indexer(es_client=mock_es_client, es_index="test")
            result = await indexer.index_document(doc, chunks, "test")
        
        assert result.status == IndexingStatus.SUCCESS


# =============================================================================
# Testes de ES Bulk Compensating Delete
# =============================================================================

@pytest.mark.asyncio
class TestESBulkCompensatingDelete:
    """Testes de compensação para falhas parciais no ES bulk."""
    
    async def test_compensating_delete_on_partial_failure(
        self,
        mock_es_client: MagicMock,
        sample_document: Document,
        sample_chunks: List[ChunkData],
        db_session: AsyncSession,
    ) -> None:
        """Testa que compensating delete é executado em falha parcial.
        
        Verifica que documentos/chunks parcialmente indexados são removidos.
        """
        # Mock para falha parcial (alguns itens falham)
        async def partial_bulk_failure(es, actions, **kwargs):
            # Simula falha de alguns chunks
            errors = [
                {"index": {"_id": f"{sample_document.document_id}_1", "error": "shard failure"}}
            ]
            return (len(actions) - 1, errors)  # parcial success
        
        with patch("elasticsearch.helpers.async_bulk", AsyncMock(side_effect=partial_bulk_failure)):
            indexer = Indexer(es_client=mock_es_client, es_index="test", enable_saga=True)
            
            result = await indexer.index_document(
                document=sample_document,
                chunks=sample_chunks,
                source_id="test-source",
            )
        
        # Deve detectar como falha
        assert result.es_success is False
        
        # Compensating delete deve ter sido chamado
        mock_es_client.delete.assert_called()


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "TestAtomicIndexing",
    "TestReindexing",
    "TestDeletion",
    "TestIdempotency",
    "TestVersioning",
    "TestDLQIntegration",
    "TestIndexingService",
    "TestPerformance",
    "TestConcurrency",
    "TestEdgeCases",
    "TestESBulkCompensatingDelete",
]
