"""Tasks de sincronização de fontes para o GABI.

Implementa o pipeline completo de ingestão:
discovery → fetch → parse → fingerprint → dedup → chunk → embed → index

Baseado em GABI_SPECS_FINAL_v1.md §2.8
"""

import asyncio
import hashlib
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Type

from celery import chain, group
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gabi.config import settings
from gabi.db import get_session
from gabi.models.dlq import DLQMessage, DLQStatus
from gabi.models.document import Document
from gabi.models.execution import ExecutionManifest, ExecutionStatus
from gabi.models.source import SourceRegistry, SourceStatus
from gabi.pipeline.chunker import Chunker
from gabi.pipeline.contracts import (
    DiscoveryResult,
    EmbeddedChunk,
    EmbeddingResult,
    FetchedContent,
    ParseResult,
    ParsedDocument,
)
from gabi.pipeline.deduplication import Deduplicator
from gabi.pipeline.discovery import DiscoveryConfig, DiscoveryEngine
from gabi.pipeline.embedder import Embedder
from gabi.pipeline.fetcher import ContentFetcher
from gabi.pipeline.fingerprint import Fingerprinter, FingerprinterConfig
from gabi.pipeline.indexer import Indexer
from gabi.pipeline.parser import get_parser
from gabi.worker import celery_app

logger = logging.getLogger(__name__)


# =============================================================================
# Task: Sync Source
# =============================================================================

@celery_app.task(
    bind=True,
    name="gabi.tasks.sync.sync_source_task",
    queue="gabi.sync",
    max_retries=3,
    default_retry_delay=60,
    time_limit=3600 * 6,  # 6 horas
)
def sync_source_task(self, source_id: str, run_id: Optional[str] = None) -> Dict[str, Any]:
    """Executa pipeline completo de sincronização para uma fonte.
    
    Pipeline: discovery → fetch → parse → fingerprint → dedup → chunk → embed → index
    
    Args:
        source_id: ID da fonte a sincronizar
        run_id: ID opcional da execução (gerado se não fornecido)
        
    Returns:
        Dict com resultados da sincronização
        
    Raises:
        Retry: Se houver erro transitório
    """
    run_id = run_id or str(uuid.uuid4())
    start_time = time.monotonic()
    
    logger.info(f"[sync_source_task] Starting sync for source {source_id}, run {run_id}")
    
    try:
        # Executa o pipeline completo de forma assíncrona
        result = asyncio.run(_run_sync_pipeline(source_id, run_id))
        
        duration = time.monotonic() - start_time
        logger.info(f"[sync_source_task] Completed sync for {source_id} in {duration:.2f}s")
        
        return {
            "run_id": run_id,
            "source_id": source_id,
            "status": "success",
            "duration_seconds": duration,
            **result,
        }
        
    except Exception as exc:
        logger.exception(f"[sync_source_task] Failed to sync source {source_id}")
        
        # Classifica o erro como retryable ou não
        is_retryable, should_dlq = _classify_exception(exc)
        
        # Adiciona à DLQ para retry manual apenas se for retryable
        if should_dlq:
            try:
                asyncio.run(_add_to_dlq(source_id, run_id, str(exc), self.request.id))
            except Exception as dlq_exc:
                logger.error(f"[sync_source_task] Failed to add to DLQ: {dlq_exc}")
        
        # Retry apenas para erros retryable
        if is_retryable and self.request.retries < self.max_retries:
            logger.warning(f"[sync_source_task] Retrying sync for {source_id} (attempt {self.request.retries + 1})")
            raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
        
        # Erro não-retryable ou esgotou retries - propaga o erro
        raise


# =============================================================================
# Pipeline Implementation
# =============================================================================

async def _run_sync_pipeline(source_id: str, run_id: str) -> Dict[str, Any]:
    """Executa o pipeline completo de sincronização.
    
    Args:
        source_id: ID da fonte
        run_id: ID da execução
        
    Returns:
        Dict com estatísticas do processamento
    """
    stats = {
        "urls_discovered": 0,
        "urls_processed": 0,
        "urls_failed": 0,
        "documents_fetched": 0,
        "documents_parsed": 0,
        "documents_deduplicated": 0,
        "documents_indexed": 0,
        "chunks_created": 0,
        "embeddings_generated": 0,
        "errors": [],
    }
    
    async with get_session() as session:
        # 1. Busca configuração da fonte
        source = await _get_source(session, source_id)
        if not source:
            raise ValueError(f"Source not found: {source_id}")
        
        if source.status != SourceStatus.ACTIVE:
            logger.warning(f"Source {source_id} is not active (status: {source.status})")
            return {**stats, "status": "skipped", "reason": f"source_{source.status.value}"}
        
        # 2. Cria execution manifest
        manifest = await _create_execution_manifest(session, run_id, source_id)
        
        # 3. Discovery
        discovery_result = await _run_discovery(source_id, source.config_json.get("discovery", {}))
        stats["urls_discovered"] = discovery_result.total_found
        
        if not discovery_result.urls:
            logger.info(f"No URLs discovered for source {source_id}")
            await _update_manifest_status(session, manifest, ExecutionStatus.COMPLETED)
            return stats
        
        # 4. Processa cada URL
        fetcher = ContentFetcher()
        fingerprinter = Fingerprinter(FingerprinterConfig())
        deduplicator = Deduplicator(session)
        chunker = Chunker()
        
        for discovered_url in discovery_result.urls:
            try:
                # Fetch
                fetched = await _run_fetch(fetcher, discovered_url)
                stats["documents_fetched"] += 1
                
                # Parse
                parsed_result = await _run_parse(fetched, source_id)
                if not parsed_result.documents:
                    logger.warning(f"No documents parsed from {discovered_url.url}")
                    continue
                stats["documents_parsed"] += len(parsed_result.documents)
                
                # Processa cada documento
                for parsed_doc in parsed_result.documents:
                    try:
                        # Fingerprint
                        fingerprint = fingerprinter.compute(parsed_doc)
                        
                        # Deduplication
                        is_duplicate = await _check_duplicate(deduplicator, fingerprint.fingerprint)
                        if is_duplicate:
                            logger.debug(f"Document {parsed_doc.document_id} is a duplicate")
                            stats["documents_deduplicated"] += 1
                            continue
                        
                        # Chunk
                        chunking_result = chunker.chunk(
                            parsed_doc.content,
                            metadata=parsed_doc.metadata,
                            document_id=parsed_doc.document_id,
                        )
                        stats["chunks_created"] += len(chunking_result.chunks)
                        
                        # Embed (será feito em batch ou via task separada)
                        # Por enquanto, marcamos para processamento assíncrono
                        
                        # Index
                        await _index_document(session, parsed_doc, chunking_result, source_id, run_id)
                        stats["documents_indexed"] += 1
                        
                    except Exception as doc_exc:
                        logger.exception(f"Error processing document {parsed_doc.document_id}")
                        stats["errors"].append({
                            "document_id": parsed_doc.document_id,
                            "error": str(doc_exc),
                        })
                        
                        # Adiciona à DLQ
                        await _add_document_to_dlq(
                            session, source_id, run_id, parsed_doc.document_id,
                            str(doc_exc), discovered_url.url
                        )
                
                stats["urls_processed"] += 1
                
            except Exception as url_exc:
                logger.exception(f"Error processing URL {discovered_url.url}")
                stats["urls_failed"] += 1
                stats["errors"].append({
                    "url": discovered_url.url,
                    "error": str(url_exc),
                })
        
        # 5. Atualiza manifest
        await _update_manifest_status(
            session, manifest, 
            ExecutionStatus.COMPLETED if stats["urls_failed"] == 0 else ExecutionStatus.PARTIAL
        )
        
        # 6. Atualiza source registry
        await _update_source_stats(session, source_id, stats)
        
        await fetcher.close()
        
    return stats


async def _get_source(session: AsyncSession, source_id: str) -> Optional[SourceRegistry]:
    """Busca fonte pelo ID."""
    result = await session.execute(
        select(SourceRegistry).where(SourceRegistry.id == source_id)
    )
    return result.scalar_one_or_none()


async def _create_execution_manifest(
    session: AsyncSession, 
    run_id: str, 
    source_id: str
) -> ExecutionManifest:
    """Cria execution manifest para rastreamento."""
    manifest = ExecutionManifest(
        run_id=uuid.UUID(run_id),
        source_id=source_id,
        status=ExecutionStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
        triggered_by="celery_task",
    )
    session.add(manifest)
    await session.commit()
    return manifest


async def _update_manifest_status(
    session: AsyncSession,
    manifest: ExecutionManifest,
    status: ExecutionStatus,
) -> None:
    """Atualiza status do execution manifest."""
    manifest.status = status
    manifest.completed_at = datetime.now(timezone.utc) if status in [ExecutionStatus.COMPLETED, ExecutionStatus.FAILED] else None
    await session.commit()


async def _update_source_stats(session: AsyncSession, source_id: str, stats: Dict[str, Any]) -> None:
    """Atualiza estatísticas da fonte."""
    result = await session.execute(
        select(SourceRegistry).where(SourceRegistry.id == source_id)
    )
    source = result.scalar_one_or_none()
    
    if source:
        source.last_sync_at = datetime.now(timezone.utc)
        if stats.get("urls_failed", 0) == 0:
            source.last_success_at = datetime.now(timezone.utc)
            source.consecutive_errors = 0
            source.status = SourceStatus.ACTIVE
        else:
            source.consecutive_errors += 1
            source.last_error_message = f"Failed URLs: {stats.get('urls_failed', 0)}"
            source.last_error_at = datetime.now(timezone.utc)
            
            if source.consecutive_errors >= 5:
                source.status = SourceStatus.ERROR
        
        await session.commit()


# =============================================================================
# Pipeline Steps
# =============================================================================

async def _run_discovery(source_id: str, discovery_config: Dict[str, Any]) -> DiscoveryResult:
    """Executa fase de discovery."""
    engine = DiscoveryEngine()
    
    config = DiscoveryConfig(
        mode=discovery_config.get("mode", "static_url"),
        url=discovery_config.get("url"),
        url_pattern=discovery_config.get("url_template"),
        range_config=discovery_config.get("params"),
        rate_limit_delay=discovery_config.get("rate_limit_delay", 1.0),
    )
    
    return await engine.discover(source_id, config)


async def _run_fetch(fetcher: ContentFetcher, discovered_url: Any) -> FetchedContent:
    """Executa fase de fetch."""
    return await fetcher.fetch(
        url=discovered_url.url,
        source_id=discovered_url.source_id,
    )


async def _run_parse(fetched: FetchedContent, source_id: str) -> ParseResult:
    """Executa fase de parsing."""
    # Detecta formato
    content_type = fetched.metadata.content_type or ""
    
    if "csv" in content_type or fetched.url.endswith(".csv"):
        parser = get_parser("csv")
        config = {"source_id": source_id, "delimiter": "|"}
    elif "html" in content_type or fetched.url.endswith(".html"):
        parser = get_parser("html")
        config = {"source_id": source_id}
    elif "pdf" in content_type or fetched.url.endswith(".pdf"):
        parser = get_parser("pdf")
        config = {"source_id": source_id}
    else:
        # Tenta CSV como default para fontes TCU
        parser = get_parser("csv")
        config = {"source_id": source_id, "delimiter": "|"}
    
    if not parser:
        raise ValueError(f"No parser available for content type: {content_type}")
    
    return await parser.parse(fetched, config)


async def _check_duplicate(deduplicator: Deduplicator, fingerprint: str) -> bool:
    """Verifica se documento é duplicado."""
    result = await deduplicator.check_duplicate(fingerprint)
    return result.is_duplicate


async def _index_document(
    session: AsyncSession,
    parsed_doc: ParsedDocument,
    chunking_result: Any,
    source_id: str,
    run_id: str,
) -> None:
    """Indexa documento no PostgreSQL."""
    # Cria ou atualiza documento
    document = Document(
        document_id=parsed_doc.document_id,
        source_id=source_id,
        title=parsed_doc.title or "",
        content_preview=parsed_doc.content_preview or parsed_doc.content[:500],
        content_hash=parsed_doc.content_hash or "",
        fingerprint=parsed_doc.content_hash or "",
        url=parsed_doc.url or "",
        doc_metadata=parsed_doc.metadata,
        status="active",
    )
    
    await session.merge(document)
    await session.commit()


# =============================================================================
# DLQ Helpers
# =============================================================================

def _compute_error_hash(error_type: str, error_message: str) -> str:
    """Computa hash único para um erro baseado no tipo e mensagem.
    
    Args:
        error_type: Tipo do erro
        error_message: Mensagem de erro
        
    Returns:
        Hash hexadecimal de 16 caracteres
    """
    hash_input = f"{error_type}:{error_message[:100]}"
    return hashlib.md5(hash_input.encode()).hexdigest()[:16]


# =============================================================================
# Exception Classification
# =============================================================================

# Exceções que são transitórias e merecem retry
RETRYABLE_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
    OSError,  # Inclui network errors
)

# Exceções de programação que NÃO devem ter retry
NON_RETRYABLE_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    ImportError,
    ModuleNotFoundError,
    NotImplementedError,
)


def _classify_exception(exc: Exception) -> tuple[bool, bool]:
    """Classifica uma exceção para determinar ação apropriada.
    
    Args:
        exc: A exceção capturada
        
    Returns:
        Tuple de (is_retryable, should_dlq)
        - is_retryable: Se a task deve ser retentada
        - should_dlq: Se deve adicionar à DLQ
    """
    exc_type = type(exc)
    
    # Erros de programação - não retry, vai direto para DLQ
    if issubclass(exc_type, NON_RETRYABLE_EXCEPTIONS):
        return False, True
    
    # Erros transitórios - retry e DLQ
    if issubclass(exc_type, RETRYABLE_EXCEPTIONS):
        return True, True
    
    # Erros HTTP específicos
    error_msg = str(exc).lower()
    if any(code in error_msg for code in ["429", "500", "502", "503", "504"]):
        return True, True  # Rate limit / server errors -> retry
    if any(code in error_msg for code in ["400", "401", "403", "404", "405"]):
        return False, True  # Client errors -> DLQ sem retry
    
    # Por padrão: retry e DLQ para erros desconhecidos
    return True, True


async def _add_to_dlq(source_id: str, run_id: str, error_message: str, task_id: str) -> None:
    """Adiciona erro à DLQ."""
    error_type = "sync_failed"
    error_hash = _compute_error_hash(error_type, error_message)
    
    async with get_session() as session:
        dlq_msg = DLQMessage(
            source_id=source_id,
            run_id=uuid.UUID(run_id) if run_id else None,
            url="",
            error_type=error_type,
            error_message=error_message,
            error_hash=error_hash,
            payload={"task_id": task_id},
        )
        dlq_msg.schedule_next_retry()
        session.add(dlq_msg)
        await session.commit()


async def _add_document_to_dlq(
    session: AsyncSession,
    source_id: str,
    run_id: str,
    document_id: str,
    error_message: str,
    url: str,
) -> None:
    """Adiciona erro de documento à DLQ."""
    error_type = "document_processing_failed"
    error_hash = _compute_error_hash(error_type, error_message)
    
    dlq_msg = DLQMessage(
        source_id=source_id,
        run_id=uuid.UUID(run_id) if run_id else None,
        url=url,
        document_id=document_id,
        error_type=error_type,
        error_message=error_message,
        error_hash=error_hash,
        payload={"document_id": document_id},
    )
    dlq_msg.schedule_next_retry()
    session.add(dlq_msg)
    await session.commit()


# =============================================================================
# Sub-tasks (para paralelização futura)
# =============================================================================

@celery_app.task(
    bind=True,
    name="gabi.tasks.sync.process_document_task",
    queue="gabi.sync",
    max_retries=3,
)
def process_document_task(self, document_data: Dict[str, Any], source_id: str) -> Dict[str, Any]:
    """Processa um documento individual (chunk + embed + index).
    
    Pipeline completo:
    1. Chunkeamento do conteúdo
    2. Geração de embeddings
    3. Indexação no Elasticsearch
    4. Persistência no PostgreSQL
    
    Args:
        document_data: Dados do documento parseado
        source_id: ID da fonte
        
    Returns:
        Resultado do processamento com status e métricas
    """
    # Celery tasks devem ser funções síncronas - usamos asyncio.run() internamente
    return asyncio.run(_process_document_async(self, document_data, source_id))


async def _process_document_async(
    self,
    document_data: Dict[str, Any],
    source_id: str
) -> Dict[str, Any]:
    """Implementação assíncrona do processamento de documento."""
    import logging
    from datetime import datetime, timezone
    
    from gabi.pipeline.indexer import create_indexer
    from gabi.services.indexing_service import DocumentContent, IndexingService
    
    logger = logging.getLogger(__name__)
    start_time = datetime.now(timezone.utc)
    
    document_id = document_data.get("document_id")
    if not document_id:
        raise ValueError("document_id is required to process document")
    
    logger.info(f"Processing document: {document_id} from source: {source_id}")
    
    indexer = await create_indexer(
        es_url=settings.elasticsearch_url,
        es_index=settings.elasticsearch_index,
    )
    
    try:
        async with Embedder(
            base_url=settings.embeddings_url,
            model=settings.embeddings_model,
            batch_size=settings.embeddings_batch_size,
            timeout=settings.embeddings_timeout,
            max_retries=settings.embeddings_max_retries,
        ) as embedder:
            indexing_service = IndexingService(indexer=indexer, embedder=embedder)
            
            content = DocumentContent(
                document_id=document_id,
                source_id=source_id,
                title=document_data.get("title", "") or "",
                content=document_data.get("content", "") or "",
                url=document_data.get("url"),
                metadata=document_data.get("metadata", {}) or {},
                content_type=document_data.get("content_type", "text/plain"),
                language=document_data.get("language", "pt-BR"),
            )
            
            result = await indexing_service.process_document(content)
        
        processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        if result.success:
            logger.info(
                f"Document processed successfully: {document_id} "
                f"({result.chunks_count} chunks in {processing_time:.2f}s)"
            )
            return {
                "status": "success",
                "document_id": document_id,
                "chunks_processed": result.chunks_count,
                "processing_time_seconds": processing_time,
            }
        
        logger.warning(f"Document processing failed: {document_id} errors={result.errors}")
        return {
            "status": "failed",
            "document_id": document_id,
            "errors": result.errors,
            "chunks_processed": result.chunks_count,
            "processing_time_seconds": processing_time,
        }
        
    except Exception as exc:
        logger.exception(f"Failed to process document {document_id}: {exc}")
        
        # Classifica o erro antes de decidir retry
        is_retryable, _ = _classify_exception(exc)
        
        if is_retryable and self.request.retries < self.max_retries:
            # Retry com backoff
            raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
        else:
            # Erro não-retryable ou esgotou retries
            raise


# =============================================================================
# Exports
# =============================================================================

__all__ = ["sync_source_task", "process_document_task"]
