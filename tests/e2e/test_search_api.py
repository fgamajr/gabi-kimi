"""Testes E2E para API de busca do GABI.

Este módulo contém testes end-to-end para os endpoints de busca:
- POST /api/v1/search/ - Busca híbrida
- GET /api/v1/search/health - Health check dos índices

Requisitos para execução:
- Elasticsearch rodando em localhost:9200
- pytest-asyncio configurado

Marcadores:
- e2e: Testes end-to-end (lentos, requerem infraestrutura)
- requires_es: Requer Elasticsearch
"""

from __future__ import annotations

import json
import os
from typing import Any, AsyncGenerator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from gabi.api.router import get_api_router, include_all_routers
from gabi.api.search import SearchService


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(scope="module")
def es_url() -> str:
    """URL do Elasticsearch para testes.
    
    Returns:
        URL do Elasticsearch (padrão: http://localhost:9200)
    """
    return os.getenv("ES_URL", "http://localhost:9200")


@pytest.fixture(scope="module")
def es_index() -> str:
    """Nome do índice para testes.
    
    Returns:
        Nome do índice de teste
    """
    return "gabi_test_search"


@pytest.fixture(scope="module")
async def es_client(es_url: str) -> AsyncGenerator[Any, None]:
    """Cliente Elasticsearch para testes.
    
    Args:
        es_url: URL do Elasticsearch
        
    Yields:
        Cliente Elasticsearch async
    """
    from elasticsearch import AsyncElasticsearch
    
    client = AsyncElasticsearch([es_url])
    
    # Verifica conexão
    if not await client.ping():
        pytest.skip("Elasticsearch não disponível")
    
    yield client
    
    await client.close()


@pytest.fixture(scope="module")
async def search_index(es_client: Any, es_index: str) -> AsyncGenerator[str, None]:
    """Cria índice de teste no Elasticsearch.
    
    Args:
        es_client: Cliente Elasticsearch
        es_index: Nome do índice
        
    Yields:
        Nome do índice criado
        
    Cleanup:
        Deleta o índice após os testes
    """
    from gabi.services.elasticsearch_setup import INDEX_MAPPINGS, INDEX_SETTINGS
    
    # Deleta se existir
    if await es_client.indices.exists(index=es_index):
        await es_client.indices.delete(index=es_index)
    
    # Cria índice
    await es_client.indices.create(
        index=es_index,
        mappings=INDEX_MAPPINGS,
        settings=INDEX_SETTINGS,
    )
    
    # Aguarda índice ficar disponível
    await es_client.indices.refresh(index=es_index)
    
    yield es_index
    
    # Cleanup
    if await es_client.indices.exists(index=es_index):
        await es_client.indices.delete(index=es_index)


@pytest.fixture
async def search_service(
    es_client: Any,
    search_index: str,
) -> AsyncGenerator[SearchService, None]:
    """Serviço de busca configurado para testes.
    
    Args:
        es_client: Cliente Elasticsearch
        search_index: Nome do índice de teste
        
    Yields:
        SearchService configurado
    """
    from unittest.mock import Mock
    
    # Mock settings com índice de teste
    mock_settings = Mock()
    mock_settings.elasticsearch_index = search_index
    mock_settings.search_rrf_k = 60
    mock_settings.search_default_limit = 10
    mock_settings.search_max_limit = 100
    mock_settings.search_bm25_weight = 1.0
    mock_settings.search_vector_weight = 1.0
    mock_settings.search_timeout_ms = 5000
    
    service = SearchService(
        es_client=es_client,
        settings=mock_settings,
    )
    
    yield service


@pytest.fixture
async def test_app(search_index: str, es_url: str) -> AsyncGenerator[FastAPI, None]:
    """Aplicação FastAPI configurada para testes.
    
    Args:
        search_index: Nome do índice de teste
        es_url: URL do Elasticsearch
        
    Yields:
        FastAPI app configurado
    """
    from unittest.mock import Mock, AsyncMock
    from elasticsearch import AsyncElasticsearch
    
    app = FastAPI()
    
    # Override dependencies
    async def override_get_es_client():
        client = AsyncElasticsearch([es_url])
        yield client
    
    def override_get_settings():
        settings = Mock()
        settings.elasticsearch_index = search_index
        settings.search_rrf_k = 60
        settings.search_default_limit = 10
        settings.search_max_limit = 100
        settings.search_bm25_weight = 1.0
        settings.search_vector_weight = 1.0
        settings.search_timeout_ms = 5000
        return settings
    
    # Include routers
    api_router = get_api_router()
    app.include_router(api_router)
    
    # Override dependencies
    from gabi.api.search import get_search_service
    from gabi.dependencies import get_es_client, get_settings
    
    app.dependency_overrides[get_es_client] = override_get_es_client
    app.dependency_overrides[get_settings] = override_get_settings
    
    yield app


@pytest.fixture
async def test_client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Cliente HTTP async para testes.
    
    Args:
        test_app: Aplicação FastAPI
        
    Yields:
        AsyncClient configurado
    """
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def sample_documents(es_client: Any, search_index: str) -> AsyncGenerator[list[dict], None]:
    """Insere documentos de teste no Elasticsearch.
    
    Args:
        es_client: Cliente Elasticsearch
        search_index: Nome do índice
        
    Yields:
        Lista de documentos inseridos
    """
    docs = [
        {
            "_id": "TCU-ACORDAO-1234-2024",
            "_source": {
                "document_id": "TCU-ACORDAO-1234-2024",
                "source_id": "tcu_acordaos",
                "title": "Acórdão sobre Licitação 1234/2024",
                "content_preview": "EMENTA: Licitação. Pregão Eletrônico. Impugnação ao edital...",
                "metadata": {
                    "year": 2024,
                    "number": "1234",
                    "relator": "Ministro Teste",
                    "assunto": "Licitações",
                },
                "url": "https://pesquisa.apps.tcu.gov.br/#/documento/acordao/1234-2024",
                "is_deleted": False,
            },
        },
        {
            "_id": "TCU-ACORDAO-5678-2023",
            "_source": {
                "document_id": "TCU-ACORDAO-5678-2023",
                "source_id": "tcu_acordaos",
                "title": "Acórdão sobre Contratos 5678/2023",
                "content_preview": "EMENTA: Contratos administrativos. Aditivo...",
                "metadata": {
                    "year": 2023,
                    "number": "5678",
                    "relator": "Ministro Exemplo",
                    "assunto": "Contratos",
                },
                "url": "https://pesquisa.apps.tcu.gov.br/#/documento/acordao/5678-2023",
                "is_deleted": False,
            },
        },
        {
            "_id": "TCU-NORMA-001-2024",
            "_source": {
                "document_id": "TCU-NORMA-001-2024",
                "source_id": "tcu_normas",
                "title": "Norma Interna 001/2024",
                "content_preview": "Dispõe sobre procedimentos internos...",
                "metadata": {
                    "year": 2024,
                    "number": "001",
                    "type": "IN",
                },
                "url": "https://portal.tcu.gov.br/normas/001-2024",
                "is_deleted": False,
            },
        },
    ]
    
    # Indexa documentos
    for doc in docs:
        await es_client.index(
            index=search_index,
            id=doc["_id"],
            document=doc["_source"],
            refresh=True,  # Refresh imediato para busca
        )
    
    yield docs
    
    # Cleanup - deleta documentos
    for doc in docs:
        try:
            await es_client.delete(index=search_index, id=doc["_id"], ignore=[404])
        except Exception:
            pass


# =============================================================================
# Testes
# =============================================================================

@pytest.mark.e2e
@pytest.mark.requires_es
class TestSearchEndpoint:
    """Testes para endpoint POST /api/v1/search/"""
    
    @pytest.mark.asyncio
    async def test_search_basic(
        self,
        test_client: AsyncClient,
        sample_documents: list[dict],
    ) -> None:
        """Testa busca básica por termo.
        
        Verifica:
        - Status 200
        - Retorna hits
        - Query é refletida na resposta
        """
        response = await test_client.post(
            "/api/v1/search/",
            json={"query": "licitação pregão", "limit": 5},
        )
        
        assert response.status_code == 200
        
        data = response.json()
        assert data["query"] == "licitação pregão"
        assert "hits" in data
        assert "total" in data
        assert "took_ms" in data
        
        # Deve encontrar pelo menos um documento
        assert len(data["hits"]) > 0
    
    @pytest.mark.asyncio
    async def test_search_with_source_filter(
        self,
        test_client: AsyncClient,
        sample_documents: list[dict],
    ) -> None:
        """Testa busca com filtro de source.
        
        Verifica:
        - Filtro de source funciona
        - Apenas documentos do source solicitado são retornados
        """
        response = await test_client.post(
            "/api/v1/search/",
            json={
                "query": "2024",
                "sources": ["tcu_normas"],
            },
        )
        
        assert response.status_code == 200
        
        data = response.json()
        for hit in data["hits"]:
            assert hit["source_id"] == "tcu_normas"
    
    @pytest.mark.asyncio
    async def test_search_empty_results(
        self,
        test_client: AsyncClient,
        sample_documents: list[dict],
    ) -> None:
        """Testa busca sem resultados.
        
        Verifica:
        - Status 200 mesmo sem resultados
        - hits é lista vazia
        - total é 0
        """
        response = await test_client.post(
            "/api/v1/search/",
            json={"query": "xyznonexistent12345"},
        )
        
        assert response.status_code == 200
        
        data = response.json()
        assert data["hits"] == []
        assert data["total"] == 0
    
    @pytest.mark.asyncio
    async def test_search_validation_empty_query(
        self,
        test_client: AsyncClient,
    ) -> None:
        """Testa validação de query vazia.
        
        Verifica:
        - Status 422 (Unprocessable Entity)
        - Erro de validação
        """
        response = await test_client.post(
            "/api/v1/search/",
            json={"query": ""},
        )
        
        assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_search_validation_invalid_limit(
        self,
        test_client: AsyncClient,
    ) -> None:
        """Testa validação de limite inválido.
        
        Verifica:
        - Status 422 para limit > max
        """
        response = await test_client.post(
            "/api/v1/search/",
            json={"query": "test", "limit": 1000},
        )
        
        assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_search_response_structure(
        self,
        test_client: AsyncClient,
        sample_documents: list[dict],
    ) -> None:
        """Testa estrutura da resposta de busca.
        
        Verifica:
        - Todos os campos esperados estão presentes
        - Tipos corretos
        """
        response = await test_client.post(
            "/api/v1/search/",
            json={"query": "licitação"},
        )
        
        assert response.status_code == 200
        
        data = response.json()
        
        # Campos raiz
        assert "query" in data
        assert "total" in data
        assert "took_ms" in data
        assert "hits" in data
        
        # Estrutura de hits
        if data["hits"]:
            hit = data["hits"][0]
            assert "document_id" in hit
            assert "title" in hit
            assert "content_preview" in hit
            assert "source_id" in hit
            assert "score" in hit
            assert "metadata" in hit


@pytest.mark.e2e
@pytest.mark.requires_es
class TestHealthEndpoint:
    """Testes para endpoint GET /api/v1/search/health"""
    
    @pytest.mark.asyncio
    async def test_health_basic(
        self,
        test_client: AsyncClient,
        search_index: str,
    ) -> None:
        """Testa health check básico.
        
        Verifica:
        - Status 200
        - Resposta contém status e índices
        """
        response = await test_client.get("/api/v1/search/health")
        
        assert response.status_code == 200
        
        data = response.json()
        assert "status" in data
        assert data["status"] in ["healthy", "degraded", "unhealthy"]
        assert "indices" in data
        assert "took_ms" in data
        assert isinstance(data["indices"], list)
    
    @pytest.mark.asyncio
    async def test_health_indices_structure(
        self,
        test_client: AsyncClient,
        search_index: str,
    ) -> None:
        """Testa estrutura dos índices no health check.
        
        Verifica:
        - Cada índice tem campos esperados
        - Tipos corretos
        """
        response = await test_client.get("/api/v1/search/health")
        
        assert response.status_code == 200
        
        data = response.json()
        
        for idx in data["indices"]:
            assert "index" in idx
            assert "status" in idx
            assert "docs_count" in idx
            assert "size_mb" in idx
            
            assert idx["status"] in ["green", "yellow", "red"]
            assert isinstance(idx["docs_count"], int)
            assert isinstance(idx["size_mb"], (int, float))
    
    @pytest.mark.asyncio
    async def test_health_contains_expected_indices(
        self,
        test_client: AsyncClient,
        search_index: str,
    ) -> None:
        """Testa que índices esperados estão presentes.
        
        Verifica:
        - Índice principal está listado
        """
        response = await test_client.get("/api/v1/search/health")
        
        assert response.status_code == 200
        
        data = response.json()
        index_names = [idx["index"] for idx in data["indices"]]
        
        assert search_index in index_names


# =============================================================================
# Testes de integração com serviço direto
# =============================================================================

@pytest.mark.e2e
@pytest.mark.requires_es
class TestSearchService:
    """Testes diretos do SearchService."""
    
    @pytest.mark.asyncio
    async def test_service_search(
        self,
        search_service: SearchService,
        sample_documents: list[dict],
    ) -> None:
        """Testa busca via serviço direto.
        
        Verifica:
        - Retorna SearchResponse
        - Resultados são ranqueados
        """
        from gabi.api.search import SearchRequest
        
        request = SearchRequest(query="licitação", limit=10)
        response = await search_service.search(request)
        
        assert response.query == "licitação"
        assert response.total >= 0
        assert response.took_ms >= 0
        assert isinstance(response.hits, list)
    
    @pytest.mark.asyncio
    async def test_service_health_check(
        self,
        search_service: SearchService,
        search_index: str,
    ) -> None:
        """Testa health check via serviço.
        
        Verifica:
        - Retorna HealthResponse
        - Índice de teste está presente
        """
        response = await search_service.health_check()
        
        assert response.status in ["healthy", "degraded", "unhealthy"]
        assert response.took_ms >= 0
        
        index_names = [idx.index for idx in response.indices]
        assert search_index in index_names
    
    @pytest.mark.asyncio
    async def test_service_fusion_rrf(
        self,
        search_service: SearchService,
        sample_documents: list[dict],
    ) -> None:
        """Testa fusão RRF de resultados.
        
        Verifica:
        - Scores são combinados corretamente
        - Resultados são ranqueados
        """
        from gabi.api.search import SearchRequest
        
        # Busca com pesos customizados
        request = SearchRequest(
            query="2024",
            limit=10,
            hybrid_weights={"bm25": 1.0, "vector": 0.0},
        )
        
        response = await search_service.search(request)
        
        # Verifica que há resultados
        if response.hits:
            # Scores devem ser positivos
            for hit in response.hits:
                assert hit.score > 0


# =============================================================================
# Testes de performance
# =============================================================================

@pytest.mark.e2e
@pytest.mark.requires_es
@pytest.mark.slow
class TestSearchPerformance:
    """Testes de performance para busca."""
    
    @pytest.mark.asyncio
    async def test_search_response_time(
        self,
        test_client: AsyncClient,
        sample_documents: list[dict],
    ) -> None:
        """Testa tempo de resposta da busca.
        
        Verifica:
        - Busca completa em menos de 2 segundos
        """
        import time
        
        start = time.time()
        response = await test_client.post(
            "/api/v1/search/",
            json={"query": "licitação contratos normas"},
        )
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 2000  # 2 segundos
        
        data = response.json()
        assert data["took_ms"] < 2000


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Fixtures
    "es_url",
    "es_index",
    "es_client",
    "search_index",
    "search_service",
    "test_app",
    "test_client",
    "sample_documents",
    # Classes de teste
    "TestSearchEndpoint",
    "TestHealthEndpoint",
    "TestSearchService",
    "TestSearchPerformance",
]
