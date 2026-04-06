from __future__ import annotations

import argparse
import os

import psycopg

from src.backend.core.config import settings
from src.backend.parsing.source_parsers import SOURCE_TYPES


def _pg_url() -> str:
    return os.getenv("POSTGRES_URL", settings.POSTGRES_URL)


def _table_ddl(source_type: str) -> str:
    table = f"parsed.{source_type}"
    return f"""
CREATE TABLE IF NOT EXISTS {table} (
    id BIGSERIAL PRIMARY KEY,
    raw_id TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL,

    pub_date DATE,
    data_sessao DATE,
    numero_acordao INTEGER,
    ano_acordao INTEGER,
    numero_norma INTEGER,
    ano_norma INTEGER,
    colegiado TEXT,
    orgao_emissor TEXT,
    art_type TEXT,
    tipo_norma TEXT,

    structured_fields JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    section_map JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    body_tagged_xml TEXT,

    h1_tipo TEXT,
    h1_subtipo TEXT,
    h1_confidence DOUBLE PRECISION,
    h1_method TEXT,
    h1_version TEXT,
    h1_status TEXT,

    tag_spans JSONB NOT NULL DEFAULT '[]'::jsonb,
    tags_flat TEXT[] NOT NULL DEFAULT '{{}}',

    summary_short TEXT,
    summary_long TEXT,
    summary_structured JSONB,
    legal_entities JSONB,
    topics TEXT[],
    chunk_summaries JSONB,

    parser_version TEXT NOT NULL,
    enrichment_version TEXT,
    h2_version TEXT,
    prompt_version TEXT,
    enrichment_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (enrichment_status IN ('pending', 'running', 'done', 'failed', 'skipped')),
    enrichment_error TEXT,
    content_hash TEXT NOT NULL,
    enrichment_input_hash TEXT,

    parsed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_{source_type}_parsed_at ON {table}(parsed_at DESC);
CREATE INDEX IF NOT EXISTS ix_{source_type}_status ON {table}(enrichment_status, updated_at DESC);
CREATE INDEX IF NOT EXISTS ix_{source_type}_content_hash ON {table}(content_hash);
CREATE INDEX IF NOT EXISTS ix_{source_type}_pub_date ON {table}(pub_date DESC);
CREATE INDEX IF NOT EXISTS ix_{source_type}_data_sessao ON {table}(data_sessao DESC);
CREATE INDEX IF NOT EXISTS ix_{source_type}_tags_flat ON {table} USING GIN(tags_flat);
"""


QUEUE_DDL = """
CREATE SCHEMA IF NOT EXISTS parsed;

CREATE TABLE IF NOT EXISTS parsed.enrichment_queue (
    id BIGSERIAL PRIMARY KEY,
    source_type TEXT NOT NULL,
    raw_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    h2_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'done', 'failed', 'skipped')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    priority INTEGER NOT NULL DEFAULT 100,
    locked_by TEXT,
    locked_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_type, raw_id, h2_version, prompt_version, input_hash)
);

CREATE INDEX IF NOT EXISTS ix_enrichment_queue_status_next
  ON parsed.enrichment_queue (status, next_retry_at, priority);
CREATE INDEX IF NOT EXISTS ix_enrichment_queue_locked
  ON parsed.enrichment_queue (locked_by, locked_at);
"""


PROMPT_DDL = """
CREATE TABLE IF NOT EXISTS parsed.prompt_registry (
    id BIGSERIAL PRIMARY KEY,
    source_type TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model TEXT NOT NULL,
    temperature DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    system_prompt TEXT NOT NULL,
    few_shot_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    prompt_sha256 TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_type, prompt_version)
);
"""


def generate_ddl() -> str:
    parts = [QUEUE_DDL, PROMPT_DDL]
    for source_type in SOURCE_TYPES:
        parts.append(_table_ddl(source_type))
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create parsed.* schema for H1/H2 pipeline")
    parser.add_argument("--postgres-url", default=_pg_url())
    parser.add_argument("--apply", action="store_true", help="Apply DDL in database")
    args = parser.parse_args()

    ddl = generate_ddl()
    if not args.apply:
        print(ddl)
        return

    with psycopg.connect(args.postgres_url) as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()
    print("parsed schema applied")


if __name__ == "__main__":
    main()
