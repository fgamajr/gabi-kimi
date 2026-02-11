#!/bin/bash
# =============================================================================
# GABI Migration - Master Orchestration Script
# =============================================================================
# This script orchestrates the complete migration from local to Fly.io

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATION_LOG="${MIGRATION_LOG:-migration_$(date +%Y%m%d_%H%M%S).log}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Logging
exec 1> >(tee -a "$MIGRATION_LOG")
exec 2>&1

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $*"; }
log_phase() { echo -e "${CYAN}[PHASE]${NC} $*"; }

# Track execution
declare -A PHASE_STATUS
CURRENT_PHASE=""

start_phase() {
    local phase="$1"
    CURRENT_PHASE="$phase"
    PHASE_STATUS[$phase]="RUNNING"
    log_phase "Starting Phase: $phase"
    echo "=========================================="
}

end_phase() {
    local phase="$1"
    local status="${2:-SUCCESS}"
    PHASE_STATUS[$phase]="$status"
    log_phase "Completed Phase: $phase ($status)"
    echo ""
}

# Error handler
error_handler() {
    local line=$1
    if [[ -n "$CURRENT_PHASE" ]]; then
        PHASE_STATUS[$CURRENT_PHASE]="FAILED"
        log_error "Phase $CURRENT_PHASE failed at line $line"
    fi
    log_error "Migration interrupted! Check logs: $MIGRATION_LOG"
    exit 1
}
trap 'error_handler $LINENO' ERR

# Confirmation prompts
confirm() {
    local message="$1"
    read -p "$message (yes/no): " response
    if [[ "$response" != "yes" ]]; then
        log_info "Cancelled by user"
        exit 0
    fi
}

print_banner() {
    cat << 'EOF'
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║              GABI Data Migration: Local → Fly.io                 ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
EOF
    echo ""
    echo "Configuration:"
    echo "  Source PG: ${SOURCE_PG_URL:-<not set>}"
    echo "  Target PG: ${TARGET_PG_URL:-<not set>}"
    echo "  Target ES: ${TARGET_ES_URL:-<not set>}"
    echo "  Log file: $MIGRATION_LOG"
    echo ""
}

print_summary() {
    echo ""
    echo "=========================================="
    echo "Migration Summary"
    echo "=========================================="
    for phase in "${!PHASE_STATUS[@]}"; do
        local status="${PHASE_STATUS[$phase]}"
        local color="$GREEN"
        if [[ "$status" == "FAILED" ]]; then
            color="$RED"
        elif [[ "$status" == "SKIPPED" ]]; then
            color="$YELLOW"
        fi
        printf "  %-30s %b%s%b\n" "$phase" "$color" "$status" "$NC"
    done
    echo "=========================================="
    echo "Log file: $MIGRATION_LOG"
}

# Phase 1: Pre-flight
check_phase() {
    start_phase "PRE-FLIGHT CHECKS"
    
    log_step "Running pre-flight checks..."
    if ! bash "$SCRIPT_DIR/01_preflight_checks.sh"; then
        log_error "Pre-flight checks failed!"
        end_phase "PRE-FLIGHT CHECKS" "FAILED"
        return 1
    fi
    
    end_phase "PRE-FLIGHT CHECKS" "SUCCESS"
}

# Phase 2: Backup
backup_phase() {
    start_phase "LOCAL BACKUP"
    
    confirm "Create local backup? This may take 30-60 minutes."
    
    log_step "Creating local backup..."
    if ! bash "$SCRIPT_DIR/02_backup_local.sh"; then
        log_error "Backup failed!"
        end_phase "LOCAL BACKUP" "FAILED"
        return 1
    fi
    
    end_phase "LOCAL BACKUP" "SUCCESS"
}

# Phase 3: PostgreSQL Migration
postgres_phase() {
    start_phase "POSTGRESQL MIGRATION"
    
    if [[ -z "${TARGET_PG_URL:-}" ]]; then
        log_error "TARGET_PG_URL not set!"
        end_phase "POSTGRESQL MIGRATION" "FAILED"
        return 1
    fi
    
    confirm "Migrate PostgreSQL data? This will transfer data to Fly.io."
    
    log_step "Migrating PostgreSQL..."
    if ! bash "$SCRIPT_DIR/03_migrate_postgres.sh"; then
        log_error "PostgreSQL migration failed!"
        end_phase "POSTGRESQL MIGRATION" "FAILED"
        return 1
    fi
    
    end_phase "POSTGRESQL MIGRATION" "SUCCESS"
}

# Phase 4: Elasticsearch Migration
elasticsearch_phase() {
    start_phase "ELASTICSEARCH MIGRATION"
    
    if [[ -z "${TARGET_ES_URL:-}" ]]; then
        log_warn "TARGET_ES_URL not set, skipping ES migration"
        end_phase "ELASTICSEARCH MIGRATION" "SKIPPED"
        return 0
    fi
    
    confirm "Migrate Elasticsearch index? This will reindex documents."
    
    log_step "Migrating Elasticsearch..."
    if ! python3 "$SCRIPT_DIR/04_migrate_elasticsearch.py"; then
        log_error "Elasticsearch migration failed!"
        end_phase "ELASTICSEARCH MIGRATION" "FAILED"
        return 1
    fi
    
    end_phase "ELASTICSEARCH MIGRATION" "SUCCESS"
}

# Phase 5: Validation
validation_phase() {
    start_phase "VALIDATION"
    
    log_step "Running validation..."
    if ! python3 "$SCRIPT_DIR/05_validate_migration.py"; then
        log_warn "Validation found issues!"
        confirm "Continue anyway?"
    fi
    
    end_phase "VALIDATION" "SUCCESS"
}

# Phase 6: Cutover
cutover_phase() {
    start_phase "CUTOVER"
    
    confirm "Proceed with production cutover? This will switch live traffic!"
    
    log_step "Executing cutover..."
    if ! bash "$SCRIPT_DIR/06_cutover.sh"; then
        log_error "Cutover failed!"
        end_phase "CUTOVER" "FAILED"
        return 1
    fi
    
    end_phase "CUTOVER" "SUCCESS"
}

# Main execution
main() {
    print_banner
    
    # Check if running in interactive mode
    if [[ -t 0 ]]; then
        confirm "Start full migration? This process will take several hours."
    else
        log_info "Non-interactive mode detected"
    fi
    
    START_TIME=$(date +%s)
    
    # Run phases
    check_phase || exit 1
    backup_phase || exit 1
    postgres_phase || exit 1
    elasticsearch_phase || exit 1
    validation_phase || exit 1
    cutover_phase || exit 1
    
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    
    print_summary
    
    echo ""
    log_info "Migration completed in $((DURATION / 3600))h $((DURATION % 3600 / 60))m"
    echo ""
    echo "Next steps:"
    echo "  1. Monitor application metrics"
    echo "  2. Run incremental sync if needed:"
    echo "     python3 $SCRIPT_DIR/07_incremental_sync.py"
    echo "  3. Schedule decommission of local infrastructure"
}

# Parse arguments
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat << EOF
GABI Migration Script

Usage: $0 [options]

Environment Variables:
  SOURCE_PG_URL    Source PostgreSQL URL (default: postgresql://localhost:5432/gabi)
  TARGET_PG_URL    Target PostgreSQL URL (required)
  TARGET_ES_URL    Target Elasticsearch URL (optional)
  FLY_APP_NAME     Fly.io app name (default: gabi-api)
  PARALLEL_JOBS    Parallel workers for pg_dump (default: 4)
  BATCH_SIZE       Batch size for ES indexing (default: 1000)

Options:
  --phase N        Run only specific phase (1-6)
  --skip-backup    Skip backup phase (use with caution)
  --dry-run        Show what would be done without executing
  --help, -h       Show this help

Phases:
  1. Pre-flight checks
  2. Local backup
  3. PostgreSQL migration
  4. Elasticsearch migration
  5. Validation
  6. Cutover

Examples:
  # Full migration
  TARGET_PG_URL=postgres://... TARGET_ES_URL=https://... $0

  # Run only phases 1 and 2
  $0 --phase 1 --phase 2

  # Skip backup (if already done)
  $0 --skip-backup

EOF
    exit 0
fi

# Handle phase selection
PHASES=""
SKIP_BACKUP=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --phase)
            PHASES="$PHASES $2"
            shift 2
            ;;
        --skip-backup)
            SKIP_BACKUP=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

if $DRY_RUN; then
    echo "DRY RUN MODE - No changes will be made"
    echo ""
    echo "Would execute:"
    echo "  1. Pre-flight checks"
    $SKIP_BACKUP || echo "  2. Local backup"
    echo "  3. PostgreSQL migration"
    [[ -n "${TARGET_ES_URL:-}" ]] && echo "  4. Elasticsearch migration"
    echo "  5. Validation"
    echo "  6. Cutover"
    exit 0
fi

if [[ -n "$PHASES" ]]; then
    # Run specific phases
    for phase in $PHASES; do
        case $phase in
            1) check_phase ;;
            2) backup_phase ;;
            3) postgres_phase ;;
            4) elasticsearch_phase ;;
            5) validation_phase ;;
            6) cutover_phase ;;
            *) echo "Invalid phase: $phase" ; exit 1 ;;
        esac
    done
    print_summary
else
    # Run full migration
    main
fi
