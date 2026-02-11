#!/bin/bash
# GABI Ingestion Alerting System
# Monitors ingestion process for failures
# Runs for 10 minutes, checking every 20 seconds

PROJECT_DIR="/home/fgamajr/dev/gabi-kimi"
LOG_DIR="$PROJECT_DIR/logs"
DB_URL="postgresql://gabi:gabi_dev_password@localhost:5433/gabi"

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Alert counter
ALERT_COUNT=0
LAST_DOC_COUNT=-1
WAS_RUNNING=0
WAS_CELERY_RUNNING=0
ITERATION=0
MAX_ITERATIONS=30  # 10 minutes = 30 * 20 seconds

echo "=========================================="
echo "GABI Ingestion Alerting System"
echo "Started at: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Duration: 10 minutes (checking every 20s)"
echo "=========================================="
echo ""

# Function to check if ingestion CLI process is alive
check_process() {
    local count
    count=$(ps aux | grep 'gabi.cli ingest' | grep -v grep | wc -l)
    if [ "$count" -eq 0 ]; then
        echo "0"
    else
        echo "1"
    fi
}

# Function to check if Celery workers are alive
check_celery() {
    local count
    count=$(ps aux | grep 'celery.*gabi.worker' | grep -v grep | wc -l)
    if [ "$count" -eq 0 ]; then
        echo "0"
    else
        echo "$count"
    fi
}

# Function to check logs for errors
check_logs() {
    local latest_log
    local errors
    
    latest_log=$(ls -t "$LOG_DIR"/ingestion_*.log 2>/dev/null | head -1)
    
    if [ -z "$latest_log" ]; then
        echo ""
        return
    fi
    
    errors=$(tail -50 "$latest_log" 2>/dev/null | grep -iE "killed|error.*ingest|failed|fatal" | tail -3)
    
    if [ -n "$errors" ]; then
        echo "$errors"
    else
        echo ""
    fi
}

# Function to get document count from PostgreSQL
get_doc_count() {
    local count
    count=$(psql "$DB_URL" -t -c "SELECT COUNT(*) FROM documents WHERE is_deleted = false;" 2>/dev/null | tr -d ' \n' || echo "")
    if [ -z "$count" ]; then
        echo "0"
    else
        echo "$count"
    fi
}

# Function to send alert
send_alert() {
    local alert_type="$1"
    local details="$2"
    
    ALERT_COUNT=$((ALERT_COUNT + 1))
    
    echo ""
    echo -e "${RED}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║                    🚨 ALERT #$ALERT_COUNT 🚨                    ║${NC}"
    echo -e "${RED}╠════════════════════════════════════════════════════════════╣${NC}"
    printf "${RED}║ Type: %-52s ║${NC}\n" "$alert_type"
    printf "${RED}║ Time: %-52s ║${NC}\n" "$(date '+%Y-%m-%d %H:%M:%S')"
    echo -e "${RED}╠════════════════════════════════════════════════════════════╣${NC}"
    echo -e "${RED}║ Details:${NC}"
    echo -e "$details" | while IFS= read -r line; do
        printf "${RED}║${NC}  %-56s${RED}║${NC}\n" "$line"
    done
    echo -e "${RED}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

# Function to print status
print_status() {
    local process_status="$1"
    local celery_workers="$2"
    local doc_count="$3"
    local change="$4"
    
    echo "[$(date '+%H:%M:%S')] Iteration $ITERATION/$MAX_ITERATIONS"
    
    if [ "$process_status" -eq 1 ]; then
        echo -e "  CLI Process: ${GREEN}✓ RUNNING${NC}"
    else
        echo -e "  CLI Process: ${YELLOW}✗ NOT RUNNING${NC}"
    fi
    
    if [ "$celery_workers" -gt 0 ]; then
        echo -e "  Celery Workers: ${GREEN}✓ $celery_workers RUNNING${NC}"
    else
        echo -e "  Celery Workers: ${YELLOW}✗ NOT RUNNING${NC}"
    fi
    
    echo -e "  Documents: ${BLUE}$doc_count${NC} ($change)"
    echo "  Alerts: $ALERT_COUNT"
    echo ""
}

# Main monitoring loop
while [ $ITERATION -lt $MAX_ITERATIONS ]; do
    ITERATION=$((ITERATION + 1))
    
    # Check CLI process status
    PROCESS_ALIVE=$(check_process)
    
    # Check Celery workers
    CELERY_WORKERS=$(check_celery)
    
    # Check logs for errors
    LOG_ERRORS=$(check_logs)
    
    # Get document count
    CURRENT_DOC_COUNT=$(get_doc_count)
    
    # Calculate change
    if [ "$LAST_DOC_COUNT" -eq -1 ]; then
        DOC_CHANGE="${GREEN}initial${NC}"
    elif [ "$CURRENT_DOC_COUNT" -gt "$LAST_DOC_COUNT" ]; then
        DOC_CHANGE="${GREEN}+$(($CURRENT_DOC_COUNT - $LAST_DOC_COUNT))${NC}"
    elif [ "$CURRENT_DOC_COUNT" -lt "$LAST_DOC_COUNT" ]; then
        DOC_CHANGE="${YELLOW}$(($CURRENT_DOC_COUNT - $LAST_DOC_COUNT))${NC}"
    else
        DOC_CHANGE="no change"
    fi
    
    # Print status
    print_status "$PROCESS_ALIVE" "$CELERY_WORKERS" "$CURRENT_DOC_COUNT" "$DOC_CHANGE"
    
    # Alert if CLI process was running but now disappeared
    if [ "$WAS_RUNNING" -eq 1 ] && [ "$PROCESS_ALIVE" -eq 0 ]; then
        send_alert "INGESTION CLI PROCESS DISAPPEARED" "The gabi.cli ingest process stopped running.\nIteration: $ITERATION"
    fi
    
    # Alert if Celery workers were running but now disappeared
    if [ "$WAS_CELERY_RUNNING" -gt 0 ] && [ "$CELERY_WORKERS" -eq 0 ]; then
        send_alert "CELERY WORKERS DISAPPEARED" "All Celery workers stopped running.\nIteration: $ITERATION"
    fi
    
    # Alert if errors found in logs
    if [ -n "$LOG_ERRORS" ]; then
        send_alert "ERRORS FOUND IN LOGS" "$LOG_ERRORS"
    fi
    
    # Update tracking variables
    if [ "$PROCESS_ALIVE" -eq 1 ]; then
        WAS_RUNNING=1
    fi
    if [ "$CELERY_WORKERS" -gt 0 ]; then
        WAS_CELERY_RUNNING=$CELERY_WORKERS
    fi
    LAST_DOC_COUNT=$CURRENT_DOC_COUNT
    
    # Sleep for 20 seconds (unless last iteration)
    if [ $ITERATION -lt $MAX_ITERATIONS ]; then
        sleep 20
    fi
done

echo "=========================================="
echo "Monitoring completed at: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Total alerts: $ALERT_COUNT"
echo "=========================================="

exit 0
