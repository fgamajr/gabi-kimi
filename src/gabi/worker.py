"""Celery worker configuration for GABI.

Configuração do aplicativo Celery com:
- task_acks_late = True (garante que tasks só são removidas da fila após execução)
- worker_prefetch_multiplier = 1 (evita prefetch de tasks, distribuição justa)
- visibility_timeout = 43200 (12h para tasks longas)

Baseado em GABI_SPECS_FINAL_v1.md §2.8.1
"""

import logging
import os
from typing import Any, Dict

from celery import Celery
from celery.signals import setup_logging, task_failure, task_postrun, task_prerun

from gabi.config import settings

logger = logging.getLogger(__name__)

# =============================================================================
# Celery App Configuration
# =============================================================================

def create_celery_app() -> Celery:
    """Cria e configura a aplicação Celery.
    
    Returns:
        Celery: Aplicação configurada
    """
    app = Celery("gabi")
    
    # Configurações principais
    app.conf.update(
        # Broker (Redis)
        broker_url=settings.redis_url,
        result_backend=settings.redis_url,
        
        # Serialização
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        
        # Timezone
        timezone="America/Sao_Paulo",
        enable_utc=True,
        
        # Configurações críticas solicitadas
        task_acks_late=True,  # Só remove da fila após execução completa
        worker_prefetch_multiplier=1,  # Evita prefetch, distribuição justa entre workers
        broker_transport_options={
            "visibility_timeout": 43200,  # 12 horas (tasks longas)
        },
        
        # Resultados
        task_track_started=True,
        task_time_limit=3600 * 12,  # 12 horas (hard limit)
        task_soft_time_limit=3600 * 11,  # 11 horas (soft limit, permite cleanup)
        
        # Retries
        task_default_retry_delay=60,
        task_max_retries=5,
        
        # Filas
        task_default_queue="gabi.default",
        task_queues={
            "gabi.default": {"binding_key": "gabi.default"},
            "gabi.sync": {"binding_key": "gabi.sync"},
            "gabi.dlq": {"binding_key": "gabi.dlq"},
            "gabi.health": {"binding_key": "gabi.health"},
            "gabi.alerts": {"binding_key": "gabi.alerts"},
        },
        task_routes={
            "gabi.tasks.sync.*": {"queue": "gabi.sync"},
            "gabi.tasks.dlq.*": {"queue": "gabi.dlq"},
            "gabi.tasks.health.*": {"queue": "gabi.health"},
            "gabi.tasks.alerts.*": {"queue": "gabi.alerts"},
        },
        
        # Worker
        worker_concurrency=int(os.getenv("GABI_WORKER_CONCURRENCY", "4")),
        worker_max_tasks_per_child=1000,  # Reinicia worker após 1000 tasks (memory leak prevention)
        
        # Result backend
        result_expires=3600 * 24 * 7,  # 7 dias
        result_extended=True,
        
        # Events (monitoring)
        worker_send_task_events=True,
        task_send_sent_event=True,
        
        # Periodic tasks schedule (celerybeat)
        beat_schedule={
            "process-pending-dlq": {
                "task": "gabi.tasks.dlq.process_pending_dlq_task",
                "schedule": 300.0,  # 5 minutes
                "kwargs": {"max_messages": 100},
                "options": {"queue": "gabi.dlq"},
            },
            "health-check": {
                "task": "gabi.tasks.health.health_check_task",
                "schedule": 60.0,  # 1 minute
                "kwargs": {"include_details": False},
                "options": {"queue": "gabi.health"},
            },
        },
    )
    
    # Autodiscover tasks
    app.autodiscover_tasks(["gabi.tasks"])
    
    return app


# Singleton global
celery_app = create_celery_app()


# =============================================================================
# Signals
# =============================================================================

@setup_logging.connect
def setup_celery_logging(**kwargs: Any) -> None:
    """Configura logging para o worker Celery."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


@task_prerun.connect
def task_prerun_handler(task_id: str, task: Any, args: tuple, kwargs: Dict[str, Any], **extras: Any) -> None:
    """Handler executado antes de cada task."""
    logger.info(f"Starting task {task.name}[{task_id}]")


@task_postrun.connect
def task_postrun_handler(task_id: str, task: Any, args: tuple, kwargs: Dict[str, Any], retval: Any, state: str, **extras: Any) -> None:
    """Handler executado após cada task."""
    logger.info(f"Completed task {task.name}[{task_id}] with state {state}")


@task_failure.connect
def task_failure_handler(task_id: str, exception: Exception, args: tuple, kwargs: Dict[str, Any], traceback: Any, einfo: Any, **extras: Any) -> None:
    """Handler executado quando uma task falha."""
    logger.error(f"Task failed: {task_id}", exc_info=exception)


# =============================================================================
# Exports
# =============================================================================

__all__ = ["celery_app", "create_celery_app"]


def main() -> None:
    """Entry point do worker Celery para scripts de console."""
    celery_app.start(
        argv=[
            "celery",
            "-A",
            "gabi.worker",
            "worker",
            "--loglevel=info",
        ]
    )


if __name__ == "__main__":
    main()
