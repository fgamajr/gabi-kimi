#!/usr/bin/env bash
# Exporta evidência de strict coverage a partir do estado atual do DB.
# Deve ser executado após zero-kelvin (ou com conexão ao mesmo DB) para evidência limpa,
# sem mistura de runs históricos.
#
# Uso: ./scripts/export-strict-coverage-evidence.sh [output_dir]
# output_dir default: reports/strict_coverage_evidence_<date>
# Requer: psql, variáveis PGPASSWORD, PGHOST, PGPORT, PGUSER, PGDATABASE (ou defaults para dev local).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="${1:-$REPO_ROOT/reports/strict_coverage_evidence_$(date +%Y-%m-%d_%H%M)}"
export PGPASSWORD="${PGPASSWORD:-gabi_dev_password}"
export PGHOST="${PGHOST:-localhost}"
export PGPORT="${PGPORT:-5433}"
export PGUSER="${PGUSER:-gabi}"
export PGDATABASE="${PGDATABASE:-gabi}"

mkdir -p "$OUTPUT_DIR"

echo "Exporting strict coverage evidence to $OUTPUT_DIR (DB: $PGHOST:$PGPORT/$PGDATABASE)"

# 1) Fontes com pipeline.coverage.strict no DB (YAML → DB)
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -t -A -F',' -c "
SELECT \"Id\",
  COALESCE(\"PipelineConfig\"::jsonb #>> '{coverage,strict}', 'false') AS strict_from_db,
  \"Enabled\"
FROM source_registry
WHERE \"PipelineConfig\" IS NOT NULL
  AND (\"PipelineConfig\"::jsonb #>> '{coverage,strict}' = 'true'
       OR \"PipelineConfig\"::jsonb ? 'strict_coverage')
ORDER BY \"Id\";
" 2>/dev/null | sed '1i source_id,strict_from_db,enabled' > "$OUTPUT_DIR/strict_sources_from_db.csv" || true

# 2) Último discovery run por source (status, error_summary, links_total)
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -t -A -F',' -c "
SELECT r.\"SourceId\",
  r.\"Status\",
  COALESCE(r.\"ErrorSummary\", ''),
  r.\"LinksTotal\",
  r.\"StartedAt\"
FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY \"SourceId\" ORDER BY \"StartedAt\" DESC) AS rn
  FROM discovery_runs
) r
WHERE r.rn = 1
ORDER BY r.\"SourceId\";
" 2>/dev/null | sed '1i source_id,status,error_summary,links_total,started_at' > "$OUTPUT_DIR/last_discovery_run_per_source.csv" || true

# 3) Último fetch run por source (status, error_summary)
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -t -A -F',' -c "
SELECT r.\"SourceId\",
  r.\"Status\",
  COALESCE(r.\"ErrorSummary\", ''),
  r.\"ItemsTotal\",
  r.\"ItemsCompleted\",
  r.\"StartedAt\"
FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY \"SourceId\" ORDER BY \"StartedAt\" DESC) AS rn
  FROM fetch_runs
) r
WHERE r.rn = 1
ORDER BY r.\"SourceId\";
" 2>/dev/null | sed '1i source_id,status,error_summary,items_total,items_completed,started_at' > "$OUTPUT_DIR/last_fetch_run_per_source.csv" || true

echo "Done. Files: $OUTPUT_DIR/strict_sources_from_db.csv, last_discovery_run_per_source.csv, last_fetch_run_per_source.csv"
