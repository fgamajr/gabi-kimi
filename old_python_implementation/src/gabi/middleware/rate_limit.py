"""Rate limiting por IP/usuário."""

import hashlib
from typing import Callable, Optional

import redis.asyncio as redis
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from gabi.config import settings


# Lua script for atomic increment and expire
# This prevents race conditions where multiple concurrent requests
# could all see the same count before expiry is set
INCR_AND_EXPIRE = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting baseado em Redis (sliding window).
    
    Prioridade de identificação:
    1. User ID (se autenticado)
    2. X-API-Key header (hashed)
    3. X-Forwarded-For header (only from trusted proxies)
    4. Client host
    5. "unknown"
    """
    
    def __init__(
        self,
        app: ASGIApp,
        redis_client: Optional[redis.Redis] = None,
    ) -> None:
        super().__init__(app)
        self._redis: Optional[redis.Redis] = redis_client
        self._public_paths = {
            "/health",
            "/health/live",
            "/health/ready",
            "/api/v1/health",
            "/api/v1/health/live",
            "/api/v1/health/ready",
            "/metrics",
        }
        self._lua_sha: Optional[str] = None
    
    async def dispatch(self, request: Request, call_next: Callable) -> JSONResponse:
        """Processa request aplicando rate limit."""
        path = request.url.path
        
        # Ignorar paths públicos
        if path in self._public_paths or path.startswith("/health") or path.startswith("/api/v1/health"):
            return await call_next(request)
        
        # Rate limiting desabilitado
        if not settings.rate_limit_enabled:
            return await call_next(request)
        
        redis_client = await self._get_redis()
        if not redis_client:
            # Sem Redis, comportamento configurável (fail-closed por padrão)
            if settings.rate_limit_fail_closed:
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": "Service Unavailable",
                        "message": "Rate limiting service temporarily unavailable. Please try again later.",
                    },
                )
            # Fail-open: permite request quando Redis indisponível (legado)
            return await call_next(request)
        
        # Identificar cliente
        client_id = self._get_client_id(request)
        key = f"gabi:ratelimit:{client_id}"
        
        # Verificar e incrementar contador (atômico)
        is_allowed, current_count = await self._check_limit(redis_client, key)
        
        if not is_allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "message": f"Too many requests. Limit: {settings.rate_limit_requests_per_minute} per minute",
                    "retry_after": settings.rate_limit_window_seconds,
                },
                headers={
                    "Retry-After": str(settings.rate_limit_window_seconds),
                    "X-RateLimit-Limit": str(settings.rate_limit_requests_per_minute),
                    "X-RateLimit-Window": str(settings.rate_limit_window_seconds),
                },
            )
        
        response = await call_next(request)
        
        # Adicionar headers de rate limit na resposta
        if hasattr(response, "headers"):
            remaining = max(0, settings.rate_limit_requests_per_minute - int(current_count))
            response.headers["X-RateLimit-Limit"] = str(settings.rate_limit_requests_per_minute)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
        
        return response
    
    async def _get_redis(self) -> Optional[redis.Redis]:
        """Obtém ou cria conexão Redis."""
        if self._redis is None:
            try:
                from gabi.db import get_redis_client
                self._redis = get_redis_client()
            except Exception:
                return None
        return self._redis
    
    async def _check_limit(self, redis_client: redis.Redis, key: str) -> tuple[bool, int]:
        """Verifica se request está dentro do limite usando operação atômica.
        
        Returns:
            Tuple of (is_allowed, current_count)
            - is_allowed: True se permitido, False se excedeu limite
            - current_count: contador atual do rate limit
        """
        try:
            # Register Lua script on first use
            if self._lua_sha is None:
                self._lua_sha = await redis_client.script_load(INCR_AND_EXPIRE)
            
            # Execute atomic increment and expire
            current_count = await redis_client.evalsha(
                self._lua_sha,
                1,  # num_keys
                key,
                settings.rate_limit_window_seconds,
            )
            current_count = int(current_count)
            
            # Burst protection: permite burst inicial
            if current_count <= settings.rate_limit_burst:
                return True, current_count
            
            # Verifica limite total
            is_allowed = current_count <= settings.rate_limit_requests_per_minute
            return is_allowed, current_count
            
        except Exception:
            # Em caso de erro no Redis, comportamento configurável
            if settings.rate_limit_fail_closed:
                return False, 0
            # Fail-open: permite request em caso de erro (legado)
            return True, 0
    
    def _get_client_id(self, request: Request) -> str:
        """Extrai identificador único do cliente."""
        # Prioridade 1: User ID autenticado
        user_id = getattr(request.state, "user_id", None)
        if user_id:
            return f"user:{user_id}"
        
        # Prioridade 2: API Key (hash para não expor valor parcial)
        api_key = request.headers.get("X-API-Key")
        if api_key:
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
            return f"apikey:{key_hash}"
        
        # Prioridade 3: IP via X-Forwarded-For (apenas de proxies confiáveis)
        client_host = request.client.host if request.client else ""
        if client_host and self._is_trusted_proxy(client_host):
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                # Pega o primeiro IP da lista (cliente original)
                ip = forwarded.split(",")[0].strip()
                return f"ip:{ip}"
        
        # Prioridade 4: Client host direto
        if client_host:
            return f"ip:{client_host}"
        
        return "ip:unknown"
    
    def _is_trusted_proxy(self, client_host: str) -> bool:
        """Verifica se o client_host é um proxy confiável.
        
        Args:
            client_host: O endereço IP do cliente direto (conexão TCP)
            
        Returns:
            True se o client_host está na lista de proxies confiáveis
        """
        if not settings.trusted_proxies:
            return False
        
        # Normalize para comparação (remover porta se presente)
        host = client_host.split(":")[0] if ":" in client_host else client_host
        
        return host in settings.trusted_proxies
