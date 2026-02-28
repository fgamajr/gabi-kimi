#!/bin/bash
# =============================================================================
# GABI Rollback Helper Script
# =============================================================================
# Usage: ./rollback.sh <command> <source_id> [options]
# =============================================================================

set -euo pipefail

# Configuration
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5433}"
DB_NAME="${DB_NAME:-gabi}"
DB_USER="${DB_USER:-postgres}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Help message
show_help() {
    cat << EOF
GABI Pipeline Rollback Helper

Usage: $0 <command> <source_id> [options]

Commands:
    check       Check current status of a source
    reset-job   Reset stuck jobs in job_registry
    reset-fetch Reset fetch phase (use --full for complete reset)
    reset-ingest Reset ingest phase (use --full for complete reset)
    nuclear     Full source reset (REQUIRES MANUAL COMMIT)
    validate    Validate rollback before restart

Options:
    --full      Full reset (for reset-fetch and reset-ingest)
    --host      Database host (default: localhost)
    --port      Database port (default: 5433)
    --db        Database name (default: gabi)
    --user      Database user (default: postgres)
    -h, --help  Show this help message

Examples:
    $0 check dou_publico
    $0 reset-fetch dou_publico
    $0 reset-fetch dou_publico --full
    $0 nuclear dou_publico
    $0 validate dou_publico

Environment Variables:
    DB_HOST     Database host
    DB_PORT     Database port
    DB_NAME     Database name
    DB_USER     Database user
    PGPASSWORD  Database password (if required)

EOF
}

# Log functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Build psql command
build_psql_cmd() {
    echo "psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME"
}

# Check prerequisites
check_prereqs() {
    if ! command -v psql &> /dev/null; then
        log_error "psql is not installed. Please install PostgreSQL client."
        exit 1
    fi
    
    if [[ $# -lt 2 ]]; then
        show_help
        exit 1
    fi
}

# Check source exists
check_source() {
    local source_id="$1"
    local psql_cmd
    psql_cmd=$(build_psql_cmd)
    
    local count
    count=$($psql_cmd -t -c "SELECT COUNT(*) FROM source_registry WHERE id = '$source_id';" 2>/dev/null || echo "0")
    
    if [[ $(echo "$count" | tr -d ' ') -eq 0 ]]; then
        log_error "Source '$source_id' not found in database."
        log_info "Available sources:"
        $psql_cmd -c "SELECT id, name FROM source_registry WHERE enabled = true ORDER BY id;"
        exit 1
    fi
    
    log_success "Source '$source_id' found."
}

# Execute SQL script
execute_sql() {
    local script="$1"
    local source_id="$2"
    local extra_vars="${3:-}"
    local psql_cmd
    psql_cmd=$(build_psql_cmd)
    
    log_info "Executing: $script"
    
    if [[ -n "$extra_vars" ]]; then
        $psql_cmd -f "$SCRIPT_DIR/$script" -v source_id="'$source_id'" $extra_vars
    else
        $psql_cmd -f "$SCRIPT_DIR/$script" -v source_id="'$source_id'"
    fi
}

# Main function
main() {
    local command=""
    local source_id=""
    local full_reset=""
    
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            check|reset-job|reset-fetch|reset-ingest|nuclear|validate)
                command="$1"
                shift
                ;;
            --full)
                full_reset="true"
                shift
                ;;
            --host)
                DB_HOST="$2"
                shift 2
                ;;
            --port)
                DB_PORT="$2"
                shift 2
                ;;
            --db)
                DB_NAME="$2"
                shift 2
                ;;
            --user)
                DB_USER="$2"
                shift 2
                ;;
            -h|--help)
                show_help
                exit 0
                ;;
            -*)
                log_error "Unknown option: $1"
                show_help
                exit 1
                ;;
            *)
                if [[ -z "$source_id" ]]; then
                    source_id="$1"
                fi
                shift
                ;;
        esac
    done
    
    # Validate required arguments
    if [[ -z "$command" ]] || [[ -z "$source_id" ]]; then
        show_help
        exit 1
    fi
    
    # Check prerequisites
    check_prereqs
    
    log_info "Database: $DB_USER@$DB_HOST:$DB_PORT/$DB_NAME"
    log_info "Command: $command"
    log_info "Source: $source_id"
    
    # Check source exists
    check_source "$source_id"
    
    # Execute command
    case $command in
        check)
            execute_sql "01_check_source_status.sql" "$source_id"
            ;;
        reset-job)
            execute_sql "02_reset_job_registry.sql" "$source_id"
            ;;
        reset-fetch)
            if [[ "$full_reset" == "true" ]]; then
                log_warning "Performing FULL fetch reset (all items will be reset to pending)"
                execute_sql "03_reset_fetch_phase.sql" "$source_id" "-v full_reset=true"
            else
                execute_sql "03_reset_fetch_phase.sql" "$source_id"
            fi
            ;;
        reset-ingest)
            if [[ "$full_reset" == "true" ]]; then
                log_warning "Performing FULL ingest reset (including completed documents)"
                execute_sql "04_reset_ingest_phase.sql" "$source_id" "-v include_completed=true"
            else
                execute_sql "04_reset_ingest_phase.sql" "$source_id"
            fi
            ;;
        nuclear)
            log_warning "⚠️  NUCLEAR RESET SELECTED ⚠️"
            log_warning "This will delete ALL data for source: $source_id"
            log_warning "You will need to manually COMMIT or ROLLBACK the transaction"
            echo ""
            read -p "Are you sure? Type 'yes' to continue: " confirm
            if [[ "$confirm" != "yes" ]]; then
                log_info "Operation cancelled."
                exit 0
            fi
            execute_sql "05_nuclear_reset.sql" "$source_id"
            ;;
        validate)
            execute_sql "06_validate_rollback.sql" "$source_id"
            ;;
        *)
            log_error "Unknown command: $command"
            show_help
            exit 1
            ;;
    esac
    
    log_success "Command completed: $command"
}

# Run main function
main "$@"
