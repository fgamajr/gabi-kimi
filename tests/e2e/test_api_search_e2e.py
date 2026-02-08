"""Testes E2E para API de busca.

Testa endpoints de busca com cliente HTTP real.
"""

from __future__ import annotations

import pytest

# Skip se não estiver rodando com servidor real
pytestmark = pytest.mark.e2e

# Use --run-e2e flag para executar estes testes
# pytest --run-e2e tests/e2e/


BASE_URL = "http://localhost:8000"
API_PREFIX = "/api/v1"


class TestSearchE2E:
    """Testes E2E para endpoints de busca."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_search_success(self, client):
        """Verifica que POST /search retorna resultados."""
        response = await client.post(
            f"{API_PREFIX}/search/",
            json={"query": "licitação", "limit": 10}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "query" in data
        assert "total" in data
        assert "hits" in data
        assert isinstance(data["hits"], list)
    
    @pytest.mark.asyncio
    async def test_search_with_limit(self, client):
        """Verifica que limite de resultados funciona."""
        response = await client.post(
            f"{API_PREFIX}/search/",
            json={"query": "test", "limit": 5}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["hits"]) <= 5
    
    @pytest.mark.asyncio
    async def test_search_with_offset(self, client):
        """Verifica que offset funciona."""
        response = await client.post(
            f"{API_PREFIX}/search/",
            json={"query": "test", "limit": 10, "offset": 10}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 0
    
    @pytest.mark.asyncio
    async def test_search_with_source_filter(self, client):
        """Verifica que filtro por sources funciona."""
        response = await client.post(
            f"{API_PREFIX}/search/",
            json={
                "query": "test",
                "sources": ["tcu_acordaos"]
            }
        )
        
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_search_with_filters(self, client):
        """Verifica que filtros adicionais funcionam."""
        response = await client.post(
            f"{API_PREFIX}/search/",
            json={
                "query": "test",
                "filters": {"metadata.year": 2024}
            }
        )
        
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_search_empty_query_returns_error(self, client):
        """Verifica que query vazia retorna erro."""
        response = await client.post(
            f"{API_PREFIX}/search/",
            json={"query": "", "limit": 10}
        )
        
        assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_search_query_too_long(self, client):
        """Verifica que query muito longa retorna erro."""
        response = await client.post(
            f"{API_PREFIX}/search/",
            json={"query": "a" * 1001, "limit": 10}
        )
        
        assert response.status_code == 422


class TestSearchValidationE2E:
    """Testes E2E para validação de busca."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_search_invalid_limit(self, client):
        """Verifica que limite inválido retorna erro."""
        response = await client.post(
            f"{API_PREFIX}/search/",
            json={"query": "test", "limit": 0}
        )
        
        assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_search_invalid_offset(self, client):
        """Verifica que offset negativo retorna erro."""
        response = await client.post(
            f"{API_PREFIX}/search/",
            json={"query": "test", "offset": -1}
        )
        
        assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_search_invalid_hybrid_weights(self, client):
        """Verifica que hybrid_weights inválido retorna erro."""
        response = await client.post(
            f"{API_PREFIX}/search/",
            json={
                "query": "test",
                "hybrid_weights": {"invalid": 1.0}
            }
        )
        
        assert response.status_code == 422


class TestSearchResponseSchemaE2E:
    """Testes E2E para schema de resposta de busca."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_search_response_schema(self, client):
        """Verifica schema da resposta de busca."""
        response = await client.post(
            f"{API_PREFIX}/search/",
            json={"query": "test", "limit": 10}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Verifica campos obrigatórios
        required_fields = ["query", "total", "took_ms", "hits"]
        for field in required_fields:
            assert field in data, f"Campo obrigatório '{field}' ausente"
        
        # Se houver hits, verifica seus campos
        if data["hits"]:
            hit = data["hits"][0]
            hit_fields = [
                "document_id", "source_id", "score"
            ]
            for field in hit_fields:
                assert field in hit, f"Campo de hit '{field}' ausente"


class TestSearchHealthE2E:
    """Testes E2E para health check de busca."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_search_health_success(self, client):
        """Verifica que GET /search/health retorna status."""
        response = await client.get(f"{API_PREFIX}/search/health")
        
        assert response.status_code in [200, 503]
        
        if response.status_code == 200:
            data = response.json()
            assert "status" in data
            assert "indices" in data
            assert isinstance(data["indices"], list)
    
    @pytest.mark.asyncio
    async def test_search_health_response_schema(self, client):
        """Verifica schema da resposta de health."""
        response = await client.get(f"{API_PREFIX}/search/health")
        
        if response.status_code == 200:
            data = response.json()
            required_fields = ["status", "indices", "took_ms"]
            for field in required_fields:
                assert field in data, f"Campo obrigatório '{field}' ausente"
            
            # Verifica schema dos índices
            for index in data.get("indices", []):
                index_fields = ["index", "status", "docs_count", "size_mb"]
                for field in index_fields:
                    assert field in index, f"Campo de índice '{field}' ausente"


class TestSearchPerformanceE2E:
    """Testes E2E para performance de busca."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_search_response_time(self, client):
        """Verifica que busca responde em tempo aceitável."""
        import time
        
        start = time.time()
        response = await client.post(
            f"{API_PREFIX}/search/",
            json={"query": "licitação", "limit": 10}
        )
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        # Deve responder em menos de 5 segundos
        assert elapsed < 5000, f"Busca demorou {elapsed:.0f}ms"
        
        # Verifica took_ms na resposta
        data = response.json()
        assert data["took_ms"] < 5000
