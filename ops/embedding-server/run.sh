#!/usr/bin/env bash
# Auto-restart wrapper for the embedding server.
# Restarts on crash with a 5s cooldown. Ctrl+C to stop.
set -e

cd "$(dirname "$0")"

while true; do
    echo "[run.sh] Starting embedding server at $(date)"
    python server.py || true
    echo "[run.sh] Server exited (crashed or killed), restarting in 5s..."
    sleep 5
done
