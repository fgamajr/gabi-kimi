#!/bin/bash

# GABI Crash Alerting System
# Monitors containers and processes every 15 seconds for 10 minutes
# Alerts immediately on any failures

set -e

ALERT_LOG="/home/fgamajr/dev/gabi-kimi/logs/crash_alerts.log"
mkdir -p "$(dirname "$ALERT_LOG")"

# Colors for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Alert function
alert() {
    local message="$1"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local alert_msg="🚨 ALERT [$timestamp] $message"
    
    # Print to terminal
    echo -e "${RED}${alert_msg}${NC}"
    
    # Log to file
    echo "$alert_msg" >> "$ALERT_LOG"
    
    # Optional: Send notification (uncomment if needed)
    # notify-send "GABI CRASH ALERT" "$message" 2>/dev/null || true
}

# Info function
info() {
    local message="$1"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${GREEN}[$timestamp]${NC} $message"
}

# Warning function
warn() {
    local message="$1"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${YELLOW}[$timestamp] WARNING: $message${NC}"
}

# Check container status
check_containers() {
    local missing=()
    
    # Get running container names
    local running_containers
    running_containers=$(docker ps --format "{{.Names}}" 2>/dev/null || echo "")
    
    # Required containers
    local required=("gabi-postgres" "gabi-elasticsearch" "gabi-redis" "gabi-tei")
    
    for container in "${required[@]}"; do
        if ! echo "$running_containers" | grep -q "^${container}$"; then
            missing+=("$container")
        fi
    done
    
    if [ ${#missing[@]} -gt 0 ]; then
        alert "CONTAINER(S) DOWN: ${missing[*]}"
        return 1
    fi
    
    return 0
}

# Check API process
check_api() {
    if ! pgrep -f "uvicorn" >/dev/null 2>&1; then
        alert "API PROCESS DOWN: uvicorn not running"
        return 1
    fi
    return 0
}

# Check Celery process
check_celery() {
    if ! pgrep -f "celery" >/dev/null 2>&1; then
        alert "CELERY PROCESS DOWN: celery not running"
        return 1
    fi
    return 0
}

# Main monitoring loop
main() {
    local duration_minutes=10
    local interval_seconds=15
    local iterations=$(( (duration_minutes * 60) / interval_seconds ))
    local current=0
    
    info "=========================================="
    info "GABI CRASH ALERTING SYSTEM STARTED"
    info "Duration: ${duration_minutes} minutes"
    info "Interval: ${interval_seconds} seconds"
    info "Iterations: ${iterations}"
    info "Alert log: ${ALERT_LOG}"
    info "=========================================="
    
    # Clear previous alert log
    echo "=== GABI Crash Alerts - $(date) ===" > "$ALERT_LOG"
    
    while [ $current -lt $iterations ]; do
        current=$((current + 1))
        local timestamp=$(date '+%H:%M:%S')
        
        echo ""
        info "--- Check #${current}/${iterations} at ${timestamp} ---"
        
        # Check all components
        local all_ok=true
        
        # Check containers
        if check_containers; then
            echo "  ✓ All containers running"
        else
            all_ok=false
        fi
        
        # Check API
        if check_api; then
            echo "  ✓ API (uvicorn) running"
        else
            all_ok=false
        fi
        
        # Check Celery
        if check_celery; then
            echo "  ✓ Celery running"
        else
            all_ok=false
        fi
        
        if $all_ok; then
            echo "  $(echo -e ${GREEN})[STATUS: ALL OK]${NC}"
        else
            echo "  $(echo -e ${RED})[STATUS: ALERTS TRIGGERED]${NC}"
        fi
        
        # Sleep unless this is the last iteration
        if [ $current -lt $iterations ]; then
            sleep $interval_seconds
        fi
    done
    
    echo ""
    info "=========================================="
    info "MONITORING COMPLETE"
    info "Total checks: ${iterations}"
    info "Alert log: ${ALERT_LOG}"
    info "=========================================="
}

# Trap to handle exit
trap 'echo -e "\n${YELLOW}Monitoring stopped by user${NC}"; exit 130' INT TERM

# Run main function
main "$@"
