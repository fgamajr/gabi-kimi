#!/usr/bin/env bash
# daily_sync.sh — DOU automatic daily sync
#
# Refreshes the catalog registry from in.gov.br, discovers new ZIPs,
# downloads and ingests them into PostgreSQL, then refreshes BM25 index.
#
# Usage:
#   ./scripts/daily_sync.sh              # Full sync (refresh + download + ingest + BM25)
#   ./scripts/daily_sync.sh --dry-run    # Show what would be synced
#   ./scripts/daily_sync.sh --no-bm25    # Skip BM25 refresh
#
# Designed to run via cron/systemd timer. Logs to data/logs/sync_YYYY-MM-DD.log

set -euo pipefail

# ---------- Config ----------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
LOG_DIR="$PROJECT_DIR/data/logs"
TODAY="$(date +%Y-%m-%d)"
LOG_FILE="$LOG_DIR/sync_${TODAY}.log"

# Parse flags
DRY_RUN=""
SKIP_BM25=false
for arg in "$@"; do
    case "$arg" in
        --dry-run)  DRY_RUN="--dry-run" ;;
        --no-bm25)  SKIP_BM25=true ;;
    esac
done

# ---------- Setup ----------
mkdir -p "$LOG_DIR"
cd "$PROJECT_DIR"

# Activate virtualenv if it exists
if [[ -d "$VENV_DIR" ]]; then
    source "$VENV_DIR/bin/activate"
fi

# Load .env if present
if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi

# ---------- Logging ----------
log() {
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[$ts] $*" | tee -a "$LOG_FILE"
}

# ---------- Health check ----------
log "=== DOU Daily Sync starting ==="
log "Project: $PROJECT_DIR"

# Check PostgreSQL is reachable
if ! PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi -c "SELECT 1" &>/dev/null; then
    log "ERROR: PostgreSQL not reachable at localhost:5433. Aborting."
    exit 1
fi
log "PostgreSQL: OK"

# ---------- Step 1: Refresh catalog ----------
log "Step 1: Refreshing catalog from in.gov.br..."
CURRENT_YEAR="$(date +%Y)"
python3 -m ingest.catalog_scraper \
    --start-year "$((CURRENT_YEAR - 1))" \
    --end-year "$CURRENT_YEAR" \
    --delay 0.5 \
    2>&1 | tee -a "$LOG_FILE"
log "Catalog refreshed."

# ---------- Step 2: Sync (download + ingest) ----------
log "Step 2: Running sync pipeline${DRY_RUN:+ (DRY RUN)}..."
python3 -m ingest.sync_pipeline \
    --refresh-catalog \
    $DRY_RUN \
    2>&1 | tee -a "$LOG_FILE"

SYNC_EXIT=$?
if [[ $SYNC_EXIT -ne 0 ]]; then
    log "WARNING: Sync pipeline exited with code $SYNC_EXIT"
fi

# If dry-run, stop here
if [[ -n "$DRY_RUN" ]]; then
    log "Dry run complete. No changes made."
    exit 0
fi

# ---------- Step 3: Refresh BM25 index ----------
if [[ "$SKIP_BM25" == false ]]; then
    log "Step 3: Refreshing BM25 index..."
    python3 -m ingest.bm25_indexer refresh 2>&1 | tee -a "$LOG_FILE"
    log "BM25 index refreshed."
else
    log "Step 3: Skipped BM25 refresh (--no-bm25)."
fi

# ---------- Step 4: Refresh suggest cache ----------
log "Step 4: Refreshing suggest_cache materialized view..."
PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi \
    -c "REFRESH MATERIALIZED VIEW CONCURRENTLY dou.suggest_cache;" 2>&1 | tee -a "$LOG_FILE" || true
log "suggest_cache refreshed."

# ---------- Summary ----------
DOC_COUNT=$(PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi -tAc \
    "SELECT reltuples::bigint FROM pg_class WHERE relname='document'" 2>/dev/null || echo "?")
ZIP_COUNT=$(PGPASSWORD=gabi psql -h localhost -p 5433 -U gabi -d gabi -tAc \
    "SELECT count(*) FROM dou.source_zip" 2>/dev/null || echo "?")

log "=== Sync complete ==="
log "  Documents: ~${DOC_COUNT}"
log "  ZIPs ingested: ${ZIP_COUNT}"
log "  Log: ${LOG_FILE}"
