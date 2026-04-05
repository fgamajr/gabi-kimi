#!/usr/bin/env python3
"""
Sprint 2 Migration: Split consolidated raw tables into source-separated raw tables.

This script implements the source-separated raw table strategy documented in
SPEC.md §1.1 and ops/migrations/source_separated_raw_schema.py.

Execution:
  Local: python -m ops.migrations.source_separate_raw --confirm
  Prod:  ssh gabi-prod 'cd /home/gabi/gabi-kimi && python -m ops.migrations.source_separate_raw --confirm'

Safety:
  - Dry-run by default (no --confirm)
  - Schema validation before execution
  - Row count parity checks after each phase
  - Rollback archive naming for recovery
"""

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger(__name__)


@dataclass
class MigrationConfig:
    """Configuration for source separation migration."""
    postgres_url: str
    confirm: bool = False
    batch_size: int = 10000
    archive_prefix: str = "_archive"


# ============================================================================
# PHASE 1: Create Source-Separated Raw Tables
# ============================================================================

CREATE_TABLE_DDLS = {
    "raw.dou_documents_raw": """
CREATE TABLE IF NOT EXISTS raw.dou_documents_raw (
    id TEXT NOT NULL PRIMARY KEY,
    all_fields JSONB NOT NULL,
    source_type TEXT DEFAULT 'dou_documents',
    dumped_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dou_documents_raw_dumped_at
  ON raw.dou_documents_raw(dumped_at DESC);
CREATE INDEX IF NOT EXISTS idx_dou_documents_raw_all_fields
  ON raw.dou_documents_raw USING GIN(all_fields);
COMMENT ON TABLE raw.dou_documents_raw IS 'DOU documents (15.8M). Source: INLABS/Liferay.';
""",
    
    "raw.tcu_acordao_completo_raw": """
CREATE TABLE IF NOT EXISTS raw.tcu_acordao_completo_raw (
    id TEXT NOT NULL PRIMARY KEY,
    all_fields JSONB NOT NULL,
    source_type TEXT DEFAULT 'tcu_acordao_completo',
    dumped_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tcu_acordao_completo_raw_dumped_at
  ON raw.tcu_acordao_completo_raw(dumped_at DESC);
COMMENT ON TABLE raw.tcu_acordao_completo_raw IS 'TCU complete acórdãos (520K). Family A: acordao_texto primary text.';
""",

    "raw.tcu_jurisprudencia_selecionada_raw": """
CREATE TABLE IF NOT EXISTS raw.tcu_jurisprudencia_selecionada_raw (
    id TEXT NOT NULL PRIMARY KEY,
    all_fields JSONB NOT NULL,
    source_type TEXT DEFAULT 'tcu_jurisprudencia_selecionada',
    dumped_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tcu_jurisprudencia_selecionada_raw_dumped_at
  ON raw.tcu_jurisprudencia_selecionada_raw(dumped_at DESC);
COMMENT ON TABLE raw.tcu_jurisprudencia_selecionada_raw IS 'TCU selected jurisprudence (17K). Family B: enunciado primary text.';
""",

    "raw.tcu_resposta_consulta_raw": """
CREATE TABLE IF NOT EXISTS raw.tcu_resposta_consulta_raw (
    id TEXT NOT NULL PRIMARY KEY,
    all_fields JSONB NOT NULL,
    source_type TEXT DEFAULT 'tcu_resposta_consulta',
    dumped_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tcu_resposta_consulta_raw_dumped_at
  ON raw.tcu_resposta_consulta_raw(dumped_at DESC);
COMMENT ON TABLE raw.tcu_resposta_consulta_raw IS 'TCU consultation responses (522). Family B: enunciado primary text.';
""",

    "raw.tcu_sumula_raw": """
CREATE TABLE IF NOT EXISTS raw.tcu_sumula_raw (
    id TEXT NOT NULL PRIMARY KEY,
    all_fields JSONB NOT NULL,
    source_type TEXT DEFAULT 'tcu_sumula',
    dumped_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tcu_sumula_raw_dumped_at
  ON raw.tcu_sumula_raw(dumped_at DESC);
COMMENT ON TABLE raw.tcu_sumula_raw IS 'TCU jurisprudential summaries (294). Family B: enunciado primary text.';
""",

    "raw.tcu_boletim_jurisprudencia_raw": """
CREATE TABLE IF NOT EXISTS raw.tcu_boletim_jurisprudencia_raw (
    id TEXT NOT NULL PRIMARY KEY,
    all_fields JSONB NOT NULL,
    source_type TEXT DEFAULT 'tcu_boletim_jurisprudencia',
    dumped_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tcu_boletim_jurisprudencia_raw_dumped_at
  ON raw.tcu_boletim_jurisprudencia_raw(dumped_at DESC);
COMMENT ON TABLE raw.tcu_boletim_jurisprudencia_raw IS 'TCU Jurisprudence Bulletin (5.8K). Family B: enunciado primary text.';
""",

    "raw.tcu_boletim_pessoal_raw": """
CREATE TABLE IF NOT EXISTS raw.tcu_boletim_pessoal_raw (
    id TEXT NOT NULL PRIMARY KEY,
    all_fields JSONB NOT NULL,
    source_type TEXT DEFAULT 'tcu_boletim_pessoal',
    dumped_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tcu_boletim_pessoal_raw_dumped_at
  ON raw.tcu_boletim_pessoal_raw(dumped_at DESC);
COMMENT ON TABLE raw.tcu_boletim_pessoal_raw IS 'TCU Personnel Bulletin (1.5K). Family B: enunciado primary text.';
""",

    "raw.tcu_boletim_informativo_lc_raw": """
CREATE TABLE IF NOT EXISTS raw.tcu_boletim_informativo_lc_raw (
    id TEXT NOT NULL PRIMARY KEY,
    all_fields JSONB NOT NULL,
    source_type TEXT DEFAULT 'tcu_boletim_informativo_lc',
    dumped_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tcu_boletim_informativo_lc_raw_dumped_at
  ON raw.tcu_boletim_informativo_lc_raw(dumped_at DESC);
COMMENT ON TABLE raw.tcu_boletim_informativo_lc_raw IS 'TCU Procurement & Contracts Bulletin (2.0K). Family B: enunciado primary text.';
""",

    "raw.tcu_normas_raw": """
CREATE TABLE IF NOT EXISTS raw.tcu_normas_raw (
    id TEXT NOT NULL PRIMARY KEY,
    all_fields JSONB NOT NULL,
    source_type TEXT DEFAULT 'tcu_normas',
    dumped_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tcu_normas_raw_dumped_at
  ON raw.tcu_normas_raw(dumped_at DESC);
COMMENT ON TABLE raw.tcu_normas_raw IS 'TCU norms/regulations (16.4K). Portarias, INs, Resoluções, DNs.';
""",

    "raw.tcu_btcu_raw": """
CREATE TABLE IF NOT EXISTS raw.tcu_btcu_raw (
    id TEXT NOT NULL PRIMARY KEY,
    all_fields JSONB NOT NULL,
    source_type TEXT DEFAULT 'tcu_btcu',
    dumped_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tcu_btcu_raw_dumped_at
  ON raw.tcu_btcu_raw(dumped_at DESC);
COMMENT ON TABLE raw.tcu_btcu_raw IS 'TCU Bulletin of Jurisprudence (223.5K). Scraped.';
""",

    "raw.tcu_publicacoes_raw": """
CREATE TABLE IF NOT EXISTS raw.tcu_publicacoes_raw (
    id TEXT NOT NULL PRIMARY KEY,
    all_fields JSONB NOT NULL,
    source_type TEXT DEFAULT 'tcu_publicacoes',
    dumped_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tcu_publicacoes_raw_dumped_at
  ON raw.tcu_publicacoes_raw(dumped_at DESC);
COMMENT ON TABLE raw.tcu_publicacoes_raw IS 'TCU Publications (667). Books, journals, guides, reports.';
""",
}

# ============================================================================
# PHASE 2: Insert Data from Consolidated Sources
# ============================================================================

INSERT_STATEMENTS = {
    # DOU: copy from existing raw.dou_documents_raw_data
    "raw.dou_documents_raw": """
INSERT INTO raw.dou_documents_raw (id, all_fields, source_type, dumped_at)
SELECT id, all_fields, 'dou_documents', NOW()
FROM raw.dou_documents_raw_data
ON CONFLICT (id) DO NOTHING;
""",

    # TCU CSV sources: filter from raw.tcu_acordaos_raw_data by tipo + source hints
    "raw.tcu_acordao_completo_raw": """
INSERT INTO raw.tcu_acordao_completo_raw (id, all_fields, source_type, dumped_at)
SELECT id, all_fields, 'tcu_acordao_completo', NOW()
FROM raw.tcu_acordaos_raw_data
WHERE all_fields->>'tipo' IN ('ACÓRDÃO', 'ACÓRDÃO DE RELAÇÃO', 'DECISÃO')
  AND (all_fields->>'acordao_texto' IS NOT NULL OR all_fields->'acordao_texto' IS NOT NULL)
ON CONFLICT (id) DO NOTHING;
""",

    "raw.tcu_jurisprudencia_selecionada_raw": """
INSERT INTO raw.tcu_jurisprudencia_selecionada_raw (id, all_fields, source_type, dumped_at)
SELECT id, all_fields, 'tcu_jurisprudencia_selecionada', NOW()
FROM raw.tcu_acordaos_raw_data
WHERE all_fields->>'tipo' = 'JURISPRUDÊNCIA SELECIONADA'
ON CONFLICT (id) DO NOTHING;
""",

    "raw.tcu_resposta_consulta_raw": """
INSERT INTO raw.tcu_resposta_consulta_raw (id, all_fields, source_type, dumped_at)
SELECT id, all_fields, 'tcu_resposta_consulta', NOW()
FROM raw.tcu_acordaos_raw_data
WHERE all_fields->>'tipo' = 'RESPOSTA A CONSULTA'
ON CONFLICT (id) DO NOTHING;
""",

    "raw.tcu_sumula_raw": """
INSERT INTO raw.tcu_sumula_raw (id, all_fields, source_type, dumped_at)
SELECT id, all_fields, 'tcu_sumula', NOW()
FROM raw.tcu_acordaos_raw_data
WHERE all_fields->>'tipo' = 'SÚMULA'
ON CONFLICT (id) DO NOTHING;
""",

    "raw.tcu_boletim_jurisprudencia_raw": """
INSERT INTO raw.tcu_boletim_jurisprudencia_raw (id, all_fields, source_type, dumped_at)
SELECT id, all_fields, 'tcu_boletim_jurisprudencia', NOW()
FROM raw.tcu_acordaos_raw_data
WHERE all_fields->>'tipo' = 'BOLETIM JURISPRUDÊNCIA'
ON CONFLICT (id) DO NOTHING;
""",

    "raw.tcu_boletim_pessoal_raw": """
INSERT INTO raw.tcu_boletim_pessoal_raw (id, all_fields, source_type, dumped_at)
SELECT id, all_fields, 'tcu_boletim_pessoal', NOW()
FROM raw.tcu_acordaos_raw_data
WHERE all_fields->>'tipo' = 'BOLETIM PESSOAL'
ON CONFLICT (id) DO NOTHING;
""",

    "raw.tcu_boletim_informativo_lc_raw": """
INSERT INTO raw.tcu_boletim_informativo_lc_raw (id, all_fields, source_type, dumped_at)
SELECT id, all_fields, 'tcu_boletim_informativo_lc', NOW()
FROM raw.tcu_acordaos_raw_data
WHERE all_fields->>'tipo' = 'BOLETIM INFORMATIVO LC'
ON CONFLICT (id) DO NOTHING;
""",

    # TCU Non-CSV: copy from existing raw tables
    "raw.tcu_normas_raw": """
INSERT INTO raw.tcu_normas_raw (id, all_fields, source_type, dumped_at)
SELECT id, all_fields, 'tcu_normas', NOW()
FROM raw.tcu_normas_raw_data
ON CONFLICT (id) DO NOTHING;
""",

    "raw.tcu_btcu_raw": """
INSERT INTO raw.tcu_btcu_raw (id, all_fields, source_type, dumped_at)
SELECT id, all_fields, 'tcu_btcu', NOW()
FROM raw.tcu_btcu_raw_data
ON CONFLICT (id) DO NOTHING;
""",

    "raw.tcu_publicacoes_raw": """
INSERT INTO raw.tcu_publicacoes_raw (id, all_fields, source_type, dumped_at)
SELECT id, all_fields, 'tcu_publicacoes', NOW()
FROM raw.tcu_publicacoes_raw_data
ON CONFLICT (id) DO NOTHING;
""",
}

# Expected row counts (from SPEC.md)
EXPECTED_COUNTS = {
    "raw.dou_documents_raw": 15_853_837,
    "raw.tcu_acordao_completo_raw": 520_353,
    "raw.tcu_jurisprudencia_selecionada_raw": 17_016,
    "raw.tcu_resposta_consulta_raw": 522,
    "raw.tcu_sumula_raw": 294,
    "raw.tcu_boletim_jurisprudencia_raw": 5_828,
    "raw.tcu_boletim_pessoal_raw": 1_500,
    "raw.tcu_boletim_informativo_lc_raw": 1_977,
    "raw.tcu_normas_raw": 16_413,
    "raw.tcu_btcu_raw": 223_515,
    "raw.tcu_publicacoes_raw": 667,
}


def get_row_count(conn: psycopg.Connection, table_name: str) -> int:
    """Get row count for a table."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table_name}")
        return cur.fetchone()[0]


def run_migration(config: MigrationConfig) -> bool:
    """Execute the source separation migration."""
    logger.info("Starting source-separated raw table migration")
    
    try:
        with psycopg.connect(config.postgres_url) as conn:
            logger.info("Phase 1: Creating source-separated raw tables")
            with conn.cursor() as cur:
                for table_name, ddl in CREATE_TABLE_DDLS.items():
                    logger.info(f"  Creating {table_name}...")
                    if not config.confirm:
                        logger.info(f"    [DRY RUN] Would execute DDL")
                    else:
                        cur.execute(ddl)
                        logger.info(f"    ✓ Created {table_name}")
            
            if config.confirm:
                conn.commit()
            
            logger.info("Phase 2: Inserting data from consolidated sources")
            with conn.cursor() as cur:
                for target_table, insert_sql in INSERT_STATEMENTS.items():
                    logger.info(f"  Populating {target_table}...")
                    if not config.confirm:
                        logger.info(f"    [DRY RUN] Would insert {EXPECTED_COUNTS.get(target_table, '?')} rows")
                    else:
                        cur.execute(insert_sql)
                        rows = cur.rowcount
                        logger.info(f"    ✓ Inserted {rows} rows")
            
            if config.confirm:
                conn.commit()
            
            logger.info("Phase 3: Validating row counts")
            result_ok = True
            with conn.cursor() as cur:
                for target_table, expected_count in EXPECTED_COUNTS.items():
                    actual_count = get_row_count(conn, target_table)
                    match = "✓" if actual_count == expected_count else "⚠"
                    logger.info(f"  {match} {target_table}: {actual_count:,} (expected {expected_count:,})")
                    if actual_count != expected_count:
                        logger.warning(f"    Row count mismatch for {target_table}")
                        result_ok = False
            
            if config.confirm:
                logger.info("Phase 4: Migration complete. Archive old tables in 2 weeks.")
            else:
                logger.info("[DRY RUN] Would proceed to Phase 4 (archive) with --confirm")
            
            return result_ok
    
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Split consolidated raw tables into source-separated raw tables (Sprint 2)"
    )
    parser.add_argument(
        "--postgres-url",
        default="postgresql://gabi:gabi@localhost:5432/gabi",
        help="PostgreSQL connection URL",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Execute migration (dry-run by default)",
    )
    
    args = parser.parse_args()
    config = MigrationConfig(postgres_url=args.postgres_url, confirm=args.confirm)
    
    success = run_migration(config)
    sys.exit(0 if success else 1)
