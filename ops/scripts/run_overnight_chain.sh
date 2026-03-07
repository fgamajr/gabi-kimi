#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/parallels/dev/gabi-kimi"
cd "$ROOT"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

WAIT_PID="${1:-}"

log() {
  printf '[%s] %s\n' "$(date -Is)" "$*"
}

if [ -n "$WAIT_PID" ]; then
  log "waiting for pid=$WAIT_PID"
  while kill -0 "$WAIT_PID" 2>/dev/null; do
    sleep 60
  done
fi

log "starting chunk backfill 2003-2005"
.venv/bin/python ops/scripts/backfill_chunks.py \
  --batch-size 1000 \
  --date-from 2003-01-01 \
  --date-to 2005-12-31 \
  --cursor-file ops/data/chunks_backfill_cursor_2003_2005.json

log "starting embedding sync for 2003-2005"
.venv/bin/python -m src.backend.ingest.embedding_pipeline \
  --cursor ops/data/es_chunks_openai_cursor_384.json \
  sync \
  --batch-size 1024

log "starting sync_pipeline 2006-2010"
.venv/bin/python -u -m src.backend.ingest.sync_pipeline \
  --refresh-catalog \
  --start 2006-01 \
  --end 2010-12

log "starting bm25 refresh"
.venv/bin/python -m src.backend.ingest.bm25_indexer refresh

log "starting es_indexer sync"
.venv/bin/python -m src.backend.ingest.es_indexer \
  --cursor ops/data/es_sync_cursor.json \
  sync

log "starting chunk backfill 2006-2010"
.venv/bin/python ops/scripts/backfill_chunks.py \
  --batch-size 1000 \
  --date-from 2006-01-01 \
  --date-to 2010-12-31 \
  --cursor-file ops/data/chunks_backfill_cursor_2006_2010.json

log "starting embedding sync for 2006-2010"
.venv/bin/python -m src.backend.ingest.embedding_pipeline \
  --cursor ops/data/es_chunks_openai_cursor_384.json \
  sync \
  --batch-size 1024

log "overnight chain done"
