"""SQLite registry for the autonomous DOU ingestion pipeline.

Tracks lifecycle of every DOU file through discovery -> download -> extract ->
ingest -> verify stages. Uses WAL mode for concurrent reader/writer access.
"""
from __future__ import annotations

import enum
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import aiosqlite


class FileStatus(enum.Enum):
    """Pipeline file lifecycle states."""

    DISCOVERED = "DISCOVERED"
    QUEUED = "QUEUED"
    DOWNLOADING = "DOWNLOADING"
    DOWNLOADED = "DOWNLOADED"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    EXTRACTING = "EXTRACTING"
    EXTRACTED = "EXTRACTED"
    EXTRACT_FAILED = "EXTRACT_FAILED"
    INGESTING = "INGESTING"
    INGESTED = "INGESTED"
    INGEST_FAILED = "INGEST_FAILED"
    VERIFIED = "VERIFIED"
    VERIFY_FAILED = "VERIFY_FAILED"


# Valid state transitions
VALID_TRANSITIONS: dict[FileStatus, set[FileStatus]] = {
    FileStatus.DISCOVERED: {FileStatus.QUEUED},
    FileStatus.QUEUED: {FileStatus.DOWNLOADING},
    FileStatus.DOWNLOADING: {FileStatus.DOWNLOADED, FileStatus.DOWNLOAD_FAILED},
    FileStatus.DOWNLOADED: {FileStatus.EXTRACTING},
    FileStatus.DOWNLOAD_FAILED: {FileStatus.QUEUED},
    FileStatus.EXTRACTING: {FileStatus.EXTRACTED, FileStatus.EXTRACT_FAILED},
    FileStatus.EXTRACTED: {FileStatus.INGESTING},
    FileStatus.EXTRACT_FAILED: {FileStatus.QUEUED},
    FileStatus.INGESTING: {FileStatus.INGESTED, FileStatus.INGEST_FAILED},
    FileStatus.INGESTED: {FileStatus.VERIFIED, FileStatus.VERIFY_FAILED},
    FileStatus.INGEST_FAILED: {FileStatus.QUEUED},
    FileStatus.VERIFIED: set(),
    FileStatus.VERIFY_FAILED: {FileStatus.QUEUED},
}

# Map status to the timestamp column to update
_STATUS_TIMESTAMP_COL: dict[FileStatus, str | None] = {
    FileStatus.DISCOVERED: None,
    FileStatus.QUEUED: "queued_at",
    FileStatus.DOWNLOADING: None,
    FileStatus.DOWNLOADED: "downloaded_at",
    FileStatus.DOWNLOAD_FAILED: None,
    FileStatus.EXTRACTING: None,
    FileStatus.EXTRACTED: "extracted_at",
    FileStatus.EXTRACT_FAILED: None,
    FileStatus.INGESTING: None,
    FileStatus.INGESTED: "ingested_at",
    FileStatus.INGEST_FAILED: None,
    FileStatus.VERIFIED: "verified_at",
    FileStatus.VERIFY_FAILED: None,
}

MAX_RETRIES = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS dou_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL UNIQUE,
    section TEXT NOT NULL,
    year_month TEXT NOT NULL,
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
    verified_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dou_files_status ON dou_files(status);
CREATE INDEX IF NOT EXISTS idx_dou_files_year_month ON dou_files(year_month);

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
    ) -> int:
        """Insert a new file record, returning its id."""
        now = _now()
        async with self.get_db() as db:
            cursor = await db.execute(
                """INSERT OR IGNORE INTO dou_files
                   (filename, section, year_month, folder_id, file_url, status,
                    discovered_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (filename, section, year_month, folder_id, file_url,
                 FileStatus.DISCOVERED.value, now, now),
            )
            await db.commit()
            return cursor.lastrowid or 0

    async def get_file_by_filename(self, filename: str) -> dict[str, Any] | None:
        """Look up a file by filename."""
        async with self.get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM dou_files WHERE filename = ?", (filename,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_file(self, file_id: int) -> dict[str, Any] | None:
        """Look up a file by id."""
        async with self.get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM dou_files WHERE id = ?", (file_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def update_status(
        self, file_id: int, new_status: FileStatus, *, _skip_validation: bool = False
    ) -> None:
        """Update file status with transition validation."""
        async with self.get_db() as db:
            cursor = await db.execute(
                "SELECT status FROM dou_files WHERE id = ?", (file_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError(f"File {file_id} not found")

            current = FileStatus(row["status"])
            if not _skip_validation:
                allowed = VALID_TRANSITIONS.get(current, set())
                if new_status not in allowed:
                    raise ValueError(
                        f"Invalid transition: {current.value} -> {new_status.value}"
                    )

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

    async def get_files_by_status(
        self, status: FileStatus, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get files with a given status."""
        async with self.get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM dou_files WHERE status = ? LIMIT ?",
                (status.value, limit),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_status_counts(self) -> dict[str, int]:
        """Get count of files by status."""
        async with self.get_db() as db:
            cursor = await db.execute(
                "SELECT status, COUNT(*) as cnt FROM dou_files GROUP BY status"
            )
            rows = await cursor.fetchall()
            return {r["status"]: r["cnt"] for r in rows}

    async def get_months(self, year: int | None = None) -> list[dict[str, Any]]:
        """Get file records grouped by year_month."""
        async with self.get_db() as db:
            query = "SELECT year_month, section, status, doc_count FROM dou_files"
            params: list[Any] = []
            if year:
                query += " WHERE year_month LIKE ?"
                params.append(f"{year}-%")
            query += " ORDER BY year_month DESC"
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

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
                (status, _now(), files_processed, files_succeeded,
                 files_failed, error_message, run_id),
            )
            await db.commit()

    async def add_log_entry(
        self, run_id: str, file_id: int | None, level: str, message: str
    ) -> None:
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
            cursor = await db.execute(
                "SELECT retry_count, status FROM dou_files WHERE id = ?", (file_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError(f"File {file_id} not found")

            new_count = row["retry_count"] + 1
            if new_count > MAX_RETRIES:
                raise ValueError(
                    f"File {file_id} has exceeded max retries ({MAX_RETRIES})"
                )

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
                    f["filename"], f["section"], f["year_month"],
                    f.get("folder_id"), f.get("file_url"),
                    f.get("status", FileStatus.DISCOVERED.value), now, now,
                )
                for f in files
            ]
            await db.executemany(
                """INSERT OR IGNORE INTO dou_files
                   (filename, section, year_month, folder_id, file_url, status,
                    discovered_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            await db.commit()
            return len(rows)

    async def get_disk_usage(self) -> dict[str, int]:
        """Get database file size."""
        try:
            size = os.path.getsize(self.db_path)
        except OSError:
            size = 0
        return {"db_size_bytes": size}
