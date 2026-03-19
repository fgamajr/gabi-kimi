#!/usr/bin/env bash
# Ingest TCU Acórdãos — weekly cron or manual run.
#
# Usage:
#   ./ops/bin/ingest_tcu.sh                  # current year only
#   ./ops/bin/ingest_tcu.sh --full           # full backfill 1992-current
#   ./ops/bin/ingest_tcu.sh --range 2020 2025

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
compose_file="${COMPOSE_FILE:-docker-compose.prod.yml}"
cache_dir="${TCU_CACHE_DIR:-${HOME}/.local/cache/gabi-kimi/tcu-csv}"
log_dir="${TCU_LOG_DIR:-${HOME}/.local/state/gabi-kimi/tcu-ingest}"

mkdir -p "${cache_dir}" "${log_dir}"
log_file="${log_dir}/run-$(date -u '+%Y%m%d-%H%M%S').log"

log() {
  printf '[%s] %s\n' "$(date -u '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "${log_file}"
}

current_year="$(date -u '+%Y')"

if [[ "${1:-}" == "--full" ]]; then
  args="--range 1992 ${current_year}"
  log "full backfill: 1992-${current_year}"
elif [[ "${1:-}" == "--range" ]]; then
  args="--range ${2} ${3}"
  log "range: ${2}-${3}"
else
  args="--year ${current_year}"
  log "incremental: year ${current_year}"
fi

cd "${repo_root}"

log "starting TCU ingest: ${args}"

docker compose -f "${compose_file}" exec -T backend \
  python -m src.backend.ingest.tcu_ingest \
  ${args} \
  --batch-size 500 \
  --cache-dir /data/gabi_dou/tcu-csv \
  2>&1 | tee -a "${log_file}"

exit_code=${PIPESTATUS[0]}

if [[ ${exit_code} -eq 0 ]]; then
  log "TCU ingest completed successfully"
else
  log "TCU ingest FAILED (exit ${exit_code})"
fi

# Keep last 30 logs
find "${log_dir}" -name 'run-*.log' -mtime +30 -delete 2>/dev/null || true

exit ${exit_code}
