"""Simple key/value JSONB cache backed by Postgres app.cache table."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import psycopg

from src.backend.core.config import settings

logger = logging.getLogger(__name__)

_DDL = """
CREATE SCHEMA IF NOT EXISTS app;
CREATE TABLE IF NOT EXISTS app.cache (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _pg_url() -> str:
    return os.getenv("POSTGRES_URL", settings.POSTGRES_URL)


def cache_get(key: str) -> dict[str, Any] | None:
    try:
        with psycopg.connect(_pg_url()) as conn:
            conn.execute(_DDL)
            row = conn.execute(
                "SELECT value FROM app.cache WHERE key = %s", (key,)
            ).fetchone()
            return row[0] if row else None
    except Exception:
        logger.warning("pg_cache get failed for key=%s", key, exc_info=True)
        return None


def cache_set(key: str, value: dict[str, Any]) -> None:
    try:
        with psycopg.connect(_pg_url()) as conn:
            conn.execute(_DDL)
            conn.execute(
                """
                INSERT INTO app.cache (key, value, updated_at)
                VALUES (%s, %s::jsonb, %s)
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value,
                        updated_at = EXCLUDED.updated_at
                """,
                (key, json.dumps(value, default=str), datetime.now(timezone.utc)),
            )
    except Exception:
        logger.warning("pg_cache set failed for key=%s", key, exc_info=True)
