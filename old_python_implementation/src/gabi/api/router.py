"""Agregador de routers FastAPI para GABI.

Este módulo centraliza todos os routers da API, incluindo:
- search: Busca híbrida (BM25 + vetorial)
- documents: Gerenciamento de documentos
- sources: Configuração de fontes de dados
- health: Health checks e readiness
- admin: Administração e operações internas

Uso:
    >>> from fastapi import FastAPI
    >>> from gabi.api.router import include_all_routers
    >>> app = FastAPI()
    >>> include_all_routers(app)
"""

from fastapi import APIRouter, FastAPI

# Import routers
from gabi.api.search import router as search_router
from gabi.api.health import router as health_router
from gabi.api.documents import router as documents_router
from gabi.api.sources import router as sources_router
from gabi.api.admin import router as admin_router
from gabi.api.dashboard import router as dashboard_router
from gabi.api.dashboard_extended import router as dashboard_extended_router
from gabi.api.pipeline_control import router as pipeline_control_router


# =============================================================================
# Routers disponíveis
# =============================================================================

# Router principal da API v1
api_v1_router = APIRouter(prefix="/api/v1")

# Registro de routers
ROUTERS = [
    search_router,
    health_router,
    documents_router,
    sources_router,
    admin_router,
    dashboard_router,
    pipeline_control_router,
]


def include_all_routers(app: FastAPI) -> None:
    """Inclui todos os routers na aplicação FastAPI.
    
    Args:
        app: Instância da aplicação FastAPI
        
    Example:
        >>> app = FastAPI()
        >>> include_all_routers(app)
    """
    for router in ROUTERS:
        app.include_router(router)


def get_api_router() -> APIRouter:
    """Retorna o router principal da API v1 com todos os sub-routers.

    Returns:
        APIRouter configurado com todos os sub-routers

    Example:
        >>> api_router = get_api_router()
        >>> app.include_router(api_router)
    """
    router = APIRouter(prefix="/api/v1")

    # Inclui routers com seus prefixos
    router.include_router(search_router, prefix="/search")
    router.include_router(documents_router, prefix="/documents")
    router.include_router(sources_router, prefix="/sources")
    router.include_router(admin_router, prefix="/admin")
    router.include_router(dashboard_router, prefix="/dashboard")
    router.include_router(dashboard_extended_router, prefix="/dashboard")
    router.include_router(pipeline_control_router, prefix="/pipeline-control")
    # Health router sem prefixo adicional (já tem /health nas rotas)
    router.include_router(health_router)

    return router


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Funções
    "include_all_routers",
    "get_api_router",
    # Routers individuais
    "search_router",
    "documents_router",
    "sources_router",
    "health_router",
    "admin_router",
    "dashboard_router",
    "pipeline_control_router",
    # Router agregado
    "api_v1_router",
]
