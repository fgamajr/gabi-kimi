"""Worker entrypoint — FastAPI + APScheduler + internal API.

Starts FastAPI on port 8081 with APScheduler running cron jobs for the
DOU ingestion pipeline. Only accessible via Fly.io internal network.
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import FastAPI

from src.backend.worker.registry import Registry
from src.backend.worker.scheduler import (
    configure_scheduler,
    scheduler,
    set_registry,
)
from src.backend.worker.snapshots import register_snapshot_repo

logger = logging.getLogger(__name__)

_start_time: float = 0.0
_last_heartbeat: str = ""


async def _heartbeat() -> None:
    """Log heartbeat for dashboard health monitoring."""
    global _last_heartbeat
    _last_heartbeat = datetime.now(timezone.utc).isoformat()
    logger.debug("heartbeat")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown lifecycle for the worker application."""
    global _start_time

    # Init registry
    db_path = os.environ.get("REGISTRY_DB_PATH", "/data/registry.db")
    registry = Registry(db_path=db_path)
    await registry.init_db()
    set_registry(registry)

    # Set registry on API module for route handlers
    import src.backend.worker.api as api_mod
    api_mod._registry = registry

    logger.info("Registry initialized at %s", db_path)

    # Register ES snapshot repo (non-blocking, warn on failure)
    es_url = os.environ.get("ES_URL", "http://es.internal:9200")
    await register_snapshot_repo(es_url)

    # Configure and start scheduler
    configure_scheduler()

    # Add heartbeat every 60s
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler.add_job(
        _heartbeat, IntervalTrigger(seconds=60),
        id="heartbeat", replace_existing=True, max_instances=1,
    )

    scheduler.start()
    _start_time = time.monotonic()
    logger.info("Worker started with %d scheduled jobs", len(scheduler.get_jobs()))

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("Worker stopped")


app = FastAPI(title="GABI Worker Internal API", lifespan=lifespan)

# Import and include API router
from src.backend.worker.api import router  # noqa: E402

app.include_router(router)


def get_uptime_seconds() -> float:
    """Return seconds since worker started."""
    if _start_time == 0.0:
        return 0.0
    return time.monotonic() - _start_time


def get_last_heartbeat() -> str:
    """Return ISO timestamp of last heartbeat."""
    return _last_heartbeat


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.backend.worker.main:app",
        host="0.0.0.0",
        port=8081,
    )
