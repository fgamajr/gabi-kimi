#!/bin/bash
# GABI - One-time development setup (run once after clone)
# Usage: ./scripts/setup.sh

set -e
# shellcheck source=scripts/_lib.sh
source "$(dirname "$0")/_lib.sh"

log_info "🚀 GABI - Development setup"
echo ""

log_warn "Checking dependencies..."
echo ""
require_setup_deps
echo ""

log_warn "Installing EF Core CLI (global tool)..."
if dotnet tool list -g 2>/dev/null | grep -q dotnet-ef; then
    log_ok "  EF Core CLI already installed"
else
    dotnet tool install --global dotnet-ef
    log_ok "  EF Core CLI installed"
fi
echo ""

log_warn "Starting infrastructure..."
"$GABI_SCRIPTS/infra-up.sh"
echo ""

log_warn "Setting up database..."
if [ -d "$GABI_POSTGRES_PROJECT/Migrations" ] && [ -n "$(ls -A "$GABI_POSTGRES_PROJECT"/Migrations/*.cs 2>/dev/null)" ]; then
    dotnet ef database update \
        --project "$GABI_POSTGRES_PROJECT" \
        --startup-project "$GABI_API_PROJECT" 2>&1 | grep -E "(Applying migration|Done|Already up)" || true
    log_ok "  Database ready"
else
    log_warn "  No migrations found yet."
    echo "     After adding entities: ./scripts/db-migrate.sh create InitialCreate"
    echo "     Then: ./scripts/db-migrate.sh apply"
fi
echo ""

echo ""
log_ok "✨ Setup complete!"
echo ""
echo "Next: ./scripts/app-up.sh   or   ./scripts/dev app up"
echo ""
