"""Tests for health check tasks.

Verifica tasks de verificação de saúde dos serviços.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from gabi.tasks.health import (
    HealthResult,
    _check_celery,
    _check_elasticsearch,
    _check_postgresql,
    _check_redis,
    _check_single_service,
    _check_tei,
    _run_health_check,
    check_service_task,
    health_check_task,
)


class TestHealthCheckTask:
    """Test suite para health_check_task."""
    
    def test_task_registered(self):
        """Task deve estar registrada no Celery."""
        from gabi.worker import celery_app
        
        assert "gabi.tasks.health.health_check_task" in celery_app.tasks
    
    def test_task_configuration(self):
        """Verifica configuração da task."""
        task = health_check_task
        
        assert task.name == "gabi.tasks.health.health_check_task"
        assert task.queue == "gabi.health"
        assert task.max_retries == 0
        assert task.time_limit == 60
    
    @patch("gabi.tasks.health._run_health_check")
    def test_health_check_all_healthy(self, mock_check):
        """Status geral healthy quando todos saudáveis."""
        mock_check.return_value = {
            "services": {
                "postgresql": {"status": "healthy"},
                "redis": {"status": "healthy"},
            },
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        
        result = health_check_task.run(include_details=False)
        
        assert result["overall_status"] == "healthy"
    
    @patch("gabi.tasks.health._run_health_check")
    def test_health_check_some_unhealthy(self, mock_check):
        """Status geral unhealthy quando algum falha."""
        mock_check.return_value = {
            "services": {
                "postgresql": {"status": "healthy"},
                "redis": {"status": "unhealthy"},
            },
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        
        result = health_check_task.run(include_details=False)
        
        assert result["overall_status"] == "unhealthy"
    
    @patch("gabi.tasks.health._run_health_check")
    def test_health_check_exception(self, mock_check):
        """Trata exceção no health check."""
        mock_check.side_effect = Exception("Check failed")
        
        result = health_check_task.run()
        
        assert result["overall_status"] == "error"
        assert "error" in result


class TestCheckServiceTask:
    """Test suite para check_service_task."""
    
    def test_task_registered(self):
        """Task deve estar registrada."""
        from gabi.worker import celery_app
        
        assert "gabi.tasks.health.check_service_task" in celery_app.tasks
    
    def test_task_configuration(self):
        """Verifica configuração."""
        task = check_service_task
        
        assert task.name == "gabi.tasks.health.check_service_task"
        assert task.queue == "gabi.health"
        assert task.max_retries == 2
    
    @patch("gabi.tasks.health._check_single_service")
    def test_check_postgresql(self, mock_check):
        """Verifica serviço PostgreSQL."""
        mock_check.return_value = {
            "name": "postgresql",
            "status": "healthy",
        }
        
        result = check_service_task.run("postgresql")
        
        assert result["name"] == "postgresql"
        assert result["status"] == "healthy"


class TestRunHealthCheck:
    """Test suite para _run_health_check."""
    
    @pytest.mark.asyncio
    async def test_all_checks_execute(self):
        """Todos os checks devem ser executados."""
        with patch("gabi.tasks.health._check_postgresql") as mock_pg, \
             patch("gabi.tasks.health._check_redis") as mock_redis, \
             patch("gabi.tasks.health._check_elasticsearch") as mock_es, \
             patch("gabi.tasks.health._check_tei") as mock_tei, \
             patch("gabi.tasks.health._check_celery") as mock_celery:
            
            mock_pg.return_value = HealthResult("postgresql", "healthy", 10.0)
            mock_redis.return_value = HealthResult("redis", "healthy", 5.0)
            mock_es.return_value = HealthResult("elasticsearch", "healthy", 20.0)
            mock_tei.return_value = HealthResult("tei", "healthy", 15.0)
            mock_celery.return_value = HealthResult("celery", "healthy", 8.0)
            
            result = await _run_health_check(include_details=False)
            
            assert "services" in result
            assert result["services"]["postgresql"]["status"] == "healthy"
            assert result["services"]["redis"]["status"] == "healthy"
            assert "checked_at" in result
            assert "check_duration_ms" in result
    
    @pytest.mark.asyncio
    async def test_exception_handling(self):
        """Trata exceções em checks individuais."""
        with patch("gabi.tasks.health._check_postgresql") as mock_pg, \
             patch("gabi.tasks.health._check_redis") as mock_redis, \
             patch("gabi.tasks.health._check_elasticsearch") as mock_es, \
             patch("gabi.tasks.health._check_tei") as mock_tei, \
             patch("gabi.tasks.health._check_celery") as mock_celery:
            
            mock_pg.return_value = HealthResult("postgresql", "healthy", 10.0)
            mock_redis.side_effect = Exception("Redis error")
            mock_es.return_value = HealthResult("elasticsearch", "healthy", 20.0)
            mock_tei.return_value = HealthResult("tei", "healthy", 15.0)
            mock_celery.return_value = HealthResult("celery", "healthy", 8.0)
            
            result = await _run_health_check(include_details=False)
            
            # Deve continuar mesmo com exceção em um check
            assert "postgresql" in result["services"]


class TestCheckSingleService:
    """Test suite para _check_single_service."""
    
    @pytest.mark.asyncio
    async def test_check_postgresql(self):
        """Deve retornar status do PostgreSQL."""
        with patch("gabi.tasks.health._check_postgresql") as mock_check:
            mock_check.return_value = HealthResult(
                "postgresql", "healthy", 10.0, "OK", {"version": "14"}
            )
            
            result = await _check_single_service("postgresql")
            
            assert result["name"] == "postgresql"
            assert result["status"] == "healthy"
            assert result["details"]["version"] == "14"
    
    @pytest.mark.asyncio
    async def test_unknown_service(self):
        """Deve retornar unknown para serviço desconhecido."""
        result = await _check_single_service("unknown_service")
        
        assert result["name"] == "unknown_service"
        assert result["status"] == "unknown"


class TestCheckPostgreSQL:
    """Test suite para _check_postgresql."""
    
    @pytest.mark.asyncio
    async def test_postgresql_healthy(self):
        """PostgreSQL saudável."""
        with patch("gabi.tasks.health.create_async_engine") as mock_engine:
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=None)
            
            mock_engine_instance = MagicMock()
            mock_engine_instance.connect = MagicMock(return_value=mock_conn)
            mock_engine_instance.dispose = AsyncMock()
            mock_engine.return_value = mock_engine_instance
            
            result = await _check_postgresql(include_details=False)
            
            assert result.name == "postgresql"
            assert result.status == "healthy"
            assert result.response_time_ms >= 0
    
    @pytest.mark.asyncio
    async def test_postgresql_unhealthy(self):
        """PostgreSQL não responde."""
        with patch("gabi.tasks.health.create_async_engine") as mock_engine:
            mock_engine.side_effect = Exception("Connection refused")
            
            result = await _check_postgresql(include_details=False)
            
            assert result.name == "postgresql"
            assert result.status == "unhealthy"
            assert "Connection refused" in result.message


class TestCheckRedis:
    """Test suite para _check_redis."""
    
    @pytest.mark.asyncio
    async def test_redis_healthy(self):
        """Redis saudável."""
        with patch("gabi.tasks.health.redis.from_url") as mock_from_url:
            mock_client = AsyncMock()
            mock_client.ping.return_value = True
            mock_client.info.return_value = {
                "redis_version": "7.0",
                "used_memory": 1024 * 1024,
                "connected_clients": 10,
            }
            mock_client.dbsize.return_value = 100
            mock_client.close = AsyncMock()
            mock_from_url.return_value = mock_client
            
            result = await _check_redis(include_details=False)
            
            assert result.name == "redis"
            assert result.status == "healthy"
            assert result.message == "Redis is responding"
    
    @pytest.mark.asyncio
    async def test_redis_unhealthy(self):
        """Redis não responde."""
        with patch("gabi.tasks.health.redis.from_url") as mock_from_url:
            mock_client = AsyncMock()
            mock_client.ping.return_value = False
            mock_client.close = AsyncMock()
            mock_from_url.return_value = mock_client
            
            result = await _check_redis(include_details=False)
            
            assert result.name == "redis"
            assert result.status == "unhealthy"
    
    @pytest.mark.asyncio
    async def test_redis_exception(self):
        """Exceção na conexão com Redis."""
        with patch("gabi.tasks.health.redis.from_url") as mock_from_url:
            mock_from_url.side_effect = Exception("Connection refused")
            
            result = await _check_redis(include_details=False)
            
            assert result.name == "redis"
            assert result.status == "unhealthy"


class TestCheckElasticsearch:
    """Test suite para _check_elasticsearch."""
    
    @pytest.mark.asyncio
    async def test_elasticsearch_green(self):
        """Cluster ES status green."""
        with patch("gabi.tasks.health.AsyncElasticsearch") as MockES:
            mock_es = AsyncMock()
            mock_es.cluster.health.return_value = {
                "status": "green",
                "number_of_nodes": 3,
                "active_shards": 10,
            }
            mock_es.info.return_value = {
                "version": {"number": "8.0.0"},
                "cluster_name": "gabi",
            }
            mock_es.close = AsyncMock()
            MockES.return_value = mock_es
            
            result = await _check_elasticsearch(include_details=False)
            
            assert result.name == "elasticsearch"
            assert result.status == "healthy"
    
    @pytest.mark.asyncio
    async def test_elasticsearch_yellow(self):
        """Cluster ES status yellow (degraded)."""
        with patch("gabi.tasks.health.AsyncElasticsearch") as MockES:
            mock_es = AsyncMock()
            mock_es.cluster.health.return_value = {
                "status": "yellow",
                "number_of_nodes": 3,
                "active_shards": 10,
            }
            mock_es.close = AsyncMock()
            MockES.return_value = mock_es
            
            result = await _check_elasticsearch(include_details=False)
            
            assert result.name == "elasticsearch"
            assert result.status == "degraded"
    
    @pytest.mark.asyncio
    async def test_elasticsearch_red(self):
        """Cluster ES status red (unhealthy)."""
        with patch("gabi.tasks.health.AsyncElasticsearch") as MockES:
            mock_es = AsyncMock()
            mock_es.cluster.health.return_value = {
                "status": "red",
                "number_of_nodes": 1,
                "active_shards": 0,
            }
            mock_es.close = AsyncMock()
            MockES.return_value = mock_es
            
            result = await _check_elasticsearch(include_details=False)
            
            assert result.name == "elasticsearch"
            assert result.status == "unhealthy"


class TestCheckTEI:
    """Test suite para _check_tei."""
    
    @pytest.mark.asyncio
    async def test_tei_healthy(self):
        """TEI respondendo corretamente."""
        with patch("aiohttp.ClientSession") as MockSession:
            mock_session = MagicMock()
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json.return_value = {
                "model_id": "sentence-transformers/all-MiniLM-L6-v2",
            }
            mock_cm = AsyncMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session.get.return_value = mock_cm
            MockSession.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            MockSession.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await _check_tei(include_details=False)
            
            assert result.name == "tei"
            assert result.status == "healthy"
    
    @pytest.mark.asyncio
    async def test_tei_timeout(self):
        """TEI timeout."""
        with patch("aiohttp.ClientSession") as MockSession:
            mock_session = MagicMock()
            mock_cm = AsyncMock()
            mock_cm.__aenter__ = AsyncMock(side_effect=TimeoutError())
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_session.get.return_value = mock_cm
            MockSession.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            MockSession.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await _check_tei(include_details=False)
            
            assert result.name == "tei"
            assert result.status == "unhealthy"
            assert "timed out" in result.message


class TestCheckCelery:
    """Test suite para _check_celery."""
    
    @pytest.mark.asyncio
    async def test_celery_healthy(self):
        """Workers Celery respondendo."""
        with patch("gabi.tasks.health.Inspect") as MockInspect:
            mock_inspect = MagicMock()
            mock_inspect.ping.return_value = {
                "worker1@host": {"ok": "pong"},
                "worker2@host": {"ok": "pong"},
            }
            mock_inspect.stats.return_value = {
                "worker1@host": {"total": {"tasks": 100}},
            }
            MockInspect.return_value = mock_inspect
            
            result = await _check_celery(include_details=False)
            
            assert result.name == "celery"
            assert result.status == "healthy"
            assert "2" in result.message
    
    @pytest.mark.asyncio
    async def test_celery_no_workers(self):
        """Nenhum worker respondendo."""
        with patch("gabi.tasks.health.Inspect") as MockInspect:
            mock_inspect = MagicMock()
            mock_inspect.ping.return_value = None
            MockInspect.return_value = mock_inspect
            
            result = await _check_celery(include_details=False)
            
            assert result.name == "celery"
            assert result.status == "unhealthy"
