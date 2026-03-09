"""Admin upload job lifecycle (admin.worker_jobs). Queryable from FastAPI, status transitions enforced."""
from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

from src.backend.apps.db_pool import acquire

_ROOT_DIR = Path(__file__).resolve().parents[3]
WORKER_JOBS_SCHEMA_SQL = _ROOT_DIR / "src" / "backend" / "dbsync" / "worker_jobs_schema.sql"

VALID_STATUSES = frozenset({"queued", "processing", "completed", "failed", "partial"})
VALID_FAILURE_CLASSES = frozenset({"permanent", "transient"})
TRANSITIONS = {
    "queued": {"processing"},
    "processing": {"completed", "failed", "partial"},
    "completed": set(),
    "failed": set(),
    "partial": set(),
}

_JOB_COLUMNS = """
    id::text AS id,
    created_at,
    updated_at,
    filename,
    storage_key,
    file_size_bytes,
    file_type,
    uploaded_by,
    status,
    articles_found,
    articles_ingested,
    articles_dup,
    articles_failed,
    error_message,
    error_detail,
    retry_count,
    max_retries,
    next_retry_at,
    failure_class,
    completed_at
"""


def _default_max_retries() -> int:
    raw = os.getenv("GABI_ADMIN_UPLOAD_MAX_RETRIES", "3").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 3


async def ensure_worker_jobs_schema() -> None:
    """Apply worker_jobs_schema.sql (idempotent)."""
    sql = WORKER_JOBS_SCHEMA_SQL.read_text(encoding="utf-8")
    async with acquire() as conn:
        for statement in [p.strip() for p in sql.split(";") if p.strip()]:
            await conn.execute(statement)


def _validate_transition(old: str, new: str) -> None:
    if new not in VALID_STATUSES:
        raise ValueError(f"invalid status: {new}")
    allowed = TRANSITIONS.get(old)
    if allowed is not None and new not in allowed and old != new:
        raise ValueError(f"status transition not allowed: {old} -> {new}")


def _validate_failure_class(failure_class: str | None) -> None:
    if failure_class is None:
        return
    if failure_class not in VALID_FAILURE_CLASSES:
        raise ValueError(f"invalid failure_class: {failure_class}")


async def create_job(
    *,
    filename: str,
    storage_key: str,
    file_size_bytes: int | None,
    file_type: str,
    uploaded_by: str | None = None,
    max_retries: int | None = None,
) -> dict[str, Any]:
    """Insert a job in status 'queued'. Returns the new row with id."""
    if file_type not in ("xml", "zip"):
        raise ValueError("file_type must be 'xml' or 'zip'")
    if max_retries is None:
        max_retries = _default_max_retries()
    max_retries = max(0, int(max_retries))
    async with acquire() as conn:
        row = await conn.fetchrow(
            f"""
            INSERT INTO admin.worker_jobs
                (filename, storage_key, file_size_bytes, file_type, uploaded_by, status, max_retries)
            VALUES ($1, $2, $3, $4, $5, 'queued', $6)
            RETURNING
                {_JOB_COLUMNS}
            """,
            filename, storage_key, file_size_bytes, file_type, uploaded_by, max_retries,
        )
        return dict(row) if row else {}


async def get_job(job_id: str) -> dict[str, Any] | None:
    """Fetch one job by id."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            f"""
            SELECT
                {_JOB_COLUMNS}
            FROM admin.worker_jobs
            WHERE id = $1::uuid
            """,
            job_id,
        )
        return dict(row) if row else None


async def list_jobs(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """List jobs newest first."""
    async with acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                {_JOB_COLUMNS}
            FROM admin.worker_jobs
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit, offset,
        )
        return [dict(r) for r in rows]


async def update_job_status(
    job_id: str,
    new_status: str,
    *,
    articles_found: int | None = None,
    articles_ingested: int | None = None,
    articles_dup: int | None = None,
    articles_failed: int | None = None,
    error_message: str | None = None,
    error_detail: Any = None,
    failure_class: str | None = None,
) -> dict[str, Any] | None:
    """Update job status with optional result fields. Enforces valid transitions."""
    _validate_failure_class(failure_class)
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status FROM admin.worker_jobs WHERE id = $1::uuid",
            job_id,
        )
        if not row:
            return None
        old_status = row["status"]
        _validate_transition(old_status, new_status)
        error_detail_json = json.dumps(error_detail) if error_detail is not None else None
        out = await conn.fetchrow(
            f"""
            UPDATE admin.worker_jobs
            SET updated_at = now(),
                status = $1,
                articles_found = COALESCE($2, articles_found),
                articles_ingested = COALESCE($3, articles_ingested),
                articles_dup = COALESCE($4, articles_dup),
                articles_failed = COALESCE($5, articles_failed),
                error_message = COALESCE($6, error_message),
                error_detail = COALESCE($7::jsonb, error_detail),
                failure_class = COALESCE($8, failure_class),
                next_retry_at = CASE WHEN $1 IN ('completed', 'failed', 'partial') THEN NULL ELSE next_retry_at END,
                completed_at = CASE WHEN $1 IN ('completed', 'failed', 'partial') THEN now() ELSE completed_at END
            WHERE id = $9::uuid
            RETURNING
                {_JOB_COLUMNS}
            """,
            new_status,
            articles_found,
            articles_ingested,
            articles_dup,
            articles_failed,
            error_message,
            error_detail_json,
            failure_class,
            job_id,
        )
        return dict(out) if out else None


async def retry_job(job_id: str) -> dict[str, Any] | None:
    """Reset a transient failed/partial job to queued and clear result fields."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT status, failure_class
            FROM admin.worker_jobs
            WHERE id = $1::uuid
            """,
            job_id,
        )
        if not row:
            return None
        if row["status"] not in ("failed", "partial"):
            return None
        if row["status"] == "failed" and row["failure_class"] == "permanent":
            return None
        out = await conn.fetchrow(
            f"""
            UPDATE admin.worker_jobs
            SET updated_at = now(),
                status = 'queued',
                error_message = NULL,
                error_detail = NULL,
                failure_class = NULL,
                next_retry_at = NULL,
                retry_count = 0,
                completed_at = NULL,
                articles_found = NULL,
                articles_ingested = NULL,
                articles_dup = NULL,
                articles_failed = NULL
            WHERE id = $1::uuid
            RETURNING
                {_JOB_COLUMNS}
            """,
            job_id,
        )
        return dict(out) if out else None


async def schedule_job_retry(
    job_id: str,
    *,
    backoff_seconds: int,
    error_message: str,
    error_detail: Any = None,
    articles_found: int | None = None,
    articles_ingested: int | None = None,
    articles_dup: int | None = None,
    articles_failed: int | None = None,
) -> dict[str, Any] | None:
    """Move a processing job back to queued with backoff, or fail if retry budget is exhausted."""
    delay = max(1, int(backoff_seconds))
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT status, retry_count, max_retries
            FROM admin.worker_jobs
            WHERE id = $1::uuid
            """,
            job_id,
        )
        if not row or row["status"] != "processing":
            return None

        retry_count = int(row["retry_count"] or 0)
        max_retries = int(row["max_retries"] or 0)
        retryable = retry_count < max_retries
        error_detail_json = json.dumps(error_detail) if error_detail is not None else None

        if retryable:
            out = await conn.fetchrow(
                f"""
                UPDATE admin.worker_jobs
                SET updated_at = now(),
                    status = 'queued',
                    retry_count = retry_count + 1,
                    next_retry_at = now() + $1,
                    error_message = $2,
                    error_detail = $3::jsonb,
                    failure_class = 'transient',
                    articles_found = COALESCE($4, articles_found),
                    articles_ingested = COALESCE($5, articles_ingested),
                    articles_dup = COALESCE($6, articles_dup),
                    articles_failed = COALESCE($7, articles_failed),
                    completed_at = NULL
                WHERE id = $8::uuid
                RETURNING
                    {_JOB_COLUMNS}
                """,
                timedelta(seconds=delay),
                error_message,
                error_detail_json,
                articles_found,
                articles_ingested,
                articles_dup,
                articles_failed,
                job_id,
            )
        else:
            out = await conn.fetchrow(
                f"""
                UPDATE admin.worker_jobs
                SET updated_at = now(),
                    status = 'failed',
                    error_message = $1,
                    error_detail = $2::jsonb,
                    failure_class = 'transient',
                    articles_found = COALESCE($3, articles_found),
                    articles_ingested = COALESCE($4, articles_ingested),
                    articles_dup = COALESCE($5, articles_dup),
                    articles_failed = COALESCE($6, articles_failed),
                    next_retry_at = NULL,
                    completed_at = now()
                WHERE id = $7::uuid
                RETURNING
                    {_JOB_COLUMNS}
                """,
                error_message,
                error_detail_json,
                articles_found,
                articles_ingested,
                articles_dup,
                articles_failed,
                job_id,
            )
        return dict(out) if out else None


async def claim_job_for_processing(job_id: str) -> dict[str, Any] | None:
    """Atomically transition queued -> processing when retry backoff has elapsed."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE admin.worker_jobs
            SET updated_at = now(),
                status = 'processing',
                next_retry_at = NULL
            WHERE id = $1::uuid
              AND status = 'queued'
              AND (next_retry_at IS NULL OR next_retry_at <= now())
            RETURNING
                {_JOB_COLUMNS}
            """,
            job_id,
        )
        return dict(row) if row else None
