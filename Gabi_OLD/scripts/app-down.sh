#!/bin/bash
# GABI - Stop backend application (API)
# Usage: ./scripts/app-down.sh

source "$(dirname "$0")/_lib.sh"
log_info "🛑 GABI - Stopping applications"
echo ""
STOPPED=0
if pgrep -f "Gabi.Api" >/dev/null; then
    log_warn "Stopping API..."; pkill -f "Gabi.Api" 2>/dev/null || true
    log_ok "  API stopped"; STOPPED=1
fi
[ $STOPPED -eq 0 ] && log_warn "No applications running."
echo ""
log_ok "Done. Infrastructure still up; stop with ./scripts/infra-down.sh"
echo ""
