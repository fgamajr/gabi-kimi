"""Shared asyncpg connection pool for the GABI backend.

Usage:
    # In FastAPI lifespan:
    await init_pool()
    yield
    await close_pool()

    # In async endpoint / helper:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT $1::int", 42)
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg


_pool: asyncpg.Pool | None = None


def _build_dsn() -> str:
    pg_dsn = os.getenv("PG_DSN", "")
    if pg_dsn:
        if "://" in pg_dsn:
            return pg_dsn
        # Parse libpq key=value format → postgresql:// URL
        parts: dict[str, str] = {}
        for kv in pg_dsn.split():
            if "=" in kv:
                k, v = kv.split("=", 1)
                parts[k] = v
        host = parts.get("host", "localhost")
        port = parts.get("port", "5433")
        dbname = parts.get("dbname", "gabi")
        user = parts.get("user", "gabi")
        password = parts.get("password", "gabi")
        sslmode = parts.get("sslmode", "prefer")
        return f"postgresql://{user}:{password}@{host}:{port}/{dbname}?sslmode={sslmode}"

    host = os.getenv("PGHOST", os.getenv("GABI_POSTGRES_HOST", "localhost"))
    port = os.getenv("PGPORT", os.getenv("GABI_POSTGRES_PORT", "5433"))
    db = os.getenv("PGDATABASE", os.getenv("GABI_POSTGRES_DB", "gabi"))
    user = os.getenv("PGUSER", os.getenv("GABI_POSTGRES_USER", "gabi"))
    password = os.getenv("PGPASSWORD", os.getenv("GABI_POSTGRES_PASSWORD", "gabi"))
    sslmode = os.getenv("PGSSLMODE", "prefer")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}?sslmode={sslmode}"


async def init_pool(*, min_size: int = 2, max_size: int = 10) -> None:
    global _pool
    if _pool is not None:
        return
    _pool = await asyncpg.create_pool(
        _build_dsn(),
        min_size=min_size,
        max_size=max_size,
        command_timeout=30,
    )


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("asyncpg pool not initialised — call init_pool() first")
    return _pool


@asynccontextmanager
async def acquire(*, timeout_ms: int = 30000) -> AsyncIterator[asyncpg.Connection]:
    """Acquire a connection from the pool with a per-session statement_timeout."""
    async with get_pool().acquire() as conn:
        await conn.execute(f"SET statement_timeout = '{timeout_ms}'")
        try:
            yield conn
        finally:
            await conn.execute("RESET statement_timeout")
