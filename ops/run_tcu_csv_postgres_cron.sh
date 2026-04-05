#!/usr/bin/env bash
# TCU CSV → Postgres (raw colunar). Espelha ops/cron/tcu_csv_postgres.cron.example.
# Uso típico em servidor com compose de produção:
#   COMPOSE_FILE=docker-compose.prod.yml ./ops/run_tcu_csv_postgres_cron.sh
#
# Requer imagem backend com o módulo src.backend.ingest.tcu_csv_postgres_ingest
# e Postgres acessível em POSTGRES_URL (no compose já aponta para o serviço postgres).

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
CACHE_DIR="${TCU_CSV_CACHE_DIR:-/data/gabi_dou/tcu_csv_cache}"
YEAR_FROM="${TCU_CSV_YEAR_FROM:-1992}"
YEAR_TO="${TCU_CSV_YEAR_TO:-2026}"

if ! docker compose -f "$COMPOSE_FILE" ps -q backend >/dev/null 2>&1; then
  echo "erro: serviço backend não encontrado em $COMPOSE_FILE (docker compose ps)" >&2
  exit 1
fi

docker compose -f "$COMPOSE_FILE" exec -T backend sh -c "
  set -e
  mkdir -p '${CACHE_DIR}'
  python -m src.backend.ingest.tcu_csv_postgres_ingest --ddl-only
  python -m src.backend.ingest.tcu_csv_postgres_ingest --all \
    --year-from ${YEAR_FROM} --year-to ${YEAR_TO} \
    --cache-dir '${CACHE_DIR}' --skip-unchanged
"
