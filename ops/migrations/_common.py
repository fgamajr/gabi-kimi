from __future__ import annotations

import hashlib
import json
import time
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Any


VALID_TABLES = {
    "raw.dou_documents",
    "raw.tcu_acordaos_raw_data",
    "raw.tcu_acordaos",
    "raw.tcu_normas_raw_data",
    "raw.tcu_btcu_raw_data",
    "raw.tcu_publicacoes_raw_data",
}
MAX_SPOT_CHECK_SIZE = 10000


def canonicalize_text(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip()


def sha256_text(value: str) -> str:
    return hashlib.sha256(canonicalize_text(value).encode("utf-8")).hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _strip_nullbytes(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_strip_nullbytes(item) for item in value]
    if isinstance(value, dict):
        return {key: _strip_nullbytes(item) for key, item in value.items()}
    return value


def safe_json_payload(document: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(json.dumps(document, default=json_default, ensure_ascii=False))
    return _strip_nullbytes(payload)


def safe_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "sim", "y"}:
            return True
        if lowered in {"0", "false", "no", "nao", "não", "n"}:
            return False
    return None


def safe_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def ensure_base_schema(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE SCHEMA IF NOT EXISTS raw;

            CREATE TABLE IF NOT EXISTS raw.migration_log (
                id BIGSERIAL PRIMARY KEY,
                collection TEXT NOT NULL,
                stage TEXT NOT NULL,
                count_mongo BIGINT,
                count_postgres BIGINT,
                hash_errors INT NOT NULL DEFAULT 0,
                duration_s DOUBLE PRECISION,
                status TEXT NOT NULL,
                details JSONB,
                ran_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
    conn.commit()


def clamp_spot_check_size(sample_size: int) -> int:
    if sample_size <= 0:
        return 0
    if sample_size > MAX_SPOT_CHECK_SIZE:
        print(f"[warn] spot_check_size capped at {MAX_SPOT_CHECK_SIZE} (requested={sample_size})")
        return MAX_SPOT_CHECK_SIZE
    return sample_size


def _validate_table_name(table_name: str) -> None:
    if table_name not in VALID_TABLES:
        raise ValueError(f"Unsupported table name: {table_name}")


def iter_batches(mongo_collection: Any, batch_size: int, limit: int | None = None) -> Any:
    cursor = mongo_collection.find({}, no_cursor_timeout=True).batch_size(batch_size)
    yielded = 0
    try:
        batch: list[dict[str, Any]] = []
        for document in cursor:
            if limit is not None and yielded >= limit:
                break
            batch.append(document)
            yielded += 1
            if len(batch) >= batch_size:
                yield batch
                batch = []
        if batch:
            yield batch
    finally:
        try:
            cursor.close()
        except Exception:
            pass


def insert_jsonb_batch(conn: Any, batch: list[dict[str, Any]], raw_table: str) -> int:
    _validate_table_name(raw_table)
    values: list[tuple[str, str]] = []
    for document in batch:
        doc_id = str(document.get("_id", "")).strip()
        if not doc_id:
            continue
        payload = safe_json_payload(document)
        values.append((doc_id, json.dumps(payload, ensure_ascii=False)))

    if not values:
        return 0

    with conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO {raw_table} (id, all_fields) VALUES (%s, %s::jsonb) ON CONFLICT (id) DO NOTHING;",
            values,
        )
    conn.commit()
    return len(values)


def count_postgres(conn: Any, table_name: str) -> int:
    _validate_table_name(table_name)
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table_name};")
        value = cur.fetchone()
    return int(value[0]) if value else 0


def write_log(
    conn: Any,
    *,
    collection: str,
    stage: str,
    count_mongo: int,
    count_postgres: int,
    hash_errors: int,
    duration_s: float,
    status: str,
    details: dict[str, Any],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw.migration_log (
                collection,
                stage,
                count_mongo,
                count_postgres,
                hash_errors,
                duration_s,
                status,
                details
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb);
            """,
            (
                collection,
                stage,
                count_mongo,
                count_postgres,
                hash_errors,
                duration_s,
                status,
                json.dumps(details, ensure_ascii=False),
            ),
        )
    conn.commit()


def run_simple_raw_collection(
    mongo_db: Any,
    conn: Any,
    *,
    collection_name: str,
    raw_table: str,
    batch_size: int,
    limit: int | None,
    ddl_only: bool,
) -> None:
    if ddl_only:
        print(json.dumps({"collection": collection_name, "stage": "ddl_only", "status": "ok"}, ensure_ascii=False))
        return

    mongo_collection = mongo_db[collection_name]
    source_count = mongo_collection.estimated_document_count()
    effective_source_count = min(source_count, limit) if limit is not None else source_count
    print(f"[{collection_name}] source_count={source_count} effective={effective_source_count}")

    raw_start = time.perf_counter()
    raw_seen = 0
    for batch in iter_batches(mongo_collection, batch_size, limit=limit):
        raw_seen += insert_jsonb_batch(conn, batch, raw_table)
        if raw_seen and raw_seen % 10000 == 0:
            print(f"[{collection_name}] raw processed={raw_seen}")

    raw_target = count_postgres(conn, raw_table)
    raw_elapsed = time.perf_counter() - raw_start
    raw_status = "ok" if raw_seen == effective_source_count else "warn"

    write_log(
        conn,
        collection=collection_name,
        stage="raw_dump",
        count_mongo=effective_source_count,
        count_postgres=raw_target,
        hash_errors=0,
        duration_s=raw_elapsed,
        status=raw_status,
        details={"batch_size": batch_size, "limit": limit, "inserted_this_run": raw_seen},
    )

    print(
        json.dumps(
            {
                "collection": collection_name,
                "stage": "raw_dump",
                "count_source": effective_source_count,
                "count_target": raw_target,
                "inserted_this_run": raw_seen,
                "duration_s": round(raw_elapsed, 2),
                "status": raw_status,
            },
            ensure_ascii=False,
        )
    )