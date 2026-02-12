#!/bin/bash
# GABI Celery Worker Monitor
# Runs for 10 minutes, checking every 15 seconds

INTERVAL=15
DURATION=600  # 10 minutes in seconds
ITERATIONS=$((DURATION / INTERVAL))
ALERT_COUNT=0
LOG_FILE="/home/fgamajr/dev/gabi-kimi/logs/celery_monitor_$(date +%Y%m%d_%H%M%S).log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo -e "$1" | tee -a "$LOG_FILE"
}

log "=========================================="
log "GABI Celery Worker Monitor"
log "Started: $(date '+%Y-%m-%d %H:%M:%S')"
log "Duration: 10 minutes | Interval: ${INTERVAL}s"
log "Log file: $LOG_FILE"
log "=========================================="
log ""

# Function to check queue depth via Redis
get_queue_depth() {
    local queue=$1
    local redis_url="${GABI_REDIS_URL:-redis://localhost:6379/0}"
    
    # Extract host and db from URL
    local host=$(echo "$redis_url" | sed -n 's|redis://\([^:]*\).*||p')
    local port=$(echo "$redis_url" | sed -n 's|redis://[^:]*:\([0-9]*\).*||p')
    local db=$(echo "$redis_url" | sed -n 's|.*/\([0-9]*\)$|\1|p')
    
    [ -z "$host" ] && host="localhost"
    [ -z "$port" ] && port="6379"
    [ -z "$db" ] && db="0"
    
    redis-cli -h "$host" -p "$port" -n "$db" LLEN "celery" 2>/dev/null || echo "N/A"
}

get_redis_queue_lengths() {
    local redis_url="${GABI_REDIS_URL:-redis://localhost:6379/0}"
    local host=$(echo "$redis_url" | sed -n 's|redis://\([^:]*\).*||p')
    local port=$(echo "$redis_url" | sed -n 's|redis://[^:]*:\([0-9]*\).*||p')
    local db=$(echo "$redis_url" | sed -n 's|.*/\([0-9]*\)$|\1|p')
    
    [ -z "$host" ] && host="localhost"
    [ -z "$port" ] && port="6379"
    [ -z "$db" ] && db="0"
    
    local queues=("gabi.default" "gabi.sync" "gabi.sync.high" "gabi.sync.normal" "gabi.sync.bulk" "gabi.dlq" "gabi.health" "gabi.alerts")
    
    log "  📊 Queue Depths:"
    for queue in "${queues[@]}"; do
        local len=$(redis-cli -h "$host" -p "$port" -n "$db" LLEN "$queue" 2>/dev/null || echo "?")
        if [ "$len" != "0" ] && [ "$len" != "?" ]; then
            log "     • $queue: ${YELLOW}$len${NC}"
        else
            log "     • $queue: $len"
        fi
    done
}

# Main monitoring loop
for ((i=1; i<=ITERATIONS; i++)); do
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
    ELAPSED=$((i * INTERVAL))
    ELAPSED_MIN=$((ELAPSED / 60))
    ELAPSED_SEC=$((ELAPSED % 60))
    
    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log "⏱️  [$TIMESTAMP] Check #${i}/${ITERATIONS} (${ELAPSED_MIN}m${ELAPSED_SEC}s elapsed)"
    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # 1. Check if Celery is running
    CELERY_PROCS=$(ps aux | grep celery | grep -v grep)
    CELERY_COUNT=$(pgrep -c celery 2>/dev/null || echo "0")
    
    if [ -z "$CELERY_PROCS" ] || [ "$CELERY_COUNT" -eq 0 ]; then
        log "${RED}🚨 ALERT: Celery is NOT running!${NC}"
        ((ALERT_COUNT++))
    else
        log "${GREEN}✅ Celery is running${NC} ($CELERY_COUNT processes)"
        
        # Show process details
        log "  📝 Process Details:"
        echo "$CELERY_PROCS" | while read -r line; do
            log "     $(echo "$line" | awk '{print $11, $12, $13}' | head -c 80)"
        done
    fi
    
    # 2. Process count
    log "  🔢 Process Count: $CELERY_COUNT"
    
    # 3. Resource usage (main worker process)
    MAIN_PID=$(pgrep -f 'celery worker' 2>/dev/null | head -1)
    if [ -n "$MAIN_PID" ]; then
        RESOURCE_INFO=$(ps -o pid,ppid,%cpu,%mem,etime,comm -p "$MAIN_PID" 2>/dev/null | tail -1)
        if [ -n "$RESOURCE_INFO" ]; then
            log "  📈 Resource Usage (PID $MAIN_PID):"
            log "     CPU% | MEM% | Elapsed"
            CPU=$(echo "$RESOURCE_INFO" | awk '{print $3}')
            MEM=$(echo "$RESOURCE_INFO" | awk '{print $4}')
            ETIME=$(echo "$RESOURCE_INFO" | awk '{print $5}')
            
            # Color code high usage
            if (( $(echo "$CPU > 80" | bc -l 2>/dev/null || echo "0") )); then
                CPU_STR="${RED}${CPU}%${NC}"
            else
                CPU_STR="${GREEN}${CPU}%${NC}"
            fi
            
            if (( $(echo "$MEM > 50" | bc -l 2>/dev/null || echo "0") )); then
                MEM_STR="${RED}${MEM}%${NC}"
            else
                MEM_STR="${GREEN}${MEM}%${NC}"
            fi
            
            log "     $CPU_STR | $MEM_STR | $ETIME"
        fi
    else
        log "  ⚠️  No main Celery worker process found"
    fi
    
    # 4. Queue depth check
    get_redis_queue_lengths
    
    # Summary line
    if [ "$CELERY_COUNT" -gt 0 ]; then
        log "  ✅ Status: HEALTHY ($CELERY_COUNT workers)"
    else
        log "  ❌ Status: DOWN"
    fi
    
    # Sleep if not last iteration
    if [ $i -lt $ITERATIONS ]; then
        sleep $INTERVAL
    fi
done

# Final summary
log ""
log "=========================================="
log "📊 MONITORING COMPLETE"
log "Finished: $(date '+%Y-%m-%d %H:%M:%S')"
log "Total Alerts: $ALERT_COUNT"
log "Log saved to: $LOG_FILE"
log "=========================================="

exit 0
