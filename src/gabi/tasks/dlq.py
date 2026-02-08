"""Tasks de gerenciamento da Dead Letter Queue (DLQ).

Implementa reprocessamento de mensagens DLQ com retry controlado.
Baseado em GABI_SPECS_FINAL_v1.md §2.7.1
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gabi.db import get_session
from gabi.models.dlq import DLQMessage, DLQStatus
from gabi.worker import celery_app

logger = logging.getLogger(__name__)


# =============================================================================
# Task: Retry DLQ Message
# =============================================================================

@celery_app.task(
    bind=True,
    name="gabi.tasks.dlq.retry_dlq_task",
    queue="gabi.dlq",
    max_retries=0,  # DLQ tem sua própria lógica de retry
    time_limit=1800,  # 30 minutos
)
def retry_dlq_task(self, message_id: str) -> Dict[str, Any]:
    """Reprocessa uma mensagem da DLQ.
    
    Busca a mensagem pelo ID e tenta reprocessar o payload original.
    Atualiza o retry_count e status da mensagem.
    
    Args:
        message_id: UUID da mensagem na DLQ
        
    Returns:
        Dict com resultado do reprocessamento
        
    Raises:
        ValueError: Se mensagem não existir ou não puder ser reprocessada
    """
    logger.info(f"[retry_dlq_task] Processing DLQ message {message_id}")
    
    try:
        result = asyncio.run(_process_dlq_message(message_id))
        logger.info(f"[retry_dlq_task] Successfully processed message {message_id}")
        return result
        
    except Exception as exc:
        logger.exception(f"[retry_dlq_task] Failed to process message {message_id}")
        
        # Atualiza a mensagem na DLQ com o erro
        try:
            asyncio.run(_update_dlq_failure(message_id, str(exc)))
        except Exception as update_exc:
            logger.error(f"[retry_dlq_task] Failed to update DLQ message: {update_exc}")
        
        raise


# =============================================================================
# Task: Process All Pending DLQ
# =============================================================================

@celery_app.task(
    bind=True,
    name="gabi.tasks.dlq.process_pending_dlq_task",
    queue="gabi.dlq",
    max_retries=0,
    time_limit=3600,  # 1 hora
)
def process_pending_dlq_task(
    self,
    max_messages: int = 100,
    source_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Processa todas as mensagens pendentes na DLQ.
    
    Busca mensagens com status PENDING ou RETRYING onde next_retry_at <= agora
    e tenta reprocessá-las.
    
    Args:
        max_messages: Máximo de mensagens a processar
        source_id: Filtrar por fonte específica (opcional)
        
    Returns:
        Dict com estatísticas do processamento
    """
    logger.info(f"[process_pending_dlq_task] Processing up to {max_messages} pending messages")
    
    return asyncio.run(_process_pending_messages(max_messages, source_id))


# =============================================================================
# Task: Resolve DLQ Message
# =============================================================================

@celery_app.task(
    bind=True,
    name="gabi.tasks.dlq.resolve_dlq_task",
    queue="gabi.dlq",
    max_retries=0,
)
def resolve_dlq_task(
    self,
    message_id: str,
    resolved_by: str,
    resolution_notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Marca uma mensagem DLQ como resolvida manualmente.
    
    Args:
        message_id: UUID da mensagem
        resolved_by: Identificador de quem resolveu
        resolution_notes: Notas sobre a resolução
        
    Returns:
        Dict com resultado da operação
    """
    logger.info(f"[resolve_dlq_task] Resolving message {message_id} by {resolved_by}")
    
    return asyncio.run(_resolve_message(message_id, resolved_by, resolution_notes))


# =============================================================================
# Task: Get DLQ Stats
# =============================================================================

@celery_app.task(
    bind=True,
    name="gabi.tasks.dlq.get_dlq_stats_task",
    queue="gabi.dlq",
    max_retries=0,
)
def get_dlq_stats_task(self, source_id: Optional[str] = None) -> Dict[str, Any]:
    """Retorna estatísticas da DLQ.
    
    Args:
        source_id: Filtrar por fonte específica (opcional)
        
    Returns:
        Dict com estatísticas
    """
    return asyncio.run(_get_dlq_stats(source_id))


# =============================================================================
# Implementation
# =============================================================================

async def _process_dlq_message(message_id: str) -> Dict[str, Any]:
    """Processa uma mensagem DLQ individual.
    
    Args:
        message_id: UUID da mensagem
        
    Returns:
        Resultado do processamento
    """
    async with get_session() as session:
        # Busca mensagem
        message = await _get_message(session, message_id)
        
        if not message:
            raise ValueError(f"DLQ message not found: {message_id}")
        
        # Verifica se pode reprocessar
        if not message.can_retry:
            raise ValueError(
                f"Message {message_id} cannot be retried (status: {message.status.value}, "
                f"retries: {message.retry_count}/{message.max_retries})"
            )
        
        # Atualiza tentativa
        message.mark_retry_attempt()
        await session.commit()
        
        # Extrai informações do payload
        payload = message.payload or {}
        error_type = message.error_type
        url = message.url
        document_id = message.document_id
        
        try:
            # Dispatch para handler baseado no tipo de erro
            if error_type == "sync_failed":
                result = await _retry_sync_failed(session, message)
            elif error_type == "document_processing_failed":
                result = await _retry_document_processing(session, message)
            elif error_type == "fetch_failed":
                result = await _retry_fetch(session, message)
            elif error_type == "parse_failed":
                result = await _retry_parse(session, message)
            else:
                # Tipo desconhecido - marca como resolvido manualmente necessário
                result = {
                    "status": "manual_resolution_required",
                    "reason": f"Unknown error type: {error_type}",
                }
            
            # Se sucesso, resolve a mensagem
            if result.get("status") == "success":
                message.resolve("dlq_worker", f"Auto-resolved on retry attempt {message.retry_count}")
                await session.commit()
            
            return {
                "message_id": message_id,
                "status": result.get("status", "unknown"),
                "result": result,
                "retry_count": message.retry_count,
            }
            
        except Exception as exc:
            # Falha no reprocessamento - agenda próximo retry se possível
            if message.can_retry:
                message.schedule_next_retry()
                await session.commit()
                raise
            else:
                # Esgotou retries
                message.status = DLQStatus.EXHAUSTED
                await session.commit()
                raise ValueError(f"Max retries exceeded for message {message_id}") from exc


async def _process_pending_messages(
    max_messages: int,
    source_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Processa mensagens pendentes em batch.
    
    Args:
        max_messages: Máximo de mensagens
        source_id: Filtro por fonte
        
    Returns:
        Estatísticas do processamento
    """
    stats = {
        "total_checked": 0,
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
    }
    
    async with get_session() as session:
        now = datetime.now(timezone.utc)
        
        # Busca mensagens pendentes
        query = select(DLQMessage).where(
            DLQMessage.status.in_([DLQStatus.PENDING, DLQStatus.RETRYING]),
            (DLQMessage.next_retry_at <= now) | (DLQMessage.next_retry_at.is_(None)),
        ).limit(max_messages)
        
        if source_id:
            query = query.where(DLQMessage.source_id == source_id)
        
        result = await session.execute(query)
        messages = result.scalars().all()
        
        stats["total_checked"] = len(messages)
        
        for message in messages:
            try:
                if not message.can_retry:
                    stats["skipped"] += 1
                    continue
                
                # Chama task individual usando delay() de forma síncrona
                # delay() é mais simples que apply_async e retorna AsyncResult
                result = retry_dlq_task.delay(str(message.id))
                
                stats["processed"] += 1
                
                # Verifica resultado (o delay envia para a fila, 
                # o resultado real vem via backend ou task completion)
                # Como não podemos await o resultado síncrono aqui,
                # assumimos que foi enviado com sucesso
                stats["succeeded"] += 1
                    
            except Exception as exc:
                logger.exception(f"Error processing DLQ message {message.id}")
                stats["failed"] += 1
                stats["errors"].append({
                    "message_id": str(message.id),
                    "error": str(exc),
                })
    
    return stats


async def _resolve_message(
    message_id: str,
    resolved_by: str,
    resolution_notes: Optional[str],
) -> Dict[str, Any]:
    """Resolve uma mensagem manualmente.
    
    Args:
        message_id: UUID da mensagem
        resolved_by: Quem resolveu
        resolution_notes: Notas
        
    Returns:
        Resultado da operação
    """
    async with get_session() as session:
        message = await _get_message(session, message_id)
        
        if not message:
            raise ValueError(f"Message not found: {message_id}")
        
        message.resolve(resolved_by, resolution_notes)
        await session.commit()
        
        return {
            "message_id": message_id,
            "status": "resolved",
            "resolved_by": resolved_by,
            "resolved_at": message.resolved_at.isoformat() if message.resolved_at else None,
        }


async def _get_dlq_stats(source_id: Optional[str] = None) -> Dict[str, Any]:
    """Retorna estatísticas da DLQ.
    
    Args:
        source_id: Filtro por fonte
        
    Returns:
        Estatísticas
    """
    async with get_session() as session:
        query = select(DLQMessage)
        if source_id:
            query = query.where(DLQMessage.source_id == source_id)
        
        result = await session.execute(query)
        messages = result.scalars().all()
        
        stats = {
            "total": len(messages),
            "by_status": {
                "pending": 0,
                "retrying": 0,
                "exhausted": 0,
                "resolved": 0,
                "archived": 0,
            },
            "by_error_type": {},
            "ready_for_retry": 0,
        }
        
        now = datetime.now(timezone.utc)
        
        for msg in messages:
            # Status
            status_key = msg.status.value.lower()
            if status_key in stats["by_status"]:
                stats["by_status"][status_key] += 1
            
            # Error type
            error_type = msg.error_type or "unknown"
            stats["by_error_type"][error_type] = stats["by_error_type"].get(error_type, 0) + 1
            
            # Ready for retry
            if msg.can_retry and (msg.next_retry_at is None or msg.next_retry_at <= now):
                stats["ready_for_retry"] += 1
        
        return stats


async def _get_message(session: AsyncSession, message_id: str) -> Optional[DLQMessage]:
    """Busca mensagem DLQ pelo ID."""
    try:
        uuid_id = UUID(message_id)
    except ValueError:
        return None
    
    result = await session.execute(
        select(DLQMessage).where(DLQMessage.id == uuid_id)
    )
    return result.scalar_one_or_none()


async def _update_dlq_failure(message_id: str, error_message: str) -> None:
    """Atualiza mensagem com falha."""
    async with get_session() as session:
        message = await _get_message(session, message_id)
        if message:
            message.error_message = f"{message.error_message}\nRetry failed: {error_message}"
            if message.can_retry:
                message.schedule_next_retry()
            else:
                message.status = DLQStatus.EXHAUSTED
            await session.commit()


# =============================================================================
# Retry Handlers
# =============================================================================

async def _retry_sync_failed(session: AsyncSession, message: DLQMessage) -> Dict[str, Any]:
    """Retry para falha de sync completo.
    
    Re-executa a task de sync da fonte.
    """
    payload = message.payload or {}
    task_id = payload.get("task_id")
    source_id = message.source_id
    
    # Importa aqui para evitar circular import
    from gabi.tasks.sync import sync_source_task
    
    # Re-executa sync
    result = sync_source_task.delay(source_id)
    
    return {
        "status": "success",
        "action": "retriggered_sync",
        "new_task_id": result.id if result else None,
    }


async def _retry_document_processing(
    session: AsyncSession, 
    message: DLQMessage
) -> Dict[str, Any]:
    """Retry para falha de processamento de documento.
    
    Tenta reprocessar o documento específico.
    """
    payload = message.payload or {}
    document_id = payload.get("document_id") or message.document_id
    
    if not document_id:
        return {
            "status": "manual_resolution_required",
            "reason": "Missing document_id in payload",
        }
    
    # Aqui implementaríamos a lógica específica de reprocessamento
    # Por simplicidade, marcamos para resolução manual
    return {
        "status": "manual_resolution_required",
        "reason": "Document reprocessing requires manual review",
        "document_id": document_id,
    }


async def _retry_fetch(session: AsyncSession, message: DLQMessage) -> Dict[str, Any]:
    """Retry para falha de fetch.
    
    Tenta refetch da URL.
    """
    url = message.url
    source_id = message.source_id
    
    # Implementação de retry de fetch
    from gabi.pipeline.fetcher import ContentFetcher
    
    fetcher = ContentFetcher()
    try:
        fetched = await fetcher.fetch(url, source_id)
        await fetcher.close()
        
        return {
            "status": "success",
            "action": "refetched",
            "size_bytes": len(fetched.content),
        }
    except Exception as exc:
        await fetcher.close()
        raise


async def _retry_parse(session: AsyncSession, message: DLQMessage) -> Dict[str, Any]:
    """Retry para falha de parse.
    
    Tenta reparse do conteúdo (requer que o conteúdo esteja cacheado).
    """
    # Parse retry geralmente requer que o conteúdo esteja disponível
    # Implementação depende de estratégia de cache
    return {
        "status": "manual_resolution_required",
        "reason": "Parse retry requires cached content",
    }


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "retry_dlq_task",
    "process_pending_dlq_task",
    "resolve_dlq_task",
    "get_dlq_stats_task",
]
