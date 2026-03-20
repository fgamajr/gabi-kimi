#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# mac_daily_ingest.sh — Daily DOU ingest from Mac (INLABS relay)
#
# Downloads ZIPs from INLABS (which blocks the Hetzner IP),
# transfers them to the server, processes, and indexes to ES.
# Skips days that already have documents in MongoDB.
#
# Usage:
#   ./ops/bin/mac_daily_ingest.sh              # Ingest last 3 days
#   ./ops/bin/mac_daily_ingest.sh --days 7     # Ingest last 7 days
#   ./ops/bin/mac_daily_ingest.sh --date 2026-03-15  # Single day
#   ./ops/bin/mac_daily_ingest.sh --force      # Last 3 days, skip check
# ─────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# ── Config ──
SERVER="root@204.168.173.163"
SERVER_COMPOSE="/home/gabi/gabi-kimi/docker-compose.yml"
VENV="$REPO_ROOT/.venv-ingest/bin/python"
TMP_DIR="/tmp/gabi_daily_ingest"
REMOTE_TMP="/tmp/gabi_daily_zips"
FORCE=false

# ── Parse args ──
MODE="--days"
MODE_VAL="3"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --days)  MODE="--days"; MODE_VAL="${2:-3}"; shift 2 ;;
        --date)  MODE="--date"; MODE_VAL="$2"; shift 2 ;;
        --force) FORCE=true; shift ;;
        *)       MODE_VAL="$1"; shift ;;
    esac
done

# ── Credentials ──
export INLABS_USER="${INLABS_USER:-fgamajr@gmail.com}"
export INLABS_PWD="${INLABS_PWD:-kqg8YDZ2eya3exq_wev}"
export PIPELINE_TMP="$TMP_DIR"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

# ── Step 0: Check which days are missing ──
log "Step 0: Checking which days need ingestion..."

# Build the date check script and run it on the server
MISSING_DATES=$(ssh "$SERVER" "docker compose -f $SERVER_COMPOSE exec -T elasticsearch curl -s 'http://localhost:9200/gabi_documents/_search' -H 'Content-Type: application/json' -d '{\"size\":0,\"aggs\":{\"dates\":{\"terms\":{\"field\":\"pub_date\",\"size\":50,\"format\":\"yyyy-MM-dd\"}}},\"query\":{\"range\":{\"pub_date\":{\"gte\":\"now-${MODE_VAL}d/d\"}}}}'" 2>/dev/null | python3 -c "
import sys, json
from datetime import date, timedelta

mode = '$MODE'
mode_val = '$MODE_VAL'
force = $( [ "$FORCE" = true ] && echo "True" || echo "False" )

if mode == '--date':
    candidates = [date.fromisoformat(mode_val)]
else:
    today = date.today()
    candidates = [today - timedelta(days=i) for i in range(int(mode_val))]

if force:
    for d in candidates:
        print(d.isoformat())
    sys.exit(0)

# Parse ES response to find which dates have docs
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
    log "All days already have documents. Nothing to do."
    exit 0
fi

MISSING_COUNT=$(echo "$MISSING_DATES" | wc -l | tr -d ' ')
log "Found $MISSING_COUNT day(s) needing ingestion: $(echo $MISSING_DATES | tr '\n' ' ')"

# ── Step 1: Download ZIPs from INLABS (only missing days) ──
log "Step 1: Downloading DOU ZIPs from INLABS..."
rm -rf "$TMP_DIR/inlabs_daily"
mkdir -p "$TMP_DIR"

$VENV -c "
import os
os.environ['PIPELINE_TMP'] = '$TMP_DIR'
from datetime import date
from src.backend.ingest.inlabs_daily import InlabsClient

dates_str = '''$MISSING_DATES'''.strip()
dates = [date.fromisoformat(d.strip()) for d in dates_str.split('\n') if d.strip()]

client = InlabsClient()
client.login()
total = 0
for d in dates:
    try:
        zips = client.download_day_zips(d)
        if zips:
            print(f'{d}: {len(zips)} ZIPs')
            total += len(zips)
        else:
            print(f'{d}: no ZIPs available')
    except Exception as e:
        print(f'{d}: FAILED - {e}')
print(f'Total: {total} ZIPs downloaded')
"

ZIP_COUNT=$(find "$TMP_DIR/inlabs_daily" -name "*.zip" 2>/dev/null | wc -l | tr -d ' ')
if [ "$ZIP_COUNT" -eq 0 ]; then
    log "No ZIPs downloaded. Nothing to do."
    exit 0
fi
log "Downloaded $ZIP_COUNT ZIPs"

# ── Step 2: Transfer ZIPs to server ──
log "Step 2: Transferring ZIPs to server..."
ssh "$SERVER" "rm -rf $REMOTE_TMP && mkdir -p $REMOTE_TMP"
scp -r "$TMP_DIR/inlabs_daily/"* "$SERVER:$REMOTE_TMP/"
log "Transfer complete"

# ── Step 3: Copy into container and process ──
log "Step 3: Processing ZIPs on server (Mongo ingest)..."
ssh "$SERVER" "
docker cp $REMOTE_TMP gabi-kimi-backend:/tmp/daily_zips

# Build zip-path args
zips=\$(find $REMOTE_TMP -name '*.zip' | sort)
zip_args=''
for z in \$zips; do
    container_path=\"/tmp/daily_zips/\$(basename \$(dirname \$z))/\$(basename \$z)\"
    zip_args=\"\$zip_args --zip-path \$container_path\"
done

docker compose -f $SERVER_COMPOSE exec -T backend python -m src.backend.ingest.inlabs_daily \$zip_args
"
log "Mongo ingest complete"

# ── Step 4: ES index sync ──
log "Step 4: Syncing to Elasticsearch..."
ssh "$SERVER" "docker compose -f $SERVER_COMPOSE exec -T backend python -m src.backend.ingest.es_indexer sync"
log "ES sync complete"

# ── Step 5: TCU ingest (acórdãos current year + súmulas/jurisprudência) ──
log "Step 5: Syncing TCU acórdãos (current year)..."
CURRENT_YEAR=$(date -u '+%Y')
ssh "$SERVER" "docker compose -f $SERVER_COMPOSE exec -T backend python -m src.backend.ingest.tcu_ingest --year $CURRENT_YEAR --cache-dir /data/gabi_dou/tcu-csv" || log "TCU acórdãos ingest failed (non-fatal)"

log "Step 5b: Syncing TCU súmulas + jurisprudência + respostas + boletins..."
ssh "$SERVER" "docker compose -f $SERVER_COMPOSE exec -T backend python -m src.backend.ingest.tcu_jurisprudencia_ingest --all --cache-dir /data/gabi_dou/tcu-csv" || log "TCU jurisprudência ingest failed (non-fatal)"

log "Step 5c: Syncing TCU normas..."
ssh "$SERVER" "docker compose -f $SERVER_COMPOSE exec -T backend python -m src.backend.ingest.tcu_normas_ingest --ingest --cache-dir /data/gabi_dou/tcu-csv" || log "TCU normas ingest failed (non-fatal)"

log "Step 5d: Embedding pending TCU docs..."
ssh "$SERVER" "docker compose -f $SERVER_COMPOSE exec -T backend python -m src.backend.ingest.tcu_embed --source tcu sync" || log "TCU embeddings failed (non-fatal)"
ssh "$SERVER" "docker compose -f $SERVER_COMPOSE exec -T backend python -m src.backend.ingest.tcu_embed --source normas sync" || log "TCU normas embeddings failed (non-fatal)"
log "TCU sync complete"

# ── Step 6: Verify ──
log "Step 6: Verifying..."
STATS=$(ssh "$SERVER" "curl -s http://localhost:8001/api/stats")
TOTAL=$(echo "$STATS" | python3 -c "import sys,json; print(json.loads(sys.stdin.read())['total_documents'])")
MAX_DATE=$(echo "$STATS" | python3 -c "import sys,json; print(json.loads(sys.stdin.read())['date_range']['max'][:10])")
TCU_COUNT=$(ssh "$SERVER" "docker exec gabi-kimi-elasticsearch curl -s http://localhost:9200/gabi_tcu_acordaos_v1/_count 2>/dev/null" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('count',0))" 2>/dev/null || echo "?")
log "DOU: $TOTAL docs (latest: $MAX_DATE) | TCU: $TCU_COUNT acórdãos"

# ── Cleanup ──
rm -rf "$TMP_DIR"
ssh "$SERVER" "rm -rf $REMOTE_TMP"
log "Done!"
