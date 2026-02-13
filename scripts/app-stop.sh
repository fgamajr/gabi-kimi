#!/bin/bash
# GABI - Stop Applications (background mode)
# Usage: ./scripts/app-stop.sh

source "$(dirname "$0")/_lib.sh"

log_info "🛑 Stopping applications"
echo ""

STOPPED=0

# Stop API — try PID file first, then pgrep
API_PID=""
if [ -f "$GABI_LOG_DIR/api.pid" ]; then
    API_PID=$(cat "$GABI_LOG_DIR/api.pid" 2>/dev/null)
    # Verify it's still a valid process
    if [ -n "$API_PID" ] && ! kill -0 "$API_PID" 2>/dev/null; then
        API_PID=""
    fi
fi
[ -z "$API_PID" ] && API_PID=$(pgrep -f "Gabi.Api" | head -1 || echo "")

if [ -n "$API_PID" ]; then
    log_warn "  Stopping API (PID: $API_PID)..."
    kill "$API_PID" 2>/dev/null || true
    sleep 2
    # Force kill if still running
    if pgrep -f "Gabi.Api" >/dev/null 2>&1; then
        pkill -9 -f "Gabi.Api" 2>/dev/null || true
    fi
    rm -f "$GABI_LOG_DIR/api.pid"
    log_ok "  API stopped"
    STOPPED=$((STOPPED + 1))
else
    rm -f "$GABI_LOG_DIR/api.pid"
    echo "  API: not running"
fi

# Stop Web — try PID file first, then pgrep
WEB_PID=""
if [ -f "$GABI_LOG_DIR/web.pid" ]; then
    WEB_PID=$(cat "$GABI_LOG_DIR/web.pid" 2>/dev/null)
    if [ -n "$WEB_PID" ] && ! kill -0 "$WEB_PID" 2>/dev/null; then
        WEB_PID=""
    fi
fi
[ -z "$WEB_PID" ] && WEB_PID=$(pgrep -f "vite" | head -1 || echo "")

if [ -n "$WEB_PID" ]; then
    log_warn "  Stopping Web (PID: $WEB_PID)..."
    kill "$WEB_PID" 2>/dev/null || true
    sleep 2
    # Force kill if still running
    if pgrep -f "vite" >/dev/null 2>&1; then
        pkill -9 -f "vite" 2>/dev/null || true
    fi
    rm -f "$GABI_LOG_DIR/web.pid"
    log_ok "  Web stopped"
    STOPPED=$((STOPPED + 1))
else
    rm -f "$GABI_LOG_DIR/web.pid"
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
