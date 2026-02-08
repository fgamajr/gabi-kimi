"""Testes E2E para API de documentos.

Testa endpoints de documentos com cliente HTTP real.
"""

from __future__ import annotations

import pytest
from typing import Any

# Skip se não estiver rodando com servidor real
pytestmark = pytest.mark.e2e

# Use --run-e2e flag para executar estes testes
# pytest --run-e2e tests/e2e/


BASE_URL = "http://localhost:8000"
API_PREFIX = "/api/v1"


class TestDocumentsE2E:
    """Testes E2E para endpoints de documentos."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_list_documents_success(self, client):
        """Verifica que GET /documents retorna lista de documentos."""
        response = await client.get(f"{API_PREFIX}/documents")
        
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "documents" in data
        assert isinstance(data["documents"], list)
    
    @pytest.mark.asyncio
    async def test_list_documents_with_pagination(self, client):
        """Verifica que paginação funciona."""
        response = await client.get(
            f"{API_PREFIX}/documents?page=1&page_size=5"
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 5
    
    @pytest.mark.asyncio
    async def test_list_documents_with_source_filter(self, client):
        """Verifica que filtro por source_id funciona."""
        response = await client.get(
            f"{API_PREFIX}/documents?source_id=test_source"
        )
        
        assert response.status_code == 200
        # Pode estar vazio se não houver documentos, mas não deve erro
    
    @pytest.mark.asyncio
    async def test_list_documents_with_search(self, client):
        """Verifica que busca em título funciona."""
        response = await client.get(
            f"{API_PREFIX}/documents?search=acordao"
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
    
    @pytest.mark.asyncio
    async def test_get_document_not_found(self, client):
        """Verifica que GET /documents/{id} retorna 404 para ID inexistente."""
        response = await client.get(
            f"{API_PREFIX}/documents/NON-EXISTENT-ID-12345"
        )
        
        assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_reindex_document_not_found(self, client):
        """Verifica que POST /documents/{id}/reindex retorna 404 para ID inexistente."""
        response = await client.post(
            f"{API_PREFIX}/documents/NON-EXISTENT-ID-12345/reindex",
            json={"force": True}
        )
        
        assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_delete_document_not_found(self, client):
        """Verifica que DELETE /documents/{id} retorna 404 para ID inexistente."""
        response = await client.delete(
            f"{API_PREFIX}/documents/NON-EXISTENT-ID-12345"
        )
        
        assert response.status_code == 404


class TestDocumentsValidationE2E:
    """Testes E2E para validação de documentos."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_list_documents_invalid_page(self, client):
        """Verifica que página inválida retorna erro."""
        response = await client.get(
            f"{API_PREFIX}/documents?page=0"
        )
        
        # Deve retornar erro de validação
        assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_list_documents_invalid_page_size(self, client):
        """Verifica que page_size inválido retorna erro."""
        response = await client.get(
            f"{API_PREFIX}/documents?page_size=0"
        )
        
        assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_list_documents_page_size_too_large(self, client):
        """Verifica que page_size muito grande retorna erro."""
        response = await client.get(
            f"{API_PREFIX}/documents?page_size=1000"
        )
        
        assert response.status_code == 422


class TestDocumentsResponseSchemaE2E:
    """Testes E2E para schema de resposta de documentos."""
    
    @pytest.fixture
    async def client(self):
        """Cliente HTTP assíncrono."""
        import httpx
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_list_documents_response_schema(self, client):
        """Verifica schema da resposta de listagem."""
        response = await client.get(f"{API_PREFIX}/documents")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verifica campos obrigatórios
        required_fields = ["total", "page", "page_size", "documents"]
        for field in required_fields:
            assert field in data, f"Campo obrigatório '{field}' ausente"
        
        # Se houver documentos, verifica seus campos
        if data["documents"]:
            doc = data["documents"][0]
            doc_fields = [
                "id", "document_id", "source_id", "title",
                "status", "is_deleted", "version"
            ]
            for field in doc_fields:
                assert field in doc, f"Campo de documento '{field}' ausente"
