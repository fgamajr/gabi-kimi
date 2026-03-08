"""
ARQ worker for GABI. Connects to Redis via REDIS_URL, runs tasks (Phase 4: test task; Phase 5+: upload job processing).

Run worker:
  arq src.backend.workers.arq_worker.WorkerSettings

Enqueue test task (e.g. from Python):
  from arq import create_pool
  from arq.connections import RedisSettings
  redis = await create_pool(RedisSettings.from_dsn(os.environ["REDIS_URL"]))
  await redis.enqueue_job("test_task", "hello")
"""
from __future__ import annotations

import os

from arq.connections import RedisSettings


async def test_task(ctx: dict, msg: str) -> str:
    """
    Test task for Phase 4: worker runs and executes a job.
    Returns a string so enqueue_job can verify execution.
    """
    return f"echo: {msg}"


def _redis_settings() -> RedisSettings:
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0").strip()
    return RedisSettings.from_dsn(url)


class WorkerSettings:
    """ARQ worker config. Used by CLI: arq src.backend.workers.arq_worker.WorkerSettings."""
    functions = [test_task]
    redis_settings = _redis_settings()
