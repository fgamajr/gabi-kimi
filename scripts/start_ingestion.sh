cd /home/fgamajr/dev/gabi-kimi

# 1. Recriar TEI
docker compose --profile infra up -d tei --force-recreate

# 2. Esperar TEI ficar ready (health check com retry)
echo "Aguardando TEI..."
for i in $(seq 1 60); do
  if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
    echo " ✓ TEI healthy"
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo " ✗ TEI não ficou healthy após 5 minutos"
    docker logs gabi-tei --tail 20
    exit 1
  fi
  echo "  aguardando... ($i/60)"
  sleep 5
done

# 3. Testar com texto longo (>128 tokens)
curl -s http://localhost:8080/embed -X POST \
  -H 'Content-Type: application/json' \
  -d '{"inputs": "O Tribunal de Contas da União, no uso de suas atribuições constitucionais, legais e regimentais, considerando os fatos apurados no processo de fiscalização referente à aplicação dos recursos públicos federais, resolve aprovar o acórdão a seguir transcrito, que foi proferido pelo Plenário em sessão ordinária. O relator apresentou análise detalhada dos elementos probatórios coligidos durante a instrução processual, com fundamento nas disposições da Lei Orgânica do TCU. A unidade técnica competente emitiu parecer conclusivo sobre a regularidade das contas públicas examinadas neste exercício financeiro."}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'TEI OK: {len(d[0])} dims (texto longo aceito)')"

# 4. Limpar docs da rodada anterior e re-seed
source .venv/bin/activate
export GABI_DATABASE_URL='postgresql+asyncpg://gabi:gabi_dev_password@localhost:5432/gabi'
export GABI_AUTH_ENABLED=false
export GABI_FETCHER_SSRF_ENABLED=false
export GABI_ELASTICSEARCH_URL=http://localhost:9200
export GABI_EMBEDDINGS_URL=http://localhost:8080
export GABI_REDIS_URL=redis://localhost:6379/0

# Limpar dados da rodada anterior (docs sem embedding)
docker exec gabi-postgres psql -U gabi -d gabi -c "DELETE FROM document_chunks; DELETE FROM documents; DELETE FROM execution_manifests;"

# 5. Re-seed sources
PYTHONPATH=src python scripts/seed_sources.py

# 6. Ingest tcu_sumulas (teste com 10 docs)
PYTHONPATH=src python -m gabi.cli ingest -s tcu_sumulas --max-docs-per-source 10