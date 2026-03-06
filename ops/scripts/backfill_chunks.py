"""Backfill dou.document_chunk from existing dou.document rows."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import execute_values

# Allow both "python -m ops.scripts.backfill_chunks" and direct execution.
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.backend.ingest.chunker import chunk_document


def _build_dsn() -> str:
    return os.getenv("PG_DSN") or (
        f"host={os.getenv('PGHOST', 'localhost')} "
        f"port={os.getenv('PGPORT', '5433')} "
        f"dbname={os.getenv('PGDATABASE', 'gabi')} "
        f"user={os.getenv('PGUSER', 'gabi')} "
        f"password={os.getenv('PGPASSWORD', 'gabi')}"
    )


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr, flush=True)


@dataclass(slots=True)
class CursorState:
    created_at: str
    doc_id: str


def _load_cursor(path: Path | None) -> CursorState | None:
    if not path or not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return CursorState(created_at=str(data["created_at"]), doc_id=str(data["doc_id"]))


def _save_cursor(path: Path | None, created_at: datetime, doc_id: str) -> None:
    if not path:
        return
    payload = {
        "created_at": created_at.astimezone(timezone.utc).isoformat(),
        "doc_id": doc_id,
        "saved_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_batch(
    conn: Any,
    *,
    cursor: CursorState | None,
    batch_size: int,
    date_from: str | None,
    date_to: str | None,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where: list[str] = ["1=1"]

    if cursor is not None:
        where.append("(d.created_at, d.id) > (%s::timestamptz, %s::uuid)")
        params.extend([cursor.created_at, cursor.doc_id])
    if date_from:
        where.append("e.publication_date >= %s::date")
        params.append(date_from)
    if date_to:
        where.append("e.publication_date <= %s::date")
        params.append(date_to)

    params.append(batch_size)

    sql = f"""
        SELECT
            d.id::text AS doc_id,
            d.identifica,
            d.titulo,
            d.sub_titulo,
            d.body_plain,
            d.issuing_organ,
            d.art_type,
            e.section,
            e.publication_date::text AS publication_date,
            d.created_at,
            COALESCE((SELECT count(*) FROM dou.document_chunk dc WHERE dc.document_id = d.id), 0) AS chunk_count
        FROM dou.document d
        JOIN dou.edition e ON e.id = d.edition_id
        WHERE {" AND ".join(where)}
        ORDER BY d.created_at, d.id
        LIMIT %s
    """
    cur = conn.cursor()
    cur.execute(sql, tuple(params))
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.close()
    return rows


def _heading_context(row: dict[str, Any]) -> str:
    parts = [
        str(row.get("identifica") or "").strip(),
        str(row.get("titulo") or "").strip(),
        str(row.get("sub_titulo") or "").strip(),
    ]
    return " | ".join([p for p in parts if p])


def _insert_chunks(
    conn: Any,
    *,
    doc_id: str,
    chunks: list[Any],
    replace: bool,
) -> int:
    cur = conn.cursor()
    if replace:
        cur.execute("DELETE FROM dou.document_chunk WHERE document_id = %s::uuid", (doc_id,))

    rows = [
        (
            doc_id,
            c.chunk_index,
            c.chunk_text,
            c.chunk_text_norm,
            c.chunk_char_start,
            c.chunk_char_end,
            c.token_estimate,
            c.heading_context or None,
            json.dumps(c.metadata, ensure_ascii=False),
        )
        for c in chunks
    ]
    if not rows:
        cur.close()
        return 0

    execute_values(
        cur,
        """
        INSERT INTO dou.document_chunk (
            document_id, chunk_index, chunk_text, chunk_text_norm,
            chunk_char_start, chunk_char_end, token_estimate,
            heading_context, metadata_json
        ) VALUES %s
        ON CONFLICT (document_id, chunk_index) DO UPDATE SET
            chunk_text = EXCLUDED.chunk_text,
            chunk_text_norm = EXCLUDED.chunk_text_norm,
            chunk_char_start = EXCLUDED.chunk_char_start,
            chunk_char_end = EXCLUDED.chunk_char_end,
            token_estimate = EXCLUDED.token_estimate,
            heading_context = EXCLUDED.heading_context,
            metadata_json = EXCLUDED.metadata_json
        """,
        rows,
        page_size=500,
    )
    cur.close()
    return len(rows)


def main() -> int:
    p = argparse.ArgumentParser(description="Backfill dou.document_chunk from dou.document")
    p.add_argument("--dsn", default=_build_dsn(), help="PostgreSQL DSN")
    p.add_argument("--batch-size", type=int, default=1000)
    p.add_argument("--date-from", help="Filter publication_date >= YYYY-MM-DD")
    p.add_argument("--date-to", help="Filter publication_date <= YYYY-MM-DD")
    p.add_argument("--chunk-size", type=int, default=int(os.getenv("CHUNK_SIZE", "900")))
    p.add_argument("--chunk-overlap", type=int, default=int(os.getenv("CHUNK_OVERLAP", "150")))
    p.add_argument("--min-chunk-size", type=int, default=int(os.getenv("MIN_CHUNK_SIZE", "280")))
    p.add_argument("--max-chunk-size", type=int, default=int(os.getenv("MAX_CHUNK_SIZE", "1400")))
    p.add_argument("--replace", action="store_true", help="Replace existing chunks for processed docs")
    p.add_argument("--only-missing", action="store_true", default=True, help="Skip docs that already have chunks (default)")
    p.add_argument("--no-only-missing", dest="only_missing", action="store_false")
    p.add_argument("--cursor-file", type=Path, default=Path("ops/data/chunks_backfill_cursor.json"))
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    t0 = time.monotonic()
    conn = psycopg2.connect(args.dsn)
    conn.autocommit = False
    try:
        cursor = _load_cursor(args.cursor_file)
        if cursor:
            _log(f"resuming from created_at={cursor.created_at} doc_id={cursor.doc_id}")
        else:
            _log("starting from beginning (no cursor)")

        docs_seen = 0
        docs_processed = 0
        docs_skipped = 0
        chunks_written = 0

        while True:
            batch = _fetch_batch(
                conn,
                cursor=cursor,
                batch_size=args.batch_size,
                date_from=args.date_from,
                date_to=args.date_to,
            )
            if not batch:
                break

            for row in batch:
                docs_seen += 1
                existing = int(row.get("chunk_count", 0) or 0)
                if args.only_missing and existing > 0 and not args.replace:
                    docs_skipped += 1
                    continue

                body = str(row.get("body_plain") or "")
                heading = _heading_context(row)
                metadata = {
                    "section": row.get("section"),
                    "publication_date": row.get("publication_date"),
                    "issuing_organ": row.get("issuing_organ"),
                    "art_type": row.get("art_type"),
                }
                chunks = chunk_document(
                    body,
                    heading_context=heading,
                    metadata=metadata,
                    chunk_size=args.chunk_size,
                    chunk_overlap=args.chunk_overlap,
                    min_chunk_size=args.min_chunk_size,
                    max_chunk_size=args.max_chunk_size,
                )

                if args.dry_run:
                    chunks_written += len(chunks)
                else:
                    chunks_written += _insert_chunks(
                        conn,
                        doc_id=str(row["doc_id"]),
                        chunks=chunks,
                        replace=args.replace,
                    )
                docs_processed += 1

            if args.dry_run:
                conn.rollback()
            else:
                conn.commit()

            last = batch[-1]
            created_at = last["created_at"]
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            cursor = CursorState(
                created_at=created_at.astimezone(timezone.utc).isoformat(),
                doc_id=str(last["doc_id"]),
            )
            _save_cursor(args.cursor_file, created_at, str(last["doc_id"]))

            _log(
                f"progress docs_seen={docs_seen} processed={docs_processed} "
                f"skipped={docs_skipped} chunks={chunks_written}"
            )

        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()

        _log(
            f"done docs_seen={docs_seen} processed={docs_processed} "
            f"skipped={docs_skipped} chunks={chunks_written} "
            f"elapsed_ms={int((time.monotonic() - t0) * 1000)}"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
