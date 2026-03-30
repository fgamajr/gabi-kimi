#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
compose_file="${COMPOSE_FILE:-docker-compose.prod.yml}"
rolling_window_days="${ROLLING_WINDOW_DAYS:-3}"
state_dir="${STATE_DIR:-${HOME}/.local/state/gabi-kimi/daily-ingest}"
log_file="${LOG_FILE:-${state_dir}/run.log}"

mkdir -p "${state_dir}"

log() {
  printf '[%s] %s\n' "$(date -u '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "${log_file}"
}

collect_dates() {
  python3 - "${rolling_window_days}" <<'PY'
from datetime import datetime, timedelta, timezone
import sys

window_days = int(sys.argv[1])
today = datetime.now(timezone.utc).date()
for offset in range(window_days):
    current = today - timedelta(days=offset)
    print(current.isoformat())
PY
}

log "Starting rolling ingest window (${rolling_window_days} days)"
cd "${repo_root}"
docker compose -f "${compose_file}" up -d mongo elasticsearch backend >>"${log_file}" 2>&1

while read -r target_date; do
  log "INLABS daily sync date=${target_date}"
  docker compose -f "${compose_file}" exec -T backend \
    python -m src.backend.ingest.inlabs_daily --date "${target_date}" --skip-counts >>"${log_file}" 2>&1 || log "DOU sync failed for ${target_date} (non-fatal)"
done < <(collect_dates)

log "Rolling DOU ingest completed"

# ── TCU sync: acórdãos (current year) + súmulas/jurisprudência ──
log "TCU sync: re-ingesting current year acórdãos..."
CURRENT_YEAR=$(date -u '+%Y')
docker compose -f "${compose_file}" exec -T backend \
  python -m src.backend.ingest.tcu_ingest --year "${CURRENT_YEAR}" \
  --cache-dir /data/gabi_dou/tcu-csv >>"${log_file}" 2>&1 || log "TCU acórdãos sync failed (non-fatal)"

log "TCU sync: súmulas + jurisprudência + respostas + boletins..."
docker compose -f "${compose_file}" exec -T backend \
  python -m src.backend.ingest.tcu_jurisprudencia_ingest --all \
  --cache-dir /data/gabi_dou/tcu-csv >>"${log_file}" 2>&1 || log "TCU jurisprudência sync failed (non-fatal)"

log "TCU sync: normas..."
docker compose -f "${compose_file}" exec -T backend \
  python -m src.backend.ingest.tcu_normas_ingest --ingest \
  --cache-dir /data/gabi_dou/tcu-csv >>"${log_file}" 2>&1 || log "TCU normas sync failed (non-fatal)"

# ── BTCU sync: scrape recent boletins ──
log "TCU sync: BTCU (boletins PDF)..."
docker compose -f "${compose_file}" exec -T backend \
  python -m src.backend.ingest.tcu_btcu_ingest --ingest --recent \
  --cache-dir /data/gabi_dou/tcu-btcu-pdf >>"${log_file}" 2>&1 || log "TCU BTCU sync failed (non-fatal)"

# ── TCU Publicações Institucionais: relatórios, cartilhas, sumários ──
log "TCU sync: publicações institucionais (relatórios, cartilhas, sumários)..."
docker compose -f "${compose_file}" exec -T backend \
  python -m src.backend.ingest.tcu_publicacoes_ingest --ingest --recent >>"${log_file}" 2>&1 || log "TCU publicações sync failed (non-fatal)"

# ── Embeddings: process any pending docs ──
log "TCU embeddings: acórdãos..."
docker compose -f "${compose_file}" exec -T backend \
  python -m src.backend.ingest.tcu_embed --source tcu sync >>"${log_file}" 2>&1 || log "TCU embeddings failed (non-fatal)"
log "TCU embeddings: normas..."
docker compose -f "${compose_file}" exec -T backend \
  python -m src.backend.ingest.tcu_embed --source normas sync >>"${log_file}" 2>&1 || log "TCU normas embeddings failed (non-fatal)"
log "TCU embeddings: btcu..."
docker compose -f "${compose_file}" exec -T backend \
  python -m src.backend.ingest.tcu_embed --source btcu sync >>"${log_file}" 2>&1 || log "TCU BTCU embeddings failed (non-fatal)"
log "TCU embeddings: publicações..."
docker compose -f "${compose_file}" exec -T backend \
  python -m src.backend.ingest.tcu_embed --source publicacoes sync >>"${log_file}" 2>&1 || log "TCU publicações embeddings failed (non-fatal)"

log "Syncing Elasticsearch from Mongo before homepage refresh..."
docker compose -f "${compose_file}" exec -T backend \
  python -m src.backend.ingest.es_indexer sync >>"${log_file}" 2>&1 || log "ES sync failed before homepage refresh (non-fatal)"

log "Refreshing homepage caches (trending + editorial)..."
"${script_dir}/update_homepage_cache.sh" >>"${log_file}" 2>&1 || log "Homepage cache refresh failed (non-fatal)"

log "All daily ingest completed"
