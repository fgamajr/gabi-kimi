"""Ingest TCU BTCU (Boletins) — scrape portal, download PDFs, chunk, index.

Usage:
  python -m src.backend.ingest.tcu_btcu_ingest --ingest           # Full scrape (all pages)
  python -m src.backend.ingest.tcu_btcu_ingest --ingest --recent  # Only new since cursor
  python -m src.backend.ingest.tcu_btcu_ingest --stats            # Show counts
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
from src.backend.ingest.tcu_btcu_scraper import (
    chunk_pdf_text,
    download_pdf,
    extract_pdf_text,
    scrape_all_listings,
    _DELAY_BETWEEN_REQUESTS,
    _USER_AGENT,
)
from src.backend.ingest.tcu_btcu_processor import btcu_chunk_to_es_doc

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_BTCU_INDEX = "gabi_tcu_btcu_v1"
_BTCU_MAPPING_PATH = (
    Path(__file__).resolve().parent.parent / "search" / "es_tcu_btcu_mapping.json"
)
_PG_TABLE = "raw.tcu_btcu_raw_data"
_CURSOR_PATH = Path(__file__).resolve().parent.parent / "data" / "btcu_sync_cursor.json"
_CONTAINER_CURSOR_PATH = Path("/data/gabi_dou/btcu_sync_cursor.json")


def _log(msg: str) -> None:
    print(f"[tcu-btcu] {msg}", flush=True)


def _es_url() -> str:
    return os.getenv("ES_URL", "http://elasticsearch:9200").rstrip("/")


def _pg_url() -> str:
    return os.getenv("POSTGRES_URL", settings.POSTGRES_URL)


def _cursor_path() -> Path:
    """Use container path if it exists, else local."""
    if _CONTAINER_CURSOR_PATH.parent.exists():
        return _CONTAINER_CURSOR_PATH
    return _CURSOR_PATH


def _load_cursor() -> str | None:
    """Load last sync date (DD/MM/YYYY) from cursor file."""
    path = _cursor_path()
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return data.get("last_date")
        except (json.JSONDecodeError, KeyError):
            pass
    return None


def _save_cursor(date_str: str) -> None:
    """Save last sync date."""
    path = _cursor_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "last_date": date_str,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    )
    _log(f"cursor saved: {date_str}")


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
    """Upsert a single BTCU chunk into Postgres."""
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


def _pg_check_parent(conn: psycopg.Connection, parent_id: str) -> bool:
    """Check if any chunk for this parent BTCU already exists."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT 1 FROM {_PG_TABLE} WHERE all_fields->>'parent_btcu_id' = %s LIMIT 1",
            (parent_id,),
        )
        return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# ES helpers
# ---------------------------------------------------------------------------


def _ensure_index(es_client: httpx.Client) -> None:
    """Create BTCU index if it doesn't exist."""
    index = os.getenv("TCU_BTCU_INDEX", _BTCU_INDEX)
    url = _es_url()
    resp = es_client.head(f"{url}/{index}")
    if resp.status_code == 404:
        with _BTCU_MAPPING_PATH.open("r", encoding="utf-8") as f:
            mapping = json.load(f)
        _log(f"creating index {index}")
        resp = es_client.put(f"{url}/{index}", json=mapping)
        resp.raise_for_status()
    es_client.get(f"{url}/_cluster/health/{index}?wait_for_status=yellow&timeout=60s")


def _es_bulk(docs: list[dict], es_client: httpx.Client) -> tuple[int, int]:
    """Bulk index documents to ES."""
    index = os.getenv("TCU_BTCU_INDEX", _BTCU_INDEX)
    lines: list[str] = []
    for doc in docs:
        doc_id = doc.get("doc_id")
        lines.append(
            json.dumps({"index": {"_index": index, "_id": doc_id}}, ensure_ascii=False)
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
# Main ingest
# ---------------------------------------------------------------------------


def run_ingest(*, recent_only: bool = False, cache_dir: str | None = None) -> None:
    """Full ingest pipeline: scrape → download → chunk → Postgres + ES."""
    cache = cache_dir or "/tmp/tcu_btcu_pdf"
    os.makedirs(cache, exist_ok=True)

    es_client = httpx.Client(timeout=60)
    _ensure_index(es_client)

    pg_conn = psycopg.connect(_pg_url())

    # Determine cursor for incremental sync
    since_date = None
    if recent_only:
        since_date = _load_cursor()
        if since_date:
            _log(f"incremental sync since {since_date}")
        else:
            _log("no cursor found, doing full scrape")

    # Phase 1: Scrape listings
    entries = scrape_all_listings(since_date=since_date)
    if not entries:
        _log("no entries found")
        es_client.close()
        pg_conn.close()
        return

    # Track latest date for cursor
    latest_date = entries[0].data_publicacao

    # Phase 2: Download PDFs, chunk, process, index
    pdf_client = httpx.Client(
        timeout=120, follow_redirects=True, headers={"User-Agent": _USER_AGENT}
    )
    t0 = time.time()
    stats = {"entries": 0, "chunks": 0, "indexed": 0, "failed": 0, "skipped": 0}
    batch: list[dict] = []

    for i, entry in enumerate(entries):
        stats["entries"] += 1

        # Check if already ingested (by parent doc_id)
        parent_id = f"BTCU-{entry.doc_id}"
        parent_exists = _pg_check_parent(pg_conn, parent_id)

        try:
            # Download PDF
            filepath = download_pdf(entry.doc_id, cache, pdf_client)
            time.sleep(_DELAY_BETWEEN_REQUESTS)

            # Extract text
            full_text, page_count = extract_pdf_text(filepath)
            if len(full_text.strip()) < 50:
                _log(f"  skip {entry.doc_id}: text too short ({len(full_text)} chars)")
                stats["skipped"] += 1
                continue

            # Chunk
            chunks = chunk_pdf_text(full_text, page_count)

            # Process each chunk
            for chunk in chunks:
                doc = btcu_chunk_to_es_doc(entry, chunk, page_count)

                # Dedup check against Postgres
                if parent_exists:
                    existing_hash = _pg_fetch_hash(pg_conn, doc["doc_id"])
                    if existing_hash and existing_hash == doc.get("deterministic_hash"):
                        stats["skipped"] += 1
                        continue

                # Upsert to Postgres
                _pg_upsert(pg_conn, doc)
                batch.append(doc)
                stats["chunks"] += 1

            pg_conn.commit()

            # Bulk index when batch is full
            if len(batch) >= 200:
                ok, failed = _es_bulk(batch, es_client)
                stats["indexed"] += ok
                stats["failed"] += failed
                _log(
                    f"  progress: {stats['entries']}/{len(entries)} entries, {stats['chunks']} chunks, {stats['indexed']} indexed"
                )
                batch = []

        except Exception as exc:
            _log(f"  error processing {entry.doc_id}: {exc}")
            pg_conn.rollback()
            stats["failed"] += 1
            continue

        # Progress log
        if stats["entries"] % 50 == 0:
            elapsed = time.time() - t0
            _log(
                f"  progress: {stats['entries']}/{len(entries)} entries, {elapsed:.0f}s"
            )

    # Flush remaining batch
    if batch:
        ok, failed = _es_bulk(batch, es_client)
        stats["indexed"] += ok
        stats["failed"] += failed

    # Save cursor
    if latest_date:
        _save_cursor(latest_date)

    pdf_client.close()
    es_client.close()
    pg_conn.close()

    elapsed = time.time() - t0
    _log(
        f"DONE in {elapsed:.0f}s — entries={stats['entries']} chunks={stats['chunks']} "
        f"indexed={stats['indexed']} failed={stats['failed']} skipped={stats['skipped']}"
    )


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def cmd_stats() -> None:
    """Show BTCU ingest stats."""
    with psycopg.connect(_pg_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {_PG_TABLE}")
            total = cur.fetchone()[0]

            cur.execute(
                f"SELECT all_fields->>'caderno' AS caderno, COUNT(*) FROM {_PG_TABLE} GROUP BY 1"
            )
            by_caderno = {row[0]: row[1] for row in cur.fetchall()}

            cur.execute(
                f"SELECT all_fields->>'embedding_status' AS status, COUNT(*) FROM {_PG_TABLE} GROUP BY 1"
            )
            by_status = {row[0]: row[1] for row in cur.fetchall()}

    print(
        json.dumps(
            {
                "total_chunks": total,
                "by_caderno": by_caderno,
                "embedding_status": by_status,
                "cursor": _load_cursor(),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest TCU BTCU (Boletins)")
    parser.add_argument("--ingest", action="store_true", help="Run ingest pipeline")
    parser.add_argument(
        "--recent", action="store_true", help="Only new editions since cursor"
    )
    parser.add_argument("--stats", action="store_true", help="Show stats")
    parser.add_argument("--cache-dir", default=None, help="PDF cache directory")
    args = parser.parse_args()

    if args.stats:
        cmd_stats()
    elif args.ingest:
        run_ingest(recent_only=args.recent, cache_dir=args.cache_dir)
    else:
        _log("ERROR: specify --ingest or --stats")
        sys.exit(1)


if __name__ == "__main__":
    main()
