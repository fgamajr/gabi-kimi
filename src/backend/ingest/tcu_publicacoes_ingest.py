"""Ingest TCU Publicações Institucionais into gabi_tcu_publicacoes_v1.

Usage:
  python -m src.backend.ingest.tcu_publicacoes_ingest --ingest          # Full scrape
  python -m src.backend.ingest.tcu_publicacoes_ingest --ingest --recent  # Skip known slugs
  python -m src.backend.ingest.tcu_publicacoes_ingest --stats            # Show counts
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import psycopg

from src.backend.core.config import settings
from src.backend.ingest.tcu_publicacoes_processor import pub_to_es_doc
from src.backend.ingest.tcu_publicacoes_scraper import scrape_all

_PUB_INDEX = "gabi_tcu_publicacoes_v1"
_MAPPING_PATH = (
    Path(__file__).resolve().parent.parent
    / "search"
    / "es_tcu_publicacoes_mapping.json"
)
_PG_TABLE = "raw.tcu_publicacoes_raw_data"
_PDF_CACHE_SUBDIR = "tcu_publicacoes_cache"
_CURSOR_FILENAME = "tcu_publicacoes_cursor.json"
_ES_BATCH_SIZE = 50
_PDF_DOWNLOAD_DELAY = 0.5  # seconds between PDF downloads


def _log(msg: str) -> None:
    print(f"[tcu-pub-ingest] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Infrastructure helpers
# ---------------------------------------------------------------------------


def _es_url() -> str:
    return os.getenv("ES_URL", "http://elasticsearch:9200").rstrip("/")


def _pub_index() -> str:
    return os.getenv("TCU_PUBLICACOES_INDEX", _PUB_INDEX)


def _pg_url() -> str:
    return os.getenv("POSTGRES_URL", settings.POSTGRES_URL)


def _cursor_path() -> Path:
    data_root = os.getenv("DOU_DATA_PATH", "/data/gabi_dou")
    container_path = Path(data_root) / _CURSOR_FILENAME
    if container_path.parent.exists():
        return container_path
    # Local dev fallback
    return Path(__file__).resolve().parents[3] / "ops" / "data" / _CURSOR_FILENAME


def _load_cursor() -> set[str]:
    """Load set of already-processed slugs from cursor file."""
    path = _cursor_path()
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return set(data.get("processed_slugs", []))
        except (json.JSONDecodeError, KeyError):
            pass
    return set()


def _save_cursor(processed_slugs: set[str]) -> None:
    path = _cursor_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "processed_slugs": sorted(processed_slugs),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    _log(f"cursor saved ({len(processed_slugs)} slugs)")


def _pdf_cache_dir() -> Path:
    data_root = os.getenv("DOU_DATA_PATH", "/data/gabi_dou")
    cache = Path(data_root) / _PDF_CACHE_SUBDIR
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _ensure_index(es_client: httpx.Client) -> None:
    index = _pub_index()
    url = _es_url()
    resp = es_client.head(f"{url}/{index}")
    if resp.status_code == 404:
        with _MAPPING_PATH.open("r", encoding="utf-8") as f:
            mapping = json.load(f)
        _log(f"creating index {index}")
        resp = es_client.put(f"{url}/{index}", json=mapping)
        resp.raise_for_status()
    es_client.get(f"{url}/_cluster/health/{index}?wait_for_status=yellow&timeout=60s")


def _es_bulk(docs: list[dict], es_client: httpx.Client) -> tuple[int, int]:
    """NDJSON bulk upsert. Returns (ok_count, failed_count)."""
    index = _pub_index()
    lines: list[str] = []
    for doc in docs:
        lines.append(
            json.dumps(
                {"index": {"_index": index, "_id": doc["doc_id"]}}, ensure_ascii=False
            )
        )
        lines.append(json.dumps(doc, ensure_ascii=False))
    body = "\n".join(lines) + "\n"
    resp = es_client.post(
        f"{_es_url()}/_bulk",
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/x-ndjson"},
        timeout=120,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    ok = sum(1 for i in items if 200 <= i.get("index", {}).get("status", 500) < 300)
    return ok, len(items) - ok


# ---------------------------------------------------------------------------
# Postgres helpers
# ---------------------------------------------------------------------------


def _pg_fetch_hash(conn: psycopg.Connection, doc_id: str) -> str | None:
    """Fetch deterministic_hash from Postgres for dedup."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT all_fields->>'deterministic_hash' FROM {_PG_TABLE} WHERE id = %s",
            (doc_id,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def _pg_upsert(conn: psycopg.Connection, doc: dict) -> None:
    """Upsert a single publication doc into Postgres."""
    doc_id = doc["doc_id"]
    all_fields = json.dumps(
        {**doc, "updated_at": datetime.now(timezone.utc).isoformat()},
        default=str,
        ensure_ascii=False,
    )
    with conn.cursor() as cur:
        cur.execute(
            f"""INSERT INTO {_PG_TABLE} (id, all_fields, dumped_at)
               VALUES (%s, %s::jsonb, NOW())
               ON CONFLICT (id) DO UPDATE SET
                   all_fields = EXCLUDED.all_fields,
                   dumped_at = NOW()""",
            (doc_id, all_fields),
        )


# ---------------------------------------------------------------------------
# PDF download + extraction
# ---------------------------------------------------------------------------


def _download_pdf(
    pdf_url: str, slug_hash: str, pdf_index: int, cache_dir: Path, client: httpx.Client
) -> str | None:
    """Download PDF to cache. Returns local filepath or None on failure."""
    filename = f"{slug_hash}_{pdf_index}.pdf"
    filepath = cache_dir / filename
    if filepath.exists() and filepath.stat().st_size > 0:
        return str(filepath)
    try:
        resp = client.get(pdf_url, timeout=120)
        resp.raise_for_status()
        filepath.write_bytes(resp.content)
        return str(filepath)
    except Exception as exc:
        _log(f"    PDF download failed ({pdf_url}): {exc}")
        return None


def _extract_pdf_text(filepath: str) -> tuple[str, int]:
    """Extract text from PDF using PyMuPDF. Returns (text, page_count)."""
    import fitz  # pymupdf

    doc = fitz.open(filepath)
    page_count = doc.page_count
    pages_text = [page.get_text() for page in doc]
    doc.close()
    return "\n".join(pages_text), page_count


# ---------------------------------------------------------------------------
# Main ingest pipeline
# ---------------------------------------------------------------------------


def run_ingest(recent_only: bool = False) -> None:
    """Run full ingest pipeline."""
    # Load cursor
    processed_slugs = _load_cursor() if recent_only else set()
    if recent_only and processed_slugs:
        _log(f"incremental mode: skipping {len(processed_slugs)} known slugs")
    elif recent_only:
        _log("incremental mode: no cursor found, doing full scrape")

    # Scrape publication list
    entries = scrape_all(skip_slugs=processed_slugs if recent_only else None)
    if not entries:
        _log("no new publications to process")
        return

    _log(f"processing {len(entries)} publications")

    pg_conn = psycopg.connect(_pg_url())
    cache_dir = _pdf_cache_dir()

    stats: dict[str, int] = {
        "entries": 0,
        "no_pdf": 0,
        "pdf_errors": 0,
        "text_too_short": 0,
        "skipped_dedup": 0,
        "indexed": 0,
        "failed": 0,
    }

    batch: list[dict] = []
    newly_processed: set[str] = set()

    with (
        httpx.Client(
            timeout=120,
            follow_redirects=True,
            headers={"User-Agent": "GABI-DOU/1.0 (legal search; +https://gabidou.top)"},
        ) as pdf_client,
        httpx.Client(timeout=60) as es_client,
    ):
        _ensure_index(es_client)

        for entry in entries:
            stats["entries"] += 1

            try:
                if not entry.pdf_urls:
                    # Register with empty body so we don't re-visit
                    _log(f"  {entry.slug}: no PDFs — registering metadata-only doc")
                    stats["no_pdf"] += 1
                    doc = pub_to_es_doc(
                        entry, body_plain="", pdf_url="", page_count=0, pdf_index=0
                    )
                    _pg_upsert(pg_conn, doc)
                    pg_conn.commit()
                    batch.append(doc)
                    newly_processed.add(entry.slug)
                else:
                    for pdf_index, pdf_url in enumerate(entry.pdf_urls):
                        from src.backend.ingest.tcu_publicacoes_processor import (
                            _sha256,
                        )

                        slug_hash = _sha256(entry.slug)

                        # Download PDF
                        filepath = _download_pdf(
                            pdf_url, slug_hash, pdf_index, cache_dir, pdf_client
                        )
                        if filepath is None:
                            stats["pdf_errors"] += 1
                            continue
                        time.sleep(_PDF_DOWNLOAD_DELAY)

                        # Extract text
                        try:
                            body_plain, page_count = _extract_pdf_text(filepath)
                        except Exception as exc:
                            _log(f"    PDF extraction failed ({pdf_url}): {exc}")
                            stats["pdf_errors"] += 1
                            continue

                        if len(body_plain.strip()) < 50:
                            _log(
                                f"    text too short ({len(body_plain)} chars) — skipping PDF"
                            )
                            stats["text_too_short"] += 1
                            # Still register a metadata doc if first PDF
                            if pdf_index == 0:
                                doc = pub_to_es_doc(
                                    entry,
                                    body_plain="",
                                    pdf_url=pdf_url,
                                    page_count=page_count,
                                    pdf_index=0,
                                )
                                _pg_upsert(pg_conn, doc)
                                pg_conn.commit()
                                batch.append(doc)
                            continue

                        doc = pub_to_es_doc(
                            entry,
                            body_plain=body_plain,
                            pdf_url=pdf_url,
                            page_count=page_count,
                            pdf_index=pdf_index,
                        )

                        # Dedup check against Postgres
                        existing_hash = _pg_fetch_hash(pg_conn, doc["doc_id"])
                        if existing_hash and existing_hash == doc["deterministic_hash"]:
                            stats["skipped_dedup"] += 1
                        else:
                            _pg_upsert(pg_conn, doc)
                            pg_conn.commit()
                            batch.append(doc)

                    newly_processed.add(entry.slug)

                # Flush batch
                if len(batch) >= _ES_BATCH_SIZE:
                    ok, failed = _es_bulk(batch, es_client)
                    stats["indexed"] += ok
                    stats["failed"] += failed
                    _log(
                        f"  flushed batch: {ok} ok, {failed} failed | total indexed: {stats['indexed']}"
                    )
                    batch = []

            except Exception as exc:
                _log(f"  ERROR on {entry.slug}: {exc}")
                pg_conn.rollback()
                stats["failed"] += 1
                continue

        # Final flush
        if batch:
            ok, failed = _es_bulk(batch, es_client)
            stats["indexed"] += ok
            stats["failed"] += failed

    # Save cursor
    all_processed = processed_slugs | newly_processed
    _save_cursor(all_processed)

    _log("=== Ingest complete ===")
    for k, v in stats.items():
        _log(f"  {k}: {v}")

    pg_conn.close()


# ---------------------------------------------------------------------------
# Stats command
# ---------------------------------------------------------------------------


def cmd_stats() -> None:
    with psycopg.connect(_pg_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {_PG_TABLE}")
            pg_count = cur.fetchone()[0]
    _log(f"Postgres {_PG_TABLE}: {pg_count} documents")

    cursor = _load_cursor()
    _log(f"Cursor: {len(cursor)} slugs processed")

    with httpx.Client(timeout=10) as es_client:
        try:
            index = _pub_index()
            resp = es_client.get(f"{_es_url()}/{index}/_count")
            if resp.status_code == 200:
                es_count = resp.json().get("count", "?")
                _log(f"Elasticsearch {index}: {es_count} documents")
            else:
                _log(
                    f"Elasticsearch {index}: index not found (status {resp.status_code})"
                )
        except Exception as exc:
            _log(f"Elasticsearch unreachable: {exc}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest TCU Publicações Institucionais"
    )
    parser.add_argument("--ingest", action="store_true", help="Run ingest pipeline")
    parser.add_argument(
        "--recent",
        action="store_true",
        help="Skip already-processed slugs (incremental)",
    )
    parser.add_argument("--stats", action="store_true", help="Show document counts")
    args = parser.parse_args()

    if args.stats:
        cmd_stats()
    elif args.ingest:
        run_ingest(recent_only=args.recent)
    else:
        _log("ERROR: specify --ingest or --stats")
        sys.exit(1)


if __name__ == "__main__":
    main()
