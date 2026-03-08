"""Admin upload job lifecycle (admin.worker_jobs). Queryable from FastAPI, status transitions enforced."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras

_ROOT_DIR = Path(__file__).resolve().parents[3]
WORKER_JOBS_SCHEMA_SQL = _ROOT_DIR / "src" / "backend" / "dbsync" / "worker_jobs_schema.sql"

VALID_STATUSES = frozenset({"queued", "processing", "completed", "failed", "partial"})
TRANSITIONS = {
    "queued": {"processing"},
    "processing": {"completed", "failed", "partial"},
    "completed": set(),
    "failed": set(),
    "partial": set(),
}


def _dsn() -> str:
    return os.getenv("PG_DSN") or (
        f"host={os.getenv('PGHOST', 'localhost')} "
        f"port={os.getenv('PGPORT', '5433')} "
        f"dbname={os.getenv('PGDATABASE', 'gabi')} "
        f"user={os.getenv('PGUSER', 'gabi')} "
        f"password={os.getenv('PGPASSWORD', 'gabi')}"
    )


def _connect():
    conn = psycopg2.connect(_dsn())
    conn.autocommit = True
    return conn


def ensure_worker_jobs_schema() -> None:
    """Apply worker_jobs_schema.sql (idempotent)."""
    sql = WORKER_JOBS_SCHEMA_SQL.read_text(encoding="utf-8")
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for statement in [p.strip() for p in sql.split(";") if p.strip()]:
                cur.execute(statement)
    finally:
        conn.close()


def _validate_transition(old: str, new: str) -> None:
    if new not in VALID_STATUSES:
        raise ValueError(f"invalid status: {new}")
    allowed = TRANSITIONS.get(old)
    if allowed is not None and new not in allowed and old != new:
        raise ValueError(f"status transition not allowed: {old} -> {new}")


def create_job(
    *,
    filename: str,
    storage_key: str,
    file_size_bytes: int | None,
    file_type: str,
    uploaded_by: str | None = None,
) -> dict[str, Any]:
    """Insert a job in status 'queued'. Returns the new row with id."""
    if file_type not in ("xml", "zip"):
        raise ValueError("file_type must be 'xml' or 'zip'")
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO admin.worker_jobs
                    (filename, storage_key, file_size_bytes, file_type, uploaded_by, status)
                VALUES (%s, %s, %s, %s, %s, 'queued')
                RETURNING
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
                    completed_at
                """,
                (filename, storage_key, file_size_bytes, file_type, uploaded_by),
            )
            row = cur.fetchone()
            return dict(row) if row else {}
    finally:
        conn.close()


def get_job(job_id: str) -> dict[str, Any] | None:
    """Fetch one job by id."""
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
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
                    completed_at
                FROM admin.worker_jobs
                WHERE id = %s::uuid
                """,
                (job_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def list_jobs(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """List jobs newest first."""
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
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
                    completed_at
                FROM admin.worker_jobs
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def update_job_status(
    job_id: str,
    new_status: str,
    *,
    articles_found: int | None = None,
    articles_ingested: int | None = None,
    articles_dup: int | None = None,
    articles_failed: int | None = None,
    error_message: str | None = None,
    error_detail: Any = None,
) -> dict[str, Any] | None:
    """Update job status with optional result fields. Enforces valid transitions."""
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT status FROM admin.worker_jobs WHERE id = %s::uuid",
                (job_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            old_status = row["status"]
            _validate_transition(old_status, new_status)
            cur.execute(
                """
                UPDATE admin.worker_jobs
                SET updated_at = now(),
                    status = %s,
                    articles_found = COALESCE(%s, articles_found),
                    articles_ingested = COALESCE(%s, articles_ingested),
                    articles_dup = COALESCE(%s, articles_dup),
                    articles_failed = COALESCE(%s, articles_failed),
                    error_message = COALESCE(%s, error_message),
                    error_detail = COALESCE(%s, error_detail),
                    completed_at = CASE WHEN %s IN ('completed', 'failed', 'partial') THEN now() ELSE completed_at END
                WHERE id = %s::uuid
                RETURNING
                    id::text AS id,
                    created_at,
                    updated_at,
                    filename,
                    storage_key,
                    status,
                    articles_found,
                    articles_ingested,
                    articles_dup,
                    articles_failed,
                    error_message,
                    completed_at
                """,
                (
                    new_status,
                    articles_found,
                    articles_ingested,
                    articles_dup,
                    articles_failed,
                    error_message,
                    psycopg2.extras.Json(error_detail) if error_detail is not None else None,
                    new_status,
                    job_id,
                ),
            )
            out = cur.fetchone()
            return dict(out) if out else None
    finally:
        conn.close()


def retry_job(job_id: str) -> dict[str, Any] | None:
    """Reset a failed/partial job to queued and clear result fields (Phase 9 retry). Returns updated row or None."""
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT status FROM admin.worker_jobs WHERE id = %s::uuid",
                (job_id,),
            )
            row = cur.fetchone()
            if not row or row["status"] not in ("failed", "partial"):
                return None
            cur.execute(
                """
                UPDATE admin.worker_jobs
                SET updated_at = now(),
                    status = 'queued',
                    error_message = NULL,
                    error_detail = NULL,
                    completed_at = NULL,
                    articles_found = NULL,
                    articles_ingested = NULL,
                    articles_dup = NULL,
                    articles_failed = NULL
                WHERE id = %s::uuid
                RETURNING
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
                    completed_at
                """,
                (job_id,),
            )
            out = cur.fetchone()
            return dict(out) if out else None
    finally:
        conn.close()


def claim_job_for_processing(job_id: str) -> dict[str, Any] | None:
    """Atomically transition queued -> processing. Returns updated row or None if not queued."""
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE admin.worker_jobs
                SET updated_at = now(), status = 'processing'
                WHERE id = %s::uuid AND status = 'queued'
                RETURNING
                    id::text AS id,
                    created_at,
                    updated_at,
                    filename,
                    storage_key,
                    file_type,
                    status
                """,
                (job_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()
