"""Discovery registry — track discovered DOU publications.

Maintains a persistent record of which publications have been discovered
and whether they have been downloaded. Used by the automated pipeline to
avoid re-discovering or re-downloading the same content.

Storage options:
  - PostgreSQL (recommended for production)
  - SQLite (for development/testing)
  - In-memory (for testing only)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import psycopg


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DiscoveredPublication:
    """Metadata about a discovered (but not necessarily downloaded) publication."""
    section: str              # do1, do2, do3, do1e, do2e, do3e, etc.
    publication_date: date    # YYYY-MM-DD (first day of month for monthly ZIPs)
    edition_number: str       # e.g., "123" (often empty for monthly bundles)
    edition_type: str         # "regular", "extra", "special"
    folder_id: int            # Liferay folder ID
    filename: str             # Server filename (e.g., S01012026.zip)
    file_size: int | None     # Bytes (None if not yet downloaded)
    discovered_at: datetime   # When we first saw this publication
    downloaded: bool = False  # Whether we've downloaded it
    downloaded_at: datetime | None = None  # When we downloaded it
    download_error: str | None = None  # Error message if download failed
    sha256: str | None = None  # SHA-256 checksum (after download)
    local_filename: str | None = None  # Local filename after download

    def as_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "section": self.section,
            "publication_date": self.publication_date.isoformat(),
            "edition_number": self.edition_number,
            "edition_type": self.edition_type,
            "folder_id": self.folder_id,
            "filename": self.filename,
            "file_size": self.file_size,
            "discovered_at": self.discovered_at.isoformat(),
            "downloaded": self.downloaded,
            "downloaded_at": self.downloaded_at.isoformat() if self.downloaded_at else None,
            "download_error": self.download_error,
            "sha256": self.sha256,
            "local_filename": self.local_filename,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiscoveredPublication:
        """Create from dict."""
        return cls(
            section=data["section"],
            publication_date=date.fromisoformat(data["publication_date"]),
            edition_number=data["edition_number"],
            edition_type=data["edition_type"],
            folder_id=data["folder_id"],
            filename=data["filename"],
            file_size=data["file_size"],
            discovered_at=datetime.fromisoformat(data["discovered_at"]),
            downloaded=data["downloaded"],
            downloaded_at=datetime.fromisoformat(data["downloaded_at"]) if data.get("downloaded_at") else None,
            download_error=data.get("download_error"),
            sha256=data.get("sha256"),
            local_filename=data.get("local_filename"),
        )


# ---------------------------------------------------------------------------
# Registry interface
# ---------------------------------------------------------------------------

class DiscoveryRegistry:
    """Interface for discovery registry storage."""

    def add_publication(self, pub: DiscoveredPublication) -> None:
        """Add a newly discovered publication."""
        raise NotImplementedError

    def mark_downloaded(
        self,
        section: str,
        publication_date: date,
        filename: str,
        file_size: int,
        sha256: str,
        local_filename: str,
    ) -> None:
        """Mark a publication as downloaded."""
        raise NotImplementedError

    def mark_download_failed(
        self,
        section: str,
        publication_date: date,
        filename: str,
        error: str,
    ) -> None:
        """Mark a publication download as failed."""
        raise NotImplementedError

    def get_publication(
        self,
        section: str,
        publication_date: date,
        filename: str,
    ) -> DiscoveredPublication | None:
        """Get a publication by key."""
        raise NotImplementedError

    def list_discovered(
        self,
        section: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        downloaded: bool | None = None,
    ) -> list[DiscoveredPublication]:
        """List discovered publications with optional filters."""
        raise NotImplementedError

    def count_discovered(
        self,
        section: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        downloaded: bool | None = None,
    ) -> int:
        """Count discovered publications with optional filters."""
        raise NotImplementedError

    def close(self) -> None:
        """Close the registry (if applicable)."""
        pass


# ---------------------------------------------------------------------------
# PostgreSQL registry
# ---------------------------------------------------------------------------

class PostgreSQLDiscoveryRegistry(DiscoveryRegistry):
    """Discovery registry backed by PostgreSQL."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create schema and tables if they don't exist."""
        with psycopg.connect(self.dsn) as conn:
            conn.execute("CREATE SCHEMA IF NOT EXISTS discovery")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS discovery.publications (
                    id SERIAL PRIMARY KEY,
                    section TEXT NOT NULL,
                    publication_date DATE NOT NULL,
                    edition_number TEXT,
                    edition_type TEXT NOT NULL,
                    folder_id INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    file_size BIGINT,
                    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    downloaded BOOLEAN NOT NULL DEFAULT FALSE,
                    downloaded_at TIMESTAMPTZ,
                    download_error TEXT,
                    sha256 TEXT,
                    local_filename TEXT,
                    UNIQUE(section, publication_date, filename)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_publications_section_date
                ON discovery.publications(section, publication_date)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_publications_downloaded
                ON discovery.publications(downloaded)
            """)
            conn.commit()

    def add_publication(self, pub: DiscoveredPublication) -> None:
        """Add a newly discovered publication."""
        with psycopg.connect(self.dsn) as conn:
            conn.execute("""
                INSERT INTO discovery.publications (
                    section, publication_date, edition_number, edition_type,
                    folder_id, filename, file_size, discovered_at,
                    downloaded, downloaded_at, download_error, sha256, local_filename
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (section, publication_date, filename) DO NOTHING
            """, (
                pub.section,
                pub.publication_date,
                pub.edition_number,
                pub.edition_type,
                pub.folder_id,
                pub.filename,
                pub.file_size,
                pub.discovered_at,
                pub.downloaded,
                pub.downloaded_at,
                pub.download_error,
                pub.sha256,
                pub.local_filename,
            ))
            conn.commit()

    def mark_downloaded(
        self,
        section: str,
        publication_date: date,
        filename: str,
        file_size: int,
        sha256: str,
        local_filename: str,
    ) -> None:
        """Mark a publication as downloaded."""
        with psycopg.connect(self.dsn) as conn:
            conn.execute("""
                UPDATE discovery.publications
                SET downloaded = TRUE,
                    downloaded_at = NOW(),
                    file_size = %s,
                    sha256 = %s,
                    local_filename = %s,
                    download_error = NULL
                WHERE section = %s
                  AND publication_date = %s
                  AND filename = %s
            """, (
                file_size,
                sha256,
                local_filename,
                section,
                publication_date,
                filename,
            ))
            conn.commit()

    def mark_download_failed(
        self,
        section: str,
        publication_date: date,
        filename: str,
        error: str,
    ) -> None:
        """Mark a publication download as failed."""
        with psycopg.connect(self.dsn) as conn:
            conn.execute("""
                UPDATE discovery.publications
                SET download_error = %s
                WHERE section = %s
                  AND publication_date = %s
                  AND filename = %s
            """, (
                error,
                section,
                publication_date,
                filename,
            ))
            conn.commit()

    def get_publication(
        self,
        section: str,
        publication_date: date,
        filename: str,
    ) -> DiscoveredPublication | None:
        """Get a publication by key."""
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute("""
                SELECT section, publication_date, edition_number, edition_type,
                       folder_id, filename, file_size, discovered_at,
                       downloaded, downloaded_at, download_error, sha256, local_filename
                FROM discovery.publications
                WHERE section = %s
                  AND publication_date = %s
                  AND filename = %s
            """, (section, publication_date, filename)).fetchone()

            if row is None:
                return None

            return DiscoveredPublication(
                section=row[0],
                publication_date=row[1],
                edition_number=row[2],
                edition_type=row[3],
                folder_id=row[4],
                filename=row[5],
                file_size=row[6],
                discovered_at=row[7],
                downloaded=row[8],
                downloaded_at=row[9],
                download_error=row[10],
                sha256=row[11],
                local_filename=row[12],
            )

    def list_discovered(
        self,
        section: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        downloaded: bool | None = None,
    ) -> list[DiscoveredPublication]:
        """List discovered publications with optional filters."""
        query = """
            SELECT section, publication_date, edition_number, edition_type,
                   folder_id, filename, file_size, discovered_at,
                   downloaded, downloaded_at, download_error, sha256, local_filename
            FROM discovery.publications
            WHERE TRUE
        """
        params: list[Any] = []

        if section is not None:
            query += " AND section = %s"
            params.append(section)
        if start_date is not None:
            query += " AND publication_date >= %s"
            params.append(start_date)
        if end_date is not None:
            query += " AND publication_date <= %s"
            params.append(end_date)
        if downloaded is not None:
            query += " AND downloaded = %s"
            params.append(downloaded)

        query += " ORDER BY publication_date DESC, section, filename"

        with psycopg.connect(self.dsn) as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            DiscoveredPublication(
                section=row[0],
                publication_date=row[1],
                edition_number=row[2],
                edition_type=row[3],
                folder_id=row[4],
                filename=row[5],
                file_size=row[6],
                discovered_at=row[7],
                downloaded=row[8],
                downloaded_at=row[9],
                download_error=row[10],
                sha256=row[11],
                local_filename=row[12],
            )
            for row in rows
        ]

    def count_discovered(
        self,
        section: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        downloaded: bool | None = None,
    ) -> int:
        """Count discovered publications with optional filters."""
        query = "SELECT COUNT(*) FROM discovery.publications WHERE TRUE"
        params: list[Any] = []

        if section is not None:
            query += " AND section = %s"
            params.append(section)
        if start_date is not None:
            query += " AND publication_date >= %s"
            params.append(start_date)
        if end_date is not None:
            query += " AND publication_date <= %s"
            params.append(end_date)
        if downloaded is not None:
            query += " AND downloaded = %s"
            params.append(downloaded)

        with psycopg.connect(self.dsn) as conn:
            row = conn.execute(query, params).fetchone()
            return row[0] if row else 0


# ---------------------------------------------------------------------------
# SQLite registry (for development/testing)
# ---------------------------------------------------------------------------

class SQLiteDiscoveryRegistry(DiscoveryRegistry):
    """Discovery registry backed by SQLite."""

    def __init__(self, db_path: Path | str) -> None:
        import sqlite3
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create schema and tables if they don't exist."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS publications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                section TEXT NOT NULL,
                publication_date TEXT NOT NULL,
                edition_number TEXT,
                edition_type TEXT NOT NULL,
                folder_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                file_size INTEGER,
                discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                downloaded BOOLEAN NOT NULL DEFAULT 0,
                downloaded_at TEXT,
                download_error TEXT,
                sha256 TEXT,
                local_filename TEXT,
                UNIQUE(section, publication_date, filename)
            )
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_publications_section_date
            ON publications(section, publication_date)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_publications_downloaded
            ON publications(downloaded)
        """)
        self.conn.commit()

    def add_publication(self, pub: DiscoveredPublication) -> None:
        """Add a newly discovered publication."""
        self.conn.execute("""
            INSERT OR IGNORE INTO publications (
                section, publication_date, edition_number, edition_type,
                folder_id, filename, file_size, discovered_at,
                downloaded, downloaded_at, download_error, sha256, local_filename
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pub.section,
            pub.publication_date.isoformat(),
            pub.edition_number,
            pub.edition_type,
            pub.folder_id,
            pub.filename,
            pub.file_size,
            pub.discovered_at.isoformat(),
            pub.downloaded,
            pub.downloaded_at.isoformat() if pub.downloaded_at else None,
            pub.download_error,
            pub.sha256,
            pub.local_filename,
        ))
        self.conn.commit()

    def mark_downloaded(
        self,
        section: str,
        publication_date: date,
        filename: str,
        file_size: int,
        sha256: str,
        local_filename: str,
    ) -> None:
        """Mark a publication as downloaded."""
        self.conn.execute("""
            UPDATE publications
            SET downloaded = 1,
                downloaded_at = CURRENT_TIMESTAMP,
                file_size = ?,
                sha256 = ?,
                local_filename = ?,
                download_error = NULL
            WHERE section = ?
              AND publication_date = ?
              AND filename = ?
        """, (
            file_size,
            sha256,
            local_filename,
            section,
            publication_date.isoformat(),
            filename,
        ))
        self.conn.commit()

    def mark_download_failed(
        self,
        section: str,
        publication_date: date,
        filename: str,
        error: str,
    ) -> None:
        """Mark a publication download as failed."""
        self.conn.execute("""
            UPDATE publications
            SET download_error = ?
            WHERE section = ?
              AND publication_date = ?
              AND filename = ?
        """, (
            error,
            section,
            publication_date.isoformat(),
            filename,
        ))
        self.conn.commit()

    def get_publication(
        self,
        section: str,
        publication_date: date,
        filename: str,
    ) -> DiscoveredPublication | None:
        """Get a publication by key."""
        row = self.conn.execute("""
            SELECT section, publication_date, edition_number, edition_type,
                   folder_id, filename, file_size, discovered_at,
                   downloaded, downloaded_at, download_error, sha256, local_filename
            FROM publications
            WHERE section = ?
              AND publication_date = ?
              AND filename = ?
        """, (section, publication_date.isoformat(), filename)).fetchone()

        if row is None:
            return None

        return DiscoveredPublication(
            section=row[0],
            publication_date=date.fromisoformat(row[1]),
            edition_number=row[2],
            edition_type=row[3],
            folder_id=row[4],
            filename=row[5],
            file_size=row[6],
            discovered_at=datetime.fromisoformat(row[7]),
            downloaded=bool(row[8]),
            downloaded_at=datetime.fromisoformat(row[9]) if row[9] else None,
            download_error=row[10],
            sha256=row[11],
            local_filename=row[12],
        )

    def list_discovered(
        self,
        section: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        downloaded: bool | None = None,
    ) -> list[DiscoveredPublication]:
        """List discovered publications with optional filters."""
        query = """
            SELECT section, publication_date, edition_number, edition_type,
                   folder_id, filename, file_size, discovered_at,
                   downloaded, downloaded_at, download_error, sha256, local_filename
            FROM publications
            WHERE TRUE
        """
        params: list[Any] = []

        if section is not None:
            query += " AND section = ?"
            params.append(section)
        if start_date is not None:
            query += " AND publication_date >= ?"
            params.append(start_date.isoformat())
        if end_date is not None:
            query += " AND publication_date <= ?"
            params.append(end_date.isoformat())
        if downloaded is not None:
            query += " AND downloaded = ?"
            params.append(int(downloaded))

        query += " ORDER BY publication_date DESC, section, filename"

        rows = self.conn.execute(query, params).fetchall()

        return [
            DiscoveredPublication(
                section=row[0],
                publication_date=date.fromisoformat(row[1]),
                edition_number=row[2],
                edition_type=row[3],
                folder_id=row[4],
                filename=row[5],
                file_size=row[6],
                discovered_at=datetime.fromisoformat(row[7]),
                downloaded=bool(row[8]),
                downloaded_at=datetime.fromisoformat(row[9]) if row[9] else None,
                download_error=row[10],
                sha256=row[11],
                local_filename=row[12],
            )
            for row in rows
        ]

    def count_discovered(
        self,
        section: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        downloaded: bool | None = None,
    ) -> int:
        """Count discovered publications with optional filters."""
        query = "SELECT COUNT(*) FROM publications WHERE TRUE"
        params: list[Any] = []

        if section is not None:
            query += " AND section = ?"
            params.append(section)
        if start_date is not None:
            query += " AND publication_date >= ?"
            params.append(start_date.isoformat())
        if end_date is not None:
            query += " AND publication_date <= ?"
            params.append(end_date.isoformat())
        if downloaded is not None:
            query += " AND downloaded = ?"
            params.append(int(downloaded))

        row = self.conn.execute(query, params).fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()


# ---------------------------------------------------------------------------
# In-memory registry (for testing)
# ---------------------------------------------------------------------------

class InMemoryDiscoveryRegistry(DiscoveryRegistry):
    """In-memory discovery registry (for testing)."""

    def __init__(self) -> None:
        self.publications: dict[tuple[str, date, str], DiscoveredPublication] = {}

    def add_publication(self, pub: DiscoveredPublication) -> None:
        """Add a newly discovered publication."""
        key = (pub.section, pub.publication_date, pub.filename)
        self.publications[key] = pub

    def mark_downloaded(
        self,
        section: str,
        publication_date: date,
        filename: str,
        file_size: int,
        sha256: str,
        local_filename: str,
    ) -> None:
        """Mark a publication as downloaded."""
        key = (section, publication_date, filename)
        if key in self.publications:
            pub = self.publications[key]
            self.publications[key] = DiscoveredPublication(
                section=pub.section,
                publication_date=pub.publication_date,
                edition_number=pub.edition_number,
                edition_type=pub.edition_type,
                folder_id=pub.folder_id,
                filename=pub.filename,
                file_size=file_size,
                discovered_at=pub.discovered_at,
                downloaded=True,
                downloaded_at=datetime.now(),
                download_error=None,
                sha256=sha256,
                local_filename=local_filename,
            )

    def mark_download_failed(
        self,
        section: str,
        publication_date: date,
        filename: str,
        error: str,
    ) -> None:
        """Mark a publication download as failed."""
        key = (section, publication_date, filename)
        if key in self.publications:
            pub = self.publications[key]
            self.publications[key] = DiscoveredPublication(
                section=pub.section,
                publication_date=pub.publication_date,
                edition_number=pub.edition_number,
                edition_type=pub.edition_type,
                folder_id=pub.folder_id,
                filename=pub.filename,
                file_size=pub.file_size,
                discovered_at=pub.discovered_at,
                downloaded=False,
                downloaded_at=None,
                download_error=error,
                sha256=pub.sha256,
                local_filename=pub.local_filename,
            )

    def get_publication(
        self,
        section: str,
        publication_date: date,
        filename: str,
    ) -> DiscoveredPublication | None:
        """Get a publication by key."""
        key = (section, publication_date, filename)
        return self.publications.get(key)

    def list_discovered(
        self,
        section: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        downloaded: bool | None = None,
    ) -> list[DiscoveredPublication]:
        """List discovered publications with optional filters."""
        results = list(self.publications.values())

        if section is not None:
            results = [p for p in results if p.section == section]
        if start_date is not None:
            results = [p for p in results if p.publication_date >= start_date]
        if end_date is not None:
            results = [p for p in results if p.publication_date <= end_date]
        if downloaded is not None:
            results = [p for p in results if p.downloaded == downloaded]

        return sorted(results, key=lambda p: (p.publication_date, p.section, p.filename), reverse=True)

    def count_discovered(
        self,
        section: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        downloaded: bool | None = None,
    ) -> int:
        """Count discovered publications with optional filters."""
        return len(self.list_discovered(section, start_date, end_date, downloaded))


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------

def create_registry(
    backend: str = "postgresql",
    **kwargs: Any,
) -> DiscoveryRegistry:
    """Create a discovery registry instance.

    Args:
        backend: "postgresql", "sqlite", or "memory"
        **kwargs: Backend-specific arguments
            - postgresql: dsn (str)
            - sqlite: db_path (Path | str)
            - memory: no arguments

    Returns:
        DiscoveryRegistry instance
    """
    if backend == "postgresql":
        return PostgreSQLDiscoveryRegistry(kwargs["dsn"])
    elif backend == "sqlite":
        return SQLiteDiscoveryRegistry(kwargs["db_path"])
    elif backend == "memory":
        return InMemoryDiscoveryRegistry()
    else:
        raise ValueError(f"Unknown backend: {backend}")
