#!/usr/bin/env bash
set -euo pipefail

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
    if $VENV -m gabi.cli ingest \
        --source "$src" \
        --sources-file sources.yaml \
        --max-docs-per-source 100 \
        > "$LOG_DIR/${src}_fix.json" 2>&1; then
        echo "$(date '+%H:%M:%S') ✅ $src completed"
    else
        echo "$(date '+%H:%M:%S') ❌ $src failed (exit=$?)"
    fi
    echo ""
done

echo "$(date '+%H:%M:%S') All done!"
echo ""
echo "=== DB document counts ==="
$VENV -c "
import asyncio, os
os.environ.setdefault('GABI_DATABASE_URL','postgresql+asyncpg://gabi:gabi@127.0.0.1:15432/gabi')
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
async def main():
    e = create_async_engine(os.environ['GABI_DATABASE_URL'])
    async with e.begin() as c:
        r = await c.execute(text('''
            SELECT s.source_id, COUNT(d.id) as docs, COALESCE(SUM(ch.cnt),0) as chunks
            FROM source_registry s
            LEFT JOIN documents d ON d.source_id = s.source_id AND d.deleted_at IS NULL
            LEFT JOIN (SELECT document_id, COUNT(*) cnt FROM chunks WHERE deleted_at IS NULL GROUP BY document_id) ch ON ch.document_id = d.document_id
            WHERE s.deleted_at IS NULL
            GROUP BY s.source_id ORDER BY s.source_id
        '''))
        print(f\"{'Source':<40} {'Docs':>6} {'Chunks':>8}\")
        print('-'*56)
        td = tc = 0
        for row in r:
            print(f\"{row[0]:<40} {row[1]:>6} {row[2]:>8}\")
            td += row[1]; tc += row[2]
        print('-'*56)
        print(f\"{'TOTAL':<40} {td:>6} {tc:>8}\")
    await e.dispose()
asyncio.run(main())
"
