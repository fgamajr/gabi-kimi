#!/bin/bash
# =============================================================================
# GABI Migration - Phase 1: Pre-flight Checks
# =============================================================================
# Run this script before migration to ensure readiness

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
SOURCE_PG_URL="${SOURCE_PG_URL:-postgresql://localhost:5432/gabi}"
TARGET_PG_URL="${TARGET_PG_URL:-}"
SOURCE_ES_URL="${SOURCE_ES_URL:-http://localhost:9200}"
TARGET_ES_URL="${TARGET_ES_URL:-}"

checks_passed=0
checks_failed=0

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

run_check() {
    local name="$1"
    local command="$2"
    
    echo -n "Checking $name... "
    if eval "$command" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
        ((checks_passed++))
        return 0
    else
        echo -e "${RED}✗${NC}"
        ((checks_failed++))
        return 1
    fi
}

echo "=========================================="
echo "GABI Migration Pre-flight Checks"
echo "=========================================="
echo ""

# 1. Source Connectivity
echo "--- Source Connectivity ---"
run_check "Source PostgreSQL" "pg_isready -d \"$SOURCE_PG_URL\""
run_check "Source Elasticsearch" "curl -sf \"$SOURCE_ES_URL/_cluster/health\""

# 2. Target Connectivity (if configured)
if [[ -n "$TARGET_PG_URL" ]]; then
    echo ""
    echo "--- Target Connectivity ---"
    run_check "Target PostgreSQL" "pg_isready -d \"$TARGET_PG_URL\""
fi

if [[ -n "$TARGET_ES_URL" ]]; then
    run_check "Target Elasticsearch" "curl -sf \"$TARGET_ES_URL/_cluster/health\""
fi

# 3. Data Volume Estimation
echo ""
echo "--- Source Data Volume ---"

if command -v psql &> /dev/null; then
    DOC_COUNT=$(psql "$SOURCE_PG_URL" -t -c "SELECT COUNT(*) FROM documents;" 2>/dev/null | xargs || echo "0")
    CHUNK_COUNT=$(psql "$SOURCE_PG_URL" -t -c "SELECT COUNT(*) FROM document_chunks;" 2>/dev/null | xargs || echo "0")
    PG_SIZE=$(psql "$SOURCE_PG_URL" -t -c "SELECT pg_size_pretty(pg_database_size('gabi'));" 2>/dev/null | xargs || echo "unknown")
    
    log_info "Documents: $DOC_COUNT"
    log_info "Chunks: $CHUNK_COUNT"
    log_info "PostgreSQL size: $PG_SIZE"
    
    # Estimate migration time
    if [[ "$DOC_COUNT" =~ ^[0-9]+$ ]]; then
        if (( DOC_COUNT < 100000 )); then
            EST_TIME="2-3 hours"
        elif (( DOC_COUNT < 500000 )); then
            EST_TIME="4-8 hours"
        else
            EST_TIME="8-16 hours"
        fi
        log_info "Estimated migration time: $EST_TIME"
    fi
fi

if command -v curl &> /dev/null; then
    ES_COUNT=$(curl -sf "$SOURCE_ES_URL/gabi_documents_v1/_count" 2>/dev/null | grep -o '"count":[0-9]*' | cut -d: -f2 || echo "0")
    log_info "ES documents: $ES_COUNT"
fi

# 4. Disk Space Check
echo ""
echo "--- Local Resources ---"

AVAILABLE_DISK=$(df -BG . 2>/dev/null | tail -1 | awk '{print $4}' | sed 's/G//')
if [[ "$AVAILABLE_DISK" =~ ^[0-9]+$ ]]; then
    if (( AVAILABLE_DISK > 100 )); then
        log_info "Available disk space: ${AVAILABLE_DISK}GB"
    else
        log_warn "Low disk space: ${AVAILABLE_DISK}GB (recommend 100GB+)"
    fi
else
    log_warn "Could not determine disk space"
fi

# Check for required tools
echo ""
echo "--- Required Tools ---"
run_check "PostgreSQL client (psql)" "command -v psql"
run_check "pg_dump" "command -v pg_dump"
run_check "curl" "command -v curl"
run_check "gzip" "command -v gzip"
run_check "pv (progress viewer)" "command -v pv"

# 5. Backup Verification
echo ""
echo "--- Backup Status ---"
BACKUP_DIR="./backups"
if [[ -d "$BACKUP_DIR" ]]; then
    LATEST_BACKUP=$(find "$BACKUP_DIR" -name "*.sql.gz" -type f -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)
    if [[ -n "$LATEST_BACKUP" ]]; then
        BACKUP_AGE=$(( ($(date +%s) - $(stat -c %Y "$LATEST_BACKUP" 2>/dev/null || echo 0)) / 3600 ))
        if (( BACKUP_AGE < 24 )); then
            log_info "Recent backup found: $LATEST_BACKUP (${BACKUP_AGE}h old)"
        else
            log_warn "Backup is old: $LATEST_BACKUP (${BACKUP_AGE}h old)"
        fi
    else
        log_warn "No backups found in $BACKUP_DIR"
    fi
else
    log_warn "Backup directory not found: $BACKUP_DIR"
fi

# 6. Environment Configuration
echo ""
echo "--- Environment ---"

if [[ -f ".env" ]]; then
    log_info ".env file exists"
else
    log_warn ".env file not found"
fi

if [[ -n "${FLY_ACCESS_TOKEN:-}" ]]; then
    log_info "Fly.io access token configured"
else
    log_warn "Fly.io access token not set (FLY_ACCESS_TOKEN)"
fi

# Summary
echo ""
echo "=========================================="
echo "Pre-flight Summary"
echo "=========================================="
echo "Checks passed: $checks_passed"
echo "Checks failed: $checks_failed"

if (( checks_failed == 0 )); then
    echo ""
    log_info "All checks passed! Ready for migration."
    exit 0
else
    echo ""
    log_error "Some checks failed. Please resolve before proceeding."
    exit 1
fi
