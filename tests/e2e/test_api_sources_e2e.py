"""Testes E2E para API de fontes.

Testa endpoints de fontes com cliente HTTP real.
"""

from __future__ import annotations

import pytest

# Skip se não estiver rodando com servidor real
pytestmark = pytest.mark.e2e

# Use --run-e2e flag para executar estes testes
# pytest --run-e2e tests/e2e/


BASE_URL = "http://localhost:8000"
API_PREFIX = "/api/v1"


class TestSourcesE2E:
    """Testes E2E para endpoints de fontes."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_list_sources_success(self, client):
        """Verifica que GET /sources retorna lista de fontes."""
        response = await client.get(f"{API_PREFIX}/sources")
        
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "sources" in data
        assert isinstance(data["sources"], list)
    
    @pytest.mark.asyncio
    async def test_list_sources_with_status_filter(self, client):
        """Verifica que filtro por status funciona."""
        response = await client.get(
            f"{API_PREFIX}/sources?status=active"
        )
        
        assert response.status_code == 200
        data = response.json()
        # Filtra apenas fontes ativas
        for source in data.get("sources", []):
            assert source["status"] == "active"
    
    @pytest.mark.asyncio
    async def test_get_source_not_found(self, client):
        """Verifica que GET /sources/{id} retorna 404 para ID inexistente."""
        response = await client.get(
            f"{API_PREFIX}/sources/NON-EXISTENT-SOURCE"
        )
        
        assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_get_source_status_not_found(self, client):
        """Verifica que GET /sources/{id}/status retorna 404 para ID inexistente."""
        response = await client.get(
            f"{API_PREFIX}/sources/NON-EXISTENT-SOURCE/status"
        )
        
        assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_sync_source_not_found(self, client):
        """Verifica que POST /sources/{id}/sync retorna 404 para ID inexistente."""
        response = await client.post(
            f"{API_PREFIX}/sources/NON-EXISTENT-SOURCE/sync",
            json={"mode": "full", "force": False}
        )
        
        assert response.status_code == 404


class TestSourcesResponseSchemaE2E:
    """Testes E2E para schema de resposta de fontes."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_list_sources_response_schema(self, client):
        """Verifica schema da resposta de listagem."""
        response = await client.get(f"{API_PREFIX}/sources")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verifica campos obrigatórios
        assert "total" in data
        assert "sources" in data
        
        # Se houver fontes, verifica seus campos
        if data["sources"]:
            source = data["sources"][0]
            source_fields = [
                "id", "name", "type", "status", "document_count",
                "is_healthy", "owner_email", "sensitivity"
            ]
            for field in source_fields:
                assert field in source, f"Campo de fonte '{field}' ausente"
    
    @pytest.mark.asyncio
    async def test_source_status_response_schema(self, client):
        """Verifica schema da resposta de status."""
        # Lista fontes primeiro
        list_response = await client.get(f"{API_PREFIX}/sources")
        
        if list_response.status_code == 200:
            data = list_response.json()
            if data.get("sources"):
                source_id = data["sources"][0]["id"]
                
                status_response = await client.get(
                    f"{API_PREFIX}/sources/{source_id}/status"
                )
                
                if status_response.status_code == 200:
                    status_data = status_response.json()
                    status_fields = [
                        "source_id", "status", "is_healthy", "document_count",
                        "consecutive_errors", "success_rate", "checked_at"
                    ]
                    for field in status_fields:
                        assert field in status_data, f"Campo de status '{field}' ausente"


class TestSourcesSyncE2E:
    """Testes E2E para sincronização de fontes."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_sync_source_invalid_mode(self, client):
        """Verifica que modo de sync inválido retorna erro."""
        # Lista fontes primeiro para pegar um ID válido
        list_response = await client.get(f"{API_PREFIX}/sources")
        
        if list_response.status_code == 200:
            data = list_response.json()
            if data.get("sources"):
                source_id = data["sources"][0]["id"]
                
                response = await client.post(
                    f"{API_PREFIX}/sources/{source_id}/sync",
                    json={"mode": "invalid_mode", "force": False}
                )
                
                # Deve retornar erro de validação
                assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_sync_source_disabled_source(self, client):
        """Verifica que sync de fonte desabilitada retorna erro."""
        # Lista fontes para encontrar uma desabilitada
        list_response = await client.get(f"{API_PREFIX}/sources?status=disabled")
        
        if list_response.status_code == 200:
            data = list_response.json()
            if data.get("sources"):
                source_id = data["sources"][0]["id"]
                
                response = await client.post(
                    f"{API_PREFIX}/sources/{source_id}/sync",
                    json={"mode": "full", "force": False}
                )
                
                assert response.status_code == 400
