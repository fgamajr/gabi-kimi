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
from gabi.pipeline.orchestrator import PipelineOrchestrator
from gabi.pipeline.parser import get_parser
from gabi.worker import celery_app

logger = logging.getLogger(__name__)


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "tei", "redis", "postgres", "elasticsearch"}


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
    
    try:
        # Executa pipeline com lifecycle de DB no mesmo event loop.
        result = asyncio.run(
            _run_sync_pipeline_entry(
                source_id,
                run_id,
                max_documents_per_source_override=max_documents_per_source_override,
                disable_embeddings=disable_embeddings,
            )
        )
        
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
                asyncio.run(_add_to_dlq_entry(source_id, run_id, str(exc), self.request.id))
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
        await close_db()

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
                try:
                    # Fetch
                    fetched = await _run_fetch(
                        fetcher,
                        discovered_url,
                        source.config_json.get("fetch", {}),
                    )
                    stats["documents_fetched"] += 1
                    
                    # Parse
                    parsed_result = await _run_parse(
                        fetched,
                        source_id,
                        source.config_json.get("parse", {}),
                        source.config_json.get("fetch", {}),
                        remaining_docs,
                    )
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
        finally:
            if embedder is not None:
                await embedder.close()
        
        # 5. Atualiza manifest
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
        if status in [ExecutionStatus.SUCCESS, ExecutionStatus.FAILED, ExecutionStatus.PARTIAL_SUCCESS]
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

    if max_size_bytes is None and max_size_mb is not None:
        max_size_bytes = int(max_size_mb) * 1024 * 1024

    parse_input_format = str((source_config.get("parse", {}) or {}).get("input_format", "")).lower()
    if max_size_bytes is None and max_documents_per_source > 0 and parse_input_format == "csv":
        # Validation mode: allow large CSV fetches while parse remains capped by max_rows.
        max_size_bytes = 1024 * 1024 * 1024

    if max_size_bytes is None:
        return ContentFetcher()

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

    if use_orchestrator_fallback and discovery_mode in {"crawler", "api_query"}:
        orchestrator = PipelineOrchestrator()
        discovered_urls = await orchestrator._discovery_phase(source_config, {})
        mapped_urls = [
            DiscoveredURL(
                url=url,
                source_id=source_id,
                priority=0,
                metadata={"discovery_mode": f"orchestrator_{discovery_mode}"},
            )
            for url in discovered_urls
        ]
        return DiscoveryResult(
            urls=mapped_urls,
            total_found=len(mapped_urls),
            filtered_out=0,
            duration_seconds=0.0,
        )

    engine = DiscoveryEngine()
    
    config = DiscoveryConfig(
        mode=discovery_config.get("mode", "static_url"),
        url=discovery_config.get("url"),
        url_pattern=discovery_config.get("url_template"),
        range_config=discovery_config.get("params"),
        rate_limit_delay=discovery_config.get("rate_limit_delay", 1.0),
        max_urls=1 if max_documents_per_source > 0 and discovery_mode == "url_pattern" else None,
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
    else:
        # Tenta CSV como default para fontes TCU
        parser = get_parser("csv")
        config = {
            "source_id": source_id,
            "delimiter": parse_config.get("delimiter", "|"),
        }
        if max_rows is not None:
            config["max_rows"] = max_rows
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
