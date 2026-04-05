"""
Source-Separated Raw Table Schema Definition for Sprint 2
=========================================================

This module defines the DDL and migration strategy for splitting the current
monolithic raw tables into 11 source-isolated raw tables following the
source-separated model in SPEC.md §1.1.

Each source gets its own raw table with minimal schema:
  - id (text, PK)
  - all_fields (jsonb) — complete original document
  - source_type (text) — normalized source identifier
  - dumped_at (timestamp) — migration timestamp

No cross-source column sharing. Each source is treated as an independent dataset.
"""

from typing import NamedTuple
from datetime import datetime


class RawTableDef(NamedTuple):
    """Definition of a source-separated raw table."""
    logical_source: str  # e.g., 'dou_documents', 'tcu_acordao_completo'
    table_name: str      # e.g., 'raw.dou_documents_raw'
    row_count: int       # approximate
    origin: str          # CSV filename, collection name, or source
    migrations_from: list[str]  # tables to migrate data from (for consolidation)
    notes: str           # context


# ============================================================================
# DOU DATASETS
# ============================================================================

DOU_DOCUMENTS = RawTableDef(
    logical_source='dou_documents',
    table_name='raw.dou_documents_raw',
    row_count=15_853_837,
    origin='INLABS/Liferay (scraped)',
    migrations_from=['raw.dou_documents'],  # Already exists; ensure compatibility
    notes=(
        'DOU raw documents. All art_types mixed in one source. '
        'No splitting by art_type_normalized (that happens in parsing, Sprint 2).'
    ),
)

# ============================================================================
# TCU CSV SOURCES (Currently consolidated in raw.tcu_acordaos_raw_data)
# ============================================================================

TCU_ACORDAO_COMPLETO = RawTableDef(
    logical_source='tcu_acordao_completo',
    table_name='raw.tcu_acordao_completo_raw',
    row_count=520_353,
    origin='acordao-completo-{ano}.csv',
    migrations_from=['raw.tcu_acordaos_raw_data'],
    notes=(
        'TCU acórdãos completos (tipo=ACÓRDÃO, ACÓRDÃO DE RELAÇÃO, DECISÃO). '
        'Family A: has relatorio, voto, relator, situacao. '
        'Primary text for hash: acordao_texto.'
    ),
)

TCU_JURISPRUDENCIA_SELECIONADA = RawTableDef(
    logical_source='tcu_jurisprudencia_selecionada',
    table_name='raw.tcu_jurisprudencia_selecionada_raw',
    row_count=17_016,
    origin='jurisprudencia-selecionada.csv',
    migrations_from=['raw.tcu_acordaos_raw_data'],
    notes=(
        'TCU selected jurisprudence (tipo=JURISPRUDÊNCIA SELECIONADA). '
        'Family B: area, tema, autortese. '
        'Primary text for hash: enunciado.'
    ),
)

TCU_RESPOSTA_CONSULTA = RawTableDef(
    logical_source='tcu_resposta_consulta',
    table_name='raw.tcu_resposta_consulta_raw',
    row_count=522,
    origin='resposta-consulta.csv',
    migrations_from=['raw.tcu_acordaos_raw_data'],
    notes=(
        'TCU consultation responses (tipo=RESPOSTA A CONSULTA). '
        'Family B: area, colegiado, data_sessao. '
        'Primary text for hash: enunciado.'
    ),
)

TCU_SUMULA = RawTableDef(
    logical_source='tcu_sumula',
    table_name='raw.tcu_sumula_raw',
    row_count=294,
    origin='sumula.csv',
    migrations_from=['raw.tcu_acordaos_raw_data'],
    notes=(
        'TCU jurisprudential summaries (tipo=SÚMULA). '
        'Family B: numero_referencia, area, vigente. '
        'Primary text for hash: enunciado.'
    ),
)

TCU_BOLETIM_JURISPRUDENCIA = RawTableDef(
    logical_source='tcu_boletim_jurisprudencia',
    table_name='raw.tcu_boletim_jurisprudencia_raw',
    row_count=5_828,
    origin='boletim-jurisprudencia.csv',
    migrations_from=['raw.tcu_acordaos_raw_data'],
    notes=(
        'TCU Jurisprudence Bulletin (tipo=BOLETIM JURISPRUDÊNCIA). '
        'Family B: enunciado-based. '
        'Primary text for hash: enunciado.'
    ),
)

TCU_BOLETIM_PESSOAL = RawTableDef(
    logical_source='tcu_boletim_pessoal',
    table_name='raw.tcu_boletim_pessoal_raw',
    row_count=1_500,
    origin='boletim-pessoal.csv',
    migrations_from=['raw.tcu_acordaos_raw_data'],
    notes=(
        'TCU Personnel Bulletin (tipo=BOLETIM PESSOAL). '
        'Family B: enunciado-based. '
        'Primary text for hash: enunciado.'
    ),
)

TCU_BOLETIM_INFORMATIVO_LC = RawTableDef(
    logical_source='tcu_boletim_informativo_lc',
    table_name='raw.tcu_boletim_informativo_lc_raw',
    row_count=1_977,
    origin='boletim-informativo-lc.csv',
    migrations_from=['raw.tcu_acordaos_raw_data'],
    notes=(
        'TCU Procurement & Contracts Bulletin (tipo=BOLETIM INFORMATIVO LC). '
        'Family B: enunciado-based. '
        'Primary text for hash: enunciado.'
    ),
)

# ============================================================================
# TCU NON-CSV SOURCES
# ============================================================================

TCU_NORMAS = RawTableDef(
    logical_source='tcu_normas',
    table_name='raw.tcu_normas_raw',
    row_count=16_413,
    origin='normas.csv (or Scraped)',
    migrations_from=['raw.tcu_normas_raw_data'],
    notes=(
        'TCU norms/regulations (Portarias, INs, Resoluções, DNs). '
        'Standalone source. Primary text for hash: titulo or texto_norma.'
    ),
)

TCU_BTCU = RawTableDef(
    logical_source='tcu_btcu',
    table_name='raw.tcu_btcu_raw',
    row_count=223_515,
    origin='Scraped (não CSV)',
    migrations_from=['raw.tcu_btcu_raw_data'],
    notes=(
        'TCU Bulletin of Jurisprudence (BTCU). Large source, ~223K articles. '
        'Cadernos: Controle Externo, Administrativo, Deliberações. '
        'Primary text for hash: texto_completo or section_text.'
    ),
)

TCU_PUBLICACOES = RawTableDef(
    logical_source='tcu_publicacoes',
    table_name='raw.tcu_publicacoes_raw',
    row_count=667,
    origin='Scraped (não CSV)',
    migrations_from=['raw.tcu_publicacoes_raw_data'],
    notes=(
        'TCU Publications (books, journals, guides, reports). '
        'Types: livro, revista, caderno_tematico, cartilha, relatorio, sumario_executivo. '
        'Primary text for hash: body_plain or titulo.'
    ),
)

# ============================================================================
# REGISTRY
# ============================================================================

ALL_RAW_TABLES = [
    # DOU
    DOU_DOCUMENTS,
    # TCU CSV
    TCU_ACORDAO_COMPLETO,
    TCU_JURISPRUDENCIA_SELECIONADA,
    TCU_RESPOSTA_CONSULTA,
    TCU_SUMULA,
    TCU_BOLETIM_JURISPRUDENCIA,
    TCU_BOLETIM_PESSOAL,
    TCU_BOLETIM_INFORMATIVO_LC,
    # TCU Non-CSV
    TCU_NORMAS,
    TCU_BTCU,
    TCU_PUBLICACOES,
]

# ============================================================================
# DDL GENERATION
# ============================================================================

def generate_raw_table_ddl(table_def: RawTableDef) -> str:
    """Generate CREATE TABLE DDL for a source-separated raw table."""
    return f"""
CREATE TABLE IF NOT EXISTS {table_def.table_name} (
    id TEXT NOT NULL PRIMARY KEY,
    all_fields JSONB NOT NULL,
    source_type TEXT DEFAULT '{table_def.logical_source}',
    dumped_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Index for timestamp-based queries (recent documents)
CREATE INDEX IF NOT EXISTS idx_{table_def.table_name.replace('.', '_')}_dumped_at
  ON {table_def.table_name}(dumped_at DESC);

-- GIN index for JSONB queries if needed for later stages
CREATE INDEX IF NOT EXISTS idx_{table_def.table_name.replace('.', '_')}_all_fields
  ON {table_def.table_name} USING GIN(all_fields);

COMMENT ON TABLE {table_def.table_name} IS
  'Source-separated raw dump for {table_def.logical_source}. '
  'Origin: {table_def.origin}. '
  'Approx. {table_def.row_count:,} documents. '
  '{table_def.notes}';
"""


def generate_all_raw_ddl() -> str:
    """Generate DDL for all 11 source-separated raw tables."""
    ddl_parts = []
    for table_def in ALL_RAW_TABLES:
        ddl_parts.append(generate_raw_table_ddl(table_def))
    return "\n".join(ddl_parts)


# ============================================================================
# MIGRATION STRATEGY
# ============================================================================

MIGRATION_PLAN = """
MIGRATION PLAN: Consolidate → Source-Separated (Sprint 2)
===========================================================

Current State (Sprint 1 Complete):
  - raw.dou_documents: 15.8M rows (typed + raw, already split-ready)
  - raw.tcu_acordaos: 547.5K rows (typed, two-family schema)
  - raw.tcu_acordaos_raw_data: 547.5K rows (7 CSV sources consolidated)
  - raw.tcu_btcu_raw_data: 223.5K rows (single source)
  - raw.tcu_normas_raw_data: 16.4K rows (single source)
  - raw.tcu_publicacoes_raw_data: 667 rows (single source)

Target State (Sprint 2):
  11 source-separated raw tables + 11 independent typed materialization layers.

Phase 1: Create New Raw Tables (non-destructive)
  1. Create raw.dou_documents_raw (copy from raw.dou_documents)
  2. Create raw.tcu_acordao_completo_raw
  3. Create raw.tcu_jurisprudencia_selecionada_raw
  4. Create raw.tcu_resposta_consulta_raw
  5. Create raw.tcu_sumula_raw
  6. Create raw.tcu_boletim_jurisprudencia_raw
  7. Create raw.tcu_boletim_pessoal_raw
  8. Create raw.tcu_boletim_informativo_lc_raw
  9. Create raw.tcu_normas_raw (copy from raw.tcu_normas_raw_data)
  10. Create raw.tcu_btcu_raw (copy from raw.tcu_btcu_raw_data)
  11. Create raw.tcu_publicacoes_raw (copy from raw.tcu_publicacoes_raw_data)

Phase 2: Split TCU CSV Sources
  - Materialize 7 source-specific subsets from raw.tcu_acordaos_raw_data
    using tipo + source_type detection
  - Insert each subset into corresponding new raw table
  - Validate row counts match expectations

Phase 3: Rename & Archive (post-validation)
  - Rename old tables to _archive suffix:
    - raw.dou_documents → raw.dou_documents_archive
    - raw.tcu_acordaos_raw_data → raw.tcu_acordaos_raw_data_archive
    - raw.tcu_btcu_raw_data → raw.tcu_btcu_raw_data_archive
    - etc.
  - Keep for rollback period (e.g., 2 weeks)
  - Then drop

Phase 4: Update Typed Materialization
  - Create 11 new typed tables (one per source)
  - Update parsers to target source-specific tables
  - Materialized schema per source (no column-sharing)

Rollback:
  - If any phase fails, keep old tables and revert
  - Typed layer can remain in old tables until validation complete
"""


if __name__ == "__main__":
    print("Source-Separated Raw Table Definitions")
    print("=" * 70)
    print()
    
    print(f"Total tables: {len(ALL_RAW_TABLES)}")
    print(f"Total approx. rows: {sum(t.row_count for t in ALL_RAW_TABLES):,}")
    print()
    
    print("All Sources:")
    for i, table_def in enumerate(ALL_RAW_TABLES, 1):
        print(f"{i:2d}. {table_def.logical_source:.<40s} ({table_def.row_count:>12,} rows)")
    
    print()
    print(MIGRATION_PLAN)
    print()
    print("DDL (ready to execute):")
    print("=" * 70)
    print(generate_all_raw_ddl())
