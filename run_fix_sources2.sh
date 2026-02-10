#!/usr/bin/env bash
set -uo pipefail

export GABI_DATABASE_URL='postgresql+asyncpg://gabi:gabi@127.0.0.1:15432/gabi'
export GABI_ELASTICSEARCH_URL='http://127.0.0.1:9200'
export GABI_REDIS_URL='redis://127.0.0.1:6379/0'
export GABI_EMBEDDINGS_URL='http://127.0.0.1:8080'
export GABI_AUTH_ENABLED=false
export GABI_FETCHER_SSRF_ENABLED=false
export GABI_PIPELINE_FETCH_MAX_SIZE_MB=30

cd /home/fgamajr/dev/gabi-kimi
VENV=".venv/bin/python"
LOG_DIR="/tmp/gabi_ingest"
mkdir -p "$LOG_DIR"

SOURCES=(tcu_publicacoes camara_leis_ordinarias)

for src in "${SOURCES[@]}"; do
    echo "========================================="
    echo "$(date '+%H:%M:%S') Ingesting: $src"
    echo "========================================="
    $VENV -m gabi.cli ingest \
        --source "$src" \
        --max-docs-per-source 100 \
        > "$LOG_DIR/${src}_fix.json" 2>&1
    RC=$?
    if [ $RC -eq 0 ]; then
        echo "$(date '+%H:%M:%S') ✅ $src completed"
    else
        echo "$(date '+%H:%M:%S') ❌ $src failed (exit=$RC)"
    fi
    tail -5 "$LOG_DIR/${src}_fix.json" 2>/dev/null || true
    echo ""
done

echo "$(date '+%H:%M:%S') All done!"
