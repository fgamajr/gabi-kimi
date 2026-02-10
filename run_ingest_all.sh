#!/bin/bash
# Run ingestion for all enabled sources, one at a time in separate processes.
# This ensures full memory reclamation between sources.
set -euo pipefail

export GABI_DATABASE_URL='postgresql+asyncpg://gabi:gabi@127.0.0.1:15432/gabi'
export GABI_ELASTICSEARCH_URL='http://127.0.0.1:9200'
export GABI_REDIS_URL='redis://127.0.0.1:6379/0'
export GABI_EMBEDDINGS_URL='http://127.0.0.1:8080'
export GABI_AUTH_ENABLED=false
export GABI_FETCHER_SSRF_ENABLED=false
export GABI_PIPELINE_FETCH_MAX_SIZE_MB=30

MAX_DOCS=${1:-100}
LOGDIR="/tmp/gabi_ingest"
mkdir -p "$LOGDIR"

# All enabled sources (excluding stf_decisoes and stj_acordaos which are disabled)
SOURCES=(
  tcu_acordaos
  tcu_normas
  tcu_sumulas
  tcu_jurisprudencia_selecionada
  tcu_resposta_consulta
  tcu_informativo_lc
  tcu_boletim_jurisprudencia
  tcu_boletim_pessoal
  tcu_publicacoes
  tcu_notas_tecnicas_ti
  camara_leis_ordinarias
)

TOTAL=${#SOURCES[@]}
SUCCESS=0
FAILED=0

echo "============================================"
echo "GABI Ingest All - $(date)"
echo "Sources: $TOTAL | Max docs/source: $MAX_DOCS | Max download: ${GABI_PIPELINE_FETCH_MAX_SIZE_MB}MB"
echo "============================================"
echo ""

for i in "${!SOURCES[@]}"; do
  SRC="${SOURCES[$i]}"
  IDX=$((i + 1))
  LOG="$LOGDIR/${SRC}.json"
  
  echo "[$IDX/$TOTAL] Processing: $SRC"
  echo -n "  Started: $(date +%H:%M:%S) ... "
  
  # Run in subprocess — memory is fully freed when it exits
  if python -m gabi.cli ingest --source "$SRC" --max-docs-per-source "$MAX_DOCS" > "$LOG" 2>&1; then
    DOCS=$(python3 -c "import json; d=json.load(open('$LOG')); print(d.get('documents_indexed', 0))" 2>/dev/null || echo "?")
    CHUNKS=$(python3 -c "import json; d=json.load(open('$LOG')); print(d.get('chunks_created', 0))" 2>/dev/null || echo "?")
    STATUS=$(python3 -c "import json; d=json.load(open('$LOG')); print(d.get('status', '?'))" 2>/dev/null || echo "?")
    echo "Done! status=$STATUS docs=$DOCS chunks=$CHUNKS"
    SUCCESS=$((SUCCESS + 1))
  else
    echo "FAILED (exit code $?)"
    tail -3 "$LOG" 2>/dev/null | head -3
    FAILED=$((FAILED + 1))
  fi
  
  # Brief pause for GC
  sleep 1
done

echo ""
echo "============================================"
echo "RESULTS: $SUCCESS succeeded, $FAILED failed out of $TOTAL"
echo "============================================"

# Summary from DB
echo ""
echo "=== Database Summary ==="
PGPASSWORD=gabi psql -h 127.0.0.1 -p 15432 -U gabi -d gabi -c "
SELECT 
  source_id, 
  count(*) as docs,
  (SELECT count(*) FROM document_chunks dc WHERE dc.document_id = ANY(array_agg(d.id))) as chunks
FROM documents d
GROUP BY source_id
ORDER BY source_id;
" 2>/dev/null || echo "(could not query DB)"

echo ""
echo "=== Totals ==="
PGPASSWORD=gabi psql -h 127.0.0.1 -p 15432 -U gabi -d gabi -c "
SELECT 
  (SELECT count(*) FROM documents) as total_docs,
  (SELECT count(*) FROM document_chunks) as total_chunks,
  (SELECT count(DISTINCT source_id) FROM documents) as sources_with_docs;
" 2>/dev/null || echo "(could not query DB)"
