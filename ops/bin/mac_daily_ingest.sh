#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# mac_daily_ingest.sh — Mac LaunchD relay (fallback)
#
# Connects to gabi-prod and runs server_daily_ingest.sh.
# Fires at 08:00 local time via com.gabi.daily-ingest.plist.
# Normally, a cron on the server handles this; this script
# is a backup in case the server cron misses a day.
# ─────────────────────────────────────────────────────────────
set -euo pipefail

REMOTE_HOST="gabi-prod"
REMOTE_REPO="/home/gabi/gabi-kimi"
LOG_FILE="/tmp/gabi_mac_ingest.log"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "${LOG_FILE}"; }

log "=== Mac relay start ==="

# Pull latest code on server before running
log "Pulling latest code on server..."
ssh "${REMOTE_HOST}" "cd ${REMOTE_REPO} && git pull --ff-only 2>&1" | tee -a "${LOG_FILE}"

# Run server-side daily ingest (last 3 days rolling window)
log "Running server_daily_ingest.sh..."
ssh "${REMOTE_HOST}" "cd ${REMOTE_REPO} && bash ops/bin/run_daily_ingest.sh 2>&1" | tee -a "${LOG_FILE}"

log "=== Mac relay complete ==="
