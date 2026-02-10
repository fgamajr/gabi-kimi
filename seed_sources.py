"""Seed source_registry from sources.yaml.

Reads sources.yaml and inserts/updates source_registry records in the database
so the pipeline can find them.

Usage:
    GABI_DATABASE_URL='postgresql+asyncpg://gabi:gabi@127.0.0.1:15432/gabi' \
    GABI_AUTH_ENABLED=false \
    python seed_sources.py
"""

import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlalchemy import text

from gabi.db import get_engine, init_db, close_db


SOURCES_FILE = Path(__file__).parent / "sources.yaml"


def _source_type(source_cfg: dict) -> str:
    """Infer source type from discovery config."""
    mode = source_cfg.get("discovery", {}).get("mode", "")
    if mode in ("url_pattern", "static_url"):
        return mode
    protocol = source_cfg.get("fetch", {}).get("protocol", "https")
    if protocol in ("http", "https"):
        return "web"
    return "file"


def _config_hash(source_cfg: dict) -> str:
    """SHA-256 hash of the source configuration."""
    raw = json.dumps(source_cfg, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


async def seed():
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    sources = data.get("sources", {}) or {}
    if not sources:
        print("No sources found in sources.yaml")
        return

    await init_db()
    engine = get_engine()
    now = datetime.now(timezone.utc)

    async with engine.begin() as conn:
        for source_id, source_cfg in sources.items():
            meta = source_cfg.get("metadata", {})
            enabled = source_cfg.get("enabled", True)
            if enabled is False:
                print(f"  SKIP {source_id} (disabled)")
                continue

            name = meta.get("description", source_id.replace("_", " ").title())
            description = meta.get("description", "")
            stype = _source_type(source_cfg)
            chash = _config_hash(source_cfg)
            cjson = json.dumps(source_cfg, default=str)
            retention = source_cfg.get("lifecycle", {}).get("purge", {}).get("retention_days", 2555)
            sensitivity = "public"  # TCU data is public
            owner_email = "gabi-admin@tcu.gov.br"

            await conn.execute(
                text("""
                    INSERT INTO source_registry (
                        id, name, description, type, status,
                        config_hash, config_json,
                        document_count, total_documents_ingested,
                        consecutive_errors,
                        owner_email, sensitivity, retention_days,
                        created_at, updated_at, is_deleted
                    ) VALUES (
                        :id, :name, :description, :type, 'active',
                        :config_hash, CAST(:config_json AS jsonb),
                        0, 0,
                        0,
                        :owner_email, :sensitivity, :retention_days,
                        :created_at, :updated_at, false
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        config_hash = EXCLUDED.config_hash,
                        config_json = EXCLUDED.config_json,
                        updated_at = EXCLUDED.updated_at
                """),
                {
                    "id": source_id,
                    "name": name,
                    "description": description,
                    "type": stype,
                    "config_hash": chash,
                    "config_json": cjson,
                    "owner_email": owner_email,
                    "sensitivity": sensitivity,
                    "retention_days": retention,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            print(f"  ✓ {source_id} ({stype})")

    await close_db()
    print(f"\nDone — {len(sources)} sources processed.")


if __name__ == "__main__":
    asyncio.run(seed())
