from __future__ import annotations

import argparse
import os

import psycopg

from src.backend.core.config import settings
from src.backend.parsing.source_parsers import SOURCE_TYPES


NEW_CHECK = "CHECK (enrichment_status IN ('pending', 'running', 'done_full', 'done_partial', 'done_fallback', 'failed', 'skipped'))"


def _pg_url() -> str:
    return os.getenv("POSTGRES_URL", settings.POSTGRES_URL)


def main() -> None:
    parser = argparse.ArgumentParser(description="Upgrade parsed.* enrichment_status checks")
    parser.add_argument("--postgres-url", default=_pg_url())
    args = parser.parse_args()

    with psycopg.connect(args.postgres_url) as conn:
        with conn.cursor() as cur:
            for source_type in SOURCE_TYPES:
                cur.execute(
                    """
                    SELECT c.conname
                    FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    JOIN pg_namespace n ON n.oid = t.relnamespace
                    WHERE n.nspname = 'parsed'
                      AND t.relname = %s
                      AND pg_get_constraintdef(c.oid) ILIKE '%%enrichment_status%%'
                    """,
                    (source_type,),
                )
                for row in cur.fetchall():
                    cur.execute(f'ALTER TABLE parsed.{source_type} DROP CONSTRAINT IF EXISTS "{row[0]}"')
                cur.execute(
                    f"ALTER TABLE parsed.{source_type} "
                    f"ADD CONSTRAINT {source_type}_enrichment_status_check {NEW_CHECK}"
                )
        conn.commit()
    print("parsed enrichment status constraints upgraded")


if __name__ == "__main__":
    main()
