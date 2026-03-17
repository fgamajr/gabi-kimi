#!/usr/bin/env bash
# Setup Elasticsearch for GABI DOU via Docker Compose
# Run from project root: bash ops/setup_elasticsearch.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

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

docker compose exec -T backend python -m json.tool < /tmp/gabi-es-health.json

echo ""
echo "=== Step 3: Add dense_vector mapping for embeddings ==="
docker compose exec -T elasticsearch curl -fsS -X PUT \
  "http://localhost:9200/gabi_documents_v1/_mapping" \
  -H 'Content-Type: application/json' \
  -d '{
    "properties": {
      "embedding": {
        "type": "dense_vector",
        "dims": 384,
        "index": true,
        "similarity": "cosine",
        "index_options": {"type": "int8_hnsw"}
      },
      "embedding_status": {"type": "keyword"},
      "embedding_model": {"type": "keyword"}
    }
  }' && echo " OK" || echo " (already exists or skipped)"

echo ""
echo "=== Step 4: Run ES backfill from MongoDB ==="
echo "  This indexes all MongoDB documents into Elasticsearch."
echo "  (Safe to re-run — uses cursor for incremental sync)"
docker compose exec -T backend python -m src.backend.ingest.es_indexer backfill

echo ""
echo "=== Step 5: Verify ==="
echo "  Index count:"
docker compose exec -T elasticsearch curl -fsS http://localhost:9200/gabi_documents_v1/_count | docker compose exec -T backend python -m json.tool

echo ""
echo "=== Done! ==="
echo "  Storage defaults point at the repo-local .data folders unless overridden in .env."
