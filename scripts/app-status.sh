#!/bin/bash
# GABI - Check Application Status
# Usage: ./scripts/app-status.sh

source "$(dirname "$0")/_lib.sh"

log_info "📊 Application Status"
echo ""

# Check API
API_PID=$(pgrep -f "Gabi.Api" | head -1 || echo "")
if [ -n "$API_PID" ]; then
    API_HEALTH=$(curl -sf --max-time 3 http://localhost:5100/health 2>/dev/null || echo "")
    if [ "$API_HEALTH" = "Healthy" ]; then
        log_ok "  API     ✅ Running (PID: $API_PID) - Healthy"
    else
        log_warn "  API     ⚠️  Running (PID: $API_PID) - Not responding"
    fi
else
    log_error "  API     ❌ Not running"
fi

# Check Web
WEB_PID=$(pgrep -f "vite" | head -1 || echo "")
if [ -n "$WEB_PID" ]; then
    WEB_RESP=$(curl -sf --max-time 3 -o /dev/null -w "%{http_code}" http://localhost:3000 2>/dev/null || echo "000")
    if [ "$WEB_RESP" = "200" ] || [ "$WEB_RESP" = "000" ]; then
        log_ok "  Web     ✅ Running (PID: $WEB_PID)"
    else
        log_warn "  Web     ⚠️  Running (PID: $WEB_PID) - HTTP $WEB_RESP"
    fi
else
    log_error "  Web     ❌ Not running"
fi

# Check Infrastructure
echo ""
log_info "🐳 Infrastructure Status"
if infra_is_running; then
    log_ok "  PostgreSQL   ✅"
    log_ok "  Elasticsearch ✅"
    log_ok "  Redis        ✅"
else
    log_error "  Infrastructure ❌ Not running"
    echo "   Run: ./scripts/infra-up.sh"
fi

echo ""
