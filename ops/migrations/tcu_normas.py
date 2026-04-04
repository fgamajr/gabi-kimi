from __future__ import annotations

from typing import Any

from ops.migrations._common import run_simple_raw_collection


RAW_TABLE = "raw.tcu_normas_raw_data"


def ensure_schema(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raw.tcu_normas_raw_data (
                id TEXT PRIMARY KEY,
                all_fields JSONB NOT NULL,
                dumped_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
    conn.commit()


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
    del typed_page_size, spot_check_size, raw_only
    ensure_schema(conn)
    run_simple_raw_collection(
        mongo_db,
        conn,
        collection_name=spec.mongo_name,
        raw_table=RAW_TABLE,
        batch_size=batch_size,
        limit=limit,
        ddl_only=ddl_only,
    )