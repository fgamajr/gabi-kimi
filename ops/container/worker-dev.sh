#!/bin/sh
set -eu

cd /workspace

batch_size="${WORKER_BATCH_SIZE:-1000}"
poll_interval="${WORKER_POLL_INTERVAL_SEC:-30}"

while true; do
  python -m src.backend.ingest.es_indexer sync --batch-size "${batch_size}" || true
  sleep "${poll_interval}"
done
