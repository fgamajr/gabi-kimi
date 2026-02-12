#!/bin/bash
# =============================================================================
# GABI Migration - Phase 2: Create Local Backup
# =============================================================================

set -euo pipefail

# Configuration
SOURCE_PG_URL="${SOURCE_PG_URL:-postgresql://localhost:5432/gabi}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_PREFIX="gabi_backup_${TIMESTAMP}"
PARALLEL_JOBS="${PARALLEL_JOBS:-4}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# Create backup directory
mkdir -p "$BACKUP_DIR"

log_info "Starting backup process..."
log_info "Backup directory: $BACKUP_DIR"
log_info "Timestamp: $TIMESTAMP"

# 1. PostgreSQL Backup
log_info "Creating PostgreSQL backup..."

# Schema backup
log_info "Backing up schema..."
pg_dump "$SOURCE_PG_URL" \
    --schema-only \
    --no-owner \
    --no-privileges \
    --file="$BACKUP_DIR/${BACKUP_PREFIX}_schema.sql"

log_info "Schema backup complete: ${BACKUP_PREFIX}_schema.sql"

# Data backup (compressed, parallel)
log_info "Backing up data (this may take a while)..."

# Check if pv is available for progress
if command -v pv &> /dev/null; then
    pg_dump "$SOURCE_PG_URL" \
        --data-only \
        --jobs="$PARALLEL_JOBS" \
        --format=directory \
        --file="$BACKUP_DIR/${BACKUP_PREFIX}_data" \
        2>&1 | pv -l -i 5 > /dev/null || true
else
    pg_dump "$SOURCE_PG_URL" \
        --data-only \
        --jobs="$PARALLEL_JOBS" \
        --format=directory \
        --file="$BACKUP_DIR/${BACKUP_PREFIX}_data" \
        --verbose
fi

# Compress the data directory
log_info "Compressing data backup..."
tar -czf "$BACKUP_DIR/${BACKUP_PREFIX}_data.tar.gz" \
    -C "$BACKUP_DIR" \
    "${BACKUP_PREFIX}_data"

# Remove uncompressed directory
rm -rf "$BACKUP_DIR/${BACKUP_PREFIX}_data"

log_info "Data backup complete: ${BACKUP_PREFIX}_data.tar.gz"

# 2. Elasticsearch Backup (optional - will be reindexed)
log_info "Creating Elasticsearch snapshot reference..."
ES_COUNT=$(curl -sf "${SOURCE_ES_URL:-http://localhost:9200}/gabi_documents_v1/_count" 2>/dev/null | grep -o '"count":[0-9]*' | cut -d: -f2 || echo "unknown")
echo "ES document count: $ES_COUNT" > "$BACKUP_DIR/${BACKUP_PREFIX}_es_info.txt"
log_info "Elasticsearch info saved"

# 3. Configuration Backup
log_info "Backing up configuration..."
cp .env "$BACKUP_DIR/${BACKUP_PREFIX}_env" 2>/dev/null || log_warn ".env not found"
cp fly.toml "$BACKUP_DIR/${BACKUP_PREFIX}_fly.toml" 2>/dev/null || true
cp sources.yaml "$BACKUP_DIR/${BACKUP_PREFIX}_sources.yaml" 2>/dev/null || true

# 4. Generate checksums
log_info "Generating checksums..."
cd "$BACKUP_DIR"
sha256sum ${BACKUP_PREFIX}_* > "${BACKUP_PREFIX}_checksums.sha256"
cd - > /dev/null

# 5. Summary
log_info "Backup complete!"
echo ""
echo "Backup files:"
ls -lh "$BACKUP_DIR/${BACKUP_PREFIX}"*

echo ""
echo "To verify backup integrity:"
echo "  cd $BACKUP_DIR && sha256sum -c ${BACKUP_PREFIX}_checksums.sha256"
