#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://localhost:5100}"
DB_SERVICE="${DB_SERVICE:-postgres}"
DB_USER="${DB_USER:-gabi}"
DB_NAME="${DB_NAME:-gabi}"
USERNAME="${USERNAME:-operator}"
PASSWORD="${PASSWORD:-op123}"
MAX_POLLS="${MAX_POLLS:-120}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-5}"
if [[ "$#" -eq 0 ]]; then
  SOURCES=("tcu_publicacoes" "camara_leis_ordinarias")
else
  SOURCES=("$@")
fi

echo "[1/5] Checking worker container health..."
docker compose ps worker

echo "[2/5] Authenticating..."
TOKEN="$(
  curl -s -X POST "${API_URL}/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"${USERNAME}\",\"password\":\"${PASSWORD}\"}" | jq -r '.token'
)"

if [[ -z "${TOKEN}" || "${TOKEN}" == "null" ]]; then
  echo "Failed to obtain auth token"
  exit 1
fi

START_TS="$(date -u +"%Y-%m-%d %H:%M:%S+00")"

echo "[3/5] Triggering seed..."
curl -s -X POST "${API_URL}/api/v1/dashboard/seed" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" | jq -c '.'

echo "[4/5] Triggering discovery for: ${SOURCES[*]}"
for source in "${SOURCES[@]}"; do
  curl -s -X POST "${API_URL}/api/v1/dashboard/sources/${source}/phases/discovery" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" | jq -c '.'
done

echo "[5/5] Polling latest discovery run status... (max_polls=${MAX_POLLS}, interval=${POLL_INTERVAL_SECONDS}s)"
for i in $(seq 1 "${MAX_POLLS}"); do
  docker compose exec -T "${DB_SERVICE}" psql -U "${DB_USER}" -d "${DB_NAME}" -c \
    "SELECT \"SourceId\", \"Status\", \"LinksTotal\", \"StartedAt\", \"CompletedAt\", \"ErrorSummary\"
     FROM discovery_runs
     WHERE \"SourceId\" IN ($(printf "'%s'," "${SOURCES[@]}" | sed 's/,$//'))
       AND \"StartedAt\" >= '${START_TS}'
     ORDER BY \"StartedAt\" DESC
     LIMIT 10;"

  all_done=true
  for source in "${SOURCES[@]}"; do
    status="$(docker compose exec -T "${DB_SERVICE}" psql -U "${DB_USER}" -d "${DB_NAME}" -t -A -c \
      "SELECT COALESCE((
         SELECT \"Status\"
         FROM discovery_runs
         WHERE \"SourceId\"='${source}'
           AND \"StartedAt\" >= '${START_TS}'
         ORDER BY \"StartedAt\" DESC
         LIMIT 1
       ), 'none');" | tr -d ' ')"
    if [[ "${status}" != "completed" && "${status}" != "failed" ]]; then
      all_done=false
    fi
  done

  if [[ "${all_done}" == "true" ]]; then
    echo "All requested sources reached terminal state."
    exit 0
  fi

  sleep "${POLL_INTERVAL_SECONDS}"
done

echo "Timeout waiting discovery terminal state."
exit 1
