"""
ARQ worker for GABI. Connects to Redis via REDIS_URL, runs tasks (Phase 4: test task; Phase 5+: upload job processing).

Run worker:
  arq src.backend.workers.arq_worker.WorkerSettings

Enqueue: process_upload_job(job_id) after POST /api/admin/upload creates a job.
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

load_dotenv()
import tempfile
from pathlib import Path

from arq.connections import RedisSettings
from arq.worker import Retry

from src.backend.apps.analytics_cache import refresh_analytics_cache
from src.backend.apps.db_pool import init_pool, close_pool
from src.backend.apps.worker_jobs import claim_job_for_processing, schedule_job_retry, update_job_status
from src.backend.ingest.dou_ingest import DOUIngestor, ZIPIngestResult
from src.backend.ingest.es_indexer import _DEFAULT_CURSOR_PATH, _run_sync
from src.backend.storage import download_to_path, is_configured as storage_is_configured

_RETRY_BASE_SECONDS = max(1, int(os.getenv("GABI_ADMIN_UPLOAD_RETRY_BASE_SECONDS", "30")))
_RETRY_MAX_SECONDS = max(_RETRY_BASE_SECONDS, int(os.getenv("GABI_ADMIN_UPLOAD_RETRY_MAX_SECONDS", "900")))
_ARQ_MAX_TRIES = max(5, int(os.getenv("GABI_ADMIN_UPLOAD_ARQ_MAX_TRIES", "10")))


def _dsn() -> str:
    return os.getenv("PG_DSN") or (
        f"host={os.getenv('PGHOST', 'localhost')} "
        f"port={os.getenv('PGPORT', '5433')} "
        f"dbname={os.getenv('PGDATABASE', 'gabi')} "
        f"user={os.getenv('PGUSER', 'gabi')} "
        f"password={os.getenv('PGPASSWORD', 'gabi')}"
    )


async def test_task(ctx: dict, msg: str) -> str:
    """Test task for Phase 4."""
    return f"echo: {msg}"


def _error_summary(errors: list[str]) -> str:
    msg = "; ".join(errors[:5]) or "Ingest failed"
    if len(errors) > 5:
        msg += f" (+{len(errors) - 5} more)"
    return msg


def _retry_delay_seconds(retry_count: int) -> int:
    return min(_RETRY_MAX_SECONDS, _RETRY_BASE_SECONDS * (2 ** max(0, retry_count)))


def classify_ingest_failure(result: ZIPIngestResult) -> str:
    if result.parse_errors > 0 and result.articles_found == 0:
        return "permanent"
    if result.xml_count == 0:
        return "permanent"
    joined = " | ".join(result.errors).lower()
    if "open zip:" in joined or "zip slip rejected" in joined:
        return "permanent"
    if any(err.startswith("parse ") for err in result.errors):
        return "permanent"
    if any(err.startswith("transaction:") for err in result.errors):
        return "transient"
    return "permanent"


async def _schedule_transient_retry(
    job_id: str,
    *,
    claimed: dict[str, Any],
    error_message: str,
    error_detail: dict[str, Any],
    articles_found: int | None = None,
    articles_ingested: int | None = None,
    articles_dup: int | None = None,
    articles_failed: int | None = None,
) -> None:
    delay_seconds = _retry_delay_seconds(int(claimed.get("retry_count") or 0))
    scheduled = await schedule_job_retry(
        job_id,
        backoff_seconds=delay_seconds,
        error_message=error_message,
        error_detail=error_detail,
        articles_found=articles_found,
        articles_ingested=articles_ingested,
        articles_dup=articles_dup,
        articles_failed=articles_failed,
    )
    if not scheduled:
        return
    if scheduled["status"] == "queued":
        raise Retry(defer=delay_seconds)


async def process_upload_job(ctx: dict, job_id: str) -> None:
    """
    Process one upload job: claim, download from Tigris, ingest (XML or ZIP), sync to ES, update job.
    Phase 5: single XML; Phase 6 will extend for ZIP partial success.
    """
    claimed = await claim_job_for_processing(job_id)
    if not claimed:
        return  # Job not queued (already taken or invalid)
    storage_key = claimed["storage_key"]
    file_type = claimed["file_type"]

    if not storage_is_configured():
        await update_job_status(
            job_id,
            "failed",
            error_message="Tigris not configured; cannot download file",
            failure_class="permanent",
        )
        return

    with tempfile.TemporaryDirectory(prefix="gabi_upload_") as tmpdir:
        local_dir = Path(tmpdir)
        local_path = local_dir / Path(storage_key).name
        try:
            download_to_path(storage_key, local_path)
        except Exception as e:
            await _schedule_transient_retry(
                job_id,
                claimed=claimed,
                error_message=f"Download failed: {e}",
                error_detail={"stage": "download", "exception": type(e).__name__},
            )
            return

        ingestor = DOUIngestor(_dsn())
        result: ZIPIngestResult
        if file_type == "xml":
            result = ingestor.ingest_single_xml(local_path)
        elif file_type == "zip":
            result = ingestor.ingest_zip(local_path)
        else:
            await update_job_status(
                job_id,
                "failed",
                error_message=f"Unsupported file_type: {file_type}",
                failure_class="permanent",
            )
            return

        if not result.success:
            err_msg = _error_summary(result.errors)
            failure_class = classify_ingest_failure(result)
            if failure_class == "transient":
                await _schedule_transient_retry(
                    job_id,
                    claimed=claimed,
                    error_message=err_msg,
                    error_detail={
                        "stage": "ingest",
                        "failure_class": failure_class,
                        "parse_errors": result.parse_errors,
                        "errors": result.errors[:10],
                    },
                    articles_found=result.articles_found,
                    articles_ingested=result.documents_inserted,
                    articles_dup=result.documents_dup,
                    articles_failed=result.documents_failed,
                )
                return
            await update_job_status(
                job_id,
                "failed",
                articles_found=result.articles_found,
                articles_ingested=result.documents_inserted,
                articles_dup=result.documents_dup,
                articles_failed=result.documents_failed,
                error_message=err_msg,
                error_detail={
                    "stage": "ingest",
                    "failure_class": failure_class,
                    "parse_errors": result.parse_errors,
                    "errors": result.errors[:10],
                },
                failure_class="permanent",
            )
            return

        # Partial success (PROC-05): some articles failed but others ingested
        is_partial = result.documents_failed > 0 and result.documents_inserted > 0
        status = "partial" if is_partial else "completed"
        err_msg = None
        if is_partial or result.documents_failed > 0:
            err_msg = "; ".join(result.errors[:5]) or "Some articles failed"
            if len(result.errors) > 5:
                err_msg += f" (+{len(result.errors) - 5} more)"

        # Sync new docs to Elasticsearch
        try:
            _run_sync(
                reset_cursor=False,
                recreate_index=False,
                batch_size=500,
                cursor_path=Path(_DEFAULT_CURSOR_PATH),
            )
        except Exception as e:
            await _schedule_transient_retry(
                job_id,
                claimed=claimed,
                error_message=f"ES sync failed: {e}",
                error_detail={"stage": "es_sync", "exception": type(e).__name__},
                articles_found=result.articles_found,
                articles_ingested=result.documents_inserted,
                articles_dup=result.documents_dup,
                articles_failed=result.documents_failed,
            )
            return

        try:
            await refresh_analytics_cache(source="worker")
        except Exception:
            # Analytics cache refresh should not fail the ingest job.
            pass

        await update_job_status(
            job_id,
            status,
            articles_found=result.articles_found,
            articles_ingested=result.documents_inserted,
            articles_dup=result.documents_dup,
            articles_failed=result.documents_failed,
            error_message=err_msg,
            error_detail={
                "stage": "ingest",
                "warnings": result.errors[:10],
                "parse_errors": result.parse_errors,
            }
            if err_msg
            else None,
        )


async def _on_startup(ctx: dict) -> None:
    await init_pool()


async def _on_shutdown(ctx: dict) -> None:
    await close_pool()


def _redis_settings() -> RedisSettings:
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0").strip()
    return RedisSettings.from_dsn(url)


class WorkerSettings:
    """ARQ worker config. Used by CLI: arq src.backend.workers.arq_worker.WorkerSettings."""

    functions = [test_task, process_upload_job]
    on_startup = _on_startup
    on_shutdown = _on_shutdown
    redis_settings = _redis_settings()
    max_tries = _ARQ_MAX_TRIES
