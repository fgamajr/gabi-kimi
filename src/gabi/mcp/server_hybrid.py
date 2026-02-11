"""
MCP Hybrid Search Server - Model Context Protocol Server com Busca Híbrida

Transport: SSE (Server-Sent Events)
Port: 8001 (default)
Auth: JWT RS256 (Keycloak TCU)

Integração com ChatTCU para busca híbrida (exata + semântica) de documentos jurídicos.
Spec: MCP 2025-03-26

Capabilities:
- search_exact: Busca exata por campos específicos
- search_semantic: Busca semântica baseada em significado
- search_hybrid: Busca híbrida com RRF (BM25 + vetorial)
- Resources: document://, chunk://, source://, search://

Author: GABI Team
Version: 2.0.0
"""

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from jose import JWTError, jwt
from jose.backends import RSAKey
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from gabi.config import settings
from gabi.db import close_db, init_db, get_redis_client
from gabi.middleware.security_headers import SecurityHeadersMiddleware
from gabi.mcp.resources_hybrid import HybridSearchResourceManager, get_hybrid_resource_manager
from gabi.mcp.tools_hybrid import HybridSearchToolManager, get_hybrid_tool_manager
from gabi.types import AuditEventType

logger = logging.getLogger(__name__)


# =============================================================================
# Schemas
# =============================================================================

class JSONRPCRequest(BaseModel):
    """Request JSON-RPC 2.0."""
    jsonrpc: str = "2.0"
    id: Optional[str] = None
    method: str
    params: Optional[Dict[str, Any]] = None


class JSONRPCResponse(BaseModel):
    """Response JSON-RPC 2.0."""
    jsonrpc: str = "2.0"
    id: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None


class MCPInitializeParams(BaseModel):
    """Parâmetros de inicialização MCP."""
    protocolVersion: str
    capabilities: Dict[str, Any]
    clientInfo: Dict[str, str]


class MCPServerCapabilities(BaseModel):
    """Capacidades do servidor MCP."""
    tools: Dict[str, Any] = Field(default_factory=lambda: {"listChanged": True})
    resources: Dict[str, Any] = Field(default_factory=lambda: {"subscribe": True, "listChanged": True})
    prompts: Optional[Dict[str, Any]] = None
    logging: Optional[Dict[str, Any]] = None
    experimental: Optional[Dict[str, Any]] = None


@dataclass
class SessionInfo:
    """Informações de uma sessão MCP."""
    id: str
    user: Dict[str, Any]
    created_at: float
    last_activity: float
    request_count: int = 0
    tools_called: Set[str] = field(default_factory=set)


# =============================================================================
# Authentication & Authorization
# =============================================================================

class JWTValidator:
    """Validador JWT com cache JWKS."""
    
    def __init__(self):
        self._jwks_cache: Dict[str, str] = {}
        self._jwks_last_fetch: float = 0
        self._cache_ttl_seconds: int = settings.jwt_jwks_cache_minutes * 60
    
    async def validate(self, token: str) -> Dict[str, Any]:
        """Valida token JWT contra Keycloak TCU."""
        try:
            await self._fetch_jwks_if_needed()
            
            unverified = jwt.get_unverified_header(token)
            kid = unverified.get("kid")
            
            if not kid:
                raise JWTError("Token sem 'kid' no header")
            
            key_pem = self._jwks_cache.get(kid)
            if not key_pem:
                await self._fetch_jwks(force=True)
                key_pem = self._jwks_cache.get(kid)
                if not key_pem:
                    raise JWTError(f"Key ID desconhecido: {kid}")
            
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
        """Busca JWKS se cache expirado."""
        if time.time() - self._jwks_last_fetch > self._cache_ttl_seconds:
            await self._fetch_jwks()
    
    async def _fetch_jwks(self, force: bool = False):
        """Busca JWKS do Keycloak."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(str(settings.jwt_jwks_url))
                response.raise_for_status()
                jwks = response.json()
            
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
    """Dependency para extrair e validar usuário do JWT."""
    if not settings.mcp_auth_required:
        return {"sub": "anonymous", "role": "guest", "permissions": ["search:read", "document:read"]}
    
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    
    token = auth_header[7:]
    
    try:
        payload = await jwt_validator.validate(token)
        # Extract permissions from token if available
        realm_access = payload.get("realm_access", {})
        roles = realm_access.get("roles", [])
        payload["permissions"] = _extract_permissions(roles)
        return payload
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")


def _extract_permissions(roles: List[str]) -> List[str]:
    """Extract MCP permissions from Keycloak roles."""
    permissions = []
    role_map = {
        "gabi-search": ["search:read"],
        "gabi-admin": ["search:read", "search:write", "document:read", "document:write", "admin"],
        "gabi-reader": ["search:read", "document:read"],
    }
    for role in roles:
        if role in role_map:
            permissions.extend(role_map[role])
    return list(set(permissions)) or ["search:read", "document:read"]


# =============================================================================
# Rate Limiting
# =============================================================================

class MCPRateLimiter:
    """Rate limiting específico para MCP."""
    
    def __init__(self):
        self._redis = None
        self._local_cache: Dict[str, Dict[str, Any]] = {}
    
    async def check_rate_limit(
        self,
        user_id: str,
        tool_name: Optional[str] = None
    ) -> tuple[bool, Dict[str, Any]]:
        """
        Verifica rate limit para usuário.
        
        Returns:
            Tuple of (is_allowed, metadata)
        """
        try:
            redis_client = await self._get_redis()
            
            # Key format: mcp:ratelimit:{user_id}:{tool_name or "global"}
            key = f"mcp:ratelimit:{user_id}:{tool_name or 'global'}"
            
            # Get current count
            current = await redis_client.incr(key)
            
            # Set expiry on first request
            if current == 1:
                await redis_client.expire(key, 60)  # 1 minute window
            
            # Limits
            tool_limits = {
                "search_exact": 60,
                "search_semantic": 30,
                "search_hybrid": 30,
                "get_document_details": 100,
            }
            limit = tool_limits.get(tool_name, 120)  # Default: 120/min
            
            is_allowed = current <= limit
            remaining = max(0, limit - current)
            
            return is_allowed, {
                "limit": limit,
                "remaining": remaining,
                "window": 60,
            }
            
        except Exception as e:
            logger.warning(f"Rate limit check failed: {e}")
            # Fail open
            return True, {"limit": 0, "remaining": 0, "window": 60}
    
    async def _get_redis(self):
        """Obtém conexão Redis."""
        if self._redis is None:
            try:
                self._redis = get_redis_client()
            except Exception:
                pass
        return self._redis


# =============================================================================
# Audit Logging
# =============================================================================

class MCPAuditLogger:
    """Logger de auditoria para operações MCP."""
    
    async def log_tool_call(
        self,
        session_id: str,
        user_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        success: bool,
        duration_ms: float,
        error: Optional[str] = None
    ):
        """Log tool call para auditoria."""
        try:
            # Sanitize arguments (remove sensitive data)
            safe_args = {k: v for k, v in arguments.items() if k not in ("password", "token", "secret")}
            
            log_entry = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event_type": "mcp_tool_call",
                "session_id": session_id,
                "user_id": user_id,
                "tool_name": tool_name,
                "arguments": safe_args,
                "success": success,
                "duration_ms": duration_ms,
            }
            
            if error:
                log_entry["error"] = error
            
            logger.info(f"MCP Audit: {json.dumps(log_entry)}")
            
            # TODO: Persist to audit database if needed
            
        except Exception as e:
            logger.error(f"Failed to log audit: {e}")


# =============================================================================
# MCP Hybrid Search Server
# =============================================================================

class MCPHybridSearchServer:
    """
    Servidor MCP com busca híbrida.
    
    Endpoints:
    - GET /mcp/sse - Conexão SSE para mensagens do servidor
    - POST /mcp/message - Envio de mensagens do cliente
    - GET /mcp/resources/{resource_uri:path} - Acesso direto a recursos
    
    Capabilities:
    - search_exact: Busca exata por campos
    - search_semantic: Busca semântica
    - search_hybrid: Busca híbrida com RRF
    """
    
    def __init__(self):
        self.tool_manager = get_hybrid_tool_manager()
        self.resource_manager = get_hybrid_resource_manager()
        self.rate_limiter = MCPRateLimiter()
        self.audit_logger = MCPAuditLogger()
        self.sessions: Dict[str, SessionInfo] = {}
        self.message_queues: Dict[str, List[Dict]] = {}
    
    def create_app(self) -> FastAPI:
        """Factory para criar aplicação FastAPI do MCP."""
        
        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncGenerator:
            """Gerencia ciclo de vida."""
            await init_db()
            logger.info("MCP Hybrid Search Server started")
            yield
            await close_db()
            logger.info("MCP Hybrid Search Server stopped")
        
        app = FastAPI(
            title="GABI MCP Hybrid Search Server",
            description="Model Context Protocol Server com busca híbrida para ChatTCU",
            version="2.0.0",
            lifespan=lifespan,
        )
        
        # Middleware
        app.add_middleware(SecurityHeadersMiddleware)
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
        """Health check do servidor MCP."""
        return {
            "status": "healthy",
            "service": "mcp-hybrid-search",
            "version": "2.0.0",
            "sessions": len(self.sessions),
            "capabilities": {
                "tools": ["search_exact", "search_semantic", "search_hybrid", "get_document_details", "list_sources", "get_source_stats"],
                "resources": ["document://", "chunk://", "source://", "search://"]
            }
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
        self.sessions[session_id] = SessionInfo(
            id=session_id,
            user=user,
            created_at=time.time(),
            last_activity=time.time()
        )
        self.message_queues[session_id] = []
        
        logger.info(f"MCP session created: {session_id} (user: {user.get('sub')})")
        
        async def event_generator() -> AsyncGenerator[str, None]:
            """Gera eventos SSE."""
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
                        self.sessions[session_id].last_activity = time.time()
                    
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
        """Sleep que verifica desconexão do cliente."""
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
        """Processa uma requisição JSON-RPC."""
        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params", {})
        
        logger.debug(f"MCP method: {method} (session: {session_id})")
        
        # Update session stats
        if session_id and session_id in self.sessions:
            self.sessions[session_id].request_count += 1
        
        try:
            if method == "initialize":
                return await self._handle_initialize(req_id, params)
            
            elif method == "initialized":
                return None  # Notificação não tem resposta
            
            elif method == "tools/list":
                return await self._handle_tools_list(req_id)
            
            elif method == "tools/call":
                return await self._handle_tools_call(req_id, params, user, session_id)
            
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
        """Handle initialize request."""
        protocol_version = params.get("protocolVersion", "2024-11-05")
        
        result = {
            "protocolVersion": "2025-03-26",
            "capabilities": MCPServerCapabilities().dict(exclude_none=True),
            "serverInfo": {
                "name": "gabi-mcp-hybrid-search",
                "version": "2.0.0"
            }
        }
        
        return self._success_response(req_id, result)
    
    async def _handle_tools_list(self, req_id: Optional[str]) -> Dict[str, Any]:
        """Listar ferramentas disponíveis."""
        tools = self.tool_manager.list_tools()
        return self._success_response(req_id, {"tools": tools})
    
    async def _handle_tools_call(
        self,
        req_id: Optional[str],
        params: Dict[str, Any],
        user: Dict[str, Any],
        session_id: Optional[str]
    ) -> Dict[str, Any]:
        """Executar ferramenta com rate limiting e auditoria."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        user_id = user.get("sub", "anonymous")
        
        start_time = time.time()
        
        # Check permissions
        permissions = user.get("permissions", [])
        required_perm = f"{tool_name.split('_')[0]}:read" if "search" in tool_name else "document:read"
        if required_perm not in permissions and "admin" not in permissions:
            return self._error_response(
                req_id, -32001, f"Permission denied: {required_perm} required"
            )
        
        # Rate limiting
        is_allowed, rate_meta = await self.rate_limiter.check_rate_limit(user_id, tool_name)
        if not is_allowed:
            return self._error_response(
                req_id, -32002, f"Rate limit exceeded for {tool_name}"
            )
        
        try:
            result = await self.tool_manager.execute_tool(
                tool_name=tool_name,
                arguments=arguments,
                user=user
            )
            
            duration_ms = (time.time() - start_time) * 1000
            
            # Log audit
            await self.audit_logger.log_tool_call(
                session_id=session_id or "unknown",
                user_id=user_id,
                tool_name=tool_name,
                arguments=arguments,
                success=not result.get("isError", False),
                duration_ms=duration_ms
            )
            
            # Update session
            if session_id and session_id in self.sessions:
                self.sessions[session_id].tools_called.add(tool_name)
            
            # Add rate limit headers to result metadata
            if "content" in result and result["content"]:
                for content_item in result["content"]:
                    if content_item.get("type") == "text":
                        try:
                            data = json.loads(content_item["text"])
                            data["_meta"] = {
                                "rate_limit": rate_meta,
                                "duration_ms": round(duration_ms, 2)
                            }
                            content_item["text"] = json.dumps(data, indent=2, ensure_ascii=False)
                        except json.JSONDecodeError:
                            pass
                        break
            
            return self._success_response(req_id, result)
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            
            await self.audit_logger.log_tool_call(
                session_id=session_id or "unknown",
                user_id=user_id,
                tool_name=tool_name,
                arguments=arguments,
                success=False,
                duration_ms=duration_ms,
                error=str(e)
            )
            
            logger.error(f"Tool execution failed: {e}")
            return self._error_response(req_id, -32603, str(e))
    
    async def _handle_resources_list(self, req_id: Optional[str]) -> Dict[str, Any]:
        """Listar recursos disponíveis."""
        resources = self.resource_manager.list_resources()
        return self._success_response(req_id, {"resources": resources})
    
    async def _handle_resources_read(
        self,
        req_id: Optional[str],
        params: Dict[str, Any],
        user: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Ler recurso."""
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
        """Endpoint HTTP direto para recursos."""
        try:
            result = await self.resource_manager.read_resource(resource_uri, user)
            return JSONResponse(content=result)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    def _success_response(self, id: Optional[str], result: Any) -> Dict[str, Any]:
        """Cria resposta de sucesso JSON-RPC."""
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
        """Cria resposta de erro JSON-RPC."""
        return {
            "jsonrpc": "2.0",
            "id": id,
            "error": {
                "code": code,
                "message": message
            }
        }
    
    def send_notification(self, session_id: str, method: str, params: Dict):
        """Envia notificação para sessão."""
        if session_id in self.message_queues:
            self.message_queues[session_id].append({
                "jsonrpc": "2.0",
                "method": method,
                "params": params
            })


# =============================================================================
# Singleton e Factory
# =============================================================================

_mcp_server: Optional[MCPHybridSearchServer] = None


def get_mcp_server() -> MCPHybridSearchServer:
    """Factory para MCP server singleton."""
    global _mcp_server
    if _mcp_server is None:
        _mcp_server = MCPHybridSearchServer()
    return _mcp_server


def create_mcp_hybrid_app() -> FastAPI:
    """Factory pública para criar app MCP híbrida."""
    server = get_mcp_server()
    return server.create_app()


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    app = create_mcp_hybrid_app()
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.mcp_port,
        log_level=settings.log_level.lower(),
    )
