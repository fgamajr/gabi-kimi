"""Legacy entrypoint: MongoDB → Postgres *raw_data* tables.

Canonical SoT is the 11 ``raw.*`` tables fed by ``src.backend.ingest`` (``sync_dou``,
``tcu_csv_postgres_ingest``, ``tcu_btcu_ingest``, ``tcu_publicacoes_ingest``, …).
This runner is opt-in only: set ``GABI_ALLOW_LEGACY_MONGO_MIGRATION=1``.
"""

from __future__ import annotations

import argparse
import importlib
import os
from typing import Any

from ops.migrations._common import ensure_base_schema
from ops.migrations._registry import COLLECTION_SPECS, resolve_specs


def main() -> None:
    if os.environ.get("GABI_ALLOW_LEGACY_MONGO_MIGRATION", "").strip() != "1":
        raise SystemExit(
            "Legacy Mongo→Postgres migrations are disabled. SoT: 11 canonical raw.* tables "
            "(ingest under src/backend/ingest). For one-off legacy runs set "
            "GABI_ALLOW_LEGACY_MONGO_MIGRATION=1."
        )

    all_names = ", ".join(COLLECTION_SPECS)
    parser = argparse.ArgumentParser(
        description="Server-side MongoDB -> Postgres raw migrations"
    )
    parser.add_argument(
        "--mongo-uri",
        default=os.getenv("MONGO_STRING", "mongodb://mongo:27017/gabi_dou"),
    )
    parser.add_argument("--mongo-db", default=os.getenv("DB_NAME", "gabi_dou"))
    parser.add_argument(
        "--collections",
        default="all",
        help=f"Comma-separated collection names to migrate, or 'all'. Known: {all_names}",
    )
    parser.add_argument(
        "--postgres-dsn",
        default=os.getenv("POSTGRES_URL", "postgresql://gabi:gabi@postgres:5432/gabi"),
    )
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--typed-page-size", type=int, default=5000)
    parser.add_argument("--spot-check-size", type=int, default=1000)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--ddl-only", action="store_true")
    parser.add_argument("--raw-only", action="store_true")
    args = parser.parse_args()

    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit(
            "psycopg is required. Install dependencies (src/backend/requirements.txt or ops/requirements-ingest.txt)."
        ) from exc

    try:
        from pymongo import MongoClient
    except ImportError as exc:
        raise SystemExit(
            "pymongo is required. Install dependencies (src/backend/requirements.txt or ops/requirements-ingest.txt)."
        ) from exc

    specs = resolve_specs(args.collections)
    mongo_client = MongoClient(args.mongo_uri)
    mongo_db = mongo_client[args.mongo_db]

    with psycopg.connect(args.postgres_dsn) as conn:
        ensure_base_schema(conn)
        for spec in specs:
            module: Any = importlib.import_module(spec.module_name)
            module.run(
                mongo_db,
                conn,
                spec,
                batch_size=args.batch_size,
                typed_page_size=args.typed_page_size,
                spot_check_size=args.spot_check_size,
                raw_only=args.raw_only,
                limit=args.limit,
                ddl_only=args.ddl_only,
            )


if __name__ == "__main__":
    main()
