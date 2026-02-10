#!/bin/bash
# Continue ingestion for remaining sources (tcu_acordaos already done).
# Uses nohup-compatible output (no tee, just redirect).
set -uo pipefail

cd /home/fgamajr/dev/gabi-kimi
source .venv/bin/activate

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

# Remaining sources (tcu_acordaos already completed with 100 docs)
SOURCES=(
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
echo "GABI Ingest Remaining - $(date)"
echo "Sources: $TOTAL | Max docs/source: $MAX_DOCS | Max download: ${GABI_PIPELINE_FETCH_MAX_SIZE_MB}MB"
echo "============================================"

for i in "${!SOURCES[@]}"; do
  SRC="${SOURCES[$i]}"
  IDX=$((i + 1))
  LOG="$LOGDIR/${SRC}.json"
  
  echo ""
  echo "[$IDX/$TOTAL] Processing: $SRC ($(date +%H:%M:%S))"
  
  if timeout 120 python -m gabi.cli ingest --source "$SRC" --max-docs-per-source "$MAX_DOCS" > "$LOG" 2>&1; then
    DOCS=$(python3 -c "import json; d=json.load(open('$LOG')); print(d.get('documents_indexed', 0))" 2>/dev/null || echo "?")
    CHUNKS=$(python3 -c "import json; d=json.load(open('$LOG')); print(d.get('chunks_created', 0))" 2>/dev/null || echo "?")
    STATUS=$(python3 -c "import json; d=json.load(open('$LOG')); print(d.get('status', '?'))" 2>/dev/null || echo "?")
    ERRS=$(python3 -c "import json; d=json.load(open('$LOG')); print(len(d.get('errors', [])))" 2>/dev/null || echo "?")
    echo "  => status=$STATUS docs=$DOCS chunks=$CHUNKS errors=$ERRS"
    SUCCESS=$((SUCCESS + 1))
  else
    EC=$?
    if [ $EC -eq 124 ]; then
      echo "  => TIMEOUT (120s)"
    elif [ $EC -eq 137 ]; then
      echo "  => OOM KILLED"
    else
      echo "  => FAILED (exit $EC)"
    fi
    # Try to read partial output
    head -5 "$LOG" 2>/dev/null
    FAILED=$((FAILED + 1))
  fi
  
  sleep 2
done

echo ""
echo "============================================"
echo "DONE: $SUCCESS ok, $FAILED failed out of $TOTAL"
echo "============================================"

# Final DB summary
echo ""
PGPASSWORD=gabi psql -h 127.0.0.1 -p 15432 -U gabi -d gabi -c "
SELECT source_id, count(*) as docs FROM documents GROUP BY source_id ORDER BY source_id;
" 2>/dev/null

PGPASSWORD=gabi psql -h 127.0.0.1 -p 15432 -U gabi -d gabi -c "
SELECT 
  (SELECT count(*) FROM documents) as total_docs,
  (SELECT count(*) FROM document_chunks) as total_chunks,
  (SELECT count(DISTINCT source_id) FROM documents) as sources_with_docs;
" 2>/dev/null

echo "FINISHED at $(date)"
