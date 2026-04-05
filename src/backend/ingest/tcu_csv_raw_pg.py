"""Postgres DDL, header validation, and UPSERT for TCU CSV → raw colunar tables."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.backend.ingest.tcu_csv_raw_catalog import TcuCsvRawSource
from src.backend.ingest.tcu_csv_raw_id import tcu_csv_row_primary_key

META_TABLE = "raw.tcu_csv_fetch_meta"

_UPSERT_SQL_CACHE: dict[str, str] = {}


def _quote_ident_pg(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def ensure_meta_table(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS raw;")
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {META_TABLE} (
                url TEXT PRIMARY KEY,
                content_sha256 TEXT NOT NULL,
                bytes_size BIGINT NOT NULL,
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            f"ALTER TABLE {META_TABLE} ADD COLUMN IF NOT EXISTS response_etag TEXT;"
        )
    conn.commit()


def ensure_source_table(conn: Any, spec: TcuCsvRawSource) -> None:
    """Create colunar raw table if not exists (id, source_type, dumped_at + one TEXT column per CSV header)."""
    col_lines: list[str] = [
        "id TEXT PRIMARY KEY NOT NULL",
        "source_type TEXT NOT NULL",
        "dumped_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    ]
    for h in spec.csv_columns:
        col_lines.append(f"{_quote_ident_pg(h)} TEXT")
    cols_sql = ",\n    ".join(col_lines)
    idx_name = spec.table.replace(".", "_")
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS raw;")
        cur.execute(f"CREATE TABLE IF NOT EXISTS {spec.table} (\n    {cols_sql}\n);")
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{idx_name}_dumped_at ON {spec.table} (dumped_at DESC);"
        )
    conn.commit()


def normalize_fieldnames(fieldnames: list[str] | None) -> list[str]:
    if not fieldnames:
        return []
    return [(f or "").strip() for f in fieldnames if f is not None]


def validate_csv_headers(fieldnames: list[str] | None, spec: TcuCsvRawSource) -> None:
    """Exact set match: CSV header columns must equal catalog (drift detection)."""
    headers = normalize_fieldnames(fieldnames)
    if not headers:
        msg = "CSV has no header row"
        raise ValueError(msg)
    header_set = set(headers)
    expected = set(spec.csv_columns)
    if header_set != expected:
        missing = sorted(expected - header_set)
        extra = sorted(header_set - expected)
        msg = f"{spec.name}: header mismatch. missing={missing} extra={extra}"
        raise ValueError(msg)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1_048_576), b""):
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def fetch_meta_digest(conn: Any, url: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(f"SELECT content_sha256 FROM {META_TABLE} WHERE url = %s", (url,))
        row = cur.fetchone()
    return row[0] if row else None


def fetch_meta_etag(conn: Any, url: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(f"SELECT response_etag FROM {META_TABLE} WHERE url = %s", (url,))
        row = cur.fetchone()
    if not row or row[0] is None:
        return None
    return str(row[0]).strip() or None


def upsert_fetch_meta(
    conn: Any, url: str, digest: str, size: int, *, response_etag: str | None = None
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {META_TABLE} AS m (url, content_sha256, bytes_size, fetched_at, response_etag)
            VALUES (%s, %s, %s, NOW(), %s)
            ON CONFLICT (url) DO UPDATE SET
                content_sha256 = EXCLUDED.content_sha256,
                bytes_size = EXCLUDED.bytes_size,
                fetched_at = NOW(),
                response_etag = COALESCE(EXCLUDED.response_etag, m.response_etag);
            """,
            (url, digest, size, response_etag),
        )
    conn.commit()


def _build_upsert_sql(spec: TcuCsvRawSource) -> str:
    if spec.table in _UPSERT_SQL_CACHE:
        return _UPSERT_SQL_CACHE[spec.table]
    headers = list(spec.csv_columns)
    cols = ["id", "source_type", "dumped_at"] + [_quote_ident_pg(h) for h in headers]
    col_list = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    set_parts = [
        "source_type = EXCLUDED.source_type",
        "dumped_at = EXCLUDED.dumped_at",
    ]
    for h in headers:
        qi = _quote_ident_pg(h)
        set_parts.append(f"{qi} = EXCLUDED.{qi}")
    stmt = (
        f"INSERT INTO {spec.table} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT (id) DO UPDATE SET " + ", ".join(set_parts)
    )
    _UPSERT_SQL_CACHE[spec.table] = stmt
    return stmt


def upsert_csv_rows(
    conn: Any,
    spec: TcuCsvRawSource,
    rows: list[dict[str, str]],
    *,
    now: datetime | None = None,
) -> tuple[int, int]:
    """UPSERT batch. Returns (upserted, skipped_bad_key)."""
    if not rows:
        return 0, 0
    ts = now or datetime.now(timezone.utc)
    headers = list(spec.csv_columns)
    stmt = _build_upsert_sql(spec)
    upserted = 0
    skipped = 0
    tuples: list[tuple[Any, ...]] = []
    for row in rows:
        try:
            rid = tcu_csv_row_primary_key(row)
        except ValueError:
            skipped += 1
            continue
        values: list[Any] = [rid, spec.source_type, ts]
        for h in headers:
            v = row.get(h)
            values.append(v if v is not None and v != "" else None)
        tuples.append(tuple(values))
    if not tuples:
        return 0, skipped
    with conn.cursor() as cur:
        cur.executemany(stmt, tuples)
        upserted = len(tuples)
    return upserted, skipped
