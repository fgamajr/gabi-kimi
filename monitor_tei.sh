#!/bin/bash

# GABI TEI Monitoring Script
# Runs for 10 minutes, checking every 20 seconds

LOG_FILE="/home/fgamajr/dev/gabi-kimi/logs/tei_monitor_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$(dirname "$LOG_FILE")"

# Database connection details (from .env or defaults)
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_NAME="${POSTGRES_DB:-gabi}"
DB_USER="${POSTGRES_USER:-gabi}"
DB_PASS="${POSTGRES_PASSWORD:-gabi}"

echo "========================================" | tee -a "$LOG_FILE"
echo "GABI TEI Service Monitor" | tee -a "$LOG_FILE"
echo "Started: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
echo "Duration: 10 minutes | Interval: 20 seconds" | tee -a "$LOG_FILE"
echo "Log file: $LOG_FILE" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"

# Function to get chunk count from database
get_chunk_count() {
    PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
        -t -c "SELECT COUNT(*) FROM document_chunks;" 2>/dev/null | tr -d '[:space:]'
}

# Function to check TEI health endpoint
check_tei_health() {
    curl -s -o /dev/null -w "%{http_code}" "http://localhost:8080/health" 2>/dev/null
}

# Initialize variables
ITERATIONS=30  # 10 minutes / 20 seconds = 30 iterations
PREV_CHUNK_COUNT=0
PREV_TIMESTAMP=$(date +%s)
FIRST_CHUNK_COUNT=$(get_chunk_count)
FIRST_TIMESTAMP=$PREV_TIMESTAMP

echo "Initial chunk count: ${FIRST_CHUNK_COUNT:-N/A}" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# Main monitoring loop
for i in $(seq 1 $ITERATIONS); do
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
    EPOCH=$(date +%s)
    
    echo "--- Check #$i at $TIMESTAMP ---" | tee -a "$LOG_FILE"
    
    # 1. Check TEI container status
    TEI_STATUS=$(docker ps --filter "name=gabi-tei" --format "{{.Names}}: {{.Status}}" 2>/dev/null)
    if [ -z "$TEI_STATUS" ]; then
        TEI_STATUS="ALERT: gabi-tei container NOT FOUND or NOT RUNNING"
        ALERT="🚨 TEI DOWN!"
    else
        ALERT=""
    fi
    echo "Container: $TEI_STATUS" | tee -a "$LOG_FILE"
    
    # Check health endpoint if container is running
    if [ -z "$ALERT" ]; then
        HEALTH_STATUS=$(check_tei_health)
        if [ "$HEALTH_STATUS" = "200" ]; then
            echo "Health Endpoint: ✓ OK (HTTP 200)" | tee -a "$LOG_FILE"
        else
            echo "Health Endpoint: ✗ FAIL (HTTP ${HEALTH_STATUS:-no response})" | tee -a "$LOG_FILE"
        fi
    fi
    
    # 2. Check TEI resource stats
    TEI_STATS=$(docker stats gabi-tei --no-stream --format "CPU: {{.CPUPerc}} | MEM: {{.MemUsage}}" 2>/dev/null)
    if [ -n "$TEI_STATS" ]; then
        echo "Resources: $TEI_STATS" | tee -a "$LOG_FILE"
    else
        echo "Resources: N/A (container not running)" | tee -a "$LOG_FILE"
    fi
    
    # 3. Check embedding generation rate via document_chunks growth
    CURRENT_CHUNK_COUNT=$(get_chunk_count)
    if [ -n "$CURRENT_CHUNK_COUNT" ]; then
        # Calculate rate since last check
        if [ $i -gt 1 ] && [ -n "$PREV_CHUNK_COUNT" ] && [ "$PREV_CHUNK_COUNT" != "0" ]; then
            CHUNK_DIFF=$((CURRENT_CHUNK_COUNT - PREV_CHUNK_COUNT))
            TIME_DIFF=$((EPOCH - PREV_TIMESTAMP))
            if [ $TIME_DIFF -gt 0 ]; then
                RATE_PER_MIN=$((CHUNK_DIFF * 60 / TIME_DIFF))
                echo "Chunks: $CURRENT_CHUNK_COUNT (Δ$CHUNK_DIFF in ${TIME_DIFF}s = ~${RATE_PER_MIN}/min)" | tee -a "$LOG_FILE"
            else
                echo "Chunks: $CURRENT_CHUNK_COUNT" | tee -a "$LOG_FILE"
            fi
        else
            echo "Chunks: $CURRENT_CHUNK_COUNT" | tee -a "$LOG_FILE"
        fi
        PREV_CHUNK_COUNT=$CURRENT_CHUNK_COUNT
        PREV_TIMESTAMP=$EPOCH
    else
        echo "Chunks: N/A (DB unavailable)" | tee -a "$LOG_FILE"
    fi
    
    # Display alert if any
    if [ -n "$ALERT" ]; then
        echo "$ALERT" | tee -a "$LOG_FILE"
    fi
    
    echo "" | tee -a "$LOG_FILE"
    
    # Sleep for 20 seconds (unless last iteration)
    if [ $i -lt $ITERATIONS ]; then
        sleep 20
    fi
done

# Final summary
FINAL_CHUNK_COUNT=$(get_chunk_count)
FINAL_TIMESTAMP=$(date +%s)

echo "========================================" | tee -a "$LOG_FILE"
echo "Monitoring Complete: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"

if [ -n "$FIRST_CHUNK_COUNT" ] && [ -n "$FINAL_CHUNK_COUNT" ]; then
    TOTAL_DIFF=$((FINAL_CHUNK_COUNT - FIRST_CHUNK_COUNT))
    TOTAL_TIME=$((FINAL_TIMESTAMP - FIRST_TIMESTAMP))
    if [ $TOTAL_TIME -gt 0 ]; then
        AVG_RATE_PER_MIN=$((TOTAL_DIFF * 60 / TOTAL_TIME))
        AVG_RATE_PER_SEC=$(echo "scale=2; $TOTAL_DIFF / $TOTAL_TIME" | bc 2>/dev/null || echo "N/A")
        echo "Total chunks created: $TOTAL_DIFF" | tee -a "$LOG_FILE"
        echo "Average throughput: ~${AVG_RATE_PER_MIN} chunks/min (${AVG_RATE_PER_SEC} chunks/sec)" | tee -a "$LOG_FILE"
    fi
    echo "Final chunk count: $FINAL_CHUNK_COUNT" | tee -a "$LOG_FILE"
fi

echo "Log saved to: $LOG_FILE"
