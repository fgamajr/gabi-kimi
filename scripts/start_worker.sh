#!/bin/bash
set -e

export PYTHONPATH=/home/fgamajr/dev/gabi-kimi/src
cd /home/fgamajr/dev/gabi-kimi

# Kill any existing worker
pkill -f "celery -A gabi.worker worker" 2>/dev/null || true
sleep 2

# Start new worker (using nohup instead of --detach for better compatibility)
nohup celery -A gabi.worker worker \
  --loglevel=info \
  --concurrency=2 \
  --prefetch-multiplier=1 \
  --max-tasks-per-child=100 \
  --queues=gabi.default,gabi.sync,gabi.dlq,gabi.health \
  > /tmp/celery_worker.log 2>&1 &

sleep 3

# Verify worker started
if celery -A gabi.worker inspect ping 2>/dev/null | grep -q "pong"; then
    echo "✅ Celery worker started successfully"
else
    echo "❌ Failed to start Celery worker - check /tmp/celery_worker.log"
    exit 1
fi
