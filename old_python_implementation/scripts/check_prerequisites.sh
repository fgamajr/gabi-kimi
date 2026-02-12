#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# GABI - Prerequisites Check
# Verifica e resolve conflitos de portas e serviços
# Uso: ./scripts/check_prerequisites.sh [--fix]
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

log() { echo -e "${BLUE}[pre-check]${NC} $*"; }
ok() { echo -e "${GREEN}[pre-check]${NC} $*"; }
warn() { echo -e "${YELLOW}[pre-check]${NC} $*"; }
error() { echo -e "${RED}[pre-check]${NC} $*" >&2; }

AUTO_FIX=false
if [[ "${1:-}" == "--fix" ]]; then
    AUTO_FIX=true
fi

# Mapa de portas e nomes de serviços
REQUIRED_PORTS=(5432 9200 6379 8080 8000)
PORT_NAMES=("PostgreSQL" "Elasticsearch" "Redis" "TEI" "API")
# Serviços systemd conhecidos que podem conflitar
SYSTEMD_SERVICES=(
    "postgresql"
    "postgresql@"
    "postgres"
    "redis-server"
    "redis"
    "elasticsearch"
)

# Função para verificar se porta está em uso
port_in_use() {
    local port=$1
    ss -tlnH 2>/dev/null | grep -qE ":${port}\b" && return 0
    bash -c "echo >/dev/tcp/127.0.0.1/${port}" 2>/dev/null && return 0
    return 1
}

# Função para obter processo na porta
get_port_process() {
    local port=$1
    fuser "${port}/tcp" 2>/dev/null | xargs 2>/dev/null || echo ""
}

# Função para parar serviço systemd
stop_systemd_service() {
    local service=$1
    if systemctl is-active --quiet "$service" 2>/dev/null; then
        log "Parando serviço systemd: $service"
        if sudo systemctl stop "$service" 2>/dev/null; then
            sleep 2
            return 0
        else
            warn "Falha ao parar $service (precisa de sudo?)"
            return 1
        fi
    fi
    return 1
}

# Função para matar processo
kill_process() {
    local pid=$1
    local signal=${2:-TERM}
    
    if kill -$signal "$pid" 2>/dev/null; then
        sleep 1
        return 0
    fi
    
    # Tentar com sudo se falhar
    if sudo kill -$signal "$pid" 2>/dev/null; then
        sleep 1
        return 0
    fi
    
    return 1
}

log "Verificando pré-requisitos..."
log "Portas necessárias: ${REQUIRED_PORTS[*]}"

PORTS_BLOCKED=false
BLOCKED_PORTS=()

for i in "${!REQUIRED_PORTS[@]}"; do
    port="${REQUIRED_PORTS[$i]}"
    name="${PORT_NAMES[$i]}"
    
    if ! port_in_use "$port"; then
        ok "✓ Porta $port ($name) está livre"
        continue
    fi
    
    BLOCKED_PORTS+=("$port")
    warn "⚠️  Porta $port ($name) está em uso"
    
    pid=$(get_port_process "$port")
    if [[ -n "$pid" ]]; then
        proc_name=$(ps -p "$pid" -o comm= 2>/dev/null || echo "unknown")
        warn "   Processo: $proc_name (PID $pid)"
    fi
    
    if [[ "$AUTO_FIX" == false ]]; then
        PORTS_BLOCKED=true
        continue
    fi
    
    # Tentar auto-fix
    log "   Tentando liberar porta $port..."
    
    # 1. Tentar parar serviço systemd
    for svc in "${SYSTEMD_SERVICES[@]}"; do
        if stop_systemd_service "$svc"; then
            break
        fi
    done
    
    # 2. Se ainda em uso, matar processo
    if port_in_use "$port"; then
        pid=$(get_port_process "$port")
        if [[ -n "$pid" ]]; then
            log "   Matando PID $pid..."
            if kill_process "$pid" TERM; then
                ok "   Processo terminado"
            elif kill_process "$pid" KILL; then
                ok "   Processo morto (KILL)"
            else
                error "   Não foi possível matar PID $pid"
                PORTS_BLOCKED=true
            fi
        fi
    fi
    
    # Verificação final
    if port_in_use "$port"; then
        error "❌ Porta $port ainda está em uso"
        PORTS_BLOCKED=true
    else
        ok "✓ Porta $port liberada"
    fi
done

echo ""
if [[ "$PORTS_BLOCKED" == true ]]; then
    error "❌ PRÉ-REQUISITOS NÃO ATENDIDOS"
    error ""
    error "Portas bloqueadas: ${BLOCKED_PORTS[*]}"
    error ""
    error "Para resolver automaticamente, execute:"
    error "  ./scripts/check_prerequisites.sh --fix"
    error ""
    error "Ou resolva manualmente:"
    for port in "${BLOCKED_PORTS[@]}"; do
        error "  sudo fuser -k ${port}/tcp"
    done
    exit 1
fi

ok "✓ Todas as portas necessárias estão livres"
exit 0
