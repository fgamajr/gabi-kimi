from __future__ import annotations

import argparse
import os

import psycopg

from src.backend.core.config import settings
from src.backend.parsing.source_parsers import SOURCE_TYPES


def _pg_url() -> str:
    return os.getenv("POSTGRES_URL", settings.POSTGRES_URL)


def main() -> None:
    parser = argparse.ArgumentParser(description="Add parsed.* confidence_fields column")
    parser.add_argument("--postgres-url", default=_pg_url())
    args = parser.parse_args()

    with psycopg.connect(args.postgres_url) as conn:
        with conn.cursor() as cur:
            for source_type in SOURCE_TYPES:
                cur.execute(
                    f"ALTER TABLE parsed.{source_type} ADD COLUMN IF NOT EXISTS confidence_fields JSONB"
                )
        conn.commit()
    print("parsed confidence_fields column added")


if __name__ == "__main__":
    main()
