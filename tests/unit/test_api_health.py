"""Testes unitários para API de health check.

Testa endpoints de health check da API REST.
"""

from __future__ import annotations

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from gabi.api.health import (
    health_check,
    liveness_check,
    readiness_check,
    check_database,
)
from gabi.schemas.health import (
    HealthResponse,
    HealthStatus,
    LivenessResponse,
    ReadinessResponse,
    ComponentStatus,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_db_session():
    """Mock de sessão do banco."""
    session = AsyncMock(spec=AsyncSession)
    return session


# =============================================================================
# Database Check Tests
# =============================================================================

class TestCheckDatabase:
    """Testes para check_database."""

    @pytest.mark.asyncio
    async def test_check_database_returns_healthy(self, mock_db_session):
        """Verifica que check_database retorna healthy quando DB OK."""
        mock_result = MagicMock()
        mock_result.scalar_one = AsyncMock(return_value=1)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = await check_database(mock_db_session)

        assert response.name == "database"
        assert response.status == HealthStatus.HEALTHY
        assert "PostgreSQL responding" in response.message
    
    @pytest.mark.asyncio
    async def test_check_database_returns_unhealthy_on_error(self, mock_db_session):
        """Verifica que check_database retorna unhealthy em erro."""
        mock_db_session.execute = AsyncMock(side_effect=Exception("DB Error"))
        
        response = await check_database(mock_db_session)
        
        assert response.name == "database"
        assert response.status == HealthStatus.UNHEALTHY
        assert "error" in response.message.lower()
    
    @pytest.mark.asyncio
    async def test_check_database_includes_response_time(self, mock_db_session):
        """Verifica que check_database inclui response_time_ms."""
        mock_result = MagicMock()
        mock_result.scalar_one = AsyncMock(return_value=1)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = await check_database(mock_db_session)

        assert response.response_time_ms is not None
        assert response.response_time_ms >= 0


# =============================================================================
# Health Check Tests
# =============================================================================

class TestHealthCheck:
    """Testes para health_check."""

    @pytest.mark.asyncio
    async def test_health_check_returns_response(self, mock_db_session):
        """Verifica que health_check retorna HealthResponse."""
        mock_result = MagicMock()
        mock_result.scalar_one = AsyncMock(return_value=1)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        # Mock check functions to return healthy status directly
        mock_db_status = ComponentStatus(
            name="database",
            status=HealthStatus.HEALTHY,
            response_time_ms=5.0,
            message="PostgreSQL responding",
        )
        mock_es_status = ComponentStatus(
            name="elasticsearch",
            status=HealthStatus.HEALTHY,
            response_time_ms=10.0,
            message="Elasticsearch 8.0.0 responding",
        )
        mock_redis_status = ComponentStatus(
            name="redis",
            status=HealthStatus.HEALTHY,
            response_time_ms=2.0,
            message="Redis responding",
        )

        with patch("gabi.api.health.check_database", return_value=mock_db_status), \
             patch("gabi.api.health.check_elasticsearch", return_value=mock_es_status), \
             patch("gabi.api.health.check_redis", return_value=mock_redis_status):
            response = await health_check(db=mock_db_session)

        assert isinstance(response, HealthResponse)
        assert response.status == HealthStatus.HEALTHY
        assert response.version is not None
        assert response.timestamp is not None
        assert response.uptime_seconds is not None
        assert len(response.components) > 0

    @pytest.mark.asyncio
    async def test_health_check_returns_unhealthy_on_db_error(self, mock_db_session):
        """Verifica que health_check retorna unhealthy em erro do DB."""
        mock_db_session.execute = AsyncMock(side_effect=Exception("DB Error"))

        # Mock ES and Redis as healthy
        mock_es_client = AsyncMock()
        mock_es_client.info = AsyncMock(return_value={"version": {"number": "8.0.0"}})

        mock_redis_client = AsyncMock()
        mock_redis_client.ping = AsyncMock(return_value=True)

        with patch("gabi.db.get_es_client", return_value=mock_es_client), \
             patch("gabi.db.get_redis_client", return_value=mock_redis_client):
            response = await health_check(db=mock_db_session)

        assert response.status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_on_partial_failure(self, mock_db_session):
        """Verifica que health_check pode retornar degraded."""
        # Este teste verifica a lógica de degraded quando componentes não-críticos falham
        mock_result = MagicMock()
        mock_result.scalar_one = AsyncMock(return_value=1)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        # Mock ES as healthy and Redis as error to get partial failure
        mock_es_client = AsyncMock()
        mock_es_client.info = AsyncMock(return_value={"version": {"number": "8.0.0"}})

        mock_redis_client = AsyncMock()
        mock_redis_client.ping = AsyncMock(side_effect=Exception("Redis Error"))

        with patch("gabi.db.get_es_client", return_value=mock_es_client), \
             patch("gabi.db.get_redis_client", return_value=mock_redis_client):
            response = await health_check(db=mock_db_session)

        # With DB and ES healthy but Redis down, overall should be DEGRADED
        # (since Redis is non-critical, but still affects health status)
        assert response.status == HealthStatus.DEGRADED


# =============================================================================
# Liveness Check Tests
# =============================================================================

class TestLivenessCheck:
    """Testes para liveness_check."""
    
    @pytest.mark.asyncio
    async def test_liveness_check_returns_alive(self):
        """Verifica que liveness_check retorna alive=True."""
        response = await liveness_check()
        
        assert isinstance(response, LivenessResponse)
        assert response.alive is True
    
    @pytest.mark.asyncio
    async def test_liveness_check_does_not_require_db(self):
        """Verifica que liveness_check não requer acesso ao DB."""
        # Liveness não deve acessar o banco
        response = await liveness_check()
        
        assert response.alive is True


# =============================================================================
# Readiness Check Tests
# =============================================================================

class TestReadinessCheck:
    """Testes para readiness_check."""
    
    @pytest.mark.asyncio
    async def test_readiness_check_returns_ready_when_db_ok(self, mock_db_session):
        """Verifica que readiness_check retorna ready=True quando DB OK."""
        mock_result = MagicMock()
        mock_result.scalar_one = AsyncMock(return_value=1)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        # Mock ES and Redis clients
        mock_es_client = AsyncMock()
        mock_es_client.info = AsyncMock(return_value={"version": {"number": "8.0.0"}})

        mock_redis_client = AsyncMock()
        mock_redis_client.ping = AsyncMock(return_value=True)

        with patch("gabi.db.get_es_client", return_value=mock_es_client), \
             patch("gabi.db.get_redis_client", return_value=mock_redis_client):
            response = await readiness_check(db=mock_db_session)

        assert isinstance(response, ReadinessResponse)
        assert response.ready is True
        assert len(response.checks) > 0
    
    @pytest.mark.asyncio
    async def test_readiness_check_returns_not_ready_on_db_error(self, mock_db_session):
        """Verifica que readiness_check retorna ready=False em erro do DB."""
        mock_db_session.execute = AsyncMock(side_effect=Exception("DB Error"))

        # Mock ES and Redis clients
        mock_es_client = AsyncMock()
        mock_es_client.info = AsyncMock(return_value={"version": {"number": "8.0.0"}})

        mock_redis_client = AsyncMock()
        mock_redis_client.ping = AsyncMock(return_value=True)

        with patch("gabi.db.get_es_client", return_value=mock_es_client), \
             patch("gabi.db.get_redis_client", return_value=mock_redis_client):
            response = await readiness_check(db=mock_db_session)

        assert response.ready is False
        assert len(response.checks) > 0
    
    @pytest.mark.asyncio
    async def test_readiness_check_database_is_critical(self, mock_db_session):
        """Verifica que o check de database é marcado como critical."""
        mock_result = MagicMock()
        mock_result.scalar_one = AsyncMock(return_value=1)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        # Mock ES and Redis clients
        mock_es_client = AsyncMock()
        mock_es_client.info = AsyncMock(return_value={"version": {"number": "8.0.0"}})

        mock_redis_client = AsyncMock()
        mock_redis_client.ping = AsyncMock(return_value=True)

        with patch("gabi.db.get_es_client", return_value=mock_es_client), \
             patch("gabi.db.get_redis_client", return_value=mock_redis_client):
            response = await readiness_check(db=mock_db_session)

        db_check = next(c for c in response.checks if c.name == "database")
        assert db_check.critical is True
    
    @pytest.mark.asyncio
    async def test_readiness_check_includes_response_time(self, mock_db_session):
        """Verifica que readiness_check inclui response_time_ms."""
        mock_result = MagicMock()
        mock_result.scalar_one = AsyncMock(return_value=1)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        # Mock ES and Redis clients
        mock_es_client = AsyncMock()
        mock_es_client.info = AsyncMock(return_value={"version": {"number": "8.0.0"}})

        mock_redis_client = AsyncMock()
        mock_redis_client.ping = AsyncMock(return_value=True)

        with patch("gabi.db.get_es_client", return_value=mock_es_client), \
             patch("gabi.db.get_redis_client", return_value=mock_redis_client):
            response = await readiness_check(db=mock_db_session)

        db_check = next(c for c in response.checks if c.name == "database")
        assert db_check.response_time_ms is not None
        assert db_check.response_time_ms >= 0


# =============================================================================
# Health Response Tests
# =============================================================================

class TestHealthResponse:
    """Testes para schemas de health."""
    
    def test_health_response_creation(self):
        """Verifica criação de HealthResponse."""
        from gabi.schemas.health import ComponentStatus
        
        response = HealthResponse(
            status=HealthStatus.HEALTHY,
            version="1.0.0",
            timestamp=datetime.utcnow(),
            uptime_seconds=3600.5,
            components=[
                ComponentStatus(
                    name="database",
                    status=HealthStatus.HEALTHY,
                    response_time_ms=5.0,
                    message="OK"
                )
            ],
            environment="test"
        )
        
        assert response.status == HealthStatus.HEALTHY
        assert response.version == "1.0.0"
        assert len(response.components) == 1
    
    def test_liveness_response_creation(self):
        """Verifica criação de LivenessResponse."""
        response = LivenessResponse(alive=True)
        assert response.alive is True
    
    def test_readiness_response_creation(self):
        """Verifica criação de ReadinessResponse."""
        from gabi.schemas.health import ReadinessCheck
        
        response = ReadinessResponse(
            ready=True,
            timestamp=datetime.utcnow(),
            checks=[
                ReadinessCheck(
                    name="database",
                    ready=True,
                    critical=True,
                    message="OK",
                    response_time_ms=5.0,
                )
            ]
        )
        
        assert response.ready is True
        assert len(response.checks) == 1


# =============================================================================
# Health Status Enum Tests
# =============================================================================

class TestHealthStatus:
    """Testes para HealthStatus enum."""
    
    def test_health_status_values(self):
        """Verifica valores do enum HealthStatus."""
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"
    
    def test_health_status_comparison(self):
        """Verifica comparação de HealthStatus."""
        assert HealthStatus.HEALTHY != HealthStatus.UNHEALTHY
        assert HealthStatus.HEALTHY == HealthStatus.HEALTHY
