#!/bin/bash
# Setup Elasticsearch for GABI DOU
# Run from project root: bash ops/setup_elasticsearch.sh
set -e

cd /home/parallels/dev/gabi-kimi

echo "=== Step 1: Ensure Parallels shared folder ==="
SHARED_DIR="/media/psf/gabi_es"
if [ -d "$SHARED_DIR" ]; then
  echo "  Shared folder already exists at $SHARED_DIR"
else
  echo "  ERROR: Shared folder not found at $SHARED_DIR"
  echo "  Please create it in Parallels:"
  echo "    1. On macOS: mkdir -p ~/Data/gabi_es"
  echo "    2. Parallels > VM Settings > Hardware > Shared Folders"
  echo "    3. Add ~/Data/gabi_es (name: gabi_es)"
  echo "  Then re-run this script."
  exit 1
fi

echo "=== Step 2: Start Elasticsearch container ==="
if docker ps --format '{{.Names}}' | grep -q '^gabi-es$'; then
  echo "  Container gabi-es already running"
elif docker ps -a --format '{{.Names}}' | grep -q '^gabi-es$'; then
  echo "  Starting existing container gabi-es..."
  docker start gabi-es
else
  echo "  Creating and starting gabi-es container..."
  docker run -d --name gabi-es \
    -p 9200:9200 \
    -e discovery.type=single-node \
    -e xpack.security.enabled=false \
    -e "ES_JAVA_OPTS=-Xms4g -Xmx4g" \
    -v "$SHARED_DIR":/usr/share/elasticsearch/data \
    docker.elastic.co/elasticsearch/elasticsearch:8.15.4
fi

echo "  Waiting for ES to be ready..."
for i in $(seq 1 30); do
  if curl -s localhost:9200 >/dev/null 2>&1; then
    echo "  ES is ready!"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "  ERROR: ES did not start within 30s. Check: docker logs gabi-es"
    exit 1
  fi
  sleep 1
done

curl -s localhost:9200 | python3 -m json.tool

echo ""
echo "=== Step 3: Run ES backfill from MongoDB ==="
echo "  This indexes all MongoDB documents into Elasticsearch."
echo "  (Safe to re-run — uses cursor for incremental sync)"
python3 -m src.backend.ingest.es_indexer backfill

echo ""
echo "=== Step 4: Verify ==="
echo "  Index count:"
curl -s localhost:9200/gabi_documents_v1/_count | python3 -m json.tool

echo ""
echo "=== Done! ==="
echo "  Restart Claude Code to pick up the updated .mcp.json"
echo "  Then test: es_health(), es_search(\"decreto\")"
