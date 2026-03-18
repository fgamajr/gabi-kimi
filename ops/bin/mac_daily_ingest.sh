#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# mac_daily_ingest.sh — Daily DOU ingest from Mac (INLABS relay)
#
# Downloads ZIPs from INLABS (which blocks the Hetzner IP),
# transfers them to the server, processes, and indexes to ES.
#
# Usage:
#   ./ops/bin/mac_daily_ingest.sh              # Ingest last 3 days
#   ./ops/bin/mac_daily_ingest.sh --days 7     # Ingest last 7 days
#   ./ops/bin/mac_daily_ingest.sh --date 2026-03-15  # Single day
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
DAYS="${1:---days}"
DAYS_VAL="${2:-3}"

# ── Credentials (from .env.example) ──
export INLABS_USER="${INLABS_USER:-fgamajr@gmail.com}"
export INLABS_PWD="${INLABS_PWD:-kqg8YDZ2eya3exq_wev}"
export PIPELINE_TMP="$TMP_DIR"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

# ── Step 1: Download ZIPs from INLABS (runs on Mac) ──
log "Step 1: Downloading DOU ZIPs from INLABS..."
rm -rf "$TMP_DIR/inlabs_daily"
mkdir -p "$TMP_DIR"

if [ "$DAYS" = "--date" ]; then
    # Single day mode
    $VENV -c "
import os, sys
os.environ['PIPELINE_TMP'] = '$TMP_DIR'
from datetime import date
from src.backend.ingest.inlabs_daily import InlabsClient
client = InlabsClient()
client.login()
d = date.fromisoformat('$DAYS_VAL')
zips = client.download_day_zips(d)
print(f'Downloaded {len(zips)} ZIPs for {d}')
for z in zips: print(f'  {z}')
"
else
    # Rolling window mode
    $VENV -c "
import os, sys
os.environ['PIPELINE_TMP'] = '$TMP_DIR'
from datetime import date, timedelta
from src.backend.ingest.inlabs_daily import InlabsClient
client = InlabsClient()
client.login()
today = date.today()
days = int('$DAYS_VAL')
total = 0
for i in range(days):
    d = today - timedelta(days=i)
    try:
        zips = client.download_day_zips(d)
        if zips:
            print(f'{d}: {len(zips)} ZIPs')
            total += len(zips)
        else:
            print(f'{d}: no ZIPs (weekend/holiday?)')
    except Exception as e:
        print(f'{d}: FAILED - {e}')
print(f'Total: {total} ZIPs downloaded')
"
fi

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

# ── Step 5: Verify ──
log "Step 5: Verifying..."
STATS=$(ssh "$SERVER" "curl -s http://localhost:8001/api/stats")
TOTAL=$(echo "$STATS" | python3 -c "import sys,json; print(json.loads(sys.stdin.read())['total_documents'])")
MAX_DATE=$(echo "$STATS" | python3 -c "import sys,json; print(json.loads(sys.stdin.read())['date_range']['max'][:10])")
log "Total documents: $TOTAL | Latest date: $MAX_DATE"

# ── Cleanup ──
rm -rf "$TMP_DIR"
ssh "$SERVER" "rm -rf $REMOTE_TMP"
log "Done! ✓"
