#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# server_daily_ingest.sh — Daily DOU ingest running on Hetzner
#
# Replaces the Mac relay (mac_daily_ingest.sh). Runs entirely
# inside Docker using the backend container, which has direct
# INLABS access (via INLABS_PROXY if needed).
#
# Usage (from /home/gabi/gabi-kimi on the server):
#   ./ops/bin/server_daily_ingest.sh           # Last 3 days
#   ./ops/bin/server_daily_ingest.sh --days 7
#   ./ops/bin/server_daily_ingest.sh --date 2026-03-28
#   ./ops/bin/server_daily_ingest.sh --force   # Skip already-indexed check
# ─────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$REPO_ROOT/docker-compose.prod.yml}"
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"

log() { printf '%s %s\n' "[$(date '+%Y-%m-%d %H:%M:%S')]" "$*"; }

MODE="--days"
MODE_VAL="3"
FORCE=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --days)  MODE="--days";  MODE_VAL="${2:-3}"; shift 2 ;;
        --date)  MODE="--date";  MODE_VAL="$2";       shift 2 ;;
        --force) FORCE=true; shift ;;
        *)       MODE_VAL="$1"; shift ;;
    esac
done

# ── Step 0: Find missing dates ──
log "Step 0: Checking which days need ingestion..."

MISSING_DATES=$(docker compose -f "$COMPOSE_FILE" exec -T elasticsearch \
  curl -s 'http://localhost:9200/gabi_documents/_search' \
  -H 'Content-Type: application/json' \
  -d "{\"size\":0,\"aggs\":{\"dates\":{\"terms\":{\"field\":\"pub_date\",\"size\":50,\"format\":\"yyyy-MM-dd\"}}},\"query\":{\"range\":{\"pub_date\":{\"gte\":\"now-${MODE_VAL}d/d\"}}}}" \
  2>/dev/null | python3 -c "
import sys, json
from datetime import date, timedelta

mode = '$MODE'
mode_val = '$MODE_VAL'
force = $([ '$FORCE' = true ] && echo True || echo False)

if mode == '--date':
    candidates = [date.fromisoformat(mode_val)]
else:
    today = date.today()
    candidates = [today - timedelta(days=i) for i in range(int(mode_val))]

if force:
    for d in candidates:
        print(d.isoformat())
    sys.exit(0)

try:
    data = json.loads(sys.stdin.read())
    buckets = data.get('aggregations', {}).get('dates', {}).get('buckets', [])
    existing = {b['key_as_string'] for b in buckets}
except Exception:
    existing = set()

for d in candidates:
    if d.weekday() >= 5:
        continue
    if d.isoformat() not in existing:
        print(d.isoformat())
    else:
        sys.stderr.write(f'  skip {d.isoformat()} ({next((b[\"doc_count\"] for b in buckets if b[\"key_as_string\"]==d.isoformat()), 0)} docs)\n')
")

if [ -z "$MISSING_DATES" ]; then
    log "All days already indexed. Nothing to do."
    exit 0
fi

log "Found days: $(echo "$MISSING_DATES" | tr '\n' ' ')"

# ── Step 1: DOU ingest (download + Mongo) ──
log "Step 1: Ingesting DOU days..."
while IFS= read -r day; do
    log "  Ingesting $day..."
    docker compose -f "$COMPOSE_FILE" exec -T backend \
        python -m src.backend.ingest.inlabs_daily --date "$day" --skip-counts \
        || log "  WARNING: ingest failed for $day (continuing)"
done <<< "$MISSING_DATES"
log "DOU ingest complete"

# ── Step 2: ES index sync ──
log "Step 2: Syncing MongoDB → Elasticsearch..."
docker compose -f "$COMPOSE_FILE" exec -T backend \
    python -m src.backend.ingest.es_indexer sync
log "ES sync complete"

# ── Step 3: TCU acórdãos ──
log "Step 3: Syncing TCU acórdãos (current year)..."
CURRENT_YEAR=$(date -u '+%Y')
docker compose -f "$COMPOSE_FILE" exec -T backend \
    python -m src.backend.ingest.tcu_ingest --year "$CURRENT_YEAR" --cache-dir /data/gabi_dou/tcu-csv \
    || log "TCU acórdãos failed (non-fatal)"

log "Step 3b: TCU súmulas + jurisprudência..."
docker compose -f "$COMPOSE_FILE" exec -T backend \
    python -m src.backend.ingest.tcu_jurisprudencia_ingest --all --cache-dir /data/gabi_dou/tcu-csv \
    || log "TCU jurisprudência failed (non-fatal)"

log "Step 3c: TCU normas..."
docker compose -f "$COMPOSE_FILE" exec -T backend \
    python -m src.backend.ingest.tcu_normas_ingest --ingest --cache-dir /data/gabi_dou/tcu-csv \
    || log "TCU normas failed (non-fatal)"

log "Step 3d: TCU BTCU boletins..."
docker compose -f "$COMPOSE_FILE" exec -T backend \
    python -m src.backend.ingest.tcu_btcu_ingest --ingest --recent --cache-dir /data/gabi_dou/tcu-btcu-pdf \
    || log "TCU BTCU failed (non-fatal)"

log "Step 3e: TCU embeddings..."
docker compose -f "$COMPOSE_FILE" exec -T backend \
    python -m src.backend.ingest.tcu_embed --source tcu sync \
    || log "TCU embeddings failed (non-fatal)"

# ── Step 4: Homepage cache ──
log "Step 4: Updating homepage cache (trending + editorial)..."
docker compose -f "$COMPOSE_FILE" exec -T backend \
    python -m src.backend.search.trending --update
docker compose -f "$COMPOSE_FILE" exec -T backend \
    python -m src.backend.search.editorial --update
log "Homepage cache updated"

# ── Step 5: Verify ──
log "Step 5: Verifying..."
STATS=$(curl -s http://localhost:8001/api/stats)
TOTAL=$(echo "$STATS" | python3 -c "import sys,json; print(json.loads(sys.stdin.read())['total_documents'])")
MAX_DATE=$(echo "$STATS" | python3 -c "import sys,json; print(json.loads(sys.stdin.read())['date_range']['max'][:10])")
log "DOU: $TOTAL docs (latest: $MAX_DATE)"

log "Done!"
