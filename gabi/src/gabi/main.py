from contextlib import asynccontextmanager

from fastapi import FastAPI

from gabi.config import Settings
from gabi.config import settings as default_settings

__version__ = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print(f"Starting GABI v{__version__}")
    yield
    # Shutdown
    print("Shutting down GABI")


def create_application(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    This factory function allows for dependency injection of custom settings,
    which is useful for testing with different configurations.

    Args:
        settings: Optional custom settings. If not provided, uses default settings.

    Returns:
        Configured FastAPI application instance.
    """
    app_settings = settings or default_settings

    app = FastAPI(
        title="GABI",
        description="Gerador Automático de Boletins por Inteligência Artificial",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if app_settings.debug else None,
        redoc_url="/redoc" if app_settings.debug else None,
    )

    # Include routers (when they exist)
    # from gabi.api.router import api_router
    # app.include_router(api_router, prefix="/api/v1")

    return app


# Default application instance
app = create_application()


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": __version__}


@app.get("/health/ready")
async def readiness_check():
    return {"status": "ready"}


@app.get("/health/live")
async def liveness_check():
    return {"status": "alive"}
