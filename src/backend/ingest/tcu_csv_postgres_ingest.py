"""TCU dados abertos CSV → Postgres raw colunar (reingest direto; sem Mongo).

Cobre as 8 fontes em tcu_csv_raw_catalog.TCU_CSV_RAW_SOURCES.

Fora de âmbito (scraping / não-CSV): tcu_btcu, tcu_publicacoes — manter pipelines existentes.

Política de PK: id == KEY normalizado do CSV, alinhado a Mongo _id / ES _id usados em
tcu_ingest.py e tcu_jurisprudencia_ingest.py (doc_id).

Usage:
  python -m src.backend.ingest.tcu_csv_postgres_ingest --ddl-only
  python -m src.backend.ingest.tcu_csv_postgres_ingest --source sumula
  python -m src.backend.ingest.tcu_csv_postgres_ingest --all --year-from 2002 --year-to 2026
  python -m src.backend.ingest.tcu_csv_postgres_ingest --validate-headers-only --source jurisprudencia_selecionada
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx
import psycopg

from src.backend.core.config import settings
from src.backend.ingest.tcu_csv_raw_catalog import (
    TCU_CSV_RAW_SOURCES,
    TcuCsvRawSource,
    acordao_url,
    source_by_name,
)
from src.backend.ingest.tcu_csv_raw_pg import (
    ensure_meta_table,
    ensure_source_table,
    fetch_meta_digest,
    fetch_meta_etag,
    sha256_file,
    upsert_csv_rows,
    upsert_fetch_meta,
    validate_csv_headers,
)
from src.backend.ingest.tcu_processor import iter_csv_rows

_log = logging.getLogger(__name__)


def _download(
    url: str, dest: Path, *, timeout: float = 600.0
) -> tuple[int, str | None]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    etag: str | None = None
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            raw_etag = resp.headers.get("etag")
            if raw_etag:
                etag = raw_etag.strip() or None
            n = 0
            with dest.open("wb") as f:
                for chunk in resp.iter_bytes(1_048_576):
                    if chunk:
                        f.write(chunk)
                        n += len(chunk)
    return n, etag


def _skip_unchanged_by_head_etag(conn: Any, url: str, *, skip_unchanged: bool) -> bool:
    if not skip_unchanged:
        return False
    stored = fetch_meta_etag(conn, url)
    if not stored:
        return False
    try:
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            head = client.head(url)
            if head.status_code in (405, 501):
                return False
            head.raise_for_status()
    except httpx.HTTPError:
        return False
    remote = (head.headers.get("etag") or "").strip()
    return bool(remote) and remote == stored


def _peek_csv_headers(path: Path) -> list[str]:
    csv.field_size_limit(sys.maxsize)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter="|", quotechar='"')
        first = next(reader, None)
    if not first:
        return []
    return [c.strip() for c in first]


def ingest_one_file(
    conn: Any,
    spec: TcuCsvRawSource,
    filepath: Path,
    meta_url: str,
    *,
    batch_size: int,
    skip_unchanged: bool,
    row_limit: int | None,
    response_etag: str | None,
) -> dict[str, int]:
    stats = {"rows_read": 0, "upserted": 0, "skipped_key": 0, "batches": 0}
    size = filepath.stat().st_size
    digest = sha256_file(filepath)
    if skip_unchanged and fetch_meta_digest(conn, meta_url) == digest:
        _log.info("skip unchanged sha256=%s url=%s", digest[:12], meta_url)
        return stats

    headers = _peek_csv_headers(filepath)
    validate_csv_headers(headers, spec)

    batch: list[dict[str, str]] = []
    for row in iter_csv_rows(str(filepath)):
        stats["rows_read"] += 1
        if row_limit is not None and stats["rows_read"] > row_limit:
            break
        batch.append(row)
        if len(batch) >= batch_size:
            u, sk = upsert_csv_rows(conn, spec, batch)
            conn.commit()
            stats["upserted"] += u
            stats["skipped_key"] += sk
            stats["batches"] += 1
            batch = []
    if batch:
        u, sk = upsert_csv_rows(conn, spec, batch)
        conn.commit()
        stats["upserted"] += u
        stats["skipped_key"] += sk
        stats["batches"] += 1

    upsert_fetch_meta(conn, meta_url, digest, size, response_etag=response_etag)
    return stats


def run_ddl(conn: Any) -> None:
    ensure_meta_table(conn)
    for spec in TCU_CSV_RAW_SOURCES:
        ensure_source_table(conn, spec)
        _log.info("ensured table %s", spec.table)


def run_validate_headers_only(cache: Path, spec: TcuCsvRawSource) -> None:
    url = spec.url
    if not url:
        raise SystemExit(
            f"{spec.name} uses year template; pass --source acordao + years"
        )
    dest = cache / url.split("/")[-1]
    _, _ = _download(url, dest)
    headers = _peek_csv_headers(dest)
    validate_csv_headers(headers, spec)
    _log.info("OK headers match catalog for %s (%d columns)", spec.name, len(headers))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="TCU CSV → Postgres raw colunar")
    p.add_argument(
        "--postgres-url", default=os.getenv("POSTGRES_URL", settings.POSTGRES_URL)
    )
    p.add_argument(
        "--ddl-only", action="store_true", help="Create meta + all raw tables"
    )
    p.add_argument(
        "--all", action="store_true", help="Ingest every CSV source + acordao years"
    )
    p.add_argument(
        "--source",
        action="append",
        dest="sources",
        metavar="NAME",
        help="Catalog name (repeatable)",
    )
    p.add_argument("--year-from", type=int, default=1992)
    p.add_argument("--year-to", type=int, default=2026)
    p.add_argument("--batch-size", type=int, default=500)
    p.add_argument("--cache-dir", default=None, help="CSV cache directory")
    p.add_argument(
        "--skip-unchanged",
        action="store_true",
        help="Skip ingest if ETag (HEAD) or file SHA256 matches last successful fetch",
    )
    p.add_argument(
        "--limit", type=int, default=None, help="Max rows per file (testing)"
    )
    p.add_argument("--validate-headers-only", action="store_true")
    p.add_argument(
        "--validate-acordao-year",
        type=int,
        default=2026,
        help="With --validate-headers-only --source acordao_completo: which year's CSV header to check",
    )
    args = p.parse_args()

    cache = Path(args.cache_dir or tempfile.mkdtemp(prefix="tcu_csv_pg_"))
    cache.mkdir(parents=True, exist_ok=True)

    if args.validate_headers_only:
        names = args.sources or [s.name for s in TCU_CSV_RAW_SOURCES]
        for name in names:
            spec = source_by_name(name)
            if spec.url_template_year:
                url = acordao_url(args.validate_acordao_year)
                dest = cache / url.split("/")[-1]
                _, _ = _download(url, dest)
                headers = _peek_csv_headers(dest)
                validate_csv_headers(headers, spec)
                _log.info(
                    "OK headers acordao_completo year=%s (%d columns)",
                    args.validate_acordao_year,
                    len(headers),
                )
                continue
            run_validate_headers_only(cache, spec)
        return

    with psycopg.connect(args.postgres_url) as conn:
        if args.ddl_only:
            run_ddl(conn)
            return

        specs: list[tuple[TcuCsvRawSource, str | None, int | None]] = []
        if args.all:
            for spec in TCU_CSV_RAW_SOURCES:
                if spec.url_template_year:
                    for year in range(args.year_from, args.year_to + 1):
                        specs.append((spec, acordao_url(year), year))
                else:
                    specs.append((spec, spec.url, None))
        elif args.sources:
            for name in args.sources:
                spec = source_by_name(name)
                if spec.url_template_year:
                    for year in range(args.year_from, args.year_to + 1):
                        specs.append((spec, acordao_url(year), year))
                else:
                    specs.append((spec, spec.url, None))
        else:
            p.error("pass --ddl-only, --all, or --source NAME")

        ensure_meta_table(conn)
        for spec, url, year in specs:
            if not url:
                continue
            ensure_source_table(conn, spec)
            meta_url = url
            dest = cache / url.split("/")[-1]
            if _skip_unchanged_by_head_etag(
                conn, meta_url, skip_unchanged=args.skip_unchanged
            ):
                _log.info("skip unchanged etag url=%s", meta_url)
                continue
            try:
                _, response_etag = _download(url, dest)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404 and spec.url_template_year:
                    _log.warning("404 skip acordao year=%s", year)
                    continue
                raise
            _log.info("ingest %s file=%s", spec.name, dest.name)
            st = ingest_one_file(
                conn,
                spec,
                dest,
                meta_url,
                batch_size=args.batch_size,
                skip_unchanged=args.skip_unchanged,
                row_limit=args.limit,
                response_etag=response_etag,
            )
            _log.info(
                "done %s read=%s upserted=%s skipped_key=%s batches=%s",
                spec.name,
                st["rows_read"],
                st["upserted"],
                st["skipped_key"],
                st["batches"],
            )


if __name__ == "__main__":
    main()
