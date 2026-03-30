from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from src.dev_converge.config import settings
from src.dev_converge.jobs import ensure_indexes, mark_running_as_failed, queue_stats
from src.dev_converge.mcp_server import get_mcp_sse_app, get_mcp_streamable_app
from src.dev_converge.worker import run_maintenance_loop, run_worker_loop

logger = logging.getLogger(__name__)

_mcp_http_session_mgr = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_indexes()
    lost = mark_running_as_failed("service_restart: in-flight jobs are not resumable")
    if lost:
        logger.warning(
            "Marked %s in-flight dev-converge jobs as failed after restart", lost
        )

    worker_task = asyncio.create_task(run_worker_loop())
    maintenance_task = asyncio.create_task(run_maintenance_loop())

    if _mcp_http_session_mgr is not None:
        async with _mcp_http_session_mgr.run():
            logger.info("Dev-converge MCP Streamable HTTP session manager started")
            yield
    else:
        yield

    worker_task.cancel()
    maintenance_task.cancel()


app = FastAPI(
    title="Dev Converge",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

if settings.allowed_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

_mcp_app = get_mcp_sse_app()
if _mcp_app:
    app.mount("/mcp", _mcp_app)
    logger.info("Dev-converge MCP SSE endpoint mounted at /mcp/")

_mcp_http_result = get_mcp_streamable_app()
if _mcp_http_result:
    _mcp_http_app, _mcp_http_session_mgr = _mcp_http_result
    app.mount("/mcp-http", _mcp_http_app)
    logger.info("Dev-converge MCP Streamable HTTP endpoint mounted at /mcp-http/")


@app.get("/api/live")
async def live() -> dict[str, str]:
    return {"status": "live"}


@app.get("/api/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "queue": queue_stats(),
        "sync_timeout_sec": settings.DEV_CONVERGE_SYNC_TIMEOUT_SEC,
        "job_retention_hours": settings.DEV_CONVERGE_JOB_RETENTION_HOURS,
        "providers": ["openai_compatible", "anthropic_compatible", "gemini_compatible"],
    }
