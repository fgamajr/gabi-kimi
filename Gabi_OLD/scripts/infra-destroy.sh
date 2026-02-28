#!/bin/bash
# GABI - Destroy infrastructure (containers + volumes; all data lost)
# Usage: ./scripts/infra-destroy.sh

set -e
# shellcheck source=scripts/_lib.sh
source "$(dirname "$0")/_lib.sh"

log_error "⚠️  WARNING: DESTRUCTIVE OPERATION"
echo ""
echo "This will:"
echo "  • Stop all containers"
echo "  • Delete all Docker volumes"
echo "  • 🗑️  Permanently delete all database data"
echo ""
echo "There is NO undo."
echo ""

read -p "Type DESTROY to confirm: " CONFIRM
echo ""

if [ "$CONFIRM" != "DESTROY" ]; then
    log_warn "Cancelled. Nothing was destroyed."
    exit 0
fi

log_error "Destroying infrastructure..."
echo ""

log_warn "Stopping applications (if running)..."
pkill -f "Gabi.Api" 2>/dev/null || true
sleep 1

log_warn "Removing containers and volumes..."
docker compose down -v --remove-orphans

echo ""
log_ok "Infrastructure destroyed."
echo ""
echo "All data has been deleted."
echo "Run ./scripts/setup.sh to start fresh."
echo ""
