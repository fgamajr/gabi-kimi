#!/bin/bash
# GABI - Start backend application (API); blocks until Ctrl+C
# Usage: ./scripts/app-up.sh

set -e
source "$(dirname "$0")/_lib.sh"

mkdir -p "$GABI_LOG_DIR"
log_info "🚀 GABI - Starting applications"
echo ""
require_app_deps
echo ""
if ! infra_is_running; then
    log_warn "Infrastructure not running. Run: ./scripts/infra-up.sh"
    exit 1
fi

cleanup() {
    echo ""
    log_warn "Stopping API..."
    pkill -f "Gabi.Api" 2>/dev/null || true
    log_ok "API stopped"
    exit 0
}
trap cleanup INT TERM

log_warn "Cleaning old processes..."
pkill -f "Gabi.Api" 2>/dev/null || true
sleep 2

log_info "Starting API (http://localhost:5100)..."
dotnet run --project "$GABI_API_PROJECT" --urls "http://localhost:5100" > "$GABI_LOG_DIR/api.log" 2>&1 &
echo -n "   Waiting"
for i in $(seq 1 30); do
    if curl -sf --max-time 2 http://localhost:5100/health >/dev/null 2>&1; then echo -e " ${GABI_GREEN}OK${GABI_NC}"; break; fi
    echo -n "."; sleep 1
done
if ! curl -sf --max-time 2 http://localhost:5100/health >/dev/null 2>&1; then
    echo -e " ${GABI_RED}FAIL${GABI_NC}"
    log_error "API failed. Check: tail -f $GABI_LOG_DIR/api.log"
    exit 1
fi

echo ""
log_ok "API running!"
echo "  API: http://localhost:5100"
echo "  Logs: ./scripts/app-logs.sh   Stop: Ctrl+C or ./scripts/app-down.sh"
echo ""
wait
