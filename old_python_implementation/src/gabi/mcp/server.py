"""
MCP Server - Model Context Protocol
Transport: SSE (Server-Sent Events)
Port: 8001
Auth: JWT RS256

Integração com ChatTCU para busca semântica de documentos jurídicos.
Spec: MCP 2025-03-26
"""

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from jose import JWTError, jwt
from jose.backends import RSAKey
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

from gabi.config import settings
from gabi.db import close_db, init_db
from gabi.middleware.rate_limit import RateLimitMiddleware
from gabi.middleware.security_headers import SecurityHeadersMiddleware
from gabi.mcp.resources import MCPResourceManager
from gabi.mcp.tools import MCPToolManager

logger = logging.getLogger(__name__)

# =============================================================================
# Schemas
# =============================================================================

class JSONRPCRequest(BaseModel):
    """Request JSON-RPC 2.0"""
    jsonrpc: str = "2.0"
    id: Optional[str] = None
    method: str
    params: Optional[Dict[str, Any]] = None


class JSONRPCResponse(BaseModel):
    """Response JSON-RPC 2.0"""
    jsonrpc: str = "2.0"
    id: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None


class MCPInitializeParams(BaseModel):
    """Parâmetros de inicialização MCP"""
    protocolVersion: str
    capabilities: Dict[str, Any]
    clientInfo: Dict[str, str]


class MCPServerCapabilities(BaseModel):
    """Capacidades do servidor MCP"""
    tools: Dict[str, Any] = Field(default_factory=lambda: {"listChanged": True})
    resources: Dict[str, Any] = Field(default_factory=lambda: {"subscribe": True, "listChanged": True})
    prompts: Optional[Dict[str, Any]] = None
    logging: Optional[Dict[str, Any]] = None


# =============================================================================
# Auth
# =============================================================================

class JWTValidator:
    """Validador JWT com cache JWKS"""
    
    def __init__(self):
        self._jwks_cache: Dict[str, str] = {}
        self._jwks_last_fetch: float = 0
        self._cache_ttl_seconds: int = settings.jwt_jwks_cache_minutes * 60
    
    async def validate(self, token: str) -> Dict[str, Any]:
        """Valida token JWT contra Keycloak TCU"""
        try:
            # Buscar JWKS se necessário
            await self._fetch_jwks_if_needed()
            
            # Decodificar header para pegar kid
            unverified = jwt.get_unverified_header(token)
            kid = unverified.get("kid")
            
            if not kid:
                raise JWTError("Token sem 'kid' no header")
            
            # Pegar chave do cache
            key_pem = self._jwks_cache.get(kid)
            if not key_pem:
                # Forçar refresh do cache
                await self._fetch_jwks(force=True)
                key_pem = self._jwks_cache.get(kid)
                if not key_pem:
                    raise JWTError(f"Key ID desconhecido: {kid}")
            
            # Validar token
            payload = jwt.decode(
                token,
                key_pem,
                algorithms=[settings.jwt_algorithm],
                issuer=str(settings.jwt_issuer),
                audience=settings.jwt_audience,
            )
            
            return payload
            
        except JWTError as e:
            logger.warning(f"JWT validation failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error validating JWT: {e}")
            raise JWTError(f"Validation error: {e}")
    
    async def _fetch_jwks_if_needed(self):
        """Busca JWKS se cache expirado"""
        if time.time() - self._jwks_last_fetch > self._cache_ttl_seconds:
            await self._fetch_jwks()
    
    async def _fetch_jwks(self, force: bool = False):
        """Busca JWKS do Keycloak"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(str(settings.jwt_jwks_url))
                response.raise_for_status()
                jwks = response.json()
            
            # Converter JWKs para PEM
            new_cache = {}
            for key in jwks.get("keys", []):
                if key.get("kty") == "RSA":
                    try:
                        rsa_key = RSAKey(key, algorithm=settings.jwt_algorithm)
                        new_cache[key["kid"]] = rsa_key.to_pem()
                    except Exception as e:
                        logger.warning(f"Failed to convert key {key.get('kid')}: {e}")
            
            if not new_cache and not force:
                logger.warning("No valid keys fetched, keeping old cache")
                return
            
            self._jwks_cache = new_cache
            self._jwks_last_fetch = time.time()
            logger.debug(f"JWKS cache updated with {len(new_cache)} keys")
            
        except Exception as e:
            logger.error(f"Failed to fetch JWKS: {e}")
            if force or not self._jwks_cache:
                raise


# Singleton validator
jwt_validator = JWTValidator()


async def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """Dependency para extrair e validar usuário do JWT"""
    if not settings.mcp_auth_required:
        return {"sub": "anonymous", "role": "guest"}
    
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    
    token = auth_header[7:]
    
    try:
        payload = await jwt_validator.validate(token)
        return payload
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")


# =============================================================================
# MCP Server
# =============================================================================

class MCPServer:
    """
    Servidor MCP com transporte SSE.
    
    Endpoints:
    - GET /mcp/sse - Conexão SSE para receber mensagens do servidor
    - POST /mcp/message - Envio de mensagens do cliente
    """
    
    def __init__(self):
        self.tool_manager = MCPToolManager()
        self.resource_manager = MCPResourceManager()
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.message_queues: Dict[str, List[Dict]] = {}
    
    def create_app(self) -> FastAPI:
        """Factory para criar aplicação FastAPI do MCP"""
        
        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncGenerator:
            """Gerencia ciclo de vida"""
            await init_db()
            yield
            await close_db()
        
        app = FastAPI(
            title="GABI MCP Server",
            description="Model Context Protocol Server para ChatTCU",
            version="1.0.0",
            lifespan=lifespan,
        )
        
        # Add security headers
        app.add_middleware(SecurityHeadersMiddleware)
        
        # Add rate limiting middleware
        app.add_middleware(RateLimitMiddleware)
        
        # Add CORS with proper configuration
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.mcp_cors_origins_list,
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )
        
        # Rotas
        app.get("/health")(self.health_check)
        app.get("/mcp/sse")(self.sse_endpoint)
        app.post("/mcp/message")(self.message_endpoint)
        app.get("/mcp/resources/{resource_uri:path}")(self.get_resource)
        
        return app
    
    async def health_check(self) -> Dict[str, Any]:
        """Health check do servidor MCP"""
        return {
            "status": "healthy",
            "service": "mcp",
            "version": "1.0.0",
            "sessions": len(self.sessions)
        }
    
    async def sse_endpoint(
        self,
        request: Request,
        user: Dict = Depends(get_current_user)
    ) -> StreamingResponse:
        """
        Endpoint SSE para conexão persistente.
        
        O cliente recebe mensagens do servidor via SSE.
        """
        session_id = str(uuid.uuid4())
        
        # Criar sessão
        self.sessions[session_id] = {
            "id": session_id,
            "user": user,
            "created_at": time.time(),
            "last_activity": time.time(),
        }
        self.message_queues[session_id] = []
        
        logger.info(f"MCP session created: {session_id} (user: {user.get('sub')})")
        
        async def event_generator() -> AsyncGenerator[str, None]:
            """Gera eventos SSE"""
            try:
                # Enviar endpoint URL no evento de conexão
                yield f"event: endpoint\ndata: /mcp/message?sessionId={session_id}\n\n"
                
                # Loop de eventos
                while True:
                    # Verificar se há mensagens na fila
                    if self.message_queues.get(session_id):
                        msg = self.message_queues[session_id].pop(0)
                        yield f"event: message\ndata: {json.dumps(msg)}\n\n"
                    
                    # Heartbeat a cada 30s
                    await self._sleep_with_check(request, 1.0)
                    
                    # Atualizar atividade
                    if session_id in self.sessions:
                        self.sessions[session_id]["last_activity"] = time.time()
                    
            except Exception as e:
                logger.debug(f"SSE connection closed for {session_id}: {e}")
            finally:
                # Cleanup
                self.sessions.pop(session_id, None)
                self.message_queues.pop(session_id, None)
                logger.info(f"MCP session closed: {session_id}")
        
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Mcp-Session-Id": session_id,
            }
        )
    
    async def _sleep_with_check(self, request: Request, duration: float):
        """Sleep que verifica desconexão do cliente"""
        import asyncio
        try:
            await asyncio.wait_for(
                request.receive(),
                timeout=duration
            )
        except asyncio.TimeoutError:
            pass
        except Exception:
            raise
    
    async def message_endpoint(
        self,
        request: Request,
        session_id: Optional[str] = Query(None, alias="sessionId"),
        user: Dict = Depends(get_current_user)
    ) -> JSONResponse:
        """
        Endpoint para receber mensagens do cliente.
        
        O cliente envia requisições JSON-RPC via POST.
        """
        body = await request.json()
        
        # Validar sessão
        if session_id and session_id not in self.sessions:
            return JSONResponse(
                status_code=400,
                content=self._error_response(None, -32000, "Invalid session")
            )
        
        # Processar batch ou single request
        if isinstance(body, list):
            results = []
            for req in body:
                result = await self._handle_request(req, user, session_id)
                if result:
                    results.append(result)
            return JSONResponse(content=results)
        else:
            result = await self._handle_request(body, user, session_id)
            return JSONResponse(content=result)
    
    async def _handle_request(
        self,
        request: Dict[str, Any],
        user: Dict[str, Any],
        session_id: Optional[str]
    ) -> Dict[str, Any]:
        """Processa uma requisição JSON-RPC"""
        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params", {})
        
        logger.debug(f"MCP method: {method} (session: {session_id})")
        
        try:
            # Métodos do protocolo MCP
            if method == "initialize":
                return await self._handle_initialize(req_id, params)
            
            elif method == "initialized":
                # Notificação de inicialização completa
                return None  # Notificação não tem resposta
            
            elif method == "tools/list":
                return await self._handle_tools_list(req_id)
            
            elif method == "tools/call":
                return await self._handle_tools_call(req_id, params, user)
            
            elif method == "resources/list":
                return await self._handle_resources_list(req_id)
            
            elif method == "resources/read":
                return await self._handle_resources_read(req_id, params, user)
            
            elif method == "ping":
                return self._success_response(req_id, {})
            
            else:
                return self._error_response(
                    req_id, -32601, f"Method not found: {method}"
                )
                
        except Exception as e:
            logger.exception(f"Error handling method {method}: {e}")
            return self._error_response(req_id, -32603, str(e))
    
    async def _handle_initialize(
        self,
        req_id: Optional[str],
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle initialize request"""
        protocol_version = params.get("protocolVersion", "2024-11-05")
        
        # Responder com capabilities do servidor
        result = {
            "protocolVersion": "2025-03-26",
            "capabilities": MCPServerCapabilities().dict(exclude_none=True),
            "serverInfo": {
                "name": "gabi-mcp-server",
                "version": "1.0.0"
            }
        }
        
        return self._success_response(req_id, result)
    
    async def _handle_tools_list(self, req_id: Optional[str]) -> Dict[str, Any]:
        """Listar ferramentas disponíveis"""
        tools = self.tool_manager.list_tools()
        return self._success_response(req_id, {"tools": tools})
    
    async def _handle_tools_call(
        self,
        req_id: Optional[str],
        params: Dict[str, Any],
        user: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Executar ferramenta"""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        try:
            result = await self.tool_manager.execute_tool(
                tool_name=tool_name,
                arguments=arguments,
                user=user
            )
            return self._success_response(req_id, result)
        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            return self._error_response(req_id, -32603, str(e))
    
    async def _handle_resources_list(self, req_id: Optional[str]) -> Dict[str, Any]:
        """Listar recursos disponíveis"""
        resources = self.resource_manager.list_resources()
        return self._success_response(req_id, {"resources": resources})
    
    async def _handle_resources_read(
        self,
        req_id: Optional[str],
        params: Dict[str, Any],
        user: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Ler recurso"""
        uri = params.get("uri")
        
        try:
            result = await self.resource_manager.read_resource(uri, user)
            return self._success_response(req_id, result)
        except Exception as e:
            logger.error(f"Resource read failed: {e}")
            return self._error_response(req_id, -32603, str(e))
    
    async def get_resource(
        self,
        resource_uri: str,
        user: Dict = Depends(get_current_user)
    ) -> JSONResponse:
        """Endpoint HTTP direto para recursos"""
        try:
            result = await self.resource_manager.read_resource(resource_uri, user)
            return JSONResponse(content=result)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    def _success_response(self, id: Optional[str], result: Any) -> Dict[str, Any]:
        """Cria resposta de sucesso JSON-RPC"""
        return {
            "jsonrpc": "2.0",
            "id": id,
            "result": result
        }
    
    def _error_response(
        self,
        id: Optional[str],
        code: int,
        message: str
    ) -> Dict[str, Any]:
        """Cria resposta de erro JSON-RPC"""
        return {
            "jsonrpc": "2.0",
            "id": id,
            "error": {
                "code": code,
                "message": message
            }
        }
    
    def send_notification(self, session_id: str, method: str, params: Dict):
        """Envia notificação para sessão"""
        if session_id in self.message_queues:
            self.message_queues[session_id].append({
                "jsonrpc": "2.0",
                "method": method,
                "params": params
            })


# Singleton server
mcp_server = MCPServer()


def create_mcp_app() -> FastAPI:
    """Factory pública para criar app MCP"""
    return mcp_server.create_app()


# Entry point para execução standalone
if __name__ == "__main__":
    import uvicorn
    
    app = create_mcp_app()
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.mcp_port,
        log_level=settings.log_level.lower(),
    )
