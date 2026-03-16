#!/bin/bash
# Setup Elasticsearch for GABI DOU via Docker Compose
# Run from project root: bash ops/setup_elasticsearch.sh
set -euo pipefail

cd /home/parallels/dev/gabi-kimi

echo "=== Step 1: Pull/start Elasticsearch and backend ==="
docker compose pull elasticsearch || true

echo ""
echo "=== Step 2: Start services ==="
docker compose up -d elasticsearch backend

echo "  Waiting for gabi-kimi-elasticsearch to be ready..."
for i in $(seq 1 30); do
  if docker compose exec -T elasticsearch curl -fsS http://localhost:9200 >/tmp/gabi-es-health.json 2>/dev/null; then
    echo "  Elasticsearch is ready!"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "  ERROR: Elasticsearch did not start within 30s. Check: docker compose logs elasticsearch"
    exit 1
  fi
  sleep 1
done

python3 -m json.tool /tmp/gabi-es-health.json

echo ""
echo "=== Step 3: Run ES backfill from MongoDB ==="
echo "  This indexes all MongoDB documents into Elasticsearch."
echo "  (Safe to re-run — uses cursor for incremental sync)"
docker compose exec -T backend python -m src.backend.ingest.es_indexer backfill

echo ""
echo "=== Step 4: Verify ==="
echo "  Index count:"
docker compose exec -T elasticsearch curl -fsS http://localhost:9200/gabi_documents_v1/_count | python3 -m json.tool

echo ""
echo "=== Done! ==="
echo "  Running containers now use the normalized gabi-kimi-* names."
