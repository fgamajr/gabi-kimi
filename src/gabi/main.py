"""FastAPI app factory com lifespan manager e middlewares."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from gabi.api.health import router as health_router
from gabi.api.router import get_api_router
from gabi.auth.middleware import AuthMiddleware, DevAuthMiddleware
from gabi.config import Environment, settings
from gabi.db import close_db, init_db
from gabi.logging_config import setup_logging
from gabi.middleware.rate_limit import RateLimitMiddleware
from gabi.middleware.request_id import RequestIDMiddleware, get_request_id
from gabi.middleware.security_headers import SecurityHeadersMiddleware
from gabi.exceptions import GABIException


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Gerencia ciclo de vida da aplicação.
    
    Startup:
        - Inicializa logging estruturado
        - Inicializa conexões com banco de dados
        - Valida configurações críticas
    
    Shutdown:
        - Fecha conexões com banco de dados
        - Libera recursos
    """
    # Startup
    setup_logging()
    await init_db()
    
    yield
    
    # Shutdown
    await close_db()


def create_app() -> FastAPI:
    """Factory para criar aplicação FastAPI.
    
    Configura:
        - Lifespan manager
        - Métricas Prometheus
        - Middlewares (ordem de execução)
        - Routers
        - Error handlers
    
    Returns:
        Aplicação FastAPI configurada
    """
    
    app = FastAPI(
        title="GABI API",
        description="Gerador Automático de Boletins por IA - TCU",
        version="2.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != Environment.PRODUCTION else None,
        redoc_url="/redoc" if settings.environment != Environment.PRODUCTION else None,
        openapi_url="/openapi.json" if settings.environment != Environment.PRODUCTION else None,
    )
    
    # Métricas Prometheus (antes dos middlewares para evitar overhead)
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)
    
    # =============================================================================
    # Middlewares (ordem importante - primeiro adicionado = primeiro a executar)
    # =============================================================================
    
    # 1. Request ID - Gera correlation ID para tracing
    app.add_middleware(RequestIDMiddleware)
    
    # 2. Security Headers - Adiciona headers de segurança
    app.add_middleware(SecurityHeadersMiddleware)
    
    # 3. Trusted Host (produção apenas)
    if settings.environment == Environment.PRODUCTION:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=["*.tcu.gov.br", "gabi.tcu.gov.br"]
        )
    
    # 4. CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods_list,
        allow_headers=settings.cors_allow_headers_list,
    )
    
    # 5. Rate Limiting
    if settings.rate_limit_enabled:
        app.add_middleware(RateLimitMiddleware)
    
    # 6. Auth (obrigatório em produção)
    if settings.auth_enabled:
        app.add_middleware(
            AuthMiddleware,
            public_paths=settings.auth_public_paths
        )
    else:
        # Dev mode: inject fake admin user so RequireAuth doesn't 401
        app.add_middleware(DevAuthMiddleware)
    
    # =============================================================================
    # Routers
    # =============================================================================

    # Expose health endpoints without API prefix for probes (/health, /health/live, /health/ready)
    app.include_router(health_router)
    app.include_router(get_api_router())
    
    # =============================================================================
    # Error Handlers
    # =============================================================================
    
    @app.exception_handler(GABIException)
    async def gabi_exception_handler(request, exc: GABIException):
        """Handle GABI-specific exceptions with proper error codes."""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                    "request_id": get_request_id(),
                }
            }
        )
    
    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        """Handler global para exceções não tratadas."""
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "request_id": get_request_id(),
            }
        )
    
    return app


# Instância global da aplicação
app = create_app()


def main() -> None:
    """Entry point do servidor API para scripts de console."""
    uvicorn.run(
        "gabi.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
        workers=settings.api_workers if not settings.api_reload else 1,
    )


if __name__ == "__main__":
    main()
