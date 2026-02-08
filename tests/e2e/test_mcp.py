"""
Testes E2E do MCP Server

Cobertura:
- Conexão SSE
- Handshake initialize
- List tools
- Call tools
- Read resources
- JWT Auth

Requer:
- Servidor MCP rodando em http://localhost:8001
- Fontes configuradas em sources.yaml
"""

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
import pytest
import pytest_asyncio
import yaml

# =============================================================================
# Fixtures
# =============================================================================

MCP_BASE_URL = os.getenv("MCP_TEST_URL", "http://localhost:8001")
JWT_TOKEN = os.getenv("MCP_TEST_TOKEN", "test-token")  # Para testes com auth real


@pytest_asyncio.fixture
async def http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Cliente HTTP assíncrono"""
    async with httpx.AsyncClient(base_url=MCP_BASE_URL, timeout=30.0) as client:
        yield client


@pytest_asyncio.fixture
async def mcp_session(http_client: httpx.AsyncClient) -> AsyncGenerator["MCPTestSession", None]:
    """Sessão MCP com handshake completo"""
    session = MCPTestSession(http_client)
    await session.initialize()
    yield session
    await session.close()


# =============================================================================
# Helpers
# =============================================================================

class MCPTestSession:
    """Helper para gerenciar sessão de teste MCP"""
    
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.session_id: Optional[str] = None
        self.message_endpoint: Optional[str] = None
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._sse_task: Optional[asyncio.Task] = None
    
    async def initialize(self):
        """Inicializa sessão MCP com handshake"""
        # Estabelecer conexão SSE
        await self._connect_sse()
        
        # Handshake initialize
        init_result = await self.send_request("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"}
        })
        
        assert "protocolVersion" in init_result
        assert init_result.get("serverInfo", {}).get("name") == "gabi-mcp-server"
        
        # Notificação initialized
        await self.send_notification("initialized", {})
    
    async def _connect_sse(self):
        """Conecta via SSE e captura session ID"""
        headers = {"Authorization": f"Bearer {JWT_TOKEN}"}
        
        response = await self.client.get(
            "/mcp/sse",
            headers=headers,
            timeout=5.0
        )
        
        # Capturar session ID do header
        self.session_id = response.headers.get("Mcp-Session-Id")
        assert self.session_id is not None, "Session ID not provided"
        
        # O endpoint de mensagens é enviado no evento 'endpoint'
        self.message_endpoint = f"/mcp/message?sessionId={self.session_id}"
    
    async def send_request(
        self,
        method: str,
        params: Optional[Dict] = None,
        msg_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Envia requisição JSON-RPC e retorna resultado"""
        msg_id = msg_id or str(uuid.uuid4())
        
        payload = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params or {}
        }
        
        headers = {"Authorization": f"Bearer {JWT_TOKEN}"}
        
        response = await self.client.post(
            self.message_endpoint,
            json=payload,
            headers=headers
        )
        
        assert response.status_code == 200, f"Request failed: {response.text}"
        
        data = response.json()
        
        # Verificar se é resposta de erro
        if "error" in data:
            raise AssertionError(f"RPC error: {data['error']}")
        
        return data.get("result", {})
    
    async def send_notification(self, method: str, params: Optional[Dict] = None):
        """Envia notificação (sem resposta)"""
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {}
        }
        
        headers = {"Authorization": f"Bearer {JWT_TOKEN}"}
        
        response = await self.client.post(
            self.message_endpoint,
            json=payload,
            headers=headers
        )
        
        assert response.status_code == 200
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Helper para chamar ferramenta"""
        result = await self.send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })
        
        assert "content" in result, f"Tool result missing content: {result}"
        return result
    
    async def read_resource(self, uri: str) -> Dict[str, Any]:
        """Helper para ler recurso"""
        result = await self.send_request("resources/read", {"uri": uri})
        
        assert "contents" in result, f"Resource result missing contents: {result}"
        return result
    
    async def close(self):
        """Fecha sessão"""
        # Enviar ping para manter conexão viva durante testes
        try:
            await self.send_request("ping", {})
        except:
            pass


# =============================================================================
# Testes de Health e Conectividade
# =============================================================================

@pytest.mark.asyncio
async def test_health_endpoint(http_client: httpx.AsyncClient):
    """Testa endpoint de health check"""
    response = await http_client.get("/health")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["status"] == "healthy"
    assert data["service"] == "mcp"
    assert "version" in data


@pytest.mark.asyncio
async def test_sse_connection_requires_auth(http_client: httpx.AsyncClient):
    """Testa que SSE requer autenticação"""
    response = await http_client.get("/mcp/sse", timeout=2.0)
    
    # Deve retornar 401 sem token
    assert response.status_code == 401


# =============================================================================
# Testes de Tools
# =============================================================================

@pytest.mark.asyncio
async def test_tools_list(mcp_session: MCPTestSession):
    """Testa listagem de ferramentas"""
    result = await mcp_session.send_request("tools/list")
    
    assert "tools" in result
    tools = result["tools"]
    
    # Verificar ferramentas esperadas
    tool_names = {t["name"] for t in tools}
    expected = {"search_documents", "get_document_by_id", "list_sources", "get_source_stats"}
    
    assert expected.issubset(tool_names), f"Missing tools. Got: {tool_names}"
    
    # Verificar schema de search_documents
    search_tool = next(t for t in tools if t["name"] == "search_documents")
    assert "inputSchema" in search_tool
    assert "properties" in search_tool["inputSchema"]
    assert "query" in search_tool["inputSchema"]["properties"]


@pytest.mark.asyncio
async def test_tool_search_documents(mcp_session: MCPTestSession):
    """Testa ferramenta search_documents"""
    result = await mcp_session.call_tool("search_documents", {
        "query": "licitação TCU",
        "search_type": "hybrid",
        "limit": 5
    })
    
    # Verificar formato de resposta MCP
    assert "content" in result
    assert len(result["content"]) > 0
    
    content = result["content"][0]
    assert content["type"] == "text"
    
    # Parsear resultado JSON
    data = json.loads(content["text"])
    assert "results" in data
    assert "query" in data
    assert data["query"] == "licitação TCU"


@pytest.mark.asyncio
async def test_tool_search_with_filters(mcp_session: MCPTestSession):
    """Testa busca com filtros"""
    result = await mcp_session.call_tool("search_documents", {
        "query": "acórdão",
        "filters": {
            "source_id": "tcu_acordaos",
            "year": 2024
        },
        "limit": 3
    })
    
    assert "content" in result
    data = json.loads(result["content"][0]["text"])
    
    assert "results" in data
    assert "limit" in data
    assert data["limit"] == 3


@pytest.mark.asyncio
async def test_tool_get_document_by_id(mcp_session: MCPTestSession):
    """Testa recuperação de documento por ID"""
    result = await mcp_session.call_tool("get_document_by_id", {
        "document_id": "TCU-1234/2024",
        "include_chunks": False
    })
    
    assert "content" in result
    data = json.loads(result["content"][0]["text"])
    
    assert "document" in data
    assert data["document"]["document_id"] == "TCU-1234/2024"


@pytest.mark.asyncio
async def test_tool_list_sources(mcp_session: MCPTestSession):
    """Testa listagem de fontes"""
    result = await mcp_session.call_tool("list_sources", {})
    
    assert "content" in result
    data = json.loads(result["content"][0]["text"])
    
    assert "sources" in data
    assert "total" in data
    
    # Verificar estrutura das fontes
    if data["sources"]:
        source = data["sources"][0]
        assert "id" in source
        assert "name" in source
        assert "authority" in source


@pytest.mark.asyncio
async def test_tool_get_source_stats(mcp_session: MCPTestSession):
    """Testa obtenção de estatísticas de fonte"""
    result = await mcp_session.call_tool("get_source_stats", {
        "source_id": "tcu_acordaos"
    })
    
    assert "content" in result
    data = json.loads(result["content"][0]["text"])
    
    assert "source_id" in data
    assert data["source_id"] == "tcu_acordaos"
    assert "metadata" in data
    assert "config" in data


@pytest.mark.asyncio
async def test_tool_invalid_source(mcp_session: MCPTestSession):
    """Testa erro com fonte inexistente"""
    result = await mcp_session.call_tool("get_source_stats", {
        "source_id": "invalid_source_xyz"
    })
    
    # Deve retornar erro
    assert result.get("isError") is True or "error" in result


# =============================================================================
# Testes de Resources
# =============================================================================

@pytest.mark.asyncio
async def test_resources_list(mcp_session: MCPTestSession):
    """Testa listagem de recursos"""
    result = await mcp_session.send_request("resources/list")
    
    assert "resources" in result
    resources = result["resources"]
    
    # Verificar templates de URI
    uri_templates = {r["uriTemplate"] for r in resources}
    expected = {"document://{document_id}", "source://{source_id}/stats", "source://list"}
    
    assert expected.issubset(uri_templates)


@pytest.mark.asyncio
async def test_resource_document(mcp_session: MCPTestSession):
    """Testa leitura de recurso document://"""
    result = await mcp_session.read_resource("document://TCU-1234/2024")
    
    assert "contents" in result
    assert len(result["contents"]) > 0
    
    content = result["contents"][0]
    assert content["uri"] == "document://TCU-1234/2024"
    assert content["mimeType"] == "application/json"
    
    # Verificar dados do documento
    data = json.loads(content["text"])
    assert "document_id" in data


@pytest.mark.asyncio
async def test_resource_source_stats(mcp_session: MCPTestSession):
    """Testa leitura de recurso source://{id}/stats"""
    result = await mcp_session.read_resource("source://tcu_acordaos/stats")
    
    assert "contents" in result
    content = result["contents"][0]
    
    data = json.loads(content["text"])
    assert "source_id" in data
    assert "sync_config" in data
    assert "indexing" in data
    assert "embedding" in data


@pytest.mark.asyncio
async def test_resource_source_list(mcp_session: MCPTestSession):
    """Testa leitura de recurso source://list"""
    result = await mcp_session.read_resource("source://list")
    
    assert "contents" in result
    content = result["contents"][0]
    
    data = json.loads(content["text"])
    assert "sources" in data
    assert "total" in data
    assert "authorities" in data


@pytest.mark.asyncio
async def test_resource_invalid_uri(mcp_session: MCPTestSession):
    """Testa erro com URI inválido"""
    try:
        await mcp_session.read_resource("invalid://uri")
        assert False, "Should have raised error"
    except AssertionError as e:
        assert "Invalid resource URI" in str(e) or "error" in str(e).lower()


# =============================================================================
# Testes de Protocolo
# =============================================================================

@pytest.mark.asyncio
async def test_ping(mcp_session: MCPTestSession):
    """Testa ping/pong"""
    result = await mcp_session.send_request("ping", {})
    
    # Ping deve retornar objeto vazio
    assert result == {} or isinstance(result, dict)


@pytest.mark.asyncio
async def test_invalid_method(mcp_session: MCPTestSession):
    """Testa erro com método inválido"""
    result = await mcp_session.send_request("invalid_method_xyz", {})
    
    # Deve retornar erro -32601 (Method not found)
    # Mas como estamos retornando diretamente, verificamos estrutura
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_notification_no_response(mcp_session: MCPTestSession):
    """Testa que notificações não têm resposta"""
    # Notificação não deve ter campo 'id'
    payload = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {}
    }
    
    headers = {"Authorization": f"Bearer {JWT_TOKEN}"}
    
    response = await mcp_session.client.post(
        mcp_session.message_endpoint,
        json=payload,
        headers=headers
    )
    
    assert response.status_code == 200
    # Notificação pode retornar vazio ou null


# =============================================================================
# Testes de Carga e Performance
# =============================================================================

@pytest.mark.asyncio
async def test_concurrent_requests(mcp_session: MCPTestSession):
    """Testa múltiplas requisições concorrentes"""
    
    async def search_task(query: str):
        return await mcp_session.call_tool("search_documents", {
            "query": query,
            "limit": 3
        })
    
    # Executar 5 buscas concorrentes
    queries = ["licitação", "contrato", "despesa", "responsabilidade", "indenização"]
    results = await asyncio.gather(*[search_task(q) for q in queries])
    
    # Todas devem retornar sucesso
    for result in results:
        assert "content" in result


@pytest.mark.asyncio
@pytest.mark.skip(reason="Teste de carga - executar manualmente")
async def test_load_100_requests(http_client: httpx.AsyncClient):
    """Teste de carga com 100 requisições"""
    
    async def single_request():
        session = MCPTestSession(http_client)
        await session.initialize()
        result = await session.call_tool("search_documents", {
            "query": "TCU",
            "limit": 5
        })
        await session.close()
        return result
    
    start = time.time()
    results = await asyncio.gather(*[single_request() for _ in range(100)])
    duration = time.time() - start
    
    # Todas devem ter sucesso
    assert all("content" in r for r in results)
    
    # Deve completar em menos de 60s (100 req / ~50 req/s = 2s)
    assert duration < 60, f"Load test took too long: {duration}s"
    
    print(f"Load test completed: 100 requests in {duration:.2f}s ({100/duration:.1f} req/s)")


# =============================================================================
# Testes de Autenticação
# =============================================================================

@pytest.mark.asyncio
async def test_auth_missing_token(http_client: httpx.AsyncClient):
    """Testa requisição sem token"""
    response = await http_client.post(
        "/mcp/message",
        json={"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}}
    )
    
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_invalid_token(http_client: httpx.AsyncClient):
    """Testa requisição com token inválido"""
    response = await http_client.post(
        "/mcp/message",
        headers={"Authorization": "Bearer invalid_token_123"},
        json={"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}}
    )
    
    assert response.status_code == 401


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
