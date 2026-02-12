#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# GABI - Kill Zombie Processes
# Mata todos os processos relacionados ao GABI
# Uso: ./scripts/kill_zombies.sh
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

log() { echo -e "${BLUE}[kill-zombies]${NC} $*"; }
ok() { echo -e "${GREEN}[kill-zombies]${NC} $*"; }
warn() { echo -e "${YELLOW}[kill-zombies]${NC} $*"; }
error() { echo -e "${RED}[kill-zombies]${NC} $*" >&2; }

log "Procurando processos GABI zumbis..."

# Padrões de processos a procurar e matar
# Ordem: mais específicos primeiro
PATTERNS=(
    "gabi.main:app"          # API uvicorn
    "gabi.worker"            # Celery worker
    "celery.*worker"         # Celery (variações)
    "celery.*beat"           # Celery beat
    "python.*gabi"           # Python rodando gabi
    "uvicorn"                # Uvicorn genérico
)

KILLED_COUNT=0

for pattern in "${PATTERNS[@]}"; do
    # Encontrar PIDs (excluindo o próprio grep e este script)
    pids=$(pgrep -f "$pattern" 2>/dev/null | grep -v "$$" || true)
    
    if [[ -z "$pids" ]]; then
        continue
    fi
    
    log "Encontrados processos para '$pattern':"
    
    for pid in $pids; do
        # Verificar se PID ainda existe
        if ! kill -0 "$pid" 2>/dev/null; then
            continue
        fi
        
        # Obter informações do processo
        cmdline=$(ps -p "$pid" -o args= 2>/dev/null || echo "unknown")
        proc_name=$(ps -p "$pid" -o comm= 2>/dev/null || echo "unknown")
        
        # Truncar cmdline para display
        cmd_display="${cmdline:0:80}"
        if [[ ${#cmdline} -gt 80 ]]; then
            cmd_display="${cmd_display}..."
        fi
        
        log "  PID $pid ($proc_name): $cmd_display"
        
        # Tentar SIGTERM primeiro
        if kill -TERM "$pid" 2>/dev/null; then
            log "    Enviado SIGTERM..."
            
            # Aguardar até 3 segundos para terminar
            for i in {1..6}; do
                sleep 0.5
                if ! kill -0 "$pid" 2>/dev/null; then
                    break
                fi
            done
        fi
        
        # Se ainda existe, usar SIGKILL
        if kill -0 "$pid" 2>/dev/null; then
            log "    Processo resistiu, usando SIGKILL..."
            if kill -KILL "$pid" 2>/dev/null; then
                sleep 0.5
            else
                # Tentar com sudo
                sudo kill -KILL "$pid" 2>/dev/null || true
                sleep 0.5
            fi
        fi
        
        # Verificar se morreu
        if ! kill -0 "$pid" 2>/dev/null; then
            ok "    ✓ PID $pid terminado"
            KILLED_COUNT=$((KILLED_COUNT + 1))
        else
            error "    ✗ Não foi possível matar PID $pid"
        fi
    done
done

# Verificar também processos nas portas específicas
log "Verificando processos nas portas críticas..."
CRITICAL_PORTS=(8000 5432 6379)

for port in "${CRITICAL_PORTS[@]}"; do
    pid=$(fuser "${port}/tcp" 2>/dev/null | xargs 2>/dev/null || true)
    if [[ -n "$pid" ]]; then
        proc_name=$(ps -p "$pid" -o comm= 2>/dev/null || echo "unknown")
        warn "  Porta $port ocupada por $proc_name (PID $pid)"
        
        # Verificar se é um processo relacionado ao projeto
        cmdline=$(ps -p "$pid" -o args= 2>/dev/null || echo "")
        if echo "$cmdline" | grep -qE "(gabi|celery|uvicorn|python)"; then
            log "    Matando processo relacionado..."
            kill -TERM "$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || sudo kill -KILL "$pid" 2>/dev/null || true
            sleep 0.5
            if ! kill -0 "$pid" 2>/dev/null; then
                ok "    ✓ PID $pid terminado"
                KILLED_COUNT=$((KILLED_COUNT + 1))
            fi
        fi
    fi
done

echo ""
if [[ $KILLED_COUNT -gt 0 ]]; then
    ok "✓ $KILLED_COUNT processo(s) terminado(s)"
else
    log "✓ Nenhum processo zumbi encontrado"
fi

exit 0
