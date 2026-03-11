"""SQLite registry for the autonomous DOU ingestion pipeline.

Tracks lifecycle of every DOU file through discovery -> download -> extract ->
BM25 index -> embedding -> verify stages. Uses WAL mode for concurrent
reader/writer access.
"""

from __future__ import annotations

import enum
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Any, AsyncIterator

import aiosqlite

from src.backend.worker.live_sync import fetch_postgres_live_snapshot


class FileStatus(enum.Enum):
    """Pipeline file lifecycle states."""

    DISCOVERED = "DISCOVERED"
    QUEUED = "QUEUED"
    DOWNLOADING = "DOWNLOADING"
    DOWNLOADED = "DOWNLOADED"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    FALLBACK_PENDING = "FALLBACK_PENDING"
    EXTRACTING = "EXTRACTING"
    EXTRACTED = "EXTRACTED"
    EXTRACT_FAILED = "EXTRACT_FAILED"
    BM25_INDEXING = "BM25_INDEXING"
    BM25_INDEXED = "BM25_INDEXED"
    BM25_INDEX_FAILED = "BM25_INDEX_FAILED"
    EMBEDDING = "EMBEDDING"
    EMBEDDED = "EMBEDDED"
    EMBEDDING_FAILED = "EMBEDDING_FAILED"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    VERIFY_FAILED = "VERIFY_FAILED"


# Valid state transitions
VALID_TRANSITIONS: dict[FileStatus, set[FileStatus]] = {
    FileStatus.DISCOVERED: {FileStatus.QUEUED},
    FileStatus.QUEUED: {FileStatus.DOWNLOADING},
    FileStatus.DOWNLOADING: {FileStatus.DOWNLOADED, FileStatus.DOWNLOAD_FAILED},
    FileStatus.DOWNLOADED: {FileStatus.EXTRACTING},
    FileStatus.DOWNLOAD_FAILED: {FileStatus.QUEUED, FileStatus.FALLBACK_PENDING},
    FileStatus.FALLBACK_PENDING: {FileStatus.DOWNLOADING},
    FileStatus.EXTRACTING: {FileStatus.EXTRACTED, FileStatus.EXTRACT_FAILED},
    FileStatus.EXTRACTED: {FileStatus.BM25_INDEXING},
    FileStatus.EXTRACT_FAILED: {FileStatus.QUEUED},
    FileStatus.BM25_INDEXING: {FileStatus.BM25_INDEXED, FileStatus.BM25_INDEX_FAILED},
    FileStatus.BM25_INDEXED: {FileStatus.VERIFYING, FileStatus.EMBEDDING},
    FileStatus.BM25_INDEX_FAILED: {FileStatus.QUEUED},
    FileStatus.EMBEDDING: {FileStatus.EMBEDDED, FileStatus.EMBEDDING_FAILED},
    FileStatus.EMBEDDED: {FileStatus.VERIFYING},
    FileStatus.EMBEDDING_FAILED: {FileStatus.QUEUED},
    FileStatus.VERIFYING: {FileStatus.VERIFIED, FileStatus.VERIFY_FAILED},
    FileStatus.VERIFIED: {FileStatus.VERIFYING, FileStatus.EMBEDDING},
    FileStatus.VERIFY_FAILED: {FileStatus.QUEUED},
}

# Map status to the timestamp column to update
_STATUS_TIMESTAMP_COL: dict[FileStatus, str | None] = {
    FileStatus.DISCOVERED: None,
    FileStatus.QUEUED: "queued_at",
    FileStatus.DOWNLOADING: None,
    FileStatus.DOWNLOADED: "downloaded_at",
    FileStatus.DOWNLOAD_FAILED: None,
    FileStatus.FALLBACK_PENDING: None,
    FileStatus.EXTRACTING: None,
    FileStatus.EXTRACTED: "extracted_at",
    FileStatus.EXTRACT_FAILED: None,
    FileStatus.BM25_INDEXING: None,
    FileStatus.BM25_INDEXED: "bm25_indexed_at",
    FileStatus.BM25_INDEX_FAILED: None,
    FileStatus.EMBEDDING: None,
    FileStatus.EMBEDDED: "embedded_at",
    FileStatus.EMBEDDING_FAILED: None,
    FileStatus.VERIFYING: None,
    FileStatus.VERIFIED: "verified_at",
    FileStatus.VERIFY_FAILED: None,
}

MAX_RETRIES = 3

# Month-level catalog lifecycle (P3)
CATALOG_STATUS_KNOWN = "KNOWN"
CATALOG_STATUS_INLABS_WINDOW = "INLABS_WINDOW"
CATALOG_STATUS_WINDOW_CLOSING = "WINDOW_CLOSING"
CATALOG_STATUS_FALLBACK_ELIGIBLE = "FALLBACK_ELIGIBLE"
CATALOG_STATUS_CLOSED = "CLOSED"
INLABS_WINDOW_DAYS = 30
WINDOW_CLOSING_DAYS_LEFT = 5  # days before window end to mark WINDOW_CLOSING

SCHEMA = """
CREATE TABLE IF NOT EXISTS dou_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL UNIQUE,
    section TEXT NOT NULL,
    year_month TEXT NOT NULL,
    publication_date TEXT,
    source TEXT NOT NULL DEFAULT 'liferay',
    folder_id INTEGER,
    file_url TEXT,
    status TEXT NOT NULL DEFAULT 'DISCOVERED',
    retry_count INTEGER DEFAULT 0,
    doc_count INTEGER,
    file_size_bytes INTEGER,
    sha256 TEXT,
    error_message TEXT,
    discovered_at TEXT NOT NULL,
    queued_at TEXT,
    downloaded_at TEXT,
    extracted_at TEXT,
    ingested_at TEXT,
    bm25_indexed_at TEXT,
    embedded_at TEXT,
    verified_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dou_files_status ON dou_files(status);
CREATE INDEX IF NOT EXISTS idx_dou_files_year_month ON dou_files(year_month);
CREATE INDEX IF NOT EXISTS idx_dou_files_publication_date ON dou_files(publication_date);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id TEXT PRIMARY KEY,
    phase TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL,
    completed_at TEXT,
    files_processed INTEGER DEFAULT 0,
    files_succeeded INTEGER DEFAULT 0,
    files_failed INTEGER DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS pipeline_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT REFERENCES pipeline_runs(id),
    file_id INTEGER REFERENCES dou_files(id),
    level TEXT NOT NULL DEFAULT 'INFO',
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pipeline_log_run_id ON pipeline_log(run_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_log_created ON pipeline_log(created_at);

CREATE TABLE IF NOT EXISTS dou_catalog_months (
    year_month TEXT NOT NULL PRIMARY KEY,
    folder_id INTEGER,
    group_id TEXT DEFAULT '49035712',
    source_of_truth TEXT,
    catalog_status TEXT DEFAULT 'KNOWN',
    month_closed INTEGER DEFAULT 0,
    inlabs_window_expires_at TEXT,
    fallback_eligible_at TEXT,
    liferay_zip_available INTEGER DEFAULT 0,
    last_reconciled_at TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS pipeline_config (
    key TEXT NOT NULL PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Registry:
    """SQLite-backed pipeline state registry."""

    def __init__(self, db_path: str = "/data/registry.db") -> None:
        self.db_path = db_path

    async def init_db(self) -> None:
        """Create schema and enable WAL mode."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=5000")
            await db.executescript(SCHEMA)
            await _ensure_registry_columns(db)
            await db.commit()

    @asynccontextmanager
    async def get_db(self) -> AsyncIterator[aiosqlite.Connection]:
        """Context manager yielding an aiosqlite connection with Row factory."""
        db = await aiosqlite.connect(self.db_path)
        db.row_factory = aiosqlite.Row
        try:
            yield db
        finally:
            await db.close()

    async def insert_file(
        self,
        filename: str,
        section: str,
        year_month: str,
        folder_id: int | None = None,
        file_url: str | None = None,
        *,
        publication_date: str | None = None,
        source: str = "liferay",
    ) -> int:
        """Insert a new file record, returning its id."""
        now = _now()
        async with self.get_db() as db:
            cursor = await db.execute(
                """INSERT OR IGNORE INTO dou_files
                   (filename, section, year_month, publication_date, source, folder_id, file_url, status,
                    discovered_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    filename,
                    section,
                    year_month,
                    publication_date,
                    source,
                    folder_id,
                    file_url,
                    FileStatus.DISCOVERED.value,
                    now,
                    now,
                ),
            )
            await db.commit()
            return cursor.lastrowid or 0

    async def get_file_by_filename(self, filename: str) -> dict[str, Any] | None:
        """Look up a file by filename."""
        async with self.get_db() as db:
            cursor = await db.execute("SELECT * FROM dou_files WHERE filename = ?", (filename,))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_file(self, file_id: int) -> dict[str, Any] | None:
        """Look up a file by id."""
        async with self.get_db() as db:
            cursor = await db.execute("SELECT * FROM dou_files WHERE id = ?", (file_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def update_status(self, file_id: int, new_status: FileStatus, *, _skip_validation: bool = False) -> None:
        """Update file status with transition validation."""
        async with self.get_db() as db:
            cursor = await db.execute("SELECT status FROM dou_files WHERE id = ?", (file_id,))
            row = await cursor.fetchone()
            if row is None:
                raise ValueError(f"File {file_id} not found")

            current = FileStatus(row["status"])
            if not _skip_validation:
                allowed = VALID_TRANSITIONS.get(current, set())
                if new_status not in allowed:
                    raise ValueError(f"Invalid transition: {current.value} -> {new_status.value}")

            now = _now()
            ts_col = _STATUS_TIMESTAMP_COL.get(new_status)
            if ts_col:
                await db.execute(
                    f"UPDATE dou_files SET status = ?, updated_at = ?, {ts_col} = ? WHERE id = ?",
                    (new_status.value, now, now, file_id),
                )
            else:
                await db.execute(
                    "UPDATE dou_files SET status = ?, updated_at = ? WHERE id = ?",
                    (new_status.value, now, file_id),
                )
            await db.commit()

    async def update_file_fields(self, file_id: int, **fields: Any) -> None:
        """Update arbitrary fields on a file record."""
        if not fields:
            return
        async with self.get_db() as db:
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            values = list(fields.values()) + [_now(), file_id]
            await db.execute(
                f"UPDATE dou_files SET {set_clause}, updated_at = ? WHERE id = ?",
                values,
            )
            await db.commit()

    async def get_files_by_status(self, status: FileStatus, limit: int = 100) -> list[dict[str, Any]]:
        """Get files with a given status."""
        async with self.get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM dou_files WHERE status = ? "
                "ORDER BY COALESCE(publication_date, year_month || '-01') DESC, id DESC LIMIT ?",
                (status.value, limit),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_files_by_status_and_month(
        self, status: FileStatus, year_month: str, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Get files with a given status and year_month (e.g. for reconciler)."""
        async with self.get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM dou_files WHERE status = ? AND year_month = ? ORDER BY id LIMIT ?",
                (status.value, year_month, limit),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def queue_discovered_files(self, limit: int = 500) -> int:
        """Promote oldest DISCOVERED files to QUEUED for downloader pickup."""
        async with self.get_db() as db:
            cursor = await db.execute(
                """
                SELECT id
                FROM dou_files
                WHERE status = ?
                ORDER BY COALESCE(publication_date, year_month || '-01') ASC, id ASC
                LIMIT ?
                """,
                (FileStatus.DISCOVERED.value, limit),
            )
            rows = await cursor.fetchall()
            file_ids = [row["id"] for row in rows]
            if not file_ids:
                return 0

            now = _now()
            placeholders = ", ".join("?" for _ in file_ids)
            await db.execute(
                f"""
                UPDATE dou_files
                SET status = ?, queued_at = ?, updated_at = ?
                WHERE id IN ({placeholders})
                """,
                [FileStatus.QUEUED.value, now, now, *file_ids],
            )
            await db.commit()
            return len(file_ids)

    async def get_catalog_months_by_status(self, catalog_status: str) -> list[dict[str, Any]]:
        """Get catalog months with the given catalog_status (e.g. FALLBACK_ELIGIBLE)."""
        async with self.get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM dou_catalog_months WHERE catalog_status = ? ORDER BY year_month DESC",
                (catalog_status,),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def set_catalog_month_liferay_available(self, year_month: str) -> None:
        """Mark liferay_zip_available=1 and last_reconciled_at for a catalog month."""
        now = _now()
        async with self.get_db() as db:
            await db.execute(
                "UPDATE dou_catalog_months SET liferay_zip_available = 1, last_reconciled_at = ?, updated_at = ? WHERE year_month = ?",
                (now, now, year_month),
            )
            await db.commit()

    async def get_latest_publication_date(self, *, source: str | None = None) -> str | None:
        """Return the newest publication_date recorded in the registry."""
        async with self.get_db() as db:
            if source:
                cursor = await db.execute(
                    "SELECT publication_date FROM dou_files "
                    "WHERE source = ? AND publication_date IS NOT NULL "
                    "ORDER BY publication_date DESC LIMIT 1",
                    (source,),
                )
            else:
                cursor = await db.execute(
                    "SELECT publication_date FROM dou_files "
                    "WHERE publication_date IS NOT NULL "
                    "ORDER BY publication_date DESC LIMIT 1"
                )
            row = await cursor.fetchone()
            return row["publication_date"] if row else None

    async def get_status_counts(self) -> dict[str, int]:
        """Get count of files by status."""
        counts = {status.value: 0 for status in FileStatus}
        async with self.get_db() as db:
            cursor = await db.execute("SELECT status, COUNT(*) as cnt FROM dou_files GROUP BY status")
            rows = await cursor.fetchall()
            for row in rows:
                counts[row["status"]] = row["cnt"]
        return counts

    async def get_months(self, year: int | None = None) -> list[dict[str, Any]]:
        """Get timeline-ready file records, optionally filtered by year."""
        live_snapshot = await fetch_postgres_live_snapshot(
            year=year,
            include_summary=False,
            include_files=True,
            include_months=False,
            include_es=False,
        )
        live_files = live_snapshot["files"] if live_snapshot else {}
        async with self.get_db() as db:
            query = (
                "SELECT id, filename, year_month, section, status, retry_count, "
                "doc_count, file_size_bytes, error_message, source, publication_date, discovered_at, "
                "queued_at, downloaded_at, extracted_at, ingested_at, bm25_indexed_at, "
                "embedded_at, verified_at, "
                "updated_at "
                "FROM dou_files"
            )
            params: list[Any] = []
            if year:
                query += " WHERE year_month LIKE ?"
                params.append(f"{year}-%")
            query += " ORDER BY year_month DESC, filename ASC"
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            registry_group_counts: dict[tuple[str, str], int] = {}
            registry_exact_keys: set[tuple[str, str, str]] = set()
            for row in rows:
                group_key = (str(row["year_month"]), str(row["section"]))
                registry_group_counts[group_key] = registry_group_counts.get(group_key, 0) + 1
                registry_exact_keys.add((str(row["year_month"]), str(row["section"]), str(row["filename"])))

            live_group_candidates: dict[
                tuple[str, str],
                list[tuple[tuple[str, str, str], dict[str, Any]]],
            ] = {}
            for (year_month, section, filename), live_record in live_files.items():
                if year and not str(year_month).startswith(f"{year}-"):
                    continue
                group_key = (str(year_month), str(section))
                live_group_candidates.setdefault(group_key, []).append(
                    ((str(year_month), str(section), str(filename)), live_record)
                )

            items: list[dict[str, Any]] = []
            matched_live_keys: set[tuple[str, str, str]] = set()
            for row in rows:
                record = dict(row)
                exact_key = (
                    str(record["year_month"]),
                    str(record["section"]),
                    str(record["filename"]),
                )
                live = live_files.get(exact_key, {})
                if not live:
                    group_key = (str(record["year_month"]), str(record["section"]))
                    candidates = live_group_candidates.get(group_key, [])
                    if registry_group_counts.get(group_key, 0) == 1 and len(candidates) == 1:
                        live_key, live = candidates[0]
                        matched_live_keys.add(live_key)
                else:
                    matched_live_keys.add(exact_key)
                record["pg_doc_count"] = int(live.get("doc_count", 0))
                record["pg_chunked_doc_count"] = int(live.get("chunked_doc_count", 0))
                record["pg_chunk_rows"] = int(live.get("chunk_row_count", 0))
                record["pg_downloaded_at"] = live.get("downloaded_at")
                record["is_live_only"] = False
                record["record_source"] = (
                    "registry+postgres_live" if record["pg_doc_count"] > 0 else "registry"
                )
                if record.get("doc_count") in (None, 0) and record["pg_doc_count"] > 0:
                    record["doc_count"] = record["pg_doc_count"]
                items.append(record)

            synthetic_id = -1
            for (year_month, section, filename), live_record in sorted(
                live_files.items(),
                key=lambda entry: (str(entry[0][0]), str(entry[0][1]), str(entry[0][2])),
                reverse=True,
            ):
                exact_key = (str(year_month), str(section), str(filename))
                if year and not str(year_month).startswith(f"{year}-"):
                    continue
                if exact_key in matched_live_keys or exact_key in registry_exact_keys:
                    continue
                downloaded_at = live_record.get("downloaded_at")
                doc_count = int(live_record.get("doc_count", 0) or 0)
                chunked_doc_count = int(live_record.get("chunked_doc_count", 0) or 0)
                chunk_row_count = int(live_record.get("chunk_row_count", 0) or 0)
                items.append(
                    {
                        "id": synthetic_id,
                        "filename": str(live_record.get("pg_filename") or filename),
                        "year_month": str(year_month),
                        "section": str(section),
                        "status": FileStatus.VERIFIED.value if doc_count > 0 else FileStatus.DOWNLOADED.value,
                        "is_live_only": True,
                        "record_source": "postgres_live",
                        "retry_count": 0,
                        "doc_count": doc_count or None,
                        "file_size_bytes": None,
                        "error_message": None,
                        "source": "postgres_live",
                        "publication_date": None,
                        "discovered_at": downloaded_at,
                        "queued_at": None,
                        "downloaded_at": downloaded_at,
                        "extracted_at": downloaded_at if doc_count > 0 else None,
                        "ingested_at": downloaded_at if doc_count > 0 else None,
                        "bm25_indexed_at": downloaded_at if doc_count > 0 else None,
                        "embedded_at": downloaded_at if chunked_doc_count > 0 else None,
                        "verified_at": downloaded_at if doc_count > 0 else None,
                        "updated_at": downloaded_at or _now(),
                        "pg_doc_count": doc_count,
                        "pg_chunked_doc_count": chunked_doc_count,
                        "pg_chunk_rows": chunk_row_count,
                        "pg_downloaded_at": downloaded_at,
                    }
                )
                synthetic_id -= 1
            items.sort(key=lambda item: (str(item["year_month"]), str(item["filename"])), reverse=True)
            return items

    async def get_summary_stats(self) -> dict[str, Any]:
        """Return dashboard-friendly registry summary statistics."""
        status_counts = await self.get_status_counts()
        live_snapshot = await fetch_postgres_live_snapshot(
            include_summary=True,
            include_files=False,
            include_months=False,
            include_es=True,
        )
        async with self.get_db() as db:
            totals_cursor = await db.execute(
                """
                SELECT
                    COUNT(*) AS total_files,
                    COALESCE(SUM(CASE WHEN status = 'VERIFIED' THEN 1 ELSE 0 END), 0) AS verified_files,
                    COALESCE(SUM(CASE WHEN status LIKE '%FAILED' THEN 1 ELSE 0 END), 0) AS failed_files,
                    COALESCE(SUM(CASE WHEN status IN (
                        'DISCOVERED', 'QUEUED', 'DOWNLOADING', 'DOWNLOADED',
                        'EXTRACTING', 'EXTRACTED', 'BM25_INDEXING', 'BM25_INDEXED',
                        'EMBEDDING', 'EMBEDDED', 'VERIFYING'
                    ) THEN 1 ELSE 0 END), 0) AS active_files,
                    COALESCE(SUM(COALESCE(doc_count, 0)), 0) AS total_docs,
                    MAX(verified_at) AS last_verified_at,
                    MAX(updated_at) AS last_activity_at,
                    MAX(retry_count) AS max_retry_count
                FROM dou_files
                """
            )
            totals = dict(await totals_cursor.fetchone())

            retry_cursor = await db.execute(
                "SELECT COUNT(*) AS retry_backlog FROM dou_files WHERE status LIKE '%FAILED'"
            )
            retry_backlog = dict(await retry_cursor.fetchone())

            run_cursor = await db.execute(
                """
                SELECT id, phase, status, started_at, completed_at, files_processed,
                       files_succeeded, files_failed, error_message
                FROM pipeline_runs
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
            latest_run_row = await run_cursor.fetchone()

        return {
            **totals,
            **retry_backlog,
            "status_counts": status_counts,
            "disk_usage": await self.get_disk_usage(),
            "latest_run": dict(latest_run_row) if latest_run_row else None,
            "pg_ingested_files": int(live_snapshot["summary"].get("pg_ingested_files", 0)) if live_snapshot else 0,
            "pg_doc_backed_files": int(live_snapshot["summary"].get("pg_doc_backed_files", 0)) if live_snapshot else 0,
            "pg_total_docs": int(live_snapshot["summary"].get("pg_total_docs", 0)) if live_snapshot else 0,
            "pg_chunked_files": int(live_snapshot["summary"].get("pg_chunked_files", 0)) if live_snapshot else 0,
            "pg_chunked_docs": int(live_snapshot["summary"].get("pg_chunked_docs", 0)) if live_snapshot else 0,
            "pg_chunk_rows": int(live_snapshot["summary"].get("pg_chunk_rows", 0)) if live_snapshot else 0,
            "pg_min_month": live_snapshot["summary"].get("pg_min_month") if live_snapshot else None,
            "pg_max_month": live_snapshot["summary"].get("pg_max_month") if live_snapshot else None,
            "es_status": live_snapshot["es_summary"].get("es_status") if live_snapshot else None,
            "es_doc_count": int(live_snapshot["es_summary"].get("es_doc_count", 0)) if live_snapshot else 0,
            "es_chunk_count": int(live_snapshot["es_summary"].get("es_chunk_count", 0)) if live_snapshot else 0,
            "es_chunks_refresh_interval": live_snapshot["es_summary"].get("es_chunks_refresh_interval")
            if live_snapshot
            else None,
            "data_sources": {
                "registry_queue": "registry_sqlite",
                "catalog_coverage": "registry_sqlite+postgres_live",
                "document_corpus": "postgres_live",
                "vector_corpus": "elasticsearch_live",
                "scheduler": "apscheduler",
            },
        }

    async def create_pipeline_run(self, phase: str) -> str:
        """Create a new pipeline run record."""
        run_id = str(uuid.uuid4())
        now = _now()
        async with self.get_db() as db:
            await db.execute(
                "INSERT INTO pipeline_runs (id, phase, status, started_at) VALUES (?, ?, ?, ?)",
                (run_id, phase, "running", now),
            )
            await db.commit()
            return run_id

    async def complete_pipeline_run(
        self,
        run_id: str,
        files_processed: int,
        files_succeeded: int,
        files_failed: int,
        error_message: str | None = None,
    ) -> None:
        """Mark a pipeline run as completed."""
        async with self.get_db() as db:
            status = "failed" if error_message else "completed"
            await db.execute(
                """UPDATE pipeline_runs
                   SET status = ?, completed_at = ?, files_processed = ?,
                       files_succeeded = ?, files_failed = ?, error_message = ?
                   WHERE id = ?""",
                (status, _now(), files_processed, files_succeeded, files_failed, error_message, run_id),
            )
            await db.commit()

    async def add_log_entry(self, run_id: str, file_id: int | None, level: str, message: str) -> None:
        """Add a log entry for a pipeline run."""
        async with self.get_db() as db:
            await db.execute(
                "INSERT INTO pipeline_log (run_id, file_id, level, message, created_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, file_id, level, message, _now()),
            )
            await db.commit()

    async def get_pipeline_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent pipeline runs."""
        async with self.get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_logs(
        self,
        run_id: str | None = None,
        file_id: int | None = None,
        level: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Get log entries with optional filters."""
        async with self.get_db() as db:
            query = "SELECT * FROM pipeline_log WHERE 1=1"
            params: list[Any] = []
            if run_id:
                query += " AND run_id = ?"
                params.append(run_id)
            if file_id:
                query += " AND file_id = ?"
                params.append(file_id)
            if level:
                query += " AND level = ?"
                params.append(level)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def retry_file(self, file_id: int) -> None:
        """Retry a failed file -- increments retry_count, resets to QUEUED."""
        async with self.get_db() as db:
            cursor = await db.execute("SELECT retry_count, status FROM dou_files WHERE id = ?", (file_id,))
            row = await cursor.fetchone()
            if row is None:
                raise ValueError(f"File {file_id} not found")

            new_count = row["retry_count"] + 1
            if new_count > MAX_RETRIES:
                raise ValueError(f"File {file_id} has exceeded max retries ({MAX_RETRIES})")

            await db.execute(
                "UPDATE dou_files SET status = ?, retry_count = ?, updated_at = ?, error_message = NULL WHERE id = ?",
                (FileStatus.QUEUED.value, new_count, _now(), file_id),
            )
            await db.commit()

    async def bulk_insert_with_status(self, files: list[dict[str, Any]]) -> int:
        """Bulk insert files with specified status (migration-only, bypasses transition validation)."""
        now = _now()
        async with self.get_db() as db:
            rows = [
                (
                    f["filename"],
                    f["section"],
                    f["year_month"],
                    f.get("publication_date"),
                    f.get("source", "liferay"),
                    f.get("folder_id"),
                    f.get("file_url"),
                    f.get("status", FileStatus.DISCOVERED.value),
                    now,
                    now,
                )
                for f in files
            ]
            await db.executemany(
                """INSERT OR IGNORE INTO dou_files
                   (filename, section, year_month, publication_date, source, folder_id, file_url, status,
                    discovered_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            await db.commit()
            return len(rows)

    async def catalog_month_upsert(
        self,
        year_month: str,
        *,
        folder_id: int | None = None,
        group_id: str = "49035712",
        source_of_truth: str | None = None,
    ) -> None:
        """Insert or replace a row in dou_catalog_months."""
        now = _now()
        async with self.get_db() as db:
            await db.execute(
                """INSERT INTO dou_catalog_months
                   (year_month, folder_id, group_id, source_of_truth, catalog_status,
                    month_closed, liferay_zip_available, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'KNOWN', 0, 0, ?, ?)
                   ON CONFLICT(year_month) DO UPDATE SET
                     folder_id = COALESCE(excluded.folder_id, folder_id),
                     group_id = COALESCE(excluded.group_id, group_id),
                     source_of_truth = COALESCE(excluded.source_of_truth, source_of_truth),
                     updated_at = excluded.updated_at""",
                (year_month, folder_id, group_id, source_of_truth, now, now),
            )
            await db.commit()

    async def has_catalog_data(self) -> bool:
        """Return True if the registry has any catalog data (files or catalog months)."""
        status_counts = await self.get_status_counts()
        if sum(status_counts.values()) > 0:
            return True
        async with self.get_db() as db:
            cursor = await db.execute("SELECT 1 FROM dou_catalog_months LIMIT 1")
            return (await cursor.fetchone()) is not None

    async def get_config(self, key: str) -> str | None:
        """Get a value from pipeline_config."""
        async with self.get_db() as db:
            cursor = await db.execute("SELECT value FROM pipeline_config WHERE key = ?", (key,))
            row = await cursor.fetchone()
            return row["value"] if row else None

    async def set_config(self, key: str, value: str) -> None:
        """Set a value in pipeline_config."""
        now = _now()
        async with self.get_db() as db:
            await db.execute(
                """INSERT INTO pipeline_config (key, value, updated_at)
                   VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?""",
                (key, value, now, value, now),
            )
            await db.commit()

    async def get_catalog_months(self, year: int | None = None) -> list[dict[str, Any]]:
        """Return catalog month rows with catalog_status for dashboard/API."""
        live_snapshot = await fetch_postgres_live_snapshot(
            year=year,
            include_summary=False,
            include_files=False,
            include_months=True,
            include_es=False,
        )
        live_months = live_snapshot["months"] if live_snapshot else {}
        async with self.get_db() as db:
            query = """
                SELECT
                    m.*,
                    COUNT(f.id) AS file_count,
                    COALESCE(SUM(CASE WHEN f.status = 'VERIFIED' THEN 1 ELSE 0 END), 0) AS verified_file_count,
                    COALESCE(SUM(CASE WHEN f.status = 'DISCOVERED' THEN 1 ELSE 0 END), 0) AS discovered_file_count,
                    COALESCE(SUM(CASE WHEN f.status = 'QUEUED' THEN 1 ELSE 0 END), 0) AS queued_file_count,
                    COALESCE(SUM(CASE WHEN f.status LIKE '%FAILED' THEN 1 ELSE 0 END), 0) AS failed_file_count,
                    COALESCE(SUM(CASE WHEN f.status IN (
                        'DISCOVERED', 'QUEUED', 'DOWNLOADING', 'DOWNLOADED',
                        'EXTRACTING', 'EXTRACTED', 'BM25_INDEXING', 'BM25_INDEXED',
                        'EMBEDDING', 'EMBEDDED', 'VERIFYING'
                    ) THEN 1 ELSE 0 END), 0) AS pending_file_count
                FROM dou_catalog_months m
                LEFT JOIN dou_files f ON f.year_month = m.year_month
            """
            params: list[Any] = []
            if year:
                query += " WHERE m.year_month LIKE ?"
                params.append(f"{year}-%")
            query += """
                GROUP BY
                    m.year_month,
                    m.folder_id,
                    m.group_id,
                    m.source_of_truth,
                    m.catalog_status,
                    m.month_closed,
                    m.inlabs_window_expires_at,
                    m.fallback_eligible_at,
                    m.liferay_zip_available,
                    m.last_reconciled_at,
                    m.created_at,
                    m.updated_at
                ORDER BY m.year_month DESC
            """
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            months: list[dict[str, Any]] = []
            seen_months: set[str] = set()
            for row in rows:
                record = dict(row)
                seen_months.add(str(record["year_month"]))
                live = live_months.get(record["year_month"], {})
                record["pg_ingested_file_count"] = int(live.get("pg_ingested_file_count", 0))
                record["pg_doc_count"] = int(live.get("pg_doc_count", 0))
                record["pg_chunked_file_count"] = int(live.get("pg_chunked_file_count", 0))
                record["pg_chunked_doc_count"] = int(live.get("pg_chunked_doc_count", 0))
                record["pg_chunk_rows"] = int(live.get("pg_chunk_rows", 0))
                total = max(int(record.get("file_count") or 0), record["pg_ingested_file_count"])
                verified = max(int(record.get("verified_file_count") or 0), record["pg_ingested_file_count"])
                record["effective_file_count"] = total
                record["effective_covered_file_count"] = verified
                record["coverage_source"] = (
                    "registry+postgres_live"
                    if int(record.get("file_count") or 0) > 0 and record["pg_ingested_file_count"] > 0
                    else "postgres_live"
                    if record["pg_ingested_file_count"] > 0
                    else "registry"
                )
                record["file_count"] = total
                record["verified_file_count"] = verified
                record["coverage_pct"] = round((verified / total) * 100, 1) if total > 0 else 0.0
                ingested = record["pg_ingested_file_count"]
                chunked_files = record["pg_chunked_file_count"]
                record["ingested_coverage_pct"] = round((ingested / total) * 100, 1) if total > 0 else 0.0
                record["chunked_coverage_pct"] = round((chunked_files / total) * 100, 1) if total > 0 else 0.0
                months.append(record)
            for year_month, live in sorted(live_months.items(), reverse=True):
                year_month = str(year_month)
                if year and not year_month.startswith(f"{year}-"):
                    continue
                if year_month in seen_months:
                    continue
                ingested = int(live.get("pg_ingested_file_count", 0) or 0)
                chunked_files = int(live.get("pg_chunked_file_count", 0) or 0)
                total = ingested
                months.append(
                    {
                        "year_month": year_month,
                        "folder_id": None,
                        "group_id": None,
                        "source_of_truth": "postgres_live",
                        "catalog_status": CATALOG_STATUS_CLOSED,
                        "month_closed": 1,
                        "inlabs_window_expires_at": None,
                        "fallback_eligible_at": None,
                        "liferay_zip_available": 0,
                        "last_reconciled_at": None,
                        "created_at": None,
                        "updated_at": None,
                        "file_count": total,
                        "verified_file_count": ingested,
                        "discovered_file_count": 0,
                        "queued_file_count": 0,
                        "failed_file_count": 0,
                        "pending_file_count": 0,
                        "effective_file_count": total,
                        "effective_covered_file_count": ingested,
                        "coverage_source": "postgres_live",
                        "coverage_pct": 100.0 if total > 0 else 0.0,
                        "pg_ingested_file_count": ingested,
                        "pg_doc_count": int(live.get("pg_doc_count", 0) or 0),
                        "pg_chunked_file_count": chunked_files,
                        "pg_chunked_doc_count": int(live.get("pg_chunked_doc_count", 0) or 0),
                        "pg_chunk_rows": int(live.get("pg_chunk_rows", 0) or 0),
                        "ingested_coverage_pct": 100.0 if total > 0 else 0.0,
                        "chunked_coverage_pct": round((chunked_files / total) * 100, 1) if total > 0 else 0.0,
                    }
                )
            months.sort(key=lambda record: str(record["year_month"]), reverse=True)
            return months

    async def refresh_catalog_month_status(self, *, today: date | None = None) -> int:
        """Update catalog_status for all dou_catalog_months based on dates and file completeness.

        Returns the number of rows updated.
        """
        from datetime import timedelta

        ref = today or date.today()

        async with self.get_db() as db:
            cursor = await db.execute("SELECT year_month FROM dou_catalog_months ORDER BY year_month")
            months = [row["year_month"] for row in await cursor.fetchall()]

        updated = 0
        for year_month in months:
            try:
                y, m = map(int, year_month.split("-"))
                if m == 12:
                    month_end = date(y + 1, 1, 1) - timedelta(days=1)
                else:
                    month_end = date(y, m + 1, 1) - timedelta(days=1)
            except (ValueError, TypeError):
                continue

            days_since_end = (ref - month_end).days
            async with self.get_db() as db:
                cursor = await db.execute(
                    """SELECT
                         COUNT(*) AS total,
                         SUM(CASE WHEN status = 'VERIFIED' THEN 1 ELSE 0 END) AS verified
                       FROM dou_files WHERE year_month = ?""",
                    (year_month,),
                )
                row = await cursor.fetchone()
            total = row["total"] or 0
            verified = row["verified"] or 0
            all_verified = total > 0 and verified >= total

            if all_verified:
                new_status = CATALOG_STATUS_CLOSED
                inlabs_at = None
                fallback_at = None
            elif days_since_end <= 0:
                new_status = CATALOG_STATUS_INLABS_WINDOW
                inlabs_at = (month_end + timedelta(days=INLABS_WINDOW_DAYS)).isoformat()
                fallback_at = (month_end + timedelta(days=INLABS_WINDOW_DAYS + 1)).isoformat()
            elif days_since_end <= INLABS_WINDOW_DAYS:
                if days_since_end >= (INLABS_WINDOW_DAYS - WINDOW_CLOSING_DAYS_LEFT):
                    new_status = CATALOG_STATUS_WINDOW_CLOSING
                else:
                    new_status = CATALOG_STATUS_INLABS_WINDOW
                inlabs_at = (month_end + timedelta(days=INLABS_WINDOW_DAYS)).isoformat()
                fallback_at = (month_end + timedelta(days=INLABS_WINDOW_DAYS + 1)).isoformat()
            else:
                new_status = CATALOG_STATUS_FALLBACK_ELIGIBLE
                inlabs_at = None
                fallback_at = (month_end + timedelta(days=INLABS_WINDOW_DAYS + 1)).isoformat()

            now = _now()
            async with self.get_db() as db:
                await db.execute(
                    """UPDATE dou_catalog_months SET
                         catalog_status = ?, inlabs_window_expires_at = ?,
                         fallback_eligible_at = ?, month_closed = ?, updated_at = ?
                       WHERE year_month = ?""",
                    (new_status, inlabs_at, fallback_at, 1 if all_verified else 0, now, year_month),
                )
                await db.commit()
            updated += 1

        return updated

    async def get_disk_usage(self) -> dict[str, int]:
        """Get database and worker-volume usage."""
        try:
            size = os.path.getsize(self.db_path)
        except OSError:
            size = 0
        db_dir = os.path.dirname(self.db_path) or "."
        tmp_dir = os.path.join(db_dir, "tmp")
        tmp_size = 0
        if os.path.isdir(tmp_dir):
            for root, _, files in os.walk(tmp_dir):
                for file_name in files:
                    try:
                        tmp_size += os.path.getsize(os.path.join(root, file_name))
                    except OSError:
                        continue
        try:
            usage = shutil.disk_usage(db_dir)
            free_bytes = usage.free
            total_bytes = usage.total
        except OSError:
            free_bytes = 0
            total_bytes = 0
        return {
            "db_size_bytes": size,
            "tmp_size_bytes": tmp_size,
            "free_bytes": free_bytes,
            "total_bytes": total_bytes,
        }


async def _ensure_registry_columns(db: aiosqlite.Connection) -> None:
    """Apply additive column migrations and ensure new tables exist."""
    # Ensure dou_catalog_months and pipeline_config exist (for DBs created before P2)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS dou_catalog_months (
            year_month TEXT NOT NULL PRIMARY KEY,
            folder_id INTEGER,
            group_id TEXT DEFAULT '49035712',
            source_of_truth TEXT,
            catalog_status TEXT DEFAULT 'KNOWN',
            month_closed INTEGER DEFAULT 0,
            inlabs_window_expires_at TEXT,
            fallback_eligible_at TEXT,
            liferay_zip_available INTEGER DEFAULT 0,
            last_reconciled_at TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_config (
            key TEXT NOT NULL PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    cursor = await db.execute("PRAGMA table_info(dou_files)")
    columns = {row[1] for row in await cursor.fetchall()}
    if "publication_date" not in columns:
        await db.execute("ALTER TABLE dou_files ADD COLUMN publication_date TEXT")
    if "source" not in columns:
        await db.execute("ALTER TABLE dou_files ADD COLUMN source TEXT NOT NULL DEFAULT 'liferay'")
    if "bm25_indexed_at" not in columns:
        await db.execute("ALTER TABLE dou_files ADD COLUMN bm25_indexed_at TEXT")
    if "embedded_at" not in columns:
        await db.execute("ALTER TABLE dou_files ADD COLUMN embedded_at TEXT")

    await db.execute("UPDATE dou_files SET status = 'BM25_INDEXING' WHERE status = 'INGESTING'")
    await db.execute("UPDATE dou_files SET status = 'BM25_INDEXED' WHERE status = 'INGESTED'")
    await db.execute("UPDATE dou_files SET status = 'BM25_INDEX_FAILED' WHERE status = 'INGEST_FAILED'")
    await db.execute(
        "UPDATE dou_files SET bm25_indexed_at = COALESCE(bm25_indexed_at, ingested_at) WHERE ingested_at IS NOT NULL"
    )
