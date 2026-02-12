"""Tasks de envio de alertas para o GABI.

Implementa notificações via múltiplos canais:
- Email
- Slack
- Webhook
- Logs (fallback)

Baseado em GABI_SPECS_FINAL_v1.md §2.9
"""

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import aiohttp

from gabi.config import settings
from gabi.worker import celery_app

logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================

class AlertType(str, Enum):
    """Tipos de alerta suportados."""
    
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    SUCCESS = "success"


class AlertChannel(str, Enum):
    """Canais de envio de alerta."""
    
    EMAIL = "email"
    SLACK = "slack"
    WEBHOOK = "webhook"
    LOG = "log"


# =============================================================================
# Task: Send Alert
# =============================================================================

@celery_app.task(
    bind=True,
    name="gabi.tasks.alerts.send_alert_task",
    queue="gabi.alerts",
    max_retries=3,
    default_retry_delay=30,
    time_limit=60,
)
def send_alert_task(
    self,
    alert_type: str,
    message: str,
    channels: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Envia alerta através dos canais configurados.
    
    Args:
        alert_type: Tipo do alerta (info, warning, error, critical, success)
        message: Mensagem do alerta
        channels: Lista de canais específicos (None = todos configurados)
        metadata: Metadados adicionais para o alerta
        
    Returns:
        Dict com resultado do envio para cada canal
        
    Raises:
        Retry: Se houver erro transitório no envio
    """
    alert_type_enum = AlertType(alert_type.lower())
    target_channels = channels or ["log"]  # Default para log
    
    logger.info(f"[send_alert_task] Sending {alert_type} alert: {message[:100]}...")
    
    # Import asyncio e executa async
    import asyncio
    
    try:
        result = asyncio.run(_send_alert(
            alert_type=alert_type_enum,
            message=message,
            channels=target_channels,
            metadata=metadata or {},
        ))
        
        return result
        
    except Exception as exc:
        logger.exception("[send_alert_task] Failed to send alert")
        
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))
        
        # Fallback para log em caso de falha completa
        _log_alert(alert_type_enum, message, metadata or {})
        
        return {
            "status": "failed",
            "error": str(exc),
            "fallback": "logged",
        }


# =============================================================================
# Task: Send Alert to Specific Channel
# =============================================================================

@celery_app.task(
    bind=True,
    name="gabi.tasks.alerts.send_alert_to_channel_task",
    queue="gabi.alerts",
    max_retries=2,
    default_retry_delay=30,
)
def send_alert_to_channel_task(
    self,
    channel: str,
    alert_type: str,
    message: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Envia alerta para um canal específico.
    
    Args:
        channel: Canal de destino (email, slack, webhook, log)
        alert_type: Tipo do alerta
        message: Mensagem do alerta
        metadata: Metadados adicionais
        
    Returns:
        Resultado do envio
    """
    alert_type_enum = AlertType(alert_type.lower())
    channel_enum = AlertChannel(channel.lower())
    
    import asyncio
    
    try:
        result = asyncio.run(_send_to_channel(
            channel=channel_enum,
            alert_type=alert_type_enum,
            message=message,
            metadata=metadata or {},
        ))
        
        return {
            "channel": channel,
            "status": "success" if result else "failed",
        }
        
    except Exception as exc:
        logger.exception(f"[send_alert_to_channel_task] Failed to send to {channel}")
        raise self.retry(exc=exc)


# =============================================================================
# Task: Batch Send Alerts
# =============================================================================

@celery_app.task(
    bind=True,
    name="gabi.tasks.alerts.batch_send_alerts_task",
    queue="gabi.alerts",
    max_retries=1,
    time_limit=300,
)
def batch_send_alerts_task(
    self,
    alerts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Envia múltiplos alertas em batch.
    
    Args:
        alerts: Lista de alertas (cada um com alert_type, message, etc.)
        
    Returns:
        Estatísticas do envio
    """
    logger.info(f"[batch_send_alerts_task] Processing {len(alerts)} alerts")
    
    import asyncio
    
    stats = {
        "total": len(alerts),
        "sent": 0,
        "failed": 0,
        "errors": [],
    }
    
    async def process_batch():
        for alert in alerts:
            try:
                await _send_alert(
                    alert_type=AlertType(alert.get("alert_type", "info")),
                    message=alert.get("message", ""),
                    channels=alert.get("channels", ["log"]),
                    metadata=alert.get("metadata", {}),
                )
                stats["sent"] += 1
            except Exception as exc:
                stats["failed"] += 1
                stats["errors"].append({
                    "message": alert.get("message", "")[:50],
                    "error": str(exc),
                })
    
    asyncio.run(process_batch())
    
    return stats


# =============================================================================
# Implementation
# =============================================================================

async def _send_alert(
    alert_type: AlertType,
    message: str,
    channels: List[str],
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """Envia alerta para múltiplos canais.
    
    Args:
        alert_type: Tipo do alerta
        message: Mensagem
        channels: Lista de canais
        metadata: Metadados
        
    Returns:
        Resultados por canal
    """
    results = {}
    
    for channel_str in channels:
        try:
            channel = AlertChannel(channel_str.lower())
            success = await _send_to_channel(channel, alert_type, message, metadata)
            results[channel_str] = "success" if success else "failed"
        except ValueError:
            results[channel_str] = "unknown_channel"
        except Exception as exc:
            logger.error(f"Failed to send to {channel_str}: {exc}")
            results[channel_str] = f"error: {str(exc)}"
    
    return {
        "status": "completed",
        "alert_type": alert_type.value,
        "channels": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def _send_to_channel(
    channel: AlertChannel,
    alert_type: AlertType,
    message: str,
    metadata: Dict[str, Any],
) -> bool:
    """Envia alerta para canal específico.
    
    Args:
        channel: Canal de destino
        alert_type: Tipo do alerta
        message: Mensagem
        metadata: Metadados
        
    Returns:
        True se enviado com sucesso
    """
    handlers = {
        AlertChannel.LOG: _send_to_log,
        AlertChannel.EMAIL: _send_to_email,
        AlertChannel.SLACK: _send_to_slack,
        AlertChannel.WEBHOOK: _send_to_webhook,
    }
    
    handler = handlers.get(channel)
    if not handler:
        logger.warning(f"No handler for channel: {channel}")
        return False
    
    return await handler(alert_type, message, metadata)


async def _send_to_log(
    alert_type: AlertType,
    message: str,
    metadata: Dict[str, Any],
) -> bool:
    """Envia alerta para logs."""
    _log_alert(alert_type, message, metadata)
    return True


def _log_alert(
    alert_type: AlertType,
    message: str,
    metadata: Dict[str, Any],
) -> None:
    """Registra alerta nos logs."""
    log_data = {
        "type": "alert",
        "alert_type": alert_type.value,
        "message": message,
        "metadata": metadata,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    log_method = getattr(logger, alert_type.value, logger.info)
    log_method(f"[ALERT] {message} | {json.dumps(metadata)}")


async def _send_to_email(
    alert_type: AlertType,
    message: str,
    metadata: Dict[str, Any],
) -> bool:
    """Envia alerta por email (placeholder).
    
    Implementação real requeria integração com serviço de email.
    """
    # Placeholder - implementação depende de infraestrutura
    recipients = metadata.get("recipients", [])
    
    if not recipients:
        logger.warning("No recipients specified for email alert")
        return False
    
    subject = f"[GABI] {alert_type.value.upper()}: {message[:50]}"
    
    # Aqui implementaria envio real via SMTP ou serviço (SendGrid, SES, etc.)
    logger.info(f"[EMAIL ALERT] To: {recipients}, Subject: {subject}")
    
    # Placeholder: simula sucesso
    return True


async def _send_to_slack(
    alert_type: AlertType,
    message: str,
    metadata: Dict[str, Any],
) -> bool:
    """Envia alerta para Slack via webhook."""
    webhook_url = metadata.get("slack_webhook_url") or _get_slack_webhook()
    
    if not webhook_url:
        logger.warning("No Slack webhook configured")
        return False
    
    # Mapeia tipos para cores
    colors = {
        AlertType.INFO: "#36a64f",
        AlertType.WARNING: "#ff9900",
        AlertType.ERROR: "#ff0000",
        AlertType.CRITICAL: "#990000",
        AlertType.SUCCESS: "#36a64f",
    }
    
    payload = {
        "attachments": [
            {
                "color": colors.get(alert_type, "#808080"),
                "title": f"GABI Alert: {alert_type.value.upper()}",
                "text": message,
                "fields": [
                    {
                        "title": k,
                        "value": str(v)[:100],
                        "short": True,
                    }
                    for k, v in metadata.items()
                    if k != "slack_webhook_url"
                ][:10],  # Limita campos
                "footer": "GABI Pipeline",
                "ts": int(datetime.now(timezone.utc).timestamp()),
            }
        ]
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    logger.info("Slack alert sent successfully")
                    return True
                else:
                    logger.error(f"Slack alert failed: HTTP {resp.status}")
                    return False
    except Exception as exc:
        logger.error(f"Slack alert exception: {exc}")
        return False


async def _send_to_webhook(
    alert_type: AlertType,
    message: str,
    metadata: Dict[str, Any],
) -> bool:
    """Envia alerta para webhook genérico."""
    webhook_url = metadata.get("webhook_url")
    
    if not webhook_url:
        logger.warning("No webhook URL specified")
        return False
    
    payload = {
        "alert_type": alert_type.value,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": {k: v for k, v in metadata.items() if k != "webhook_url"},
    }
    
    headers = metadata.get("webhook_headers", {"Content-Type": "application/json"})
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                success = 200 <= resp.status < 300
                if not success:
                    logger.error(f"Webhook alert failed: HTTP {resp.status}")
                return success
    except Exception as exc:
        logger.error(f"Webhook alert exception: {exc}")
        return False


def _get_slack_webhook() -> Optional[str]:
    """Retorna webhook do Slack das configurações."""
    import os
    return os.getenv("GABI_SLACK_WEBHOOK_URL")


# =============================================================================
# Utility Functions
# =============================================================================

def alert_pipeline_failure(
    source_id: str,
    run_id: str,
    error_message: str,
    severity: AlertType = AlertType.ERROR,
) -> None:
    """Envia alerta de falha no pipeline.
    
    Args:
        source_id: ID da fonte
        run_id: ID da execução
        error_message: Mensagem de erro
        severity: Severidade do alerta
    """
    message = f"Pipeline failure for source {source_id}: {error_message}"
    metadata = {
        "source_id": source_id,
        "run_id": run_id,
        "error": error_message,
    }
    
    send_alert_task.delay(
        alert_type=severity.value,
        message=message,
        metadata=metadata,
    )


def alert_dlq_threshold_reached(
    threshold: int,
    current_count: int,
) -> None:
    """Envia alerta quando DLQ atinge threshold.
    
    Args:
        threshold: Limite configurado
        current_count: Contagem atual
    """
    message = f"DLQ threshold reached: {current_count} messages (threshold: {threshold})"
    
    send_alert_task.delay(
        alert_type=AlertType.WARNING.value,
        message=message,
        metadata={
            "threshold": threshold,
            "current_count": current_count,
        },
    )


def alert_service_degraded(
    service_name: str,
    status: str,
    details: Dict[str, Any],
) -> None:
    """Envia alerta de serviço degradado.
    
    Args:
        service_name: Nome do serviço
        status: Status atual
        details: Detalhes adicionais
    """
    message = f"Service {service_name} is {status}"
    
    send_alert_task.delay(
        alert_type=AlertType.WARNING.value,
        message=message,
        metadata={
            "service": service_name,
            "status": status,
            **details,
        },
    )


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "send_alert_task",
    "send_alert_to_channel_task",
    "batch_send_alerts_task",
    "alert_pipeline_failure",
    "alert_dlq_threshold_reached",
    "alert_service_degraded",
    "AlertType",
    "AlertChannel",
]
