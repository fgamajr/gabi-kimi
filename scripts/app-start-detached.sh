#!/bin/bash
# GABI - Start Applications in Background (detached mode)
# Usage: ./scripts/app-start-detached.sh
# Non-blocking - apps run in background, use app-status.sh to check, app-stop.sh to stop

set -e
source "$(dirname "$0")/_lib.sh"

mkdir -p "$GABI_LOG_DIR"

log_info "🚀 Starting applications in background"
echo ""

# Check dependencies
require_app_deps
echo ""

# Check infrastructure
if ! infra_is_running; then
    log_error "Infrastructure not running. Run: ./scripts/infra-up.sh"
    exit 1
fi

# Clean old processes
log_warn "Cleaning old processes..."
pkill -f "Gabi.Api" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true
sleep 2

# Start API (stdbuf unbuffers stdout so logs flush in real-time)
log_info "Starting API (http://localhost:5100)..."
if command -v stdbuf >/dev/null 2>&1; then
    nohup stdbuf -oL dotnet run --project "$GABI_API_PROJECT" --urls "http://localhost:5100" > "$GABI_LOG_DIR/api.log" 2>&1 &
else
    nohup dotnet run --project "$GABI_API_PROJECT" --urls "http://localhost:5100" > "$GABI_LOG_DIR/api.log" 2>&1 &
fi
API_PID=$!
echo "$API_PID" > "$GABI_LOG_DIR/api.pid"
echo "  PID: $API_PID (saved to $GABI_LOG_DIR/api.pid)"

# Wait for API health
echo -n "  Waiting for API"
for i in $(seq 1 30); do
    if curl -sf --max-time 2 http://localhost:5100/health >/dev/null 2>&1; then
        echo -e " ${GABI_GREEN}✅ Ready${GABI_NC}"
        break
    fi
    echo -n "."
    sleep 1
done

if ! curl -sf --max-time 2 http://localhost:5100/health >/dev/null 2>&1; then
    echo -e " ${GABI_RED}❌ Failed${GABI_NC}"
    log_error "API failed to start. Check: tail -f $GABI_LOG_DIR/api.log"
    exit 1
fi

# Start Web
log_info "Starting Web (http://localhost:3000)..."
cd "$GABI_WEB_DIR"
nohup npm run dev > "$GABI_LOG_DIR/web.log" 2>&1 &
WEB_PID=$!
cd "$GABI_ROOT"
echo "$WEB_PID" > "$GABI_LOG_DIR/web.pid"
echo "  PID: $WEB_PID (saved to $GABI_LOG_DIR/web.pid)"

# Wait for Web
echo -n "  Waiting for Web"
for i in $(seq 1 45); do
    if curl -sf --max-time 2 http://localhost:3000 >/dev/null 2>&1; then
        echo -e " ${GABI_GREEN}✅ Ready${GABI_NC}"
        break
    fi
    echo -n "."
    sleep 1
done

if ! curl -sf --max-time 2 http://localhost:3000 >/dev/null 2>&1; then
    echo -e " ${GABI_YELLOW}...${GABI_NC}"
    log_warn "Web still starting (may take longer on first run)"
fi

echo ""
log_ok "✨ Applications started in background!"
echo ""
echo "┌──────────────────────────────────────────────┐"
echo "│  🌐 URLs:                                    │"
echo "│     • Web:     http://localhost:3000         │"
echo "│     • API:     http://localhost:5100         │"
echo "│     • Swagger: http://localhost:5100/swagger │"
echo "│                                              │"
echo "│  📊 Status:  ./scripts/dev app status        │"
echo "│  🛑 Stop:    ./scripts/dev app stop          │"
echo "│  📝 Logs:    ./scripts/dev app logs          │"
echo "└──────────────────────────────────────────────┘"
echo ""
