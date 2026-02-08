"""Tests for Celery worker configuration.

Verifica configurações críticas do worker Celery.
"""

import pytest

from gabi.worker import celery_app, create_celery_app


class TestCeleryApp:
    """Test suite para configuração do Celery."""
    
    def test_app_exists(self):
        """Celery app deve estar disponível como singleton."""
        assert celery_app is not None
        assert celery_app.main == "gabi"
    
    def test_critical_settings(self):
        """Verifica configurações críticas solicitadas."""
        # task_acks_late = True (garante processamento completo)
        assert celery_app.conf.task_acks_late is True
        
        # worker_prefetch_multiplier = 1 (evita prefetch, distribuição justa)
        assert celery_app.conf.worker_prefetch_multiplier == 1
        
        # visibility_timeout = 43200 (12 horas)
        assert celery_app.conf.broker_transport_options["visibility_timeout"] == 43200
    
    def test_serialization_config(self):
        """Configuração de serialização."""
        assert celery_app.conf.task_serializer == "json"
        assert "json" in celery_app.conf.accept_content
        assert celery_app.conf.result_serializer == "json"
    
    def test_timezone_config(self):
        """Configuração de timezone."""
        assert celery_app.conf.timezone == "America/Sao_Paulo"
        assert celery_app.conf.enable_utc is True
    
    def test_task_time_limits(self):
        """Limites de tempo para tasks."""
        # Hard limit: 12 horas
        assert celery_app.conf.task_time_limit == 3600 * 12
        
        # Soft limit: 11 horas
        assert celery_app.conf.task_soft_time_limit == 3600 * 11
    
    def test_default_retry_config(self):
        """Configuração padrão de retry."""
        assert celery_app.conf.task_default_retry_delay == 60
        assert celery_app.conf.task_max_retries == 5
    
    def test_default_queue(self):
        """Fila padrão configurada."""
        assert celery_app.conf.task_default_queue == "gabi.default"
    
    def test_queues_defined(self):
        """Todas as filas devem estar definidas."""
        expected_queues = [
            "gabi.default",
            "gabi.sync",
            "gabi.dlq",
            "gabi.health",
            "gabi.alerts",
        ]
        
        for queue in expected_queues:
            assert queue in celery_app.conf.task_queues
    
    def test_task_routes(self):
        """Routes para tasks definidos."""
        routes = celery_app.conf.task_routes
        
        assert "gabi.tasks.sync.*" in routes
        assert routes["gabi.tasks.sync.*"]["queue"] == "gabi.sync"
        
        assert "gabi.tasks.dlq.*" in routes
        assert routes["gabi.tasks.dlq.*"]["queue"] == "gabi.dlq"
        
        assert "gabi.tasks.health.*" in routes
        assert routes["gabi.tasks.health.*"]["queue"] == "gabi.health"
        
        assert "gabi.tasks.alerts.*" in routes
        assert routes["gabi.tasks.alerts.*"]["queue"] == "gabi.alerts"
    
    def test_result_backend_config(self):
        """Configuração do result backend."""
        # Expiração: 7 dias
        assert celery_app.conf.result_expires == 3600 * 24 * 7
        assert celery_app.conf.result_extended is True
    
    def test_worker_max_tasks_per_child(self):
        """Worker reinicia após N tasks para prevenir memory leaks."""
        assert celery_app.conf.worker_max_tasks_per_child == 1000
    
    def test_events_enabled(self):
        """Eventos habilitados para monitoring."""
        assert celery_app.conf.worker_send_task_events is True
        assert celery_app.conf.task_send_sent_event is True


class TestCreateCeleryApp:
    """Test suite para factory de app Celery."""
    
    def test_create_app(self):
        """Deve criar nova instância de app."""
        app = create_celery_app()
        
        assert app is not None
        assert app.main == "gabi"
        assert app.conf.task_acks_late is True
    
    def test_app_isolation(self):
        """Apps criadas devem ser independentes."""
        app1 = create_celery_app()
        app2 = create_celery_app()
        
        # Devem ser instâncias diferentes
        assert app1 is not app2
        
        # Mas com mesma configuração
        assert app1.conf.task_acks_late == app2.conf.task_acks_late


class TestTaskDiscovery:
    """Test suite para autodiscovery de tasks."""
    
    def test_tasks_registered(self):
        """Tasks devem estar registradas no app."""
        expected_tasks = [
            "gabi.tasks.sync.sync_source_task",
            "gabi.tasks.sync.process_document_task",
            "gabi.tasks.dlq.retry_dlq_task",
            "gabi.tasks.dlq.process_pending_dlq_task",
            "gabi.tasks.dlq.resolve_dlq_task",
            "gabi.tasks.dlq.get_dlq_stats_task",
            "gabi.tasks.health.health_check_task",
            "gabi.tasks.health.check_service_task",
            "gabi.tasks.alerts.send_alert_task",
            "gabi.tasks.alerts.send_alert_to_channel_task",
            "gabi.tasks.alerts.batch_send_alerts_task",
        ]
        
        registered_tasks = celery_app.tasks.keys()
        
        for task in expected_tasks:
            assert task in registered_tasks, f"Task {task} not registered"
