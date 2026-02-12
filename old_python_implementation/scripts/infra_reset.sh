#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# GABI - Infrastructure Hard Reset
# Destrói TUDO relacionado ao GABI no Docker e limpa dados locais
# Uso: ./scripts/infra_reset.sh [--force]
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[infra-reset]${NC} $*"; }
ok() { echo -e "${GREEN}[infra-reset]${NC} $*"; }
warn() { echo -e "${YELLOW}[infra-reset]${NC} $*"; }
error() { echo -e "${RED}[infra-reset]${NC} $*" >&2; }

# Confirmar se não estiver em modo force
if [[ "${1:-}" != "--force" ]]; then
    echo "⚠️  AVISO: Esta operação irá destruir TODOS os dados do GABI!"
    echo "   - Containers Docker (gabi-*)"
    echo "   - Volumes Docker"
    echo "   - Diretórios de dados locais (data/postgres, data/elasticsearch, data/redis)"
    echo "   - Cache Python (__pycache__)"
    echo ""
    read -p "Tem certeza? Digite 'destruir' para confirmar: " confirm
    if [[ "$confirm" != "destruir" ]]; then
        warn "Operação cancelada."
        exit 0
    fi
fi

log "Iniciando hard reset da infraestrutura..."

# 1. Parar e remover containers via compose (incluindo órfãos)
log "1. Derrubando containers Docker..."
docker compose --profile infra --profile all down -v --remove-orphans 2>/dev/null || true

# 2. Remover containers específicos manualmente (garantia)
log "2. Removendo containers órfãos..."
for container in gabi-postgres gabi-elasticsearch gabi-redis gabi-tei; do
    if docker ps -a --format '{{.Names}}' | grep -qE "^${container}$"; then
        docker rm -f "$container" 2>/dev/null || true
        log "   Removido: $container"
    fi
done

# 3. Limpar redes órfãs
log "3. Limpando redes Docker..."
docker network prune -f 2>/dev/null || true

# 4. Limpar volumes não utilizados
log "4. Limpando volumes Docker..."
docker volume prune -f 2>/dev/null || true

# 5. Limpar sistema (imagens dangling)
log "5. Limpando imagens dangling..."
docker system prune -f 2>/dev/null || true

# 6. Limpar diretórios de dados locais
log "6. Limpando diretórios de dados..."
sudo rm -rf data/postgres/* data/elasticsearch/* data/redis/* 2>/dev/null || true

# 7. Recriar estrutura de diretórios
log "7. Recriando estrutura de diretórios..."
mkdir -p data/{postgres,elasticsearch,redis,tei/model}
chmod 777 data/elasticsearch 2>/dev/null || true

# 8. Limpar cache Python
log "8. Limpando cache Python..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true
find . -name "*.pyo" -delete 2>/dev/null || true
find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
rm -rf .mypy_cache 2>/dev/null || true

# Verificação final
log "Verificando estado pós-reset..."
CONTAINERS=$(docker ps -a --format '{{.Names}}' | grep -E "^gabi-" | wc -l)
if [[ "$CONTAINERS" -eq 0 ]]; then
    ok "✓ Nenhum container GABI remanescente"
else
    warn "⚠️  $CONTAINERS container(s) GABI ainda presentes:"
    docker ps -a --format 'table {{.Names}}\t{{.Status}}' | grep "^gabi-" || true
fi

ok "✓ Hard reset completo!"
ok "  Containers removidos: $CONTAINERS"
ok "  Dados locais limpos: data/{postgres,elasticsearch,redis}"
ok "  Cache Python limpo"
