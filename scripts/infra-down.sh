#!/bin/bash
# GABI - Stop infrastructure (containers only; volumes preserved)
# Usage: ./scripts/infra-down.sh

set -e
# shellcheck source=scripts/_lib.sh
source "$(dirname "$0")/_lib.sh"

log_info "🐳 GABI - Stopping infrastructure"
echo ""

if ! docker compose ps 2>/dev/null | grep -q "running"; then
    log_warn "No containers running."
    exit 0
fi

log_warn "Stopping containers..."
docker compose down

echo ""
log_ok "Infrastructure stopped."
echo ""
echo "💾 Data preserved in Docker volumes."
echo ""
echo "To remove data as well: ./scripts/infra-destroy.sh  # ⚠️ Destructive"
echo ""
