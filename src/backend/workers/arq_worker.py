"""
ARQ worker for GABI. Connects to Redis via REDIS_URL, runs tasks (Phase 4: test task; Phase 5+: upload job processing).

Run worker:
  arq src.backend.workers.arq_worker.WorkerSettings

Enqueue: process_upload_job(job_id) after POST /api/admin/upload creates a job.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from arq.connections import RedisSettings

from src.backend.apps.worker_jobs import claim_job_for_processing, update_job_status
from src.backend.ingest.dou_ingest import DOUIngestor, ZIPIngestResult
from src.backend.ingest.es_indexer import _DEFAULT_CURSOR_PATH, _run_sync
from src.backend.storage import download_to_path, is_configured as storage_is_configured


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


async def process_upload_job(ctx: dict, job_id: str) -> None:
    """
    Process one upload job: claim, download from Tigris, ingest (XML or ZIP), sync to ES, update job.
    Phase 5: single XML; Phase 6 will extend for ZIP partial success.
    """
    claimed = claim_job_for_processing(job_id)
    if not claimed:
        return  # Job not queued (already taken or invalid)
    storage_key = claimed["storage_key"]
    file_type = claimed["file_type"]

    if not storage_is_configured():
        update_job_status(
            job_id,
            "failed",
            error_message="Tigris not configured; cannot download file",
        )
        raise RuntimeError("Tigris not configured")

    with tempfile.TemporaryDirectory(prefix="gabi_upload_") as tmpdir:
        local_dir = Path(tmpdir)
        local_path = local_dir / Path(storage_key).name
        try:
            download_to_path(storage_key, local_path)
        except Exception as e:
            update_job_status(
                job_id,
                "failed",
                error_message=f"Download failed: {e}",
            )
            raise

        ingestor = DOUIngestor(_dsn())
        result: ZIPIngestResult
        if file_type == "xml":
            result = ingestor.ingest_single_xml(local_path)
        elif file_type == "zip":
            result = ingestor.ingest_zip(local_path)
        else:
            update_job_status(
                job_id,
                "failed",
                error_message=f"Unsupported file_type: {file_type}",
            )
            return

        if not result.success:
            err_msg = "; ".join(result.errors[:5]) or "Ingest failed"
            if len(result.errors) > 5:
                err_msg += f" (+{len(result.errors) - 5} more)"
            update_job_status(
                job_id,
                "failed",
                articles_found=result.articles_found,
                articles_ingested=result.documents_inserted,
                articles_failed=len(result.errors),
                error_message=err_msg,
            )
            return

        # Sync new docs to Elasticsearch
        try:
            _run_sync(
                reset_cursor=False,
                recreate_index=False,
                batch_size=500,
                cursor_path=Path(_DEFAULT_CURSOR_PATH),
            )
        except Exception as e:
            update_job_status(
                job_id,
                "failed",
                articles_found=result.articles_found,
                articles_ingested=result.documents_inserted,
                error_message=f"ES sync failed: {e}",
            )
            raise

        articles_dup = max(0, result.articles_found - result.documents_inserted - len(result.errors))
        update_job_status(
            job_id,
            "completed",
            articles_found=result.articles_found,
            articles_ingested=result.documents_inserted,
            articles_dup=articles_dup,
            articles_failed=len(result.errors),
        )


def _redis_settings() -> RedisSettings:
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0").strip()
    return RedisSettings.from_dsn(url)


class WorkerSettings:
    """ARQ worker config. Used by CLI: arq src.backend.workers.arq_worker.WorkerSettings."""
    functions = [test_task, process_upload_job]
    redis_settings = _redis_settings()
