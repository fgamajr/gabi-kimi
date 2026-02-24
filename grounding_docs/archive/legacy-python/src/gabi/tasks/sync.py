"""Tasks de sincronização de fontes para o GABI.

Implementa o pipeline completo de ingestão:
discovery → fetch → parse → fingerprint → dedup → chunk → embed → index

Baseado em GABI_SPECS_FINAL_v1.md §2.8
"""

import asyncio
import gc
import hashlib
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Type
from urllib.parse import urlparse

from celery import chain, group
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gabi.config import settings
from gabi.db import close_db, get_session, init_db
from gabi.models.dlq import DLQMessage, DLQStatus
from gabi.models.chunk import DocumentChunk
from gabi.models.document import Document
from gabi.models.execution import ExecutionManifest, ExecutionStatus
from gabi.models.pipeline_action import PipelineAction
from gabi.models.source import SourceRegistry, SourceStatus
from gabi.pipeline.chunker import Chunker
from gabi.pipeline.contracts import (
    DiscoveredURL,
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
from gabi.pipeline.fetcher import ContentFetcher, FetcherConfig
from gabi.pipeline.fingerprint import Fingerprinter, FingerprinterConfig
from gabi.pipeline.indexer import Indexer
from gabi.pipeline.parser import get_parser
from gabi.worker import celery_app

logger = logging.getLogger(__name__)


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "tei", "redis", "postgres", "elasticsearch"}


# =============================================================================
# Memory Monitoring Utilities
# =============================================================================

# Memory thresholds (in MB)
MEMORY_WARNING_MB = 300
MEMORY_CRITICAL_MB = 400
MEMORY_CIRCUIT_BREAKER_MB = 500


def get_memory_usage_mb() -> float:
    """Get current process memory usage in MB.

    Returns:
        Memory usage in megabytes (RSS - Resident Set Size)
    """
    try:
        import psutil
        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024
    except ImportError:
        logger.warning("psutil not installed - memory monitoring disabled")
        return 0.0
    except Exception as e:
        logger.warning(f"Failed to get memory usage: {e}")
        return 0.0


def force_cleanup() -> None:
    """Force garbage collection for memory cleanup.

    Runs GC multiple times to ensure cyclic references are collected.
    Useful after processing large batches to reclaim memory.
    """
    gc.collect()
    gc.collect()  # Twice for cyclic references
    gc.collect()  # Third time to be thorough


def check_memory_thresholds(operation: str, context: Optional[Dict[str, Any]] = None) -> Tuple[float, str]:
    """Check memory usage against thresholds and log warnings.

    Args:
        operation: Name of the current operation (for logging)
        context: Optional additional context to include in logs

    Returns:
        Tuple of (memory_mb, status) where status is 'ok', 'warning', 'critical', or 'emergency'
    """
    mem_mb = get_memory_usage_mb()
    status = "ok"
    ctx_str = f" | context={context}" if context else ""

    if mem_mb >= MEMORY_CIRCUIT_BREAKER_MB:
        logger.critical(
            f"[MEMORY EMERGENCY] Operation '{operation}' - Memory at {mem_mb:.1f}MB "
            f"(exceeds {MEMORY_CIRCUIT_BREAKER_MB}MB emergency threshold)! "
            f"Forcing immediate cleanup.{ctx_str}"
        )
        force_cleanup()
        mem_after = get_memory_usage_mb()
        logger.critical(
            f"[MEMORY EMERGENCY] After forced cleanup: {mem_after:.1f}MB "
            f"(freed {mem_mb - mem_after:.1f}MB)"
        )
        if mem_after >= MEMORY_CIRCUIT_BREAKER_MB:
            logger.critical(
                f"[MEMORY EMERGENCY] Cleanup insufficient - memory still at {mem_after:.1f}MB. "
                f"Circuit breaker triggered!"
            )
            raise MemoryError(
                f"Memory emergency: {mem_after:.1f}MB exceeds {MEMORY_CIRCUIT_BREAKER_MB}MB threshold"
            )
        mem_mb = mem_after
        status = "emergency"
    elif mem_mb >= MEMORY_CRITICAL_MB:
        logger.error(
            f"[MEMORY CRITICAL] Operation '{operation}' - Memory at {mem_mb:.1f}MB "
            f"(exceeds {MEMORY_CRITICAL_MB}MB threshold). Forcing cleanup.{ctx_str}"
        )
        force_cleanup()
        mem_after = get_memory_usage_mb()
        logger.warning(
            f"[MEMORY CRITICAL] After cleanup: {mem_after:.1f}MB (freed {mem_mb - mem_after:.1f}MB)"
        )
        mem_mb = mem_after
        status = "critical"
    elif mem_mb >= MEMORY_WARNING_MB:
        logger.warning(
            f"[MEMORY WARNING] Operation '{operation}' - Memory at {mem_mb:.1f}MB "
            f"(exceeds {MEMORY_WARNING_MB}MB threshold).{ctx_str}"
        )
        status = "warning"

    return mem_mb, status


def log_memory_before(operation: str, context: Optional[Dict[str, Any]] = None) -> float:
    """Log memory usage before an operation.

    Args:
        operation: Name of the operation about to start
        context: Optional additional context

    Returns:
        Current memory usage in MB
    """
    mem_mb = get_memory_usage_mb()
    ctx_str = f" | context={context}" if context else ""
    logger.info(f"[MEMORY] Before {operation}: {mem_mb:.1f}MB{ctx_str}")
    return mem_mb


def log_memory_after(operation: str, mem_before_mb: float, context: Optional[Dict[str, Any]] = None) -> float:
    """Log memory usage after an operation and calculate delta.

    Args:
        operation: Name of the operation that completed
        mem_before_mb: Memory usage before the operation (from log_memory_before)
        context: Optional additional context

    Returns:
        Current memory usage in MB
    """
    mem_after_mb = get_memory_usage_mb()
    delta_mb = mem_after_mb - mem_before_mb
    ctx_str = f" | context={context}" if context else ""
    
    if delta_mb > 50:
        logger.warning(
            f"[MEMORY] After {operation}: {mem_after_mb:.1f}MB "
            f"(+{delta_mb:.1f}MB increase){ctx_str}"
        )
    elif delta_mb < -50:
        logger.info(
            f"[MEMORY] After {operation}: {mem_after_mb:.1f}MB "
            f"({delta_mb:.1f}MB freed){ctx_str}"
        )
    else:
        logger.info(
            f"[MEMORY] After {operation}: {mem_after_mb:.1f}MB "
            f"({'+' if delta_mb >= 0 else ''}{delta_mb:.1f}MB){ctx_str}"
        )
    
    # Check thresholds after logging
    check_memory_thresholds(f"post_{operation}", context)
    
    return mem_after_mb


# =============================================================================
# Helper Functions
# =============================================================================

def _cancel_key(source_id: str) -> str:
    return f"gabi:pipeline:cancel:{source_id}:all"


async def _mark_runtime_task_started(
    source_id: str,
    run_id: str,
    task_id: str,
    action_id: Optional[str] = None,
    phase: Optional[str] = None,
) -> None:
    if not task_id:
        return
    from gabi.db import get_redis_client

    redis = get_redis_client()
    runtime_key = f"gabi:pipeline:runtime:{source_id}:{phase or 'all'}"
    await redis.hset(
        runtime_key,
        mapping={
            "source_id": source_id,
            "run_id": run_id,
            "task_id": task_id,
            "action_id": action_id or "",
            "phase": phase or "all",
            "status": "running",
            "is_running": "true",
            "cancel_requested": "false",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    await redis.sadd(f"gabi:pipeline:active_tasks:{source_id}", task_id)
    await redis.expire(runtime_key, 60 * 60 * 24)


async def _mark_runtime_task_finished(source_id: str, task_id: str) -> None:
    if not task_id:
        return
    from gabi.db import get_redis_client

    redis = get_redis_client()
    await redis.srem(f"gabi:pipeline:active_tasks:{source_id}", task_id)
    runtime_prefix = f"gabi:pipeline:runtime:{source_id}:"
    keys = await redis.keys(f"{runtime_prefix}*")
    now = datetime.now(timezone.utc).isoformat()
    for key in keys:
        if await redis.hget(key, "task_id") == task_id:
            await redis.hset(
                key,
                mapping={
                    "status": "idle",
                    "is_running": "false",
                    "updated_at": now,
                },
            )


async def _is_cancel_requested(source_id: str) -> bool:
    from gabi.db import get_redis_client

    redis = get_redis_client()
    # Keep phase-specific cancellation for future phases; full pipeline uses :all.
    key = _cancel_key(source_id)
    return bool(await redis.get(key))


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
def sync_source_task(
    self,
    source_id: str,
    run_id: Optional[str] = None,
    max_documents_per_source_override: Optional[int] = None,
    disable_embeddings: bool = False,
    action_id: Optional[str] = None,
    phase: Optional[str] = None,
) -> Dict[str, Any]:
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
    
    task_id = self.request.id
    
    # Use a single event loop for the entire task to avoid "Event loop is closed" errors
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        # Mark runtime task started
        try:
            loop.run_until_complete(_mark_runtime_task_started(source_id, run_id, task_id, action_id=action_id, phase=phase))
        except Exception as rt_exc:
            logger.warning("[sync_source_task] runtime start tracking failed: %s", rt_exc)

        # Executa pipeline com lifecycle de DB no mesmo event loop.
        result = loop.run_until_complete(
            _run_sync_pipeline_entry(
                source_id,
                run_id,
                max_documents_per_source_override=max_documents_per_source_override,
                disable_embeddings=disable_embeddings,
            )
        )
        
        duration = time.monotonic() - start_time
        logger.info(f"[sync_source_task] Completed sync for {source_id} in {duration:.2f}s")
        if action_id:
            final_status = "cancelled" if result.get("cancelled") else "completed"
            loop.run_until_complete(_update_pipeline_action_status_entry(action_id, final_status))
        
        return {
            "run_id": run_id,
            "source_id": source_id,
            "status": "success",
            "duration_seconds": duration,
            **result,
        }
        
    except Exception as exc:
        logger.exception(f"[sync_source_task] Failed to sync source {source_id}")
        if action_id:
            try:
                loop.run_until_complete(_update_pipeline_action_status_entry(action_id, "failed", error_message=str(exc)))
            except Exception as action_exc:
                logger.warning("[sync_source_task] failed to update action status: %s", action_exc)
        
        # Classifica o erro como retryable ou não
        is_retryable, should_dlq = _classify_exception(exc)
        
        # Adiciona à DLQ para retry manual apenas se for retryable
        if should_dlq:
            try:
                loop.run_until_complete(_add_to_dlq_entry(source_id, run_id, str(exc), self.request.id))
            except Exception as dlq_exc:
                logger.error(f"[sync_source_task] Failed to add to DLQ: {dlq_exc}")
        
        # Retry apenas para erros retryable
        if is_retryable and self.request.retries < self.max_retries:
            logger.warning(f"[sync_source_task] Retrying sync for {source_id} (attempt {self.request.retries + 1})")
            raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
        
        # Erro não-retryable ou esgotou retries - propaga o erro
        raise
    finally:
        try:
            # Complete runtime task tracking
            loop.run_until_complete(_mark_runtime_task_finished(source_id, task_id))
        except Exception as cleanup_exc:
            logger.warning(
                "[sync_source_task] failed runtime cleanup for source %s task %s: %s",
                source_id,
                task_id,
                cleanup_exc,
            )
        finally:
            # Ensure ALL pending tasks complete before closing loop
            # This prevents "Event loop is closed" errors
            try:
                pending = asyncio.all_tasks(loop)
                if pending:
                    logger.debug(f"[sync_source_task] Cancelling {len(pending)} pending tasks before loop close")
                    for task in pending:
                        task.cancel()
                    # Gather with return_exceptions=True to handle cancellations gracefully
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception as pending_exc:
                logger.warning(f"[sync_source_task] Error cleaning pending tasks: {pending_exc}")
            finally:
                loop.close()


# =============================================================================
# Pipeline Implementation
# =============================================================================

async def _run_sync_pipeline_entry(
    source_id: str,
    run_id: str,
    max_documents_per_source_override: Optional[int] = None,
    disable_embeddings: bool = False,
) -> Dict[str, Any]:
    """Wrapper que garante init/close de DB no mesmo event loop."""
    await init_db()
    try:
        return await _run_sync_pipeline(
            source_id,
            run_id,
            max_documents_per_source_override=max_documents_per_source_override,
            disable_embeddings=disable_embeddings,
        )
    finally:
        # Close DB with timeout to prevent hanging
        try:
            await asyncio.wait_for(close_db(), timeout=30.0)
        except asyncio.TimeoutError:
            logger.warning(f"[_run_sync_pipeline_entry] DB close timeout after 30s for source {source_id}")
        except Exception as close_exc:
            logger.warning(f"[_run_sync_pipeline_entry] DB close failed for source {source_id}: {close_exc}")

async def _run_sync_pipeline(
    source_id: str,
    run_id: str,
    max_documents_per_source_override: Optional[int] = None,
    disable_embeddings: bool = False,
) -> Dict[str, Any]:
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
        "cancelled": False,
    }
    
    async with get_session() as session:
        # 1. Busca configuração da fonte
        source = await _get_source(session, source_id)
        if not source:
            raise ValueError(f"Source not found: {source_id}")
        
        if source.status != SourceStatus.ACTIVE and source.status != SourceStatus.ACTIVE.value:
            logger.warning(f"Source {source_id} is not active (status: {source.status})")
            status_value = source.status.value if hasattr(source.status, "value") else str(source.status)
            return {**stats, "status": "skipped", "reason": f"source_{status_value}"}
        
        # 2. Cria execution manifest
        manifest = await _create_execution_manifest(session, run_id, source_id)
        max_documents_per_source = (
            int(max_documents_per_source_override)
            if max_documents_per_source_override is not None
            else int(source.config_json.get("pipeline_validation_max_docs", 0) or 0)
        )
        
        # 3. Discovery
        discovery_result = await _run_discovery(
            source_id,
            source.config_json,
            use_orchestrator_fallback=max_documents_per_source > 0,
            max_documents_per_source=max_documents_per_source,
        )
        stats["urls_discovered"] = discovery_result.total_found
        
        if not discovery_result.urls:
            logger.info(f"No URLs discovered for source {source_id}")
            await _update_manifest_status(session, manifest, ExecutionStatus.SUCCESS)
            return stats
        
        # 4. Processa cada URL
        fetcher = _build_source_fetcher(source.config_json, max_documents_per_source)
        fingerprinter = Fingerprinter(FingerprinterConfig())
        deduplicator = Deduplicator(session)
        chunker = Chunker()
        embedding_cfg = source.config_json.get("embedding", {}) or {}
        embedding_enabled = bool(embedding_cfg.get("enabled", False)) and not disable_embeddings
        embedding_required = bool(embedding_cfg.get("required", False))
        embedder = (
            Embedder(
                base_url=settings.embeddings_url,
                model=settings.embeddings_model,
                batch_size=settings.embeddings_batch_size,
                timeout=settings.embeddings_timeout,
                max_retries=settings.embeddings_max_retries,
            )
            if embedding_enabled
            else None
        )
        
        try:
            for discovered_url in discovery_result.urls:
                if await _is_cancel_requested(source_id):
                    logger.warning("Cancellation requested for source %s", source_id)
                    stats["cancelled"] = True
                    break

                if max_documents_per_source > 0:
                    remaining_docs = max_documents_per_source - stats["documents_indexed"]
                    if remaining_docs <= 0:
                        logger.info(
                            "Reached document limit for source %s (limit=%s)",
                            source_id,
                            max_documents_per_source,
                        )
                        break
                else:
                    remaining_docs = None

                # Check if streaming is enabled for this source
                parse_config = source.config_json.get("parse", {}) or {}
                parse_input_format = str(parse_config.get("input_format", "")).lower()
                has_streaming_method = hasattr(fetcher, 'fetch_streaming')
                use_streaming = (
                    parse_config.get("streaming", False)
                    and parse_input_format == "csv"
                    and has_streaming_method
                )

                # Debug logging for streaming detection
                logger.info(
                    f"[STREAMING CHECK] streaming={parse_config.get('streaming', False)}, "
                    f"format={parse_input_format}, "
                    f"has_method={has_streaming_method}, "
                    f"use_streaming={use_streaming}"
                )

                try:
                    if use_streaming:
                        # ===================================================================
                        # TRUE STREAMING PATH - Never loads full file to memory
                        # ===================================================================
                        logger.info(
                            f"[STREAMING] Processing {discovered_url.url} with TRUE streaming "
                            f"(never loads to memory, file-size independent)"
                        )

                        # Log memory before fetch
                        mem_before_fetch = log_memory_before("streaming_fetch", {"url": discovered_url.url})
                        
                        # Check memory before fetch
                        check_memory_thresholds("pre_streaming_fetch", {"url": discovered_url.url})

                        # Fetch as streaming iterator
                        streaming_content = await fetcher.fetch_streaming(
                            url=discovered_url.url,
                            source_id=source_id,
                            method="GET",
                        )
                        stats["documents_fetched"] += 1
                        
                        # Log memory after fetch
                        log_memory_after("streaming_fetch", mem_before_fetch, {"url": discovered_url.url})

                        # Get parser for CSV
                        parser = get_parser("csv")
                        if not parser:
                            raise ValueError("CSV parser not registered")

                        # Log memory before parse
                        mem_before_parse = log_memory_before("streaming_parse", {"url": discovered_url.url})
                        
                        # Check memory before parse
                        check_memory_thresholds("pre_streaming_parse", {"url": discovered_url.url})

                        # Parse and process in batches
                        batch_count = 0
                        async for batch in parser.parse_streaming(streaming_content, parse_config):
                            # Log memory after parse batch
                            if batch_count == 0:
                                log_memory_after("streaming_parse_first_batch", mem_before_parse, {"url": discovered_url.url})
                            batch_count += 1
                            logger.info(
                                f"[STREAMING] Processing batch {batch.chunk_index}: "
                                f"{len(batch.documents)} docs ({batch.rows_processed} rows total)"
                            )

                            for parsed_doc in batch.documents:
                                if await _is_cancel_requested(source_id):
                                    logger.warning("Cancellation requested during streaming")
                                    stats["cancelled"] = True
                                    break

                                # Check document limit
                                if remaining_docs is not None and stats["documents_indexed"] >= max_documents_per_source:
                                    logger.info(f"[STREAMING] Reached document limit ({max_documents_per_source})")
                                    break

                                try:
                                    # Process single document: fingerprint, dedup, chunk, embed, index
                                    # Fingerprint
                                    mem_before_fingerprint = log_memory_before("fingerprint", {"doc_id": parsed_doc.document_id})
                                    fingerprint = fingerprinter.compute(parsed_doc)
                                    log_memory_after("fingerprint", mem_before_fingerprint, {"doc_id": parsed_doc.document_id})

                                    # Deduplication
                                    mem_before_dedup = log_memory_before("deduplication", {"doc_id": parsed_doc.document_id})
                                    is_duplicate = await _check_duplicate(deduplicator, fingerprint.fingerprint)
                                    log_memory_after("deduplication", mem_before_dedup, {"doc_id": parsed_doc.document_id, "is_duplicate": is_duplicate})
                                    if is_duplicate:
                                        logger.debug(f"Document {parsed_doc.document_id} is a duplicate")
                                        stats["documents_deduplicated"] += 1
                                        continue

                                    # Chunk
                                    mem_before_chunk = log_memory_before("chunk", {"doc_id": parsed_doc.document_id, "content_len": len(parsed_doc.content)})
                                    
                                    chunking_result = chunker.chunk(
                                        parsed_doc.content,
                                        metadata=parsed_doc.metadata,
                                        document_id=parsed_doc.document_id,
                                    )
                                    stats["chunks_created"] += len(chunking_result.chunks)
                                    
                                    # Log memory after chunk
                                    log_memory_after("chunk", mem_before_chunk, {"doc_id": parsed_doc.document_id, "chunks": len(chunking_result.chunks)})

                                    # Embed
                                    embedding_result = None
                                    if embedder and chunking_result.chunks:
                                        # Log memory before embed
                                        mem_before_embed = log_memory_before("embed", {"doc_id": parsed_doc.document_id, "chunks": len(chunking_result.chunks)})
                                        
                                        try:
                                            embedding_result = await embedder.embed_chunks(
                                                chunking_result.chunks,
                                                document_id=parsed_doc.document_id,
                                            )
                                            stats["embeddings_generated"] += embedding_result.total_embeddings
                                            
                                            # Log memory after embed
                                            log_memory_after("embed", mem_before_embed, {"doc_id": parsed_doc.document_id})
                                        except Exception as embed_exc:
                                            logger.exception(
                                                "Embedding failed for document %s", parsed_doc.document_id
                                            )
                                            if embedding_required:
                                                raise
                                            stats["errors"].append({
                                                "document_id": parsed_doc.document_id,
                                                "error": f"embedding_failed: {embed_exc}",
                                                "classification": "embedding_backend_unavailable",
                                            })

                                    # Index
                                    mem_before_index = log_memory_before("index", {"doc_id": parsed_doc.document_id})
                                    
                                    await _index_document(
                                        session,
                                        parsed_doc,
                                        chunking_result,
                                        source_id,
                                        run_id,
                                        embedding_result=embedding_result,
                                    )
                                    stats["documents_indexed"] += 1
                                    stats["documents_parsed"] += 1
                                    
                                    # Log memory after index
                                    log_memory_after("index", mem_before_index, {"doc_id": parsed_doc.document_id})
                                    
                                    # Force cleanup of large objects to prevent memory accumulation
                                    del parsed_doc
                                    del chunking_result
                                    if embedding_result:
                                        del embedding_result
                                    
                                    # Periodic garbage collection every 50 documents
                                    if stats["documents_indexed"] % 50 == 0:
                                        gc.collect()
                                        mem_after_gc = get_memory_usage_mb()
                                        logger.info(f"[MEMORY] GC completed after {stats['documents_indexed']} docs: {mem_after_gc:.1f}MB")

                                except Exception as doc_exc:
                                    await session.rollback()
                                    logger.exception(f"Error processing document {parsed_doc.document_id}")
                                    stats["errors"].append({
                                        "document_id": parsed_doc.document_id,
                                        "error": str(doc_exc),
                                        "classification": _classify_runtime_error(str(doc_exc)),
                                    })
                                    await _add_document_to_dlq(
                                        session, source_id, run_id, parsed_doc.document_id,
                                        str(doc_exc), discovered_url.url
                                    )

                            # Commit after each batch
                            await session.commit()
                            
                            # Force garbage collection after batch commit
                            gc.collect()

                            # Memory monitoring and cleanup
                            mem_mb = get_memory_usage_mb()
                            logger.info(
                                f"[STREAMING] Batch {batch.chunk_index} committed: "
                                f"{stats['documents_indexed']} docs indexed total, "
                                f"memory: {mem_mb:.1f}MB"
                            )

                            # Proactive memory cleanup if usage is high
                            if mem_mb > 300:  # Warning threshold
                                logger.warning(f"[STREAMING] High memory usage: {mem_mb:.1f}MB")
                                if mem_mb > 450:  # Critical threshold
                                    logger.warning("[STREAMING] Critical memory - forcing cleanup")
                                    force_cleanup()
                                    mem_after = get_memory_usage_mb()
                                    logger.info(f"[STREAMING] Memory after cleanup: {mem_after:.1f}MB")

                            if stats["cancelled"]:
                                break

                        logger.info(
                            f"[STREAMING] Completed {discovered_url.url}: "
                            f"{batch_count} batches, {stats['documents_indexed']} docs indexed"
                        )
                        stats["urls_processed"] += 1

                    else:
                        # ===================================================================
                        # LEGACY PATH - Loads full file to memory (existing behavior)
                        # ===================================================================
                        # Fetch
                        mem_before_fetch = log_memory_before("fetch", {"url": discovered_url.url})
                        fetched = await _run_fetch(
                            fetcher,
                            discovered_url,
                            source.config_json.get("fetch", {}),
                        )
                        stats["documents_fetched"] += 1
                        log_memory_after("fetch", mem_before_fetch, {"url": discovered_url.url, "size": fetched.size_bytes})

                        # Parse
                        mem_before_parse = log_memory_before("parse", {"url": discovered_url.url})
                        parsed_result = await _run_parse(
                            fetched,
                            source_id,
                            source.config_json.get("parse", {}),
                            source.config_json.get("fetch", {}),
                            remaining_docs,
                        )
                        log_memory_after("parse", mem_before_parse, {"url": discovered_url.url, "docs": len(parsed_result.documents)})
                    if parsed_result.errors:
                        for parse_err in parsed_result.errors:
                            err_msg = str(parse_err.get("error", "parse_error"))
                            stats["errors"].append(
                                {
                                    "url": discovered_url.url,
                                    "error": err_msg,
                                    "classification": _classify_runtime_error(err_msg, discovered_url.url),
                                    "phase": "parse",
                                }
                            )
                    if not parsed_result.documents:
                        logger.warning(f"No documents parsed from {discovered_url.url}")
                        continue
                    if remaining_docs is not None:
                        parsed_result.documents = parsed_result.documents[:remaining_docs]
                    stats["documents_parsed"] += len(parsed_result.documents)
                    
                    # Processa cada documento
                    for parsed_doc in parsed_result.documents:
                        if await _is_cancel_requested(source_id):
                            logger.warning(
                                "Cancellation requested while processing documents for source %s",
                                source_id,
                            )
                            stats["cancelled"] = True
                            break
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

                            embedding_result = None
                            if embedder and chunking_result.chunks:
                                try:
                                    embedding_result = await embedder.embed_chunks(
                                        chunking_result.chunks,
                                        document_id=parsed_doc.document_id,
                                    )
                                    stats["embeddings_generated"] += embedding_result.total_embeddings
                                except Exception as embed_exc:
                                    logger.exception(
                                        "Embedding failed for document %s", parsed_doc.document_id
                                    )
                                    if embedding_required:
                                        raise
                                    stats["errors"].append(
                                        {
                                            "document_id": parsed_doc.document_id,
                                            "error": f"embedding_failed: {embed_exc}",
                                            "classification": "embedding_backend_unavailable",
                                        }
                                    )
                            
                            # Index
                            await _index_document(
                                session,
                                parsed_doc,
                                chunking_result,
                                source_id,
                                run_id,
                                embedding_result=embedding_result,
                            )
                            stats["documents_indexed"] += 1
                            
                        except Exception as doc_exc:
                            await session.rollback()
                            logger.exception(f"Error processing document {parsed_doc.document_id}")
                            stats["errors"].append({
                                "document_id": parsed_doc.document_id,
                                "error": str(doc_exc),
                                "classification": _classify_runtime_error(str(doc_exc)),
                            })
                            
                            # Adiciona à DLQ
                            await _add_document_to_dlq(
                                session, source_id, run_id, parsed_doc.document_id,
                                str(doc_exc), discovered_url.url
                            )
                    if stats["cancelled"]:
                        break
                    
                    stats["urls_processed"] += 1
                    
                except Exception as url_exc:
                    await session.rollback()
                    logger.exception(f"Error processing URL {discovered_url.url}")
                    classification = _classify_runtime_error(str(url_exc), discovered_url.url)
                    stats["urls_failed"] += 1
                    stats["errors"].append({
                        "url": discovered_url.url,
                        "error": str(url_exc),
                        "classification": classification,
                    })
                if stats["cancelled"]:
                    break
        finally:
            if embedder is not None:
                await embedder.close()
        
        # 5. Atualiza manifest
        if stats["cancelled"]:
            await _update_manifest_status(session, manifest, ExecutionStatus.CANCELLED)
        else:
            await _update_manifest_status(
                session, manifest, 
                ExecutionStatus.SUCCESS if stats["urls_failed"] == 0 else ExecutionStatus.PARTIAL_SUCCESS
            )
        
        # 6. Atualiza source registry
        await _update_source_stats(session, source_id, stats)
        
        await fetcher.close()

    stats["error_summary"] = _build_error_summary(stats["errors"])
    stats["source_unreachable"] = bool(
        stats["error_summary"].get("source_unreachable_external", 0)
    )
        
    return stats


async def _add_to_dlq_entry(source_id: str, run_id: str, error_message: str, task_id: str) -> None:
    """Wrapper para DLQ com init/close de DB no mesmo event loop."""
    await init_db()
    try:
        await _add_to_dlq(source_id, run_id, error_message, task_id)
    finally:
        await close_db()


async def _update_pipeline_action_status_entry(
    action_id: str,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """Wrapper to update pipeline action status in DB."""
    await init_db()
    try:
        async with get_session() as session:
            await _update_pipeline_action_status(session, action_id, status, error_message=error_message)
    finally:
        await close_db()


async def _update_pipeline_action_status(
    session: AsyncSession,
    action_id: str,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    try:
        action_uuid = uuid.UUID(action_id)
    except ValueError:
        return
    result = await session.execute(
        select(PipelineAction).where(PipelineAction.action_id == action_uuid)
    )
    action = result.scalar_one_or_none()
    if not action:
        return
    action.status = status
    if error_message:
        action.error_message = error_message
    action.updated_at = datetime.now(timezone.utc)
    await session.commit()


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
        status=ExecutionStatus.RUNNING.value,
        trigger="manual",
        # Compatibility: some local DBs were created with timestamp without timezone.
        started_at=datetime.utcnow(),
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
    manifest.status = status.value if hasattr(status, "value") else str(status)
    manifest.completed_at = (
        datetime.utcnow()
        if status in [ExecutionStatus.SUCCESS, ExecutionStatus.FAILED, ExecutionStatus.PARTIAL_SUCCESS, ExecutionStatus.CANCELLED]
        else None
    )
    await session.commit()


async def _update_source_stats(session: AsyncSession, source_id: str, stats: Dict[str, Any]) -> None:
    """Atualiza estatísticas da fonte."""
    result = await session.execute(
        select(SourceRegistry).where(SourceRegistry.id == source_id)
    )
    source = result.scalar_one_or_none()
    
    if source:
        active_documents = await session.scalar(
            select(func.count(Document.id)).where(
                Document.source_id == source_id,
                Document.is_deleted.is_(False),
            )
        )

        source.last_sync_at = datetime.utcnow()
        source.document_count = int(active_documents or 0)
        source.total_documents_ingested = int(source.total_documents_ingested or 0) + int(
            stats.get("documents_indexed", 0)
        )
        if stats.get("documents_indexed", 0) > 0:
            source.last_document_at = datetime.utcnow()
        if stats.get("urls_failed", 0) == 0:
            source.last_success_at = datetime.utcnow()
            source.consecutive_errors = 0
            source.status = SourceStatus.ACTIVE.value
        else:
            source.consecutive_errors += 1
            source.last_error_message = f"Failed URLs: {stats.get('urls_failed', 0)}"
            source.last_error_at = datetime.utcnow()
            
            if source.consecutive_errors >= 5:
                source.status = SourceStatus.ERROR.value
        
        await session.commit()


# =============================================================================
# Pipeline Steps
# =============================================================================

def _build_source_fetcher(source_config: Dict[str, Any], max_documents_per_source: int) -> ContentFetcher:
    """Cria fetcher com overrides de tamanho por fonte."""
    fetch_cfg = source_config.get("fetch", {}) or {}
    max_size_bytes = fetch_cfg.get("max_size_bytes")
    max_size_mb = fetch_cfg.get("max_size_mb")

    # Convert max_size_mb to bytes if specified in config
    config_has_size_limit = (max_size_bytes is not None or max_size_mb is not None)
    if max_size_bytes is None and max_size_mb is not None:
        max_size_bytes = int(max_size_mb) * 1024 * 1024
        logger.info(f"[_build_source_fetcher] Using max_size from config: {max_size_mb}MB ({max_size_bytes} bytes)")

    parse_input_format = str((source_config.get("parse", {}) or {}).get("input_format", "")).lower()

    # For CSV sources without explicit size limit in config, set reasonable defaults
    if max_size_bytes is None and parse_input_format == "csv":
        if max_documents_per_source > 0:
            # Validation/test mode: allow large CSV fetches
            max_size_bytes = 1024 * 1024 * 1024  # 1GB
            logger.info("[_build_source_fetcher] Validation mode: allowing 1GB for CSV fetch")
        # Note: For production mode (max_documents_per_source == 0) without explicit config,
        # we fall through to default ContentFetcher (100MB limit)

    # If explicit size limit was set in config, use it regardless of mode
    if config_has_size_limit and max_size_bytes is not None:
        logger.info(f"[_build_source_fetcher] Creating fetcher with explicit size limit: {max_size_bytes} bytes")
        return ContentFetcher(FetcherConfig(max_size_bytes=int(max_size_bytes)))

    # No explicit limit in config - use default (100MB from settings)
    if max_size_bytes is None:
        logger.debug("[_build_source_fetcher] Using default fetcher (100MB limit)")
        return ContentFetcher()

    # Shouldn't reach here, but handle just in case
    return ContentFetcher(FetcherConfig(max_size_bytes=int(max_size_bytes)))


async def _run_discovery(
    source_id: str,
    source_config: Dict[str, Any],
    use_orchestrator_fallback: bool = False,
    max_documents_per_source: int = 0,
) -> DiscoveryResult:
    """Executa fase de discovery."""
    discovery_config = source_config.get("discovery", {}) or {}
    discovery_mode = str(discovery_config.get("mode", "static_url")).lower()

    engine = DiscoveryEngine()

    # Determine max_urls based on mode and limits
    max_urls: Optional[int] = None
    if max_documents_per_source > 0:
        if discovery_mode == "url_pattern":
            max_urls = 1  # For CSV sources each URL has many rows
        elif discovery_mode in {"crawler", "api_query"}:
            max_urls = max_documents_per_source  # Each URL is one document

    config = DiscoveryConfig(
        mode=discovery_config.get("mode", "static_url"),
        url=discovery_config.get("url") or discovery_config.get("root_url"),
        url_pattern=discovery_config.get("url_template"),
        range_config=discovery_config.get("params"),
        rate_limit_delay=discovery_config.get("rate_limit_delay", 1.0),
        max_urls=max_urls,
        # Crawler mode
        crawler_rules=discovery_config.get("rules"),
        # API query mode
        api_query_config={
            "driver": discovery_config.get("driver"),
            "params": discovery_config.get("params", {}),
            "url": discovery_config.get("url") or discovery_config.get("endpoint"),
        } if discovery_mode == "api_query" else None,
    )
    
    return await engine.discover(source_id, config)


async def _run_fetch(
    fetcher: ContentFetcher,
    discovered_url: Any,
    fetch_config: Optional[Dict[str, Any]] = None,
) -> FetchedContent:
    """Executa fase de fetch."""
    fetch_config = fetch_config or {}
    return await fetcher.fetch(
        url=discovered_url.url,
        source_id=discovered_url.source_id,
        method=fetch_config.get("method", "GET"),
        headers=fetch_config.get("headers"),
    )


async def _run_parse(
    fetched: FetchedContent,
    source_id: str,
    parse_config: Optional[Dict[str, Any]] = None,
    fetch_config: Optional[Dict[str, Any]] = None,
    max_rows: Optional[int] = None,
) -> ParseResult:
    """Executa fase de parsing."""
    parse_config = parse_config or {}
    fetch_config = fetch_config or {}
    # Detecta formato
    content_type = fetched.metadata.content_type or ""
    
    if "csv" in content_type or fetched.url.endswith(".csv"):
        parser = get_parser("csv")
        config = {
            "source_id": source_id,
            "delimiter": parse_config.get("delimiter", "|"),
        }
        if max_rows is not None:
            config["max_rows"] = max_rows
        # Always set max_parse_size_bytes if available (independent of max_rows)
        max_parse_size_bytes = parse_config.get("max_parse_size_bytes")
        if max_parse_size_bytes is None:
            if fetch_config.get("max_size_bytes") is not None:
                max_parse_size_bytes = int(fetch_config["max_size_bytes"])
            elif fetch_config.get("max_size_mb") is not None:
                max_parse_size_bytes = int(fetch_config["max_size_mb"]) * 1024 * 1024
            else:
                max_parse_size_bytes = 1024 * 1024 * 1024
        config["max_parse_size_bytes"] = int(max_parse_size_bytes)
    elif "html" in content_type or fetched.url.endswith(".html"):
        parser = get_parser("html")
        config = {"source_id": source_id}
    elif "pdf" in content_type or fetched.url.endswith(".pdf"):
        parser = get_parser("pdf")
        config = {"source_id": source_id}
    elif "json" in content_type or fetched.url.endswith(".json"):
        parser = get_parser("json")
        config = {
            "source_id": source_id,
            "data_path": parse_config.get("data_path", "dados"),
            "text_fields": parse_config.get("text_fields"),
            "id_field": parse_config.get("id_field", "id"),
            "title_field": parse_config.get("title_field"),
        }
        if max_rows is not None:
            config["max_rows"] = max_rows
    else:
        # Tenta CSV como default para fontes TCU
        parser = get_parser("csv")
        config = {
            "source_id": source_id,
            "delimiter": parse_config.get("delimiter", "|"),
        }
        if max_rows is not None:
            config["max_rows"] = max_rows
        # Always set max_parse_size_bytes if available (independent of max_rows)
        max_parse_size_bytes = parse_config.get("max_parse_size_bytes")
        if max_parse_size_bytes is None:
            if fetch_config.get("max_size_bytes") is not None:
                max_parse_size_bytes = int(fetch_config["max_size_bytes"])
            elif fetch_config.get("max_size_mb") is not None:
                max_parse_size_bytes = int(fetch_config["max_size_mb"]) * 1024 * 1024
            else:
                max_parse_size_bytes = 1024 * 1024 * 1024
        config["max_parse_size_bytes"] = int(max_parse_size_bytes)
    
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
    embedding_result: Optional[EmbeddingResult] = None,
) -> None:
    """Indexa documento no PostgreSQL."""
    result = await session.execute(
        select(Document).where(Document.document_id == parsed_doc.document_id)
    )
    persisted_document = result.scalar_one_or_none()
    if asyncio.iscoroutine(persisted_document):
        persisted_document = await persisted_document
    if persisted_document is not None and not isinstance(persisted_document, Document):
        persisted_document = None

    if persisted_document is None:
        persisted_document = Document(
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
        session.add(persisted_document)
    else:
        persisted_document.source_id = source_id
        persisted_document.title = parsed_doc.title or ""
        persisted_document.content_preview = parsed_doc.content_preview or parsed_doc.content[:500]
        persisted_document.content_hash = parsed_doc.content_hash or ""
        persisted_document.fingerprint = parsed_doc.content_hash or ""
        persisted_document.url = parsed_doc.url or ""
        persisted_document.doc_metadata = parsed_doc.metadata
        persisted_document.status = "active"

        # Rebuild chunks for this document to keep chunk_index uniqueness consistent.
        await session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == parsed_doc.document_id)
        )

    persisted_document.chunks_count = len(chunking_result.chunks)
    await session.flush()

    embedding_by_index: Dict[int, EmbeddedChunk] = {}
    if embedding_result is not None:
        embedding_by_index = {chunk.index: chunk for chunk in embedding_result.chunks}

    for chunk in chunking_result.chunks:
        section_type = chunk.section_type.value if hasattr(chunk.section_type, "value") else chunk.section_type
        embedded_chunk = embedding_by_index.get(chunk.index)
        row = DocumentChunk(
            document_id=parsed_doc.document_id,
            chunk_index=chunk.index,
            chunk_text=chunk.text,
            token_count=chunk.token_count or 0,
            char_count=chunk.char_count or len(chunk.text),
            embedding=(embedded_chunk.embedding if embedded_chunk else None),
            embedding_model=(embedded_chunk.embedding_model if embedded_chunk else None),
            embedded_at=(embedded_chunk.embedded_at if embedded_chunk else None),
            chunk_metadata=chunk.metadata or {},
            section_type=section_type,
        )
        session.add(row)

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


def _is_external_source_url(url: Optional[str]) -> bool:
    """Retorna True quando a URL parece ser de uma fonte externa."""
    if not url:
        return False
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    if host in LOCAL_HOSTS:
        return False
    if host.endswith(".local"):
        return False
    if host.startswith("127.") or host.startswith("10.") or host.startswith("192.168."):
        return False
    return True


def _classify_runtime_error(error_text: str, url: Optional[str] = None) -> str:
    """Classifica erro de execução para separar falhas externas e internas."""
    msg = (error_text or "").lower()

    # External reachability failures (strict bucket)
    dns_markers = [
        "no address associated with hostname",
        "name or service not known",
        "temporary failure in name resolution",
        "getaddrinfo",
        "dns",
        "nodename nor servname",
    ]
    network_unreachable_markers = [
        "network error",
        "connecterror",
        "failed to connect",
        "max retries exceeded",
    ]
    if _is_external_source_url(url) and (
        any(marker in msg for marker in dns_markers)
        or any(marker in msg for marker in network_unreachable_markers)
    ):
        return "source_unreachable_external"

    if "content-length" in msg and "exceeds max" in msg:
        return "source_content_too_large"

    if "embedding_failed" in msg or "teiconnectionerror" in msg:
        return "embedding_backend_unavailable"

    if any(code in msg for code in [" 400", " 401", " 403", " 404", " 429", " 500", " 502", " 503", " 504"]):
        return "source_http_error"

    if any(marker in msg for marker in ["invalid", "valueerror", "keyerror", "typeerror"]):
        return "internal_pipeline_regression"

    return "unknown"


def _build_error_summary(errors: List[Dict[str, Any]]) -> Dict[str, int]:
    """Agrega contagem de erros por classificação."""
    summary: Dict[str, int] = {}
    for err in errors:
        klass = str(err.get("classification") or _classify_runtime_error(str(err.get("error", "")), err.get("url")))
        summary[klass] = summary.get(klass, 0) + 1
    return summary


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
