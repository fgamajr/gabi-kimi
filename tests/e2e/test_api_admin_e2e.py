"""Testes E2E para API administrativa.

Testa endpoints administrativos com cliente HTTP real.
"""

from __future__ import annotations

import pytest
from uuid import uuid4

# Skip se não estiver rodando com servidor real
pytestmark = pytest.mark.e2e

# Use --run-e2e flag para executar estes testes
# pytest --run-e2e tests/e2e/


BASE_URL = "http://localhost:8000"
API_PREFIX = "/api/v1"


class TestAdminExecutionsE2E:
    """Testes E2E para endpoints de execuções."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_list_executions_success(self, client):
        """Verifica que GET /admin/executions retorna lista."""
        response = await client.get(f"{API_PREFIX}/admin/executions")
        
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "executions" in data
        assert isinstance(data["executions"], list)
    
    @pytest.mark.asyncio
    async def test_list_executions_with_pagination(self, client):
        """Verifica que paginação funciona."""
        response = await client.get(
            f"{API_PREFIX}/admin/executions?page=1&page_size=10"
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 10
    
    @pytest.mark.asyncio
    async def test_list_executions_with_source_filter(self, client):
        """Verifica que filtro por source_id funciona."""
        response = await client.get(
            f"{API_PREFIX}/admin/executions?source_id=test_source"
        )
        
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_list_executions_with_status_filter(self, client):
        """Verifica que filtro por status funciona."""
        response = await client.get(
            f"{API_PREFIX}/admin/executions?status=success"
        )
        
        assert response.status_code == 200
        data = response.json()
        # Filtra apenas execuções com status success
        for execution in data.get("executions", []):
            assert execution["status"] == "success"
    
    @pytest.mark.asyncio
    async def test_get_execution_not_found(self, client):
        """Verifica que GET /admin/executions/{id} retorna 404."""
        response = await client.get(
            f"{API_PREFIX}/admin/executions/{uuid4()}"
        )
        
        assert response.status_code == 404


class TestAdminDLQE2E:
    """Testes E2E para endpoints de DLQ."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_list_dlq_success(self, client):
        """Verifica que GET /admin/dlq retorna lista."""
        response = await client.get(f"{API_PREFIX}/admin/dlq")
        
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "messages" in data
        assert isinstance(data["messages"], list)
    
    @pytest.mark.asyncio
    async def test_list_dlq_with_status_filter(self, client):
        """Verifica que filtro por status funciona."""
        response = await client.get(
            f"{API_PREFIX}/admin/dlq?status=pending"
        )
        
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_list_dlq_with_source_filter(self, client):
        """Verifica que filtro por source_id funciona."""
        response = await client.get(
            f"{API_PREFIX}/admin/dlq?source_id=test_source"
        )
        
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_list_dlq_includes_status_counts(self, client):
        """Verifica que resposta inclui contagens por status."""
        response = await client.get(f"{API_PREFIX}/admin/dlq")
        
        assert response.status_code == 200
        data = response.json()
        assert "by_status" in data
        assert isinstance(data["by_status"], dict)
    
    @pytest.mark.asyncio
    async def test_retry_dlq_not_found(self, client):
        """Verifica que POST /admin/dlq/{id}/retry retorna 404."""
        response = await client.post(
            f"{API_PREFIX}/admin/dlq/{uuid4()}/retry",
            json={"force": False, "priority": False}
        )
        
        assert response.status_code == 404


class TestAdminStatsE2E:
    """Testes E2E para endpoint de estatísticas."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_get_system_stats_success(self, client):
        """Verifica que GET /admin/stats retorna estatísticas."""
        response = await client.get(f"{API_PREFIX}/admin/stats")
        
        assert response.status_code == 200
        data = response.json()
        assert "stats" in data
        assert "computed_at" in data
    
    @pytest.mark.asyncio
    async def test_system_stats_response_schema(self, client):
        """Verifica schema da resposta de estatísticas."""
        response = await client.get(f"{API_PREFIX}/admin/stats")
        
        assert response.status_code == 200
        data = response.json()
        stats = data.get("stats", {})
        
        # Verifica campos de estatísticas
        stat_fields = [
            "total_documents", "total_sources", "total_chunks",
            "active_sources", "sources_in_error", "dlq_pending",
            "dlq_exhausted", "executions_today", "executions_failed_today"
        ]
        for field in stat_fields:
            assert field in stats, f"Campo de estatística '{field}' ausente"


class TestAdminResponseSchemaE2E:
    """Testes E2E para schemas de resposta administrativa."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_executions_response_schema(self, client):
        """Verifica schema da resposta de execuções."""
        response = await client.get(f"{API_PREFIX}/admin/executions")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verifica campos obrigatórios
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "executions" in data
        
        # Se houver execuções, verifica seus campos
        if data["executions"]:
            execution = data["executions"][0]
            exec_fields = [
                "run_id", "source_id", "status", "trigger",
                "started_at", "stats_summary"
            ]
            for field in exec_fields:
                assert field in execution, f"Campo de execução '{field}' ausente"
    
    @pytest.mark.asyncio
    async def test_dlq_response_schema(self, client):
        """Verifica schema da resposta de DLQ."""
        response = await client.get(f"{API_PREFIX}/admin/dlq")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verifica campos obrigatórios
        assert "total" in data
        assert "by_status" in data
        assert "page" in data
        assert "page_size" in data
        assert "messages" in data
        
        # Se houver mensagens, verifica seus campos
        if data["messages"]:
            message = data["messages"][0]
            msg_fields = [
                "id", "source_id", "url", "error_type",
                "error_message", "status", "retry_count", "max_retries"
            ]
            for field in msg_fields:
                assert field in message, f"Campo de mensagem '{field}' ausente"


class TestAdminValidationE2E:
    """Testes E2E para validação de endpoints administrativos."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_list_executions_invalid_page(self, client):
        """Verifica que página inválida retorna erro."""
        response = await client.get(
            f"{API_PREFIX}/admin/executions?page=0"
        )
        
        assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_list_executions_invalid_page_size(self, client):
        """Verifica que page_size inválido retorna erro."""
        response = await client.get(
            f"{API_PREFIX}/admin/executions?page_size=0"
        )
        
        assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_list_dlq_invalid_page(self, client):
        """Verifica que página inválida retorna erro."""
        response = await client.get(
            f"{API_PREFIX}/admin/dlq?page=0"
        )
        
        assert response.status_code == 422
