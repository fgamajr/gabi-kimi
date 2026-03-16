#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATE_DIR="${HOME}/.local/state/gabi-kimi/overnight-ingest"
LOG_FILE="${STATE_DIR}/run.log"
PID_FILE="${STATE_DIR}/run.pid"
STATUS_FILE="${STATE_DIR}/status.env"
START_YEAR="${START_YEAR:-2002}"
END_YEAR="${END_YEAR:-2026}"

mkdir -p "${STATE_DIR}"

cd "${ROOT_DIR}"

echo "$$" > "${PID_FILE}"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "${LOG_FILE}"
}

trap 'rm -f "${PID_FILE}"' EXIT

log "Starting overnight ingest: years ${START_YEAR}-${END_YEAR}"
docker compose up -d mongo elasticsearch backend >>"${LOG_FILE}" 2>&1

log "Waiting for backend readiness"
for _ in $(seq 1 60); do
  if docker compose exec -T backend python - <<'PY' >>"${LOG_FILE}" 2>&1
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:8000/", timeout=5) as response:
    print(response.status)
PY
  then
    log "Backend is ready"
    break
  fi
  sleep 5
done

if ! docker compose exec -T backend python - <<'PY' >>"${LOG_FILE}" 2>&1
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:8000/", timeout=5) as response:
    print(response.status)
PY
then
  log "Backend failed readiness check"
  exit 1
fi

for year in $(seq "${START_YEAR}" "${END_YEAR}"); do
  printf 'CURRENT_YEAR=%s\n' "${year}" > "${STATUS_FILE}"
  log "Running sync_dou for year ${year}"
  if docker compose exec -T backend python -m src.backend.ingest.sync_dou --year "${year}" >>"${LOG_FILE}" 2>&1; then
    log "Year ${year} completed"
  else
    rc=$?
    log "Year ${year} failed with exit code ${rc}"
    exit "${rc}"
  fi
done

printf 'CURRENT_YEAR=\nCOMPLETED=1\n' > "${STATUS_FILE}"
log "Overnight ingest finished"
