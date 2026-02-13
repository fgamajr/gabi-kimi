#!/bin/bash
# GABI - Database migration manager
# Usage: ./scripts/db-migrate.sh [apply|create|status|reset|help]

set -e
# shellcheck source=scripts/_lib.sh
source "$(dirname "$0")/_lib.sh"

show_help() {
    echo "GABI - Database migrations"
    echo ""
    echo "Usage:"
    echo "  ./scripts/db-migrate.sh apply              Apply pending migrations"
    echo "  ./scripts/db-migrate.sh create <Name>     Create new migration"
    echo "  ./scripts/db-migrate.sh status            List migrations"
    echo "  ./scripts/db-migrate.sh reset             Drop and re-apply (⚠️ destructive)"
    echo "  ./scripts/db-migrate.sh help              This help"
    echo ""
    echo "Examples:"
    echo "  ./scripts/db-migrate.sh create AddDocumentsTable"
    echo "  ./scripts/db-migrate.sh apply"
    echo ""
}

cmd_apply() {
    log_warn "Applying migrations..."
    if ! infra_is_running; then
        log_warn "Starting infrastructure first..."
        "$GABI_SCRIPTS/infra-up.sh"
    fi
    dotnet ef database update \
        --project "$GABI_POSTGRES_PROJECT" \
        --startup-project "$GABI_API_PROJECT"
    log_ok "Migrations applied"
}

cmd_create() {
    local name="$1"
    if [ -z "$name" ]; then
        log_error "Migration name required."
        echo "Usage: ./scripts/db-migrate.sh create AddTableName"
        exit 1
    fi
    log_warn "Creating migration: $name"
    dotnet ef migrations add "$name" \
        --project "$GABI_POSTGRES_PROJECT" \
        --startup-project "$GABI_API_PROJECT" \
        --output-dir Migrations
    echo ""
    log_ok "Migration created."
    echo "  Review: $GABI_POSTGRES_PROJECT/Migrations/"
    echo "  Apply:  ./scripts/db-migrate.sh apply"
    echo "  Commit: git add src/Gabi.Postgres/Migrations/"
}

cmd_status() {
    log_info "Migration status"
    echo ""
    dotnet ef migrations list \
        --project "$GABI_POSTGRES_PROJECT" \
        --startup-project "$GABI_API_PROJECT"
}

cmd_reset() {
    log_error "⚠️  This will drop the database and remove all data!"
    echo ""
    read -p "Type RESET to confirm: " CONFIRM
    echo ""
    if [ "$CONFIRM" != "RESET" ]; then
        log_warn "Cancelled."
        exit 0
    fi
    log_warn "Resetting database..."
    dotnet ef database update 0 \
        --project "$GABI_POSTGRES_PROJECT" \
        --startup-project "$GABI_API_PROJECT"
    log_ok "Database reset."
    echo ""
    echo "Run ./scripts/db-migrate.sh apply to re-apply migrations."
}

# Ensure dotnet exists for any command
if ! command -v dotnet >/dev/null 2>&1; then
    log_error ".NET SDK not found. Install: https://dotnet.microsoft.com/download"
    exit 1
fi

case "${1:-help}" in
    apply|up|update)  cmd_apply ;;
    create|new|add)   cmd_create "$2" ;;
    status|list|ls)  cmd_status ;;
    reset|down)      cmd_reset ;;
    help|--help|-h)  show_help ;;
    *)
        log_error "Unknown command: $1"
        show_help
        exit 1
        ;;
esac
