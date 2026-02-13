#!/bin/bash
# GABI - Start applications (API + Web); blocks until Ctrl+C
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
    log_warn "Stopping applications..."
    pkill -f "Gabi.Api" 2>/dev/null || true
    pkill -f "vite" 2>/dev/null || true
    log_ok "Applications stopped"
    exit 0
}
trap cleanup INT TERM

log_warn "Cleaning old processes..."
pkill -f "Gabi.Api" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true
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

log_info "Starting Web (http://localhost:3000)..."
[ ! -d "$GABI_WEB_DIR" ] && { log_error "Web dir missing: $GABI_WEB_DIR"; exit 1; }
cd "$GABI_WEB_DIR"
npm run dev > "$GABI_LOG_DIR/web.log" 2>&1 &
cd "$GABI_ROOT"
echo -n "   Waiting"
for i in $(seq 1 45); do
    if curl -sf --max-time 2 http://localhost:3000 >/dev/null 2>&1; then echo -e " ${GABI_GREEN}OK${GABI_NC}"; break; fi
    echo -n "."; sleep 1
done
if ! curl -sf --max-time 2 http://localhost:3000 >/dev/null 2>&1; then
    echo -e " ${GABI_YELLOW}...${GABI_NC}"
    log_warn "Web still starting. tail -f $GABI_LOG_DIR/web.log"
fi

echo ""
log_ok "Applications running!"
echo "  Web: http://localhost:3000  API: http://localhost:5100"
echo "  Logs: ./scripts/app-logs.sh   Stop: Ctrl+C or ./scripts/app-down.sh"
echo ""
wait
