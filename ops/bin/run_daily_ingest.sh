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

collect_year_months() {
  python3 - "${rolling_window_days}" <<'PY'
from datetime import datetime, timedelta, timezone
import sys

window_days = int(sys.argv[1])
today = datetime.now(timezone.utc).date()
months: list[tuple[int, int]] = []
seen: set[tuple[int, int]] = set()
for offset in range(window_days):
    current = today - timedelta(days=offset)
    key = (current.year, current.month)
    if key not in seen:
        months.append(key)
        seen.add(key)

for year, month in sorted(months):
    print(f"{year}-{month:02d}")
PY
}

log "Starting rolling ingest window (${rolling_window_days} days)"
cd "${repo_root}"
docker compose -f "${compose_file}" up -d mongo elasticsearch backend >>"${log_file}" 2>&1

while read -r year_month; do
  year="${year_month%-*}"
  month="${year_month#*-}"
  log "Syncing year=${year} month=${month}"
  docker compose -f "${compose_file}" exec -T backend \
    python -m src.backend.ingest.sync_dou --year "${year}" --month "${month}" --skip-es-sync >>"${log_file}" 2>&1
done < <(collect_year_months)

log "Rolling DOU ingest completed"

# ── TCU sync: re-ingest current year CSV (idempotent upsert) ──
log "TCU sync: re-ingesting current year..."
CURRENT_YEAR=$(date -u '+%Y')
docker compose -f "${compose_file}" exec -T backend \
  python -m src.backend.ingest.tcu_ingest --year "${CURRENT_YEAR}" \
  --cache-dir /data/gabi_dou/tcu-csv >>"${log_file}" 2>&1 || log "TCU sync failed (non-fatal)"
log "TCU sync completed"

log "All daily ingest completed"
