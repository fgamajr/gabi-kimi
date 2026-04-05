from __future__ import annotations

import json
import time
from typing import Any

from bson import ObjectId

from ops.migrations._common import (
    clamp_spot_check_size,
    count_postgres,
    iter_batches,
    safe_date,
    safe_json_payload,
    sha256_text,
    write_log,
)


RAW_TABLE = "raw.dou_documents_raw_data"


def ensure_schema(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raw.dou_documents_raw_data (
                id TEXT PRIMARY KEY,
                pub_date DATE,
                section TEXT,
                source_zip TEXT,
                art_type TEXT,
                content_html TEXT,
                raw_html_hash TEXT NOT NULL,
                all_fields JSONB NOT NULL,
                migrated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS ix_raw_dou_documents_raw_data_pub_date ON raw.dou_documents_raw_data (pub_date);
            CREATE INDEX IF NOT EXISTS ix_raw_dou_documents_raw_data_art_type ON raw.dou_documents_raw_data (art_type);
            CREATE INDEX IF NOT EXISTS ix_raw_dou_documents_raw_data_raw_html_hash ON raw.dou_documents_raw_data (raw_html_hash);
            """
            )


def _build_row(document: dict[str, Any]) -> tuple[str, Any, Any, Any, Any, Any, str, str] | None:
    doc_id = str(document.get("_id", "")).strip()
    if not doc_id:
        return None

    payload = safe_json_payload(document)
    content_html = document.get("content_html") if isinstance(document.get("content_html"), str) else None
    raw_html_hash = sha256_text(content_html or "")
    return (
        doc_id,
        safe_date(document.get("pub_date")),
        document.get("section"),
        document.get("source_zip"),
        document.get("art_type"),
        content_html,
        raw_html_hash,
        json.dumps(payload, ensure_ascii=False),
    )


def _insert_batch(conn: Any, batch: list[dict[str, Any]]) -> int:
    values: list[tuple[str, Any, Any, Any, Any, Any, str, str]] = []
    for document in batch:
        row = _build_row(document)
        if row is not None:
            values.append(row)

    if not values:
        return 0

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO raw.dou_documents_raw_data (
                id,
                pub_date,
                section,
                source_zip,
                art_type,
                content_html,
                raw_html_hash,
                all_fields
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (id) DO NOTHING;
            """,
            values,
        )
    conn.commit()
    return len(values)


def _spot_check_hashes(mongo_collection: Any, conn: Any, sample_size: int) -> tuple[int, int]:
    sample_size = clamp_spot_check_size(sample_size)
    if sample_size <= 0:
        return 0, 0

    # Sample from Postgres to guarantee we only verify rows that were actually migrated.
    # (Sampling from Mongo would yield rows not yet in Postgres when --limit is used.)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, raw_html_hash FROM raw.dou_documents_raw_data ORDER BY random() LIMIT %s",
            (sample_size,),
        )
        pg_rows: dict[str, str] = {row[0]: row[1] for row in cur.fetchall()}

    if not pg_rows:
        return 0, 0

    oid_list: list[Any] = []
    for id_str in pg_rows:
        try:
            oid_list.append(ObjectId(id_str))
        except Exception:
            pass

    if not oid_list:
        return 0, 0

    checked = 0
    errors = 0
    for document in mongo_collection.find({"_id": {"$in": oid_list}}):
        doc_id = str(document.get("_id", "")).strip()
        if not doc_id:
            continue
        content_html = document.get("content_html") if isinstance(document.get("content_html"), str) else ""
        expected = sha256_text(content_html)
        stored = pg_rows.get(doc_id)
        checked += 1
        if stored != expected:
            errors += 1

    return checked, errors


def run(
    mongo_db: Any,
    conn: Any,
    spec: Any,
    *,
    batch_size: int,
    typed_page_size: int,
    spot_check_size: int,
    raw_only: bool,
    limit: int | None,
    ddl_only: bool,
) -> None:
    del typed_page_size, raw_only
    ensure_schema(conn)
    if ddl_only:
        print(json.dumps({"collection": spec.name, "stage": "ddl_only", "status": "ok"}, ensure_ascii=False))
        return

    mongo_collection = mongo_db[spec.mongo_name]
    source_count = mongo_collection.estimated_document_count()
    effective_source_count = min(source_count, limit) if limit is not None else source_count
    print(f"[{spec.name}] source_count={source_count} effective={effective_source_count}")

    raw_start = time.perf_counter()
    inserted = 0
    for batch in iter_batches(mongo_collection, batch_size, limit=limit):
        inserted += _insert_batch(conn, batch)
        if inserted and inserted % 50000 == 0:
            print(f"[{spec.name}] raw processed={inserted}")

    raw_target = count_postgres(conn, RAW_TABLE)
    raw_elapsed = time.perf_counter() - raw_start
    checked, hash_errors = _spot_check_hashes(mongo_collection, conn, spot_check_size)
    status = "ok" if inserted == effective_source_count and hash_errors == 0 else "warn"

    write_log(
        conn,
        collection=spec.name,
        stage="raw_dump",
        count_mongo=effective_source_count,
        count_postgres=raw_target,
        hash_errors=hash_errors,
        duration_s=raw_elapsed,
        status=status,
        details={
            "batch_size": batch_size,
            "limit": limit,
            "inserted_this_run": inserted,
            "spot_check_size": spot_check_size,
            "spot_check_checked": checked,
        },
    )

    print(
        json.dumps(
            {
                "collection": spec.name,
                "stage": "raw_dump",
                "count_source": effective_source_count,
                "count_target": raw_target,
                "inserted_this_run": inserted,
                "spot_check_checked": checked,
                "hash_errors": hash_errors,
                "duration_s": round(raw_elapsed, 2),
                "status": status,
            },
            ensure_ascii=False,
        )
    )