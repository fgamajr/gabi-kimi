"""Testes E2E para API de health check.

Testa endpoints de health check com cliente HTTP real.
"""

from __future__ import annotations

import pytest

# Skip se não estiver rodando com servidor real
pytestmark = pytest.mark.e2e

# Use --run-e2e flag para executar estes testes
# pytest --run-e2e tests/e2e/


BASE_URL = "http://localhost:8000"


class TestHealthE2E:
    """Testes E2E para endpoints de health check."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_health_check_success(self, client):
        """Verifica que GET /health retorna status."""
        response = await client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] in ["healthy", "degraded", "unhealthy"]
    
    @pytest.mark.asyncio
    async def test_health_check_response_schema(self, client):
        """Verifica schema da resposta de health."""
        response = await client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verifica campos obrigatórios
        required_fields = [
            "status", "version", "timestamp", "uptime_seconds",
            "components", "environment"
        ]
        for field in required_fields:
            assert field in data, f"Campo obrigatório '{field}' ausente"
        
        # Verifica schema dos componentes
        for component in data.get("components", []):
            comp_fields = ["name", "status", "response_time_ms", "message"]
            for field in comp_fields:
                assert field in component, f"Campo de componente '{field}' ausente"
    
    @pytest.mark.asyncio
    async def test_health_check_includes_database(self, client):
        """Verifica que health check inclui componente database."""
        response = await client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        
        component_names = [c["name"] for c in data.get("components", [])]
        assert "database" in component_names, "Componente 'database' ausente"


class TestLivenessE2E:
    """Testes E2E para endpoint de liveness."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_liveness_check_success(self, client):
        """Verifica que GET /health/live retorna alive."""
        response = await client.get("/health/live")
        
        assert response.status_code == 200
        data = response.json()
        assert "alive" in data
        assert data["alive"] is True
    
    @pytest.mark.asyncio
    async def test_liveness_check_response_schema(self, client):
        """Verifica schema da resposta de liveness."""
        response = await client.get("/health/live")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "alive" in data
        assert isinstance(data["alive"], bool)


class TestReadinessE2E:
    """Testes E2E para endpoint de readiness."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_readiness_check_success(self, client):
        """Verifica que GET /health/ready retorna readiness."""
        response = await client.get("/health/ready")
        
        # Pode ser 200 (ready) ou 503 (not ready)
        assert response.status_code in [200, 503]
        
        data = response.json()
        assert "ready" in data
        assert isinstance(data["ready"], bool)
    
    @pytest.mark.asyncio
    async def test_readiness_check_response_schema(self, client):
        """Verifica schema da resposta de readiness."""
        response = await client.get("/health/ready")
        
        assert response.status_code in [200, 503]
        data = response.json()
        
        # Verifica campos obrigatórios
        required_fields = ["ready", "timestamp", "checks"]
        for field in required_fields:
            assert field in data, f"Campo obrigatório '{field}' ausente"
        
        # Verifica schema dos checks
        for check in data.get("checks", []):
            check_fields = ["name", "ready", "critical", "message", "response_time_ms"]
            for field in check_fields:
                assert field in check, f"Campo de check '{field}' ausente"
    
    @pytest.mark.asyncio
    async def test_readiness_check_includes_database(self, client):
        """Verifica que readiness check inclui database."""
        response = await client.get("/health/ready")
        
        assert response.status_code in [200, 503]
        data = response.json()
        
        check_names = [c["name"] for c in data.get("checks", [])]
        assert "database" in check_names, "Check 'database' ausente"
    
    @pytest.mark.asyncio
    async def test_readiness_database_is_critical(self, client):
        """Verifica que check de database é marcado como critical."""
        response = await client.get("/health/ready")
        
        assert response.status_code in [200, 503]
        data = response.json()
        
        db_check = next(
            (c for c in data.get("checks", []) if c["name"] == "database"),
            None
        )
        assert db_check is not None
        assert db_check["critical"] is True


class TestHealthPerformanceE2E:
    """Testes E2E para performance de health check."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_health_check_response_time(self, client):
        """Verifica que health check responde rapidamente."""
        import time
        
        start = time.time()
        response = await client.get("/health")
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        # Deve responder em menos de 1 segundo
        assert elapsed < 1000, f"Health check demorou {elapsed:.0f}ms"
    
    @pytest.mark.asyncio
    async def test_liveness_check_response_time(self, client):
        """Verifica que liveness check responde rapidamente."""
        import time
        
        start = time.time()
        response = await client.get("/health/live")
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        # Deve responder em menos de 100ms
        assert elapsed < 100, f"Liveness check demorou {elapsed:.0f}ms"
    
    @pytest.mark.asyncio
    async def test_readiness_check_response_time(self, client):
        """Verifica que readiness check responde rapidamente."""
        import time
        
        start = time.time()
        response = await client.get("/health/ready")
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code in [200, 503]
        # Deve responder em menos de 1 segundo
        assert elapsed < 1000, f"Readiness check demorou {elapsed:.0f}ms"


class TestHealthConsistencyE2E:
    """Testes E2E para consistência de health check."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_health_check_consistent_uptime(self, client):
        """Verifica que uptime aumenta consistentemente."""
        response1 = await client.get("/health")
        data1 = response1.json()
        uptime1 = data1["uptime_seconds"]
        
        # Pequena pausa
        import asyncio
        await asyncio.sleep(0.1)
        
        response2 = await client.get("/health")
        data2 = response2.json()
        uptime2 = data2["uptime_seconds"]
        
        # Uptime deve ter aumentado
        assert uptime2 > uptime1
    
    @pytest.mark.asyncio
    async def test_health_check_valid_timestamp(self, client):
        """Verifica que timestamp é válido."""
        from datetime import datetime
        
        response = await client.get("/health")
        data = response.json()
        
        # Timestamp deve ser parseável
        try:
            timestamp = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
            assert timestamp <= datetime.utcnow()
        except (ValueError, KeyError):
            pytest.fail("Timestamp inválido ou ausente")
    
    @pytest.mark.asyncio
    async def test_liveness_always_true(self, client):
        """Verifica que liveness sempre retorna True."""
        # Chama múltiplas vezes
        for _ in range(3):
            response = await client.get("/health/live")
            data = response.json()
            assert data["alive"] is True


class TestHealthStatusValuesE2E:
    """Testes E2E para valores de status de health."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_health_status_valid_values(self, client):
        """Verifica que status é um valor válido."""
        valid_statuses = ["healthy", "degraded", "unhealthy"]
        
        response = await client.get("/health")
        data = response.json()
        
        assert data["status"] in valid_statuses
    
    @pytest.mark.asyncio
    async def test_component_status_valid_values(self, client):
        """Verifica que status de componentes são valores válidos."""
        valid_statuses = ["healthy", "degraded", "unhealthy"]
        
        response = await client.get("/health")
        data = response.json()
        
        for component in data.get("components", []):
            assert component["status"] in valid_statuses
    
    @pytest.mark.asyncio
    async def test_readiness_status_valid_values(self, client):
        """Verifica que ready é um booleano."""
        response = await client.get("/health/ready")
        data = response.json()
        
        assert isinstance(data["ready"], bool)
        
        for check in data.get("checks", []):
            assert isinstance(check["ready"], bool)
