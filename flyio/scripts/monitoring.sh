#!/bin/bash
# =============================================================================
# GABI Fly.io Monitoring & Operations
# Health checks, logs, and metrics
# =============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log() { echo -e "${BLUE}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
info() { echo -e "${CYAN}[DATA]${NC} $1"; }

# Health check all services
health_check() {
    log "Health Check"
    log "============"
    echo ""
    
    local apps=("gabi-api" "gabi-mcp")
    local failed=0
    
    for app in "${apps[@]}"; do
        local url="https://${app}.fly.dev/health"
        local status
        status=$(curl -sf "$url" 2>/dev/null && echo "HEALTHY" || echo "UNHEALTHY")
        
        if [ "$status" = "HEALTHY" ]; then
            success "$app: $status"
        else
            error "$app: $status"
            failed=$((failed + 1))
        fi
    done
    
    # Check worker status
    local worker_status
    worker_status=$(fly status --app gabi-worker 2>/dev/null | grep -c "running" || echo "0")
    if [ "$worker_status" -gt 0 ]; then
        success "gabi-worker: RUNNING ($worker_status machines)"
    else
        warn "gabi-worker: STOPPED or no machines"
    fi
    
    echo ""
    if [ $failed -eq 0 ]; then
        success "All services healthy"
    else
        error "$failed service(s) unhealthy"
    fi
}

# Show service status
show_status() {
    log "Service Status"
    log "=============="
    echo ""
    
    for app in gabi-api gabi-mcp gabi-worker; do
        echo "--- $app ---"
        fly status --app "$app" 2>/dev/null || warn "Could not get status for $app"
        echo ""
    done
}

# Show logs
show_logs() {
    local app=${1:-gabi-api}
    local lines=${2:-50}
    
    log "Showing last $lines lines for $app..."
    fly logs --app "$app" --tail "$lines"
}

# Show metrics
show_metrics() {
    log "Metrics Summary"
    log "==============="
    echo ""
    
    for app in gabi-api gabi-mcp; do
        log "$app Metrics:"
        
        # Try to get Prometheus metrics
        local metrics
        metrics=$(curl -sf "https://${app}.fly.dev/metrics" 2>/dev/null | head -20 || echo "No metrics available")
        
        echo "$metrics"
        echo ""
    done
    
    log "For detailed metrics, use: fly metrics --app <app>"
}

# Database stats
show_db_stats() {
    log "Database Statistics"
    log "==================="
    echo ""
    
    fly ssh console --app gabi-db --command "psql -c \"\nSELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
LIMIT 10;\""
}

# Redis stats
show_redis_stats() {
    log "Redis Statistics"
    log "================"
    echo ""
    
    # Get Redis URL from secrets
    local redis_url
    redis_url=$(fly secrets list --app gabi-api | grep REDIS_URL | awk '{print $2}')
    
    if [ -z "$redis_url" ]; then
        warn "Could not get Redis URL"
        return
    fi
    
    log "Redis connection info:"
    echo "URL: ${redis_url//:*@/:***@}"  # Hide password
    
    log "For detailed Redis stats, use Upstash dashboard"
}

# Performance test
performance_test() {
    log "Performance Test"
    log "================"
    echo ""
    
    local url="https://gabi-api.fly.dev"
    local concurrent=${1:-10}
    local requests=${2:-100}
    
    log "Testing with $concurrent concurrent users, $requests total requests"
    
    # Check if ab (Apache Bench) is available
    if command -v ab >/dev/null 2>&1; then
        ab -n "$requests" -c "$concurrent" "${url}/health"
    else
        # Simple curl test
        log "Running simple curl test..."
        for i in $(seq 1 $requests); do
            curl -sf "${url}/health" > /dev/null && echo -n "." || echo -n "X"
            if [ $((i % 50)) -eq 0 ]; then
                echo " ($i/$requests)"
            fi
        done
        echo ""
        success "Test complete"
    fi
}

# Search test
search_test() {
    log "Search API Test"
    log "==============="
    echo ""
    
    local url="https://gabi-api.fly.dev/api/v1/search"
    local query=${1:-"licitação"}
    
    log "Testing search with query: '$query'"
    
    local result
    result=$(curl -sf -X POST "$url" \
        -H "Content-Type: application/json" \
        -d "{\"query\": \"$query\", \"limit\": 5}" 2>/dev/null || echo '{"error": "Request failed"}')
    
    echo "$result" | jq . 2>/dev/null || echo "$result"
}

# Interactive dashboard
dashboard() {
    while true; do
        clear
        log "GABI Fly.io Dashboard"
        log "====================="
        echo ""
        
        # Quick health summary
        health_check
        
        echo ""
        log "Quick Actions:"
        echo "  1) View full status"
        echo "  2) View API logs"
        echo "  3) View MCP logs"
        echo "  4) View Worker logs"
        echo "  5) Database stats"
        echo "  6) Performance test"
        echo "  7) Search test"
        echo "  r) Refresh"
        echo "  q) Quit"
        echo ""
        
        read -rt 5 -p "Select option (auto-refresh in 5s): " choice || true
        
        case $choice in
            1) show_status; read -rp "Press Enter..." ;;
            2) show_logs gabi-api 100; read -rp "Press Enter..." ;;
            3) show_logs gabi-mcp 100; read -rp "Press Enter..." ;;
            4) show_logs gabi-worker 100; read -rp "Press Enter..." ;;
            5) show_db_stats; read -rp "Press Enter..." ;;
            6) performance_test; read -rp "Press Enter..." ;;
            7) search_test; read -rp "Press Enter..." ;;
            r|"") continue ;;
            q) break ;;
            *) warn "Invalid option" ; sleep 1 ;;
        esac
    done
}

# Main menu
show_menu() {
    echo ""
    log "GABI Monitoring & Operations"
    log "============================"
    echo ""
    echo "1) Health check"
    echo "2) Service status"
    echo "3) View logs"
    echo "4) Show metrics"
    echo "5) Database stats"
    echo "6) Redis stats"
    echo "7) Performance test"
    echo "8) Search API test"
    echo "9) Dashboard (interactive)"
    echo "q) Quit"
    echo ""
}

main() {
    # If called with arguments, execute directly
    if [ $# -gt 0 ]; then
        case $1 in
            health) health_check ;;
            status) show_status ;;
            logs) show_logs "${2:-gabi-api}" "${3:-50}" ;;
            metrics) show_metrics ;;
            db) show_db_stats ;;
            redis) show_redis_stats ;;
            perf) performance_test "${2:-10}" "${3:-100}" ;;
            search) search_test "${2:-licitação}" ;;
            dashboard) dashboard ;;
            *) echo "Unknown command: $1" ;;
        esac
        return
    fi
    
    # Interactive mode
    while true; do
        show_menu
        read -rp "Select option: " choice
        
        case $choice in
            1) health_check ;;
            2) show_status ;;
            3) 
                read -rp "App name (gabi-api/gabi-mcp/gabi-worker): " app
                read -rp "Number of lines (default 50): " lines
                show_logs "${app:-gabi-api}" "${lines:-50}"
                ;;
            4) show_metrics ;;
            5) show_db_stats ;;
            6) show_redis_stats ;;
            7)
                read -rp "Concurrent users (default 10): " concurrent
                read -rp "Total requests (default 100): " requests
                performance_test "${concurrent:-10}" "${requests:-100}"
                ;;
            8)
                read -rp "Search query (default 'licitação'): " query
                search_test "${query:-licitação}"
                ;;
            9) dashboard ;;
            q|Q) log "Goodbye!"; exit 0 ;;
            *) warn "Invalid option" ;;
        esac
    done
}

main "$@"
