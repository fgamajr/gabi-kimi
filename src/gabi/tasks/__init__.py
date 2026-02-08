"""Tasks - Tarefas assíncronas e background jobs.

Exporta tasks Celery do GABI para descoberta automática.
"""

from gabi.tasks.alerts import (
    AlertChannel,
    AlertType,
    alert_dlq_threshold_reached,
    alert_pipeline_failure,
    alert_service_degraded,
    batch_send_alerts_task,
    send_alert_task,
    send_alert_to_channel_task,
)
from gabi.tasks.dlq import (
    get_dlq_stats_task,
    process_pending_dlq_task,
    resolve_dlq_task,
    retry_dlq_task,
)
from gabi.tasks.health import check_service_task, health_check_task
from gabi.tasks.sync import process_document_task, sync_source_task

__all__ = [
    # Sync
    "sync_source_task",
    "process_document_task",
    # DLQ
    "retry_dlq_task",
    "process_pending_dlq_task",
    "resolve_dlq_task",
    "get_dlq_stats_task",
    # Health
    "health_check_task",
    "check_service_task",
    # Alerts
    "send_alert_task",
    "send_alert_to_channel_task",
    "batch_send_alerts_task",
    "alert_pipeline_failure",
    "alert_dlq_threshold_reached",
    "alert_service_degraded",
    "AlertType",
    "AlertChannel",
]
