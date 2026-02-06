from contextlib import asynccontextmanager
from fastapi import FastAPI
from gabi.config import settings

__version__ = "0.1.0"

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print(f"Starting GABI v{__version__}")
    yield
    # Shutdown
    print("Shutting down GABI")

app = FastAPI(
    title="GABI",
    description="Gerador Automático de Boletins por Inteligência Artificial",
    version=__version__,
    lifespan=lifespan,
)

@app.get("/health")
async def health_check():
    return {"status": "ok", "version": __version__}

@app.get("/health/ready")
async def readiness_check():
    return {"status": "ready"}

@app.get("/health/live")
async def liveness_check():
    return {"status": "alive"}
