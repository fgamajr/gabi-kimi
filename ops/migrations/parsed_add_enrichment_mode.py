from __future__ import annotations

import argparse
import os

import psycopg

from src.backend.core.config import settings
from src.backend.parsing.source_parsers import SOURCE_TYPES


MODE_CHECK = "CHECK (enrichment_mode IN ('llm', 'heuristic', 'fallback'))"


def _pg_url() -> str:
    return os.getenv("POSTGRES_URL", settings.POSTGRES_URL)


def _backfill_mode_sql(source_type: str) -> str:
    return f"""
    UPDATE parsed.{source_type}
    SET enrichment_mode = CASE
        WHEN enrichment_status = 'done_fallback' THEN 'fallback'
        WHEN enrichment_status IN ('done_partial', 'done_full') THEN 'heuristic'
        ELSE NULL
    END
    WHERE enrichment_mode IS NULL
    """


def main() -> None:
    parser = argparse.ArgumentParser(description="Add parsed.* enrichment_mode column")
    parser.add_argument("--postgres-url", default=_pg_url())
    args = parser.parse_args()

    with psycopg.connect(args.postgres_url) as conn:
        with conn.cursor() as cur:
            for source_type in SOURCE_TYPES:
                cur.execute(
                    f"ALTER TABLE parsed.{source_type} ADD COLUMN IF NOT EXISTS enrichment_mode TEXT"
                )
                cur.execute(f"ALTER TABLE parsed.{source_type} DROP CONSTRAINT IF EXISTS {source_type}_enrichment_mode_check")
                cur.execute(_backfill_mode_sql(source_type))
                cur.execute(
                    f"ALTER TABLE parsed.{source_type} "
                    f"ADD CONSTRAINT {source_type}_enrichment_mode_check {MODE_CHECK}"
                )
        conn.commit()
    print("parsed enrichment_mode column added")


if __name__ == "__main__":
    main()
