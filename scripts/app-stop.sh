#!/bin/bash
# GABI - Stop Applications (background mode)
# Usage: ./scripts/app-stop.sh

source "$(dirname "$0")/_lib.sh"

log_info "🛑 Stopping applications"
echo ""

STOPPED=0

# Stop API
API_PID=$(pgrep -f "Gabi.Api" | head -1 || echo "")
if [ -n "$API_PID" ]; then
    log_warn "  Stopping API (PID: $API_PID)..."
    kill "$API_PID" 2>/dev/null || true
    sleep 2
    # Force kill if still running
    if pgrep -f "Gabi.Api" >/dev/null 2>&1; then
        pkill -9 -f "Gabi.Api" 2>/dev/null || true
    fi
    log_ok "  API stopped"
    STOPPED=$((STOPPED + 1))
else
    echo "  API: not running"
fi

# Stop Web
WEB_PID=$(pgrep -f "vite" | head -1 || echo "")
if [ -n "$WEB_PID" ]; then
    log_warn "  Stopping Web (PID: $WEB_PID)..."
    kill "$WEB_PID" 2>/dev/null || true
    sleep 2
    # Force kill if still running
    if pgrep -f "vite" >/dev/null 2>&1; then
        pkill -9 -f "vite" 2>/dev/null || true
    fi
    log_ok "  Web stopped"
    STOPPED=$((STOPPED + 1))
else
    echo "  Web: not running"
fi

if [ $STOPPED -eq 0 ]; then
    log_warn "No applications were running"
else
    echo ""
    log_ok "✨ Applications stopped ($STOPPED processes)"
fi

# Port status
echo ""
echo "Port status:"
lsof -i :5100 2>/dev/null && echo "  5100: in use" || echo "  5100: free"
lsof -i :3000 2>/dev/null && echo "  3000: in use" || echo "  3000: free"
