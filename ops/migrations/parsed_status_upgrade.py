from __future__ import annotations

import argparse
import os

import psycopg

from src.backend.core.config import settings
from src.backend.parsing.source_parsers import SOURCE_TYPES


NEW_CHECK = "CHECK (enrichment_status IN ('pending', 'running', 'done_full', 'done_partial', 'done_fallback', 'failed', 'skipped'))"
LEGACY_STATUS_MAP = {
    "done": "done_partial",
    "preview_fallback": "done_fallback",
    "fallback": "done_fallback",
    "partial": "done_partial",
    "full": "done_full",
}


def _pg_url() -> str:
    return os.getenv("POSTGRES_URL", settings.POSTGRES_URL)


def main() -> None:
    parser = argparse.ArgumentParser(description="Upgrade parsed.* enrichment_status checks")
    parser.add_argument("--postgres-url", default=_pg_url())
    args = parser.parse_args()

    with psycopg.connect(args.postgres_url) as conn:
        with conn.cursor() as cur:
            for source_type in SOURCE_TYPES:
                cur.execute(f"ALTER TABLE parsed.{source_type} DROP CONSTRAINT IF EXISTS {source_type}_enrichment_status_check")
                for old_status, new_status in LEGACY_STATUS_MAP.items():
                    cur.execute(
                        f"UPDATE parsed.{source_type} SET enrichment_status = %s WHERE enrichment_status = %s",
                        (new_status, old_status),
                    )
                cur.execute(
                    f"ALTER TABLE parsed.{source_type} "
                    f"ADD CONSTRAINT {source_type}_enrichment_status_check {NEW_CHECK}"
                )
        conn.commit()
    print("parsed enrichment status constraints upgraded")


if __name__ == "__main__":
    main()
