#!/bin/bash

# GABI Ingestion Monitor - OOM and Error Watcher
# Runs for 10 minutes (60 iterations), checking every 10 seconds

TOTAL_ITERATIONS=60
INTERVAL=10
LOG_DIR="/home/fgamajr/dev/gabi-kimi/logs"
ALERT_COUNT=0

echo "=========================================="
echo "  GABI Ingestion Monitor Started"
echo "  Duration: 10 minutes"
echo "  Interval: 10 seconds"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="
echo ""

for i in $(seq 1 $TOTAL_ITERATIONS); do
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
    HAS_ALERT=0
    
    # 1. Check ingestion logs for errors
    LOG_ERRORS=$(tail -50 ${LOG_DIR}/ingestion_*.log 2>/dev/null | grep -iE "killed|oom|error|fatal|exception" | tail -5)
    
    # 2. Check dmesg for OOM
    DMESG_OOM=$(dmesg 2>/dev/null | grep -i "oom\|killed" | tail -3)
    
    # 3. Check if ingestion process is alive
    PROCESS_CHECK=$(ps aux | grep gabi.cli | grep -v grep)
    
    # Print status header every 6 iterations (every minute)
    if [ $((i % 6)) -eq 1 ]; then
        echo "[$TIMESTAMP] Check #$i - Monitoring..."
    fi
    
    # Check for errors in logs
    if [ -n "$LOG_ERRORS" ]; then
        echo ""
        echo "🚨 ALERT: Errors found in ingestion logs!"
        echo "------------------------------------------"
        echo "$LOG_ERRORS"
        echo "------------------------------------------"
        HAS_ALERT=1
        ((ALERT_COUNT++))
    fi
    
    # Check dmesg for OOM
    if [ -n "$DMESG_OOM" ]; then
        echo ""
        echo "🚨 ALERT: OOM detected in dmesg!"
        echo "------------------------------------------"
        echo "$DMESG_OOM"
        echo "------------------------------------------"
        HAS_ALERT=1
        ((ALERT_COUNT++))
    fi
    
    # Check if process is running (only alert if it was running before)
    if [ -z "$PROCESS_CHECK" ] && [ $i -gt 3 ]; then
        echo ""
        echo "⚠️  WARNING: No gabi.cli process found!"
        echo "------------------------------------------"
        HAS_ALERT=1
        ((ALERT_COUNT++))
    elif [ -n "$PROCESS_CHECK" ]; then
        # Show process info every minute
        if [ $((i % 6)) -eq 1 ]; then
            PID=$(echo "$PROCESS_CHECK" | awk '{print $2}')
            MEM=$(echo "$PROCESS_CHECK" | awk '{print $4}')
            CPU=$(echo "$PROCESS_CHECK" | awk '{print $3}')
            echo "   └─ Process running - PID: $PID, CPU: ${CPU}%, MEM: ${MEM}%"
        fi
    fi
    
    if [ $HAS_ALERT -eq 1 ]; then
        echo "[$TIMESTAMP] ALERT DETECTED (Total alerts: $ALERT_COUNT)"
        echo ""
    fi
    
    # Sleep for interval (unless last iteration)
    if [ $i -lt $TOTAL_ITERATIONS ]; then
        sleep $INTERVAL
    fi
done

echo ""
echo "=========================================="
echo "  Monitoring Complete"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "  Total Alerts: $ALERT_COUNT"
echo "=========================================="

exit $ALERT_COUNT
