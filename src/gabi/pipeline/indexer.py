"""Indexer atômico com Saga pattern para GABI.

Este módulo implementa indexação atômica entre PostgreSQL e Elasticsearch,
garantindo consistência através de transações PG + Saga pattern para rollback.

Baseado em GABI_SPECS_FINAL_v1.md:
- P-001: Indexação atômica (PG + ES em transação)
- Saga pattern para compensação em caso de falha ES
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Dict, List, Optional, Protocol, Tuple
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession

from gabi.db import get_session_no_commit
from gabi.models.chunk import DocumentChunk
from gabi.models.document import Document
from gabi.models.dlq import DLQMessage, DLQStatus
from gabi.models.execution import ExecutionManifest
from gabi.models.source import SourceRegistry
from gabi.types import SourceType
from gabi.config import settings

if TYPE_CHECKING:
    from elasticsearch import AsyncElasticsearch

logger = logging.getLogger(__name__)


# =============================================================================
# Enums e Tipos
# =============================================================================

class IndexingStatus(str, Enum):
    """Status do processo de indexação."""
    
    PENDING = "pending"  # Status inicial
    SUCCESS = "success"
    PARTIAL = "partial"  # PG ok, ES falhou (será retentado)
    FAILED = "failed"    # Falha em ambos
    ROLLED_BACK = "rolled_back"  # Saga executou rollback
    DUPLICATE = "duplicate"  # Documento duplicado (mesmo fingerprint)
    IGNORED = "ignored"  # Duplicata ignorada na execução atual


class SagaStepStatus(str, Enum):
    """Status de um passo do Saga."""
    
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    COMPENSATED = "compensated"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ChunkData:
    """Dados de um chunk para indexação."""
    
    chunk_index: int
    text: str
    token_count: int
    char_count: int
    embedding: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)
    section_type: Optional[str] = None


@dataclass  
class IndexingResult:
    """Resultado da indexação de um documento.
    
    Attributes:
        document_id: ID do documento indexado
        status: Status final da indexação
        chunks_indexed: Quantidade de chunks indexados
        pg_success: Se PostgreSQL foi atualizado com sucesso
        es_success: Se Elasticsearch foi indexado com sucesso
        saga_executed: Se o Saga de rollback foi executado
        errors: Lista de erros ocorridos
        duration_ms: Duração total em milissegundos
    """
    
    document_id: str
    status: IndexingStatus
    chunks_indexed: int = 0
    pg_success: bool = False
    es_success: bool = False
    saga_executed: bool = False
    errors: List[str] = field(default_factory=list)
    duration_ms: Optional[float] = None


@dataclass
class SagaStep:
    """Passo individual do Saga pattern.
    
    Attributes:
        name: Nome do passo
        action: Ação a executar
        compensate: Ação de compensação (rollback)
        status: Status atual
        result: Resultado da execução
    """
    
    name: str
    action: Callable[[], Coroutine[Any, Any, Any]]
    compensate: Callable[[], Coroutine[Any, Any, Any]]
    status: SagaStepStatus = SagaStepStatus.PENDING
    result: Any = None
    error: Optional[str] = None


@dataclass
class DocumentVersionInfo:
    """Informações de versão para optimistic locking.
    
    Attributes:
        document_id: ID do documento
        version: Versão esperada
        fingerprint: Fingerprint do documento
        es_indexed: Flag de indexação ES
    """
    document_id: str
    version: int
    fingerprint: str
    es_indexed: bool


# =============================================================================
# Exceções
# =============================================================================

class IndexingError(Exception):
    """Erro base para falhas de indexação."""
    pass


class PostgreSQLError(IndexingError):
    """Erro ao persistir no PostgreSQL."""
    pass


class ElasticsearchError(IndexingError):
    """Erro ao indexar no Elasticsearch."""
    pass


class SagaError(IndexingError):
    """Erro durante execução do Saga."""
    pass


class DuplicateDocumentError(IndexingError):
    """Erro quando documento duplicado é detectado."""
    pass


class VersionMismatchError(IndexingError):
    """Erro quando versão do documento não corresponde (race condition)."""
    pass


# =============================================================================
# Indexer
# =============================================================================

class Indexer:
    """Indexer atômico com Saga pattern para consistência PG + ES.
    
    Garante que:
    1. PostgreSQL é atualizado primeiro (source of truth)
    2. Se ES falhar, Saga executa rollback no PG
    3. DLQ é populada para retries automáticos
    4. Idempotência via fingerprint checking
    5. Optimistic locking para prevenir race conditions
    
    Fluxo:
        1. Verificar duplicatas (fingerprint)
        2. Iniciar transação PG
        3. Deletar chunks antigos (se reindexação)
        4. Inserir/atualizar documento
        5. Inserir chunks com embeddings
        6. COMMIT PG
        7. Indexar no ES (atomic bulk)
        8. Marcar como es_indexed
        9. Se ES falhar -> Saga rollback (deletar do PG)
    """
    
    def __init__(
        self,
        es_client: AsyncElasticsearch,
        es_index: Optional[str] = None,
        embedding_dim: int = 384,
        enable_saga: bool = True,
        bulk_fn: Optional[Callable[..., Coroutine[Any, Any, Tuple[int, List[Any]]]]] = None,
    ):
        """Inicializa o Indexer.
        
        Args:
            es_client: Cliente Elasticsearch async
            es_index: Nome do índice ES
            embedding_dim: Dimensionalidade dos embeddings (padrão: 384)
            enable_saga: Habilita rollback automático via Saga
        """
        self.es = es_client
        self.es_index = es_index or settings.elasticsearch_index
        self.embedding_dim = embedding_dim
        self.enable_saga = enable_saga
        self._saga_steps: List[SagaStep] = []
        self._processed_fingerprints: set[str] = set()
        self._bulk_fn = bulk_fn
        
    # ========================================================================
    # API Pública
    # ========================================================================
    
    async def index_document(
        self,
        document: Document,
        chunks: List[ChunkData],
        source_id: str,
        run_id: Optional[UUID] = None,
    ) -> IndexingResult:
        """Indexa um documento com atomicidade PG + ES.
        
        Args:
            document: Documento a indexar
            chunks: Lista de chunks com embeddings
            source_id: ID da fonte de origem
            run_id: ID da execução atual (para tracking)
            
        Returns:
            IndexingResult com status da operação
        """
        start_time = datetime.now()
        result = IndexingResult(document_id=document.document_id, status=IndexingStatus.PENDING)
        
        try:
            # =================================================================
            # FASE 0: Idempotência - Verificar duplicatas
            # =================================================================
            duplicate_check = await self._check_duplicate_by_fingerprint(
                document.fingerprint, document.document_id
            )
            if duplicate_check.is_duplicate and duplicate_check.existing_doc_id != document.document_id:
                logger.info(
                    f"Documento {document.document_id} é duplicata de "
                    f"{duplicate_check.existing_doc_id} (fingerprint match)"
                )
                result.status = (
                    IndexingStatus.IGNORED
                    if document.fingerprint in self._processed_fingerprints
                    else IndexingStatus.DUPLICATE
                )
                result.errors.append(
                    f"Duplicate fingerprint: {duplicate_check.existing_doc_id}"
                )
                result.duration_ms = round(
                    (datetime.now() - start_time).total_seconds() * 1000, 2
                )
                return result
            
            # =================================================================
            # FASE 1: PostgreSQL (Source of Truth)
            # =================================================================
            pg_result, document = await self._execute_pg_phase(document, chunks)
            result.pg_success = pg_result.success
            
            if not pg_result.success:
                result.status = IndexingStatus.FAILED
                result.errors.append("Falha na persistência PostgreSQL")
                return result
            
            # Guarda info de versão para Saga rollback
            version_info = DocumentVersionInfo(
                document_id=document.document_id,
                version=document.version,
                fingerprint=document.fingerprint,
                es_indexed=document.es_indexed,
            )
            
            result.chunks_indexed = len(chunks)
            
            # =================================================================
            # FASE 2: Elasticsearch (Secondary Index)
            # =================================================================
            try:
                await self._execute_es_phase(document, chunks)
                result.es_success = True
                result.status = IndexingStatus.SUCCESS
                
                # Mark as synced after successful ES indexing
                await self._mark_document_indexed(document.document_id)
                self._processed_fingerprints.add(document.fingerprint)
                
            except ElasticsearchError as e:
                result.errors.append(f"Elasticsearch error: {e}")
                
                # =============================================================
                # FASE 3: Saga Rollback (se habilitado)
                # =============================================================
                if self.enable_saga:
                    logger.warning(
                        f"ES falhou para {document.document_id}. "
                        "Executando Saga rollback..."
                    )
                    saga_success = await self._execute_saga_rollback(version_info)
                    result.saga_executed = True
                    
                    if saga_success:
                        result.status = IndexingStatus.ROLLED_BACK
                    else:
                        result.status = IndexingStatus.PARTIAL
                        # PG tem dados mas ES não - necessita reconciliação
                else:
                    result.status = IndexingStatus.PARTIAL
                    
        except Exception as e:
            logger.exception(f"Erro inesperado na indexação: {e}")
            result.status = IndexingStatus.FAILED
            result.errors.append(str(e))
            
        finally:
            duration = (datetime.now() - start_time).total_seconds() * 1000
            result.duration_ms = round(duration, 2)
            
        return result
    
    async def reindex_document(
        self,
        document_id: str,
        chunks: List[ChunkData],
    ) -> IndexingResult:
        """Reindexa um documento existente (update).
        
        Args:
            document_id: ID do documento a reindexar
            chunks: Novos chunks com embeddings
            
        Returns:
            IndexingResult com status da operação
        """
        # Busca documento existente
        async with get_session_no_commit() as session:
            stmt = select(Document).where(Document.document_id == document_id)
            result_query = await session.execute(stmt)
            document = result_query.scalar_one_or_none()
            
            if not document:
                raise IndexingError(f"Documento {document_id} não encontrado")
            
            # Atualiza versão
            document.version += 1
            document.updated_at = datetime.now(timezone.utc)
            
            return await self.index_document(
                document=document,
                chunks=chunks,
                source_id=document.source_id,
            )
    
    async def delete_document(
        self,
        document_id: str,
        soft: bool = True,
        deleted_by: Optional[str] = None,
    ) -> bool:
        """Remove um documento dos índices.
        
        Args:
            document_id: ID do documento
            soft: Se True, soft delete; se False, delete físico
            deleted_by: Identificador de quem está deletando
            
        Returns:
            True se removido com sucesso
        """
        async with get_session_no_commit() as session:
            try:
                if soft:
                    # Soft delete no PG with audit info
                    now = datetime.now(timezone.utc)
                    now_naive = now.replace(tzinfo=None)
                    stmt = (
                        update(Document)
                        .where(Document.document_id == document_id)
                        .values(
                            is_deleted=True,
                            deleted_at=now,
                            deleted_by=deleted_by,
                            status="deleted",
                            es_indexed=False,
                        )
                    )
                    await session.execute(stmt)
                    
                    # Also soft delete associated chunks
                    stmt_chunks = (
                        update(DocumentChunk)
                        .where(DocumentChunk.document_id == document_id)
                        .values(
                            is_deleted=True,
                            deleted_at=now_naive,
                        )
                    )
                    await session.execute(stmt_chunks)
                else:
                    # Delete físico
                    stmt = delete(Document).where(Document.document_id == document_id)
                    await session.execute(stmt)
                
                await session.commit()
                
                # Update ES (mark as deleted instead of hard delete)
                try:
                    await self.es.update(
                        index=self.es_index,
                        id=document_id,
                        doc={
                            "is_deleted": True,
                            "deleted_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                except Exception as e:
                    logger.warning(f"Falha ao atualizar ES: {e}")
                    # Não falha - PG é source of truth
                
                # Clean up ES chunks
                try:
                    await self._delete_es_chunks(document_id)
                except Exception as e:
                    logger.warning(f"Falha ao limpar chunks do ES: {e}")
                    # Não falha - PG é source of truth
                    
                return True
                
            except Exception as e:
                await session.rollback()
                logger.exception(f"Erro ao deletar documento: {e}")
                return False
    
    # ========================================================================
    # Fases Internas
    # ========================================================================
    
    async def _execute_pg_phase(
        self,
        document: Document,
        chunks: List[ChunkData],
    ) -> Tuple["PGPhaseResult", Document]:
        """Executa a fase PostgreSQL da indexação.
        
        Args:
            document: Documento a persistir
            chunks: Chunks com embeddings
            
        Returns:
            Tuple[PGPhaseResult, Document] com status e documento (possivelmente merged)
        """
        async with get_session_no_commit() as session:
            try:
                # Inicia transação se não estiver em uma
                nested = session.in_transaction()
                cm = session.begin_nested() if nested else session.begin()
                
                async with cm:
                    # 1. Verifica se documento existe (para reindexação)
                    existing = await self._get_document_by_id(
                        session, document.document_id
                    )
                    
                    if existing:
                        # Reindexação: deleta chunks antigos
                        await self._delete_chunks_by_document(
                            session, document.document_id
                        )
                        # Garante update na linha existente (evita INSERT duplicado)
                        document.id = existing.id

                    # Merge cobre tanto novos documentos quanto reindexação
                    persistent_doc = await session.merge(document)
                    
                    # Force document persist before chunks to satisfy FK
                    await session.flush()
                    
                    # 2. Insere novos chunks
                    for chunk_data in chunks:
                        chunk = DocumentChunk(
                            document_id=document.document_id,
                            chunk_index=chunk_data.chunk_index,
                            chunk_text=chunk_data.text,
                            token_count=chunk_data.token_count,
                            char_count=chunk_data.char_count,
                            embedding=chunk_data.embedding,
                            embedding_model="paraphrase-multilingual-MiniLM-L12-v2",
                            embedded_at=datetime.now(),
                            chunk_metadata=chunk_data.metadata,
                            section_type=chunk_data.section_type,
                        )
                        session.add(chunk)
                    
                    # 3. Atualiza contador de chunks
                    persistent_doc.chunks_count = len(chunks)
                    
                # Commit automático pelo context manager
                
                # Refresh para garantir que atributos (updated_at, etc) estejam carregados
                # antes de fechar a sessão, evitando DetachedInstanceError na fase ES
                try:
                    await session.refresh(persistent_doc)
                except InvalidRequestError:
                    logger.debug(
                        "Documento não estava persistente para refresh; usando valores em memória."
                    )
                # Force load of datetime fields
                _ = persistent_doc.ingested_at
                _ = persistent_doc.updated_at
                _ = persistent_doc.created_at if hasattr(persistent_doc, 'created_at') else None
                
                logger.debug(f"PG commit OK para {document.document_id}")
                return PGPhaseResult(success=True), persistent_doc
                
            except Exception as e:
                await session.rollback()
                logger.exception(f"Falha na fase PG: {e}")
                raise PostgreSQLError(f"Falha PostgreSQL: {e}") from e
    
    async def _execute_es_phase(
        self,
        document: Document,
        chunks: List[ChunkData],
    ) -> None:
        """Executa a fase Elasticsearch da indexação.
        
        Args:
            document: Documento a indexar
            chunks: Chunks para indexação
            
        Raises:
            ElasticsearchError: Se falhar ao indexar
        """
        try:
            # Use atomic bulk indexing for document + chunks
            success, failed_items = await self._execute_es_phase_atomic(document, chunks)
            if not success:
                # Compensating delete for partial failures
                if failed_items:
                    await self._compensate_es_partial_failure(document.document_id, failed_items)
                raise ElasticsearchError(f"Bulk indexing failed: {failed_items}")
            
            logger.debug(f"ES index OK para {document.document_id}")
            
        except Exception as e:
            logger.exception(f"Falha na fase ES: {e}")
            raise ElasticsearchError(f"Falha Elasticsearch: {e}") from e
    
    async def _execute_es_phase_atomic(
        self,
        document: Document,
        chunks: List[ChunkData],
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """Index document and chunks atomically using bulk API.
        
        Args:
            document: Documento a indexar
            chunks: Chunks para indexação
            
        Returns:
            Tuple de (sucesso, lista de falhas)
        """
        try:
            from elasticsearch.helpers import async_bulk
            bulk_fn = self._bulk_fn or async_bulk
            
            actions = [
                {
                    "_index": self.es_index,
                    "_id": document.document_id,
                    "_source": {
                        "document_id": document.document_id,
                        "source_id": document.source_id,
                        "title": document.title,
                        "content_preview": document.content_preview,
                        "fingerprint": document.fingerprint,
                        "metadata": document.doc_metadata,
                        "status": document.status,
                        "version": document.version,
                        "language": document.language,
                        "chunks_count": len(chunks),
                        "is_deleted": document.is_deleted,
                        "ingested_at": document.ingested_at.isoformat() if document.ingested_at else None,
                        "updated_at": document.updated_at.isoformat() if document.updated_at else None,
                    }
                }
            ]
            
            for chunk in chunks:
                actions.append({
                    "_index": f"{self.es_index}_chunks",
                    "_id": f"{document.document_id}_{chunk.chunk_index}",
                    "_source": {
                        "document_id": document.document_id,
                        "chunk_index": chunk.chunk_index,
                        "text": chunk.text,
                        "embedding": chunk.embedding,
                        "section_type": chunk.section_type,
                        "metadata": chunk.metadata,
                    }
                })
            
            # Bulk index with refresh
            success, errors = await bulk_fn(
                self.es, 
                actions, 
                refresh="wait_for",
                raise_on_error=False,  # Don't raise, let us handle errors
            )
            
            # Process errors
            failed_items = []
            if errors:
                for item in errors:
                    failed_items.append(item)
                    logger.error(f"Bulk indexing error: {item}")
                
                # If any failed, consider it a partial failure
                if len(failed_items) > 0:
                    logger.error(f"Bulk indexing had {len(failed_items)} errors out of {len(actions)} actions")
                    return False, failed_items
            
            return True, []
            
        except Exception as e:
            logger.error(f"Bulk indexing failed: {e}")
            return False, [{"error": str(e)}]
    
    async def _compensate_es_partial_failure(
        self,
        document_id: str,
        failed_items: List[Dict[str, Any]],
    ) -> None:
        """Compensating action for partial ES bulk failures.
        
        Deletes any successfully indexed documents/chunks when partial
        failure occurs to maintain consistency.
        
        Args:
            document_id: ID do documento
            failed_items: Lista de itens que falharam
        """
        try:
            logger.warning(
                f"Executando compensating delete para {document_id} "
                f"devido a falha parcial no bulk"
            )
            
            # Delete document
            try:
                await self.es.delete(
                    index=self.es_index,
                    id=document_id,
                    ignore=[404]
                )
            except Exception as e:
                logger.warning(f"Compensating delete failed for document: {e}")
            
            # Delete all chunks
            await self._delete_es_chunks(document_id)
            
        except Exception as e:
            logger.error(f"Compensating delete failed: {e}")
    
    async def _delete_es_chunks(self, document_id: str) -> None:
        """Deleta todos os chunks de um documento do ES.
        
        Args:
            document_id: ID do documento
        """
        try:
            # Use delete_by_query para remover todos os chunks do documento
            await self.es.delete_by_query(
                index=f"{self.es_index}_chunks",
                body={
                    "query": {
                        "term": {
                            "document_id": document_id
                        }
                    }
                },
                refresh=True,
                ignore=[404]
            )
            logger.debug(f"ES chunks deletados para {document_id}")
        except Exception as e:
            logger.warning(f"Falha ao deletar ES chunks: {e}")
    
    async def _mark_document_indexed(self, document_id: str) -> None:
        """Mark document as indexed in PostgreSQL.
        
        Uses the model's mark_es_synced() method to ensure consistency.
        
        Args:
            document_id: ID do documento a marcar
        """
        try:
            async with get_session_no_commit() as session:
                stmt = select(Document).where(Document.document_id == document_id)
                result = await session.execute(stmt)
                document = result.scalar_one_or_none()
                
                if document:
                    # Use the model method to ensure consistency
                    document.mark_es_synced()
                    await session.commit()
                    logger.debug(f"Document {document_id} marked as indexed")
                else:
                    logger.warning(f"Document {document_id} not found for marking")
        except Exception as e:
            logger.warning(f"Failed to mark document {document_id} as indexed: {e}")
    
    async def _execute_saga_rollback(
        self,
        version_info: DocumentVersionInfo,
    ) -> bool:
        """Executa compensação Saga para rollback.
        
        Remove o documento do PG se ES falhou.
        Inclui version checking para evitar race conditions.
        
        Args:
            version_info: Informações de versão do documento
            
        Returns:
            True se rollback bem-sucedido
        """
        async with get_session_no_commit() as session:
            try:
                # 1. Verifica versão para evitar race condition
                stmt = select(Document).where(
                    Document.document_id == version_info.document_id
                )
                result = await session.execute(stmt)
                current_doc = result.scalar_one_or_none()
                
                if not current_doc:
                    logger.warning(
                        f"Documento {version_info.document_id} não encontrado "
                        "para rollback - pode já ter sido deletado"
                    )
                    return True  # Considera sucesso (estado desejado)
                
                # Version check: só faz rollback se versão for a mesma
                # Isso evita deletar um documento que foi modificado por outro processo
                if current_doc.version != version_info.version:
                    logger.error(
                        f"Version mismatch no Saga rollback: "
                        f"esperado {version_info.version}, "
                        f"encontrado {current_doc.version}. "
                        "Rollback abortado para evitar data loss."
                    )
                    # Não faz rollback - documento foi modificado
                    return False
                
                # 2. Deleta chunks
                await self._delete_chunks_by_document(session, version_info.document_id)
                
                # 3. Deleta documento
                stmt = delete(Document).where(
                    Document.document_id == version_info.document_id
                )
                await session.execute(stmt)
                await session.commit()
                
                logger.info(f"Saga rollback executado para {version_info.document_id}")
                return True
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Falha no Saga rollback: {e}")
                return False
    
    async def _check_duplicate_by_fingerprint(
        self,
        fingerprint: str,
        current_document_id: str,
    ) -> "DuplicateCheckResult":
        """Verifica se existe documento com mesmo fingerprint.
        
        Args:
            fingerprint: Fingerprint a verificar
            current_document_id: ID do documento atual (para permitir reindexação)
            
        Returns:
            DuplicateCheckResult com resultado da verificação
        """
        try:
            async with get_session_no_commit() as session:
                stmt = select(Document).where(
                    Document.fingerprint == fingerprint,
                    Document.is_deleted == False,  # noqa: E712
                )
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()
                
                if existing and existing.document_id != current_document_id:
                    return DuplicateCheckResult(
                        is_duplicate=True,
                        existing_doc_id=existing.document_id,
                    )
                
                return DuplicateCheckResult(is_duplicate=False)
                
        except Exception as e:
            logger.warning(f"Erro ao verificar duplicata: {e}")
            # Em caso de erro, permite continuar (fail open)
            return DuplicateCheckResult(is_duplicate=False)
    
    # ========================================================================
    # Helpers
    # ========================================================================
    
    async def _get_document_by_id(
        self,
        session: AsyncSession,
        document_id: str,
    ) -> Optional[Document]:
        """Busca documento pelo ID."""
        stmt = select(Document).where(Document.document_id == document_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def _delete_chunks_by_document(
        self,
        session: AsyncSession,
        document_id: str,
    ) -> None:
        """Deleta todos os chunks de um documento."""
        stmt = delete(DocumentChunk).where(
            DocumentChunk.document_id == document_id
        )
        await session.execute(stmt)
    
    def _prepare_es_document(
        self,
        document: Document,
        chunks: List[ChunkData],
    ) -> Dict[str, Any]:
        """Prepara documento para indexação no ES."""
        return {
            "document_id": document.document_id,
            "source_id": document.source_id,
            "title": document.title,
            "content_preview": document.content_preview,
            "fingerprint": document.fingerprint,
            "metadata": document.doc_metadata,
            "status": document.status,
            "version": document.version,
            "language": document.language,
            "chunks_count": len(chunks),
            "ingested_at": document.ingested_at.isoformat() if document.ingested_at else None,
            "updated_at": document.updated_at.isoformat() if document.updated_at else None,
        }


# =============================================================================
# Helper Data Classes
# =============================================================================

@dataclass
class PGPhaseResult:
    """Resultado da fase PostgreSQL."""
    success: bool
    error: Optional[str] = None


@dataclass
class DuplicateCheckResult:
    """Resultado da verificação de duplicatas."""
    is_duplicate: bool
    existing_doc_id: Optional[str] = None


# =============================================================================
# DLQ Integration
# =============================================================================

class IndexingDLQHandler:
    """Handler para gerenciar falhas de indexação na DLQ.
    
    Popula a DLQ com falhas para retry automático.
    """
    
    def __init__(self, session_factory: Optional[Callable] = None):
        """Inicializa o handler.
        
        Args:
            session_factory: Factory de sessões (default: get_session_no_commit)
        """
        self.session_factory = session_factory or get_session_no_commit
    
    async def enqueue_failure(
        self,
        document_id: str,
        source_id: str,
        error: Exception,
        run_id: Optional[UUID] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> DLQMessage:
        """Adiciona uma falha de indexação na DLQ.
        
        Args:
            document_id: ID do documento que falhou
            source_id: ID da fonte
            error: Exceção ocorrida
            run_id: ID da execução
            payload: Dados adicionais do contexto
            
        Returns:
            DLQMessage criada
        """
        error_hash = self._compute_error_hash(error)

        async with self.session_factory() as session:
            # Garante que a fonte exista para respeitar FK
            stmt = select(SourceRegistry).where(SourceRegistry.id == source_id)
            result = await session.execute(stmt)
            source = result.scalar_one_or_none()
            if source is None:
                placeholder = SourceRegistry(
                    id=source_id,
                    name=source_id,
                    type=SourceType.API,
                    config_hash=hashlib.sha256(source_id.encode()).hexdigest(),
                    owner_email="unknown@example.com",
                )
                session.add(placeholder)

            # Se run_id não existir, limpa para evitar FK inválida
            if run_id is not None:
                stmt = select(ExecutionManifest).where(ExecutionManifest.run_id == run_id)
                result = await session.execute(stmt)
                if result.scalar_one_or_none() is None:
                    run_id = None

            message = DLQMessage(
                source_id=source_id,
                run_id=run_id,
                url=f"internal://indexing/{document_id}",
                document_id=document_id,
                error_type=type(error).__name__,
                error_message=str(error),
                error_traceback=self._get_traceback(error),
                error_hash=error_hash,
                status=DLQStatus.PENDING,
                payload=payload or {},
            )

            session.add(message)
            await session.commit()
            
        logger.info(f"Falha de indexação enfileirada na DLQ: {message.id}")
        return message
    
    def _compute_error_hash(self, error: Exception) -> str:
        """Computa hash para agrupar erros similares."""
        content = f"{type(error).__name__}:{str(error)[:100]}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def _get_traceback(self, error: Exception) -> Optional[str]:
        """Extrai traceback da exceção."""
        import traceback
        return "".join(traceback.format_exception(type(error), error, error.__traceback__))


# =============================================================================
# Factory
# =============================================================================

async def create_indexer(
    es_url: str = "http://localhost:9200",
    es_index: Optional[str] = None,
    **kwargs,
) -> Indexer:
    """Factory para criar Indexer com cliente ES.
    
    Args:
        es_url: URL do Elasticsearch
        es_index: Nome do índice
        **kwargs: Parâmetros adicionais para Indexer
        
    Returns:
        Indexer configurado
    """
    from elasticsearch import AsyncElasticsearch
    
    es_client = AsyncElasticsearch([es_url])
    return Indexer(
        es_client=es_client,
        es_index=es_index or settings.elasticsearch_index,
        **kwargs,
    )


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Enums
    "IndexingStatus",
    "SagaStepStatus",
    # Data classes
    "ChunkData",
    "IndexingResult",
    "SagaStep",
    "DocumentVersionInfo",
    # Exceções
    "IndexingError",
    "PostgreSQLError",
    "ElasticsearchError",
    "SagaError",
    "DuplicateDocumentError",
    "VersionMismatchError",
    # Classes principais
    "Indexer",
    "IndexingDLQHandler",
    # Factory
    "create_indexer",
]
