"""Backfill legacy <img src="/images/..."> refs into dou.document_media.

This is useful for early years where XML references image URLs but ZIP bundles
do not include binary image files.
"""
from __future__ import annotations

import argparse
import os
from datetime import date
from typing import Any

import psycopg2
from dotenv import load_dotenv

from src.backend.ingest.html_extractor import extract_images
from src.backend.ingest.image_checker import check_document_images, checked_image_row, rewrite_document_html_images


def _dsn() -> str:
    load_dotenv()
    return os.getenv("GABI_DSN", "host=localhost port=5433 dbname=gabi user=gabi password=gabi")


def _iter_docs(cur: Any, start: date | None, end: date | None, limit: int) -> list[tuple[str, str]]:
    cur.execute(
        """
        SELECT d.id::text, d.body_html
        FROM dou.document d
        JOIN dou.edition e ON e.id = d.edition_id
        WHERE d.body_html ILIKE '%%<img%%'
          AND (%s::date IS NULL OR e.publication_date >= %s::date)
          AND (%s::date IS NULL OR e.publication_date <= %s::date)
          AND NOT EXISTS (
              SELECT 1 FROM dou.document_media dm WHERE dm.document_id = d.id
          )
        ORDER BY e.publication_date, d.id
        LIMIT %s
        """,
        (start, start, end, end, limit),
    )
    return [(r[0], r[1] or "") for r in cur.fetchall()]


def run(dsn: str, start: date | None, end: date | None, limit: int) -> None:
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    docs_seen = 0
    rows_inserted = 0
    try:
        with conn.cursor() as cur:
            docs = _iter_docs(cur, start, end, limit)
            for doc_id, body_html in docs:
                docs_seen += 1
                refs = extract_images(body_html)
                checked_images = check_document_images(doc_id=doc_id, refs=refs, image_lookup={})
                for item in checked_images:
                    row = checked_image_row(item)
                    cur.execute(
                        """
                        INSERT INTO dou.document_media (
                            document_id, media_name, media_type, file_extension,
                            data, size_bytes, sequence_in_document, source_filename, external_url,
                            original_url, availability_status, alt_text, context_hint,
                            fallback_text, local_path, width_px, height_px,
                            ingest_checked_at, retry_count
                        )
                        SELECT %s::uuid, %s, %s, %s,
                               %s, %s, %s, %s, %s,
                               %s, %s, %s, %s,
                               %s, %s, %s, %s,
                               %s, %s
                        WHERE NOT EXISTS (
                            SELECT 1 FROM dou.document_media
                            WHERE document_id = %s::uuid
                              AND media_name = %s
                              AND sequence_in_document = %s
                        )
                        """,
                        (
                            doc_id,
                            row["media_name"],
                            row["media_type"],
                            row["file_extension"],
                            item.data,
                            row["size_bytes"],
                            row["position_in_doc"],
                            row["source_filename"],
                            row["original_url"],
                            row["original_url"],
                            row["availability_status"],
                            row["alt_text"],
                            row["context_hint"],
                            row["fallback_text"],
                            row["local_path"],
                            row["width_px"],
                            row["height_px"],
                            row["ingest_timestamp"],
                            row["retry_count"],
                            doc_id,
                            row["media_name"],
                            row["position_in_doc"],
                        ),
                    )
                    rows_inserted += cur.rowcount
                if checked_images:
                    rewritten_html = rewrite_document_html_images(body_html, doc_id, checked_images)
                    cur.execute(
                        "UPDATE dou.document SET body_html = %s WHERE id = %s::uuid",
                        (rewritten_html, doc_id),
                    )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"docs_scanned={docs_seen} media_rows_inserted={rows_inserted}")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill legacy image refs into dou.document_media")
    parser.add_argument("--dsn", default=_dsn())
    parser.add_argument("--start-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=50000)
    args = parser.parse_args()
    run(
        dsn=args.dsn,
        start=_parse_date(args.start_date),
        end=_parse_date(args.end_date),
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
