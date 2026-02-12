#!/bin/bash
# =============================================================================
# GABI Migration - Phase 3: PostgreSQL Migration
# =============================================================================

set -euo pipefail

# Configuration
SOURCE_PG_URL="${SOURCE_PG_URL:-postgresql://localhost:5432/gabi}"
TARGET_PG_URL="${TARGET_PG_URL:-}"
MIGRATION_DIR="${MIGRATION_DIR:-./migration_work}"
PARALLEL_JOBS="${PARALLEL_JOBS:-4}"
BATCH_SIZE="${BATCH_SIZE:-10000}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $*"; }

# Validate target URL
if [[ -z "$TARGET_PG_URL" ]]; then
    log_error "TARGET_PG_URL not set"
    echo "Usage: TARGET_PG_URL=postgres://... $0"
    exit 1
fi

mkdir -p "$MIGRATION_DIR"
START_TIME=$(date +%s)

log_step "Starting PostgreSQL migration"
log_info "Source: $SOURCE_PG_URL"
log_info "Target: $TARGET_PG_URL"

# Step 1: Schema migration
log_step "Migrating schema..."
pg_dump "$SOURCE_PG_URL" \
    --schema-only \
    --no-owner \
    --no-privileges \
    --file="$MIGRATION_DIR/schema.sql"

# Modify schema for Fly.io (remove local-specific settings)
sed -i 's/SET lock_timeout = 0;//g' "$MIGRATION_DIR/schema.sql" 2>/dev/null || true
sed -i 's/SET idle_in_transaction_session_timeout = 0;//g' "$MIGRATION_DIR/schema.sql" 2>/dev/null || true

psql "$TARGET_PG_URL" \
    --file="$MIGRATION_DIR/schema.sql" \
    --set ON_ERROR_STOP=on

log_info "Schema migration complete"

# Step 2: Data migration by table (for progress tracking)
log_step "Migrating data..."

TABLES=(
    "source_registry"
    "documents"
    "document_chunks"
    "execution_manifests"
    "dlq_messages"
    "audit_logs"
)

for table in "${TABLES[@]}"; do
    log_info "Migrating table: $table"
    
    # Get row count from source
    ROW_COUNT=$(psql "$SOURCE_PG_URL" -t -c "SELECT COUNT(*) FROM $table;" 2>/dev/null | xargs || echo "0")
    log_info "  Source rows: $ROW_COUNT"
    
    if [[ "$ROW_COUNT" == "0" ]]; then
        log_warn "  Skipping empty table"
        continue
    fi
    
    # Export and import
    pg_dump "$SOURCE_PG_URL" \
        --data-only \
        --table="$table" \
        --no-owner | \
    psql "$TARGET_PG_URL" \
        --set ON_ERROR_STOP=on
    
    # Verify
    TARGET_COUNT=$(psql "$TARGET_PG_URL" -t -c "SELECT COUNT(*) FROM $table;" 2>/dev/null | xargs || echo "0")
    log_info "  Target rows: $TARGET_COUNT"
    
    if [[ "$ROW_COUNT" != "$TARGET_COUNT" ]]; then
        log_warn "  Row count mismatch: $ROW_COUNT vs $TARGET_COUNT"
    fi
done

# Step 3: Run Alembic migrations to ensure latest schema
log_step "Running Alembic migrations..."
if command -v alembic &> /dev/null; then
    alembic upgrade head || log_warn "Alembic upgrade may have already been applied"
else
    log_warn "Alembic not found, skipping migrations"
fi

# Step 4: Create indexes and constraints
log_step "Creating indexes and constraints..."
psql "$TARGET_PG_URL" -c "REINDEX DATABASE current;" || log_warn "Some indexes may have failed"

# Step 5: Verify migration
log_step "Verifying migration..."

SOURCE_DOC_COUNT=$(psql "$SOURCE_PG_URL" -t -c "SELECT COUNT(*) FROM documents;" 2>/dev/null | xargs || echo "0")
TARGET_DOC_COUNT=$(psql "$TARGET_PG_URL" -t -c "SELECT COUNT(*) FROM documents;" 2>/dev/null | xargs || echo "0")
SOURCE_CHUNK_COUNT=$(psql "$SOURCE_PG_URL" -t -c "SELECT COUNT(*) FROM document_chunks;" 2>/dev/null | xargs || echo "0")
TARGET_CHUNK_COUNT=$(psql "$TARGET_PG_URL" -t -c "SELECT COUNT(*) FROM document_chunks;" 2>/dev/null | xargs || echo "0")

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo "=========================================="
echo "PostgreSQL Migration Summary"
echo "=========================================="
echo "Duration: $((DURATION / 60)) minutes $((DURATION % 60)) seconds"
echo ""
echo "Document Count:"
echo "  Source: $SOURCE_DOC_COUNT"
echo "  Target: $TARGET_DOC_COUNT"
echo ""
echo "Chunk Count:"
echo "  Source: $SOURCE_CHUNK_COUNT"
echo "  Target: $TARGET_CHUNK_COUNT"
echo ""

if [[ "$SOURCE_DOC_COUNT" == "$TARGET_DOC_COUNT" && "$SOURCE_CHUNK_COUNT" == "$TARGET_CHUNK_COUNT" ]]; then
    log_info "✓ Migration verification PASSED"
    exit 0
else
    log_error "✗ Migration verification FAILED"
    log_error "Row counts do not match!"
    exit 1
fi
