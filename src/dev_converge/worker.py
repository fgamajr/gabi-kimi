from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from src.dev_converge.executor import execute_job
from src.dev_converge.jobs import complete_job, expire_old_jobs, fail_job
from src.dev_converge.providers import AgentSpec

logger = logging.getLogger(__name__)

_job_queue: asyncio.Queue[_JobTask] = asyncio.Queue()


@dataclass
class _JobTask:
    job_id: str
    job_type: str
    payload: dict[str, Any]
    catalog: list[AgentSpec]


def enqueue_job(
    job_id: str,
    job_type: str,
    payload: dict[str, Any],
    catalog: list[AgentSpec],
) -> None:
    """Enqueue a job for in-process async execution. Non-blocking."""
    _job_queue.put_nowait(
        _JobTask(job_id=job_id, job_type=job_type, payload=payload, catalog=catalog)
    )


async def _process_one(task: _JobTask) -> None:
    logger.info("Processing dev-converge job %s (%s)", task.job_id, task.job_type)
    try:
        result = await execute_job(task.job_type, task.payload, task.catalog)
        complete_job(task.job_id, result)
        logger.info("Completed dev-converge job %s", task.job_id)
    except Exception as exc:
        logger.exception("Dev-converge job %s failed", task.job_id)
        fail_job(task.job_id, str(exc))


async def run_worker_loop() -> None:
    """Long-running coroutine that drains the in-memory job queue."""
    while True:
        task = await _job_queue.get()
        asyncio.create_task(_process_one(task))
        _job_queue.task_done()


async def run_maintenance_loop(interval_sec: int = 3600) -> None:
    """Periodically expire old completed jobs."""
    while True:
        await asyncio.sleep(interval_sec)
        try:
            expired = expire_old_jobs()
            if expired:
                logger.info("Expired %s old dev-converge jobs", expired)
        except Exception as exc:
            logger.warning("Job expiry failed: %s", exc)
