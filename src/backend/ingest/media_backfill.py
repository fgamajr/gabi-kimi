"""Backfill legacy <img src="/images/..."> refs into dou.document_media.

This is useful for early years where XML references image URLs but ZIP bundles
do not include binary image files.
"""
from __future__ import annotations

import argparse
import mimetypes
import os
import re
from datetime import date
from typing import Any

import psycopg2
from dotenv import load_dotenv

from src.backend.ingest.html_extractor import extract_images

_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff"})


def _guess_media_type(ext: str) -> str:
    mt = mimetypes.guess_type(f"file{ext}")[0]
    return mt or "application/octet-stream"


def _media_name_from_ref(raw: str) -> str:
    if not raw:
        return ""
    token = raw.strip().rsplit("/", 1)[-1].strip()
    return re.sub(r"\.[A-Za-z0-9]{2,5}$", "", token)


def _resolve_external_media_url(src: str | None) -> str | None:
    if not src:
        return None
    ref = src.strip()
    if not ref:
        return None
    if ref.startswith("http://") or ref.startswith("https://"):
        return ref
    if ref.startswith("/"):
        return f"https://www.in.gov.br{ref}"
    return None


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
                for ref in refs:
                    media_name = _media_name_from_ref(ref.name)
                    if not media_name:
                        continue
                    external_url = _resolve_external_media_url(ref.source)
                    if not external_url:
                        continue
                    src_name = (ref.source or "").strip().rsplit("/", 1)[-1]
                    ext_raw = os.path.splitext(src_name)[1].lower() if src_name else ""
                    ext = ext_raw if ext_raw in _IMAGE_EXTENSIONS else ""
                    media_type = _guess_media_type(ext) if ext else "application/octet-stream"

                    cur.execute(
                        """
                        INSERT INTO dou.document_media (
                            document_id, media_name, media_type, file_extension,
                            data, size_bytes, sequence_in_document, source_filename, external_url
                        )
                        SELECT %s::uuid, %s, %s, %s, NULL, NULL, %s, %s, %s
                        WHERE NOT EXISTS (
                            SELECT 1 FROM dou.document_media
                            WHERE document_id = %s::uuid
                              AND media_name = %s
                              AND COALESCE(source_filename, '') = COALESCE(%s, '')
                        )
                        """,
                        (
                            doc_id,
                            media_name,
                            media_type,
                            ext or None,
                            ref.sequence,
                            src_name or ref.source,
                            external_url,
                            doc_id,
                            media_name,
                            src_name or ref.source,
                        ),
                    )
                    rows_inserted += cur.rowcount
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
