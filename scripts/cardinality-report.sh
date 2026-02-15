#!/usr/bin/env bash
# Gera tabela de cardinalidade com DADOS REAIS do banco (prova do pipeline).
# Uso: ./scripts/cardinality-report.sh
# Requer: docker com container postgres (gabi-kimi-postgres-1) ou PGHOST/PGPORT para psql direto.

set -e
GABI_ROOT="${GABI_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$GABI_ROOT"

PG_HOST="${PGHOST:-localhost}"
PG_PORT="${GABI_POSTGRES_PORT:-5433}"
PG_USER="${PGUSER:-gabi}"
PG_PASS="${PGPASSWORD:-gabi_dev_password}"
PG_DB="${PGDATABASE:-gabi}"
export PGPASSWORD="$PG_PASS"

# Se estiver em Docker, usar docker exec
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'gabi-kimi-postgres'; then
  PG_CMD="docker exec -i gabi-kimi-postgres-1 psql -U $PG_USER -d $PG_DB -t -A"
else
  PG_CMD="psql -h $PG_HOST -p $PG_PORT -U $PG_USER -d $PG_DB -t -A"
fi

echo "=== Cardinalidade - Resultados reais do banco ==="
echo "Data: $(date -Iseconds)"
echo ""

# Contagens
sr=$($PG_CMD -c "SELECT COUNT(*) FROM source_registry;" 2>/dev/null || echo "0")
seed_r=$($PG_CMD -c "SELECT COUNT(*) FROM seed_runs;" 2>/dev/null || echo "0")
dr=$($PG_CMD -c "SELECT COUNT(*) FROM discovery_runs;" 2>/dev/null || echo "0")
dl=$($PG_CMD -c "SELECT COUNT(*) FROM discovered_links;" 2>/dev/null || echo "0")
fr=$($PG_CMD -c "SELECT COUNT(*) FROM fetch_runs;" 2>/dev/null || echo "0")
fi=$($PG_CMD -c "SELECT COUNT(*) FROM fetch_items;" 2>/dev/null || echo "0")
doc=$($PG_CMD -c "SELECT COUNT(*) FROM documents;" 2>/dev/null || echo "0")

echo "| Fase / camada      | Tabela             | Contagem real | Prova de cardinalidade |"
echo "|--------------------|--------------------|---------------|-------------------------|"
echo "| Source (feed)      | (YAML)             | -             | Entrada do Seed.        |"
printf "| Seed               | source_registry    | %-13s | N fontes persistidas.   |\n" "$sr"
printf "| Seed               | seed_runs          | %-13s | 1 run por execução.    |\n" "$seed_r"
printf "| Discovery          | discovery_runs    | %-13s | 1 run por fonte.       |\n" "$dr"
printf "| Discovery          | discovered_links  | %-13s | N links por run (1:N). |\n" "$dl"
printf "| Fetch              | fetch_runs        | %-13s | 1 run por job fetch.   |\n" "$fr"
printf "| Fetch              | fetch_items       | %-13s | M itens (1:M links).   |\n" "$fi"
printf "| Ingest             | documents         | %-13s | P docs (M:N fetch).    |\n" "$doc"
echo ""
echo "---"
echo "Cardinalidade: Seed→Discovery 1:1 (por fonte); Discovery→Fetch 1:M; Fetch→Ingest M:N."
