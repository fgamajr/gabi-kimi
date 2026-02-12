"""API - Endpoints FastAPI para GABI."""

from gabi.api.router import (
    include_all_routers,
    get_api_router,
    api_v1_router,
)

from gabi.api.search import router as search_router
from gabi.api.health import router as health_router
from gabi.api.documents import router as documents_router
from gabi.api.sources import router as sources_router
from gabi.api.admin import router as admin_router

__all__ = [
    # Router utilities
    "include_all_routers",
    "get_api_router",
    "api_v1_router",
    # Individual routers
    "search_router",
    "health_router",
    "documents_router",
    "sources_router",
    "admin_router",
]
