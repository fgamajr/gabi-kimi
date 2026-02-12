#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# GABI - Development Environment Manager
# Interface unificada para todas as operações de desenvolvimento
#
# Uso: ./scripts/dev.sh [command] [options]
#
# Commands:
#   reset              Hard reset completo (docker, cache, processos)
#   infra-up           Sobe infraestrutura Docker
#   infra-down         Derruba infraestrutura Docker
#   infra-status       Mostra status dos containers
#   env-setup          Configura variáveis de ambiente (source)
#   ingest [source]    Executa ingestão (opcional: source específica)
#   test [pattern]     Roda testes (opcional: pattern)
#   shell              Abre shell com ambiente configurado
#   logs [service]     Mostra logs (postgres|elasticsearch|redis|tei)
#   reindex [source]   Reindexa PostgreSQL → Elasticsearch
#   doctor             Diagnóstico completo do ambiente
#
# Exemplos:
#   ./scripts/dev.sh reset && ./scripts/dev.sh infra-up
#   ./scripts/dev.sh ingest tcu_normas
#   ./scripts/dev.sh test tests/unit/test_discovery.py
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# Detectar diretório do projeto (funciona de qualquer lugar)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Logging
log() { echo -e "${BLUE}[dev]${NC} $*"; }
ok() { echo -e "${GREEN}[dev]${NC} $*"; }
warn() { echo -e "${YELLOW}[dev]${NC} $*"; }
error() { echo -e "${RED}[dev]${NC} $*" >&2; }
header() { echo -e "${BOLD}${CYAN}$*${NC}"; }

# Validação de diretório
if [[ ! -f "$PROJECT_DIR/pyproject.toml" ]]; then
    error "❌ Erro: Não parece ser o diretório do projeto GABI"
    exit 1
fi

# ═══════════════════════════════════════════════════════════════════════════════
# COMANDOS
# ═══════════════════════════════════════════════════════════════════════════════

cmd_reset() {
    header "═══════════════════════════════════════════════════"
    header "  HARD RESET - GABI Development Environment"
    header "═══════════════════════════════════════════════════"
    echo ""
    
    # 1. Matar processos
    log "1/5 Matando processos zumbis..."
    if [[ -x "$SCRIPT_DIR/kill_zombies.sh" ]]; then
        "$SCRIPT_DIR/kill_zombies.sh" || warn "Alguns processos podem persistir"
    else
        warn "kill_zombies.sh não encontrado, pulando..."
    fi
    echo ""
    
    # 2. Verificar portas
    log "2/5 Verificando conflitos de porta..."
    if [[ -x "$SCRIPT_DIR/check_prerequisites.sh" ]]; then
        "$SCRIPT_DIR/check_prerequisites.sh" --fix || {
            error "Não foi possível liberar todas as portas"
            exit 1
        }
    else
        warn "check_prerequisites.sh não encontrado, pulando..."
    fi
    echo ""
    
    # 3. Reset Docker
    log "3/5 Resetando infraestrutura Docker..."
    if [[ -x "$SCRIPT_DIR/infra_reset.sh" ]]; then
        "$SCRIPT_DIR/infra_reset.sh" --force || {
            error "Falha ao resetar infraestrutura"
            exit 1
        }
    else
        warn "infra_reset.sh não encontrado, pulando..."
    fi
    echo ""
    
    # 4. Limpar cache Python (redundância de segurança)
    log "4/5 Limpando cache Python..."
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -name "*.pyc" -delete 2>/dev/null || true
    ok "Cache Python limpo"
    echo ""
    
    # 5. Setup ambiente
    log "5/5 Configurando ambiente..."
    if [[ -f "$SCRIPT_DIR/setup_env.sh" ]]; then
        # shellcheck source=/dev/null
        source "$SCRIPT_DIR/setup_env.sh"
    else
        warn "setup_env.sh não encontrado"
    fi
    echo ""
    
    ok "═══════════════════════════════════════════════════"
    ok "  ✓ Hard reset completo!"
    ok "═══════════════════════════════════════════════════"
    echo ""
    log "Próximos passos:"
    log "  ./scripts/dev.sh infra-up     # Subir infraestrutura"
    log "  ./scripts/dev.sh ingest       # Ingerir dados"
}

cmd_infra_up() {
    header "═══════════════════════════════════════════════════"
    header "  SUBINDO INFRAESTRUTURA"
    header "═══════════════════════════════════════════════════"
    echo ""
    
    log "Iniciando containers Docker..."
    docker compose --profile infra up -d
    echo ""
    
    log "Aguardando containers ficarem healthy..."
    echo ""
    
    MAX_WAIT=120
    WAITED=0
    EXPECTED_CONTAINERS=("gabi-postgres" "gabi-elasticsearch" "gabi-redis" "gabi-tei")
    
    while [[ $WAITED -lt $MAX_WAIT ]]; do
        ALL_HEALTHY=true
        for cname in "${EXPECTED_CONTAINERS[@]}"; do
            status=$(docker inspect --format='{{.State.Health.Status}}' "$cname" 2>/dev/null || echo "not_found")
            if [[ "$status" != "healthy" ]]; then
                ALL_HEALTHY=false
                break
            fi
        done
        
        if $ALL_HEALTHY; then
            ok "Todos os containers healthy após ${WAITED}s"
            break
        fi
        
        printf "\r⏳ Aguardando... (${WAITED}s/${MAX_WAIT}s) - $cname: $status        "
        sleep 5
        WAITED=$((WAITED + 5))
    done
    
    printf "\n"
    echo ""
    
    if ! $ALL_HEALTHY; then
        warn "Timeout (${MAX_WAIT}s). Status atual:"
        docker ps --format 'table {{.Names}}\t{{.Status}}'
    fi
    
    echo ""
    header "Status dos containers:"
    docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep gabi- || true
    echo ""
    
    # Verificar TEI
    log "Testando TEI..."
    if curl -sf http://localhost:8080/health >/dev/null 2>&1; then
        ok "✓ TEI respondendo"
    else
        warn "⚠️  TEI não respondeu ainda (pode estar baixando modelo)"
    fi
    
    echo ""
    ok "Infraestrutura pronta!"
}

cmd_infra_down() {
    header "═══════════════════════════════════════════════════"
    header "  DERRUBANDO INFRAESTRUTURA"
    header "═══════════════════════════════════════════════════"
    echo ""
    
    log "Derrubando containers..."
    docker compose --profile infra --profile all down --remove-orphans
    
    ok "✓ Infraestrutura derrubada"
}

cmd_infra_status() {
    header "═══════════════════════════════════════════════════"
    header "  STATUS DA INFRAESTRUTURA"
    header "═══════════════════════════════════════════════════"
    echo ""
    
    echo "Containers:"
    docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep gabi- || echo "  Nenhum container GABI rodando"
    echo ""
    
    echo "Portas em uso:"
    for port in 5432 9200 6379 8080 8000; do
        if ss -tlnH 2>/dev/null | grep -qE ":${port}\b"; then
            pid=$(fuser "${port}/tcp" 2>/dev/null | xargs 2>/dev/null || true)
            proc=$(ps -p "$pid" -o comm= 2>/dev/null || echo "?")
            echo "  Port $port: $proc (PID $pid)"
        else
            echo "  Port $port: livre"
        fi
    done
    echo ""
    
    # Testar conexões
    echo "Testando serviços:"
    
    # PostgreSQL
    if docker exec gabi-postgres pg_isready -U gabi 2>/dev/null | grep -q "accepting"; then
        ok "  ✓ PostgreSQL"
    else
        error "  ✗ PostgreSQL"
    fi
    
    # Elasticsearch
    if curl -sf http://localhost:9200/_cluster/health >/dev/null 2>&1; then
        ok "  ✓ Elasticsearch"
    else
        error "  ✗ Elasticsearch"
    fi
    
    # Redis
    if docker exec gabi-redis redis-cli ping 2>/dev/null | grep -q "PONG"; then
        ok "  ✓ Redis"
    else
        error "  ✗ Redis"
    fi
    
    # TEI
    if curl -sf http://localhost:8080/health >/dev/null 2>&1; then
        ok "  ✓ TEI"
    else
        warn "  ⚠️  TEI (pode estar inicializando)"
    fi
}

cmd_env_setup() {
    header "═══════════════════════════════════════════════════"
    header "  CONFIGURANDO AMBIENTE"
    header "═══════════════════════════════════════════════════"
    echo ""
    
    if [[ -f "$SCRIPT_DIR/setup_env.sh" ]]; then
        # shellcheck source=/dev/null
        source "$SCRIPT_DIR/setup_env.sh"
        echo ""
        ok "Ambiente configurado!"
        echo ""
        log "Para ativar este ambiente em outro terminal, execute:"
        log "  source ./scripts/setup_env.sh"
    else
        error "setup_env.sh não encontrado!"
        exit 1
    fi
}

cmd_ingest() {
    local source="${1:-}"
    
    header "═══════════════════════════════════════════════════"
    header "  INGESTÃO DE DADOS"
    header "═══════════════════════════════════════════════════"
    echo ""
    
    # Configurar ambiente
    if [[ -f "$SCRIPT_DIR/setup_env.sh" ]]; then
        # shellcheck source=/dev/null
        source "$SCRIPT_DIR/setup_env.sh"
    else
        error "setup_env.sh não encontrado!"
        exit 1
    fi
    
    if [[ -n "$source" ]]; then
        log "Ingerindo source específica: $source"
        echo ""
        python -m gabi.cli ingest --source "$source" --max-docs-per-source 0
    else
        log "Ingerindo todas as sources configuradas"
        echo ""
        python -m gabi.cli ingest-schedule --sources-file sources.yaml
    fi
}

cmd_test() {
    local pattern="${1:-}"
    
    header "═══════════════════════════════════════════════════"
    header "  EXECUTANDO TESTES"
    header "═══════════════════════════════════════════════════"
    echo ""
    
    # Configurar ambiente
    if [[ -f "$SCRIPT_DIR/setup_env.sh" ]]; then
        # shellcheck source=/dev/null
        source "$SCRIPT_DIR/setup_env.sh"
    fi
    
    local pytest_args=(-v --timeout=60)
    
    if [[ -n "$pattern" ]]; then
        log "Rodando testes com pattern: $pattern"
        pytest_args+=("$pattern")
    else
        log "Rodando testes (excluindo test_indexer.py)"
        pytest_args+=(tests/ --ignore=tests/integration/test_indexer.py)
    fi
    
    echo ""
    python -m pytest "${pytest_args[@]}"
}

cmd_shell() {
    header "═══════════════════════════════════════════════════"
    header "  SHELL INTERATIVO"
    header "═══════════════════════════════════════════════════"
    echo ""
    
    # Configurar ambiente
    if [[ -f "$SCRIPT_DIR/setup_env.sh" ]]; then
        # shellcheck source=/dev/null
        source "$SCRIPT_DIR/setup_env.sh"
    fi
    
    log "Abrindo shell com ambiente GABI configurado"
    log "Dica: use 'python -m gabi.cli --help' para ver comandos"
    echo ""
    
    exec bash
}

cmd_logs() {
    local service="${1:-}"
    
    header "═══════════════════════════════════════════════════"
    header "  LOGS"
    header "═══════════════════════════════════════════════════"
    echo ""
    
    if [[ -z "$service" ]]; then
        log "Serviços disponíveis: postgres, elasticsearch, redis, tei"
        echo ""
        log "Uso: ./scripts/dev.sh logs [serviço]"
        return
    fi
    
    case "$service" in
        postgres|db)
            docker logs -f gabi-postgres --tail 100
            ;;
        elasticsearch|es)
            docker logs -f gabi-elasticsearch --tail 100
            ;;
        redis)
            docker logs -f gabi-redis --tail 100
            ;;
        tei)
            docker logs -f gabi-tei --tail 100
            ;;
        *)
            error "Serviço desconhecido: $service"
            log "Serviços disponíveis: postgres, elasticsearch, redis, tei"
            exit 1
            ;;
    esac
}

cmd_reindex() {
    local source="${1:-}"
    
    header "═══════════════════════════════════════════════════"
    header "  REINDEX PostgreSQL → Elasticsearch"
    header "═══════════════════════════════════════════════════"
    echo ""
    
    # Configurar ambiente
    if [[ -f "$SCRIPT_DIR/setup_env.sh" ]]; then
        # shellcheck source=/dev/null
        source "$SCRIPT_DIR/setup_env.sh"
    else
        error "setup_env.sh não encontrado!"
        exit 1
    fi
    
    if [[ -n "$source" ]]; then
        log "Reindexando source: $source"
        echo ""
        python scripts/reindex_to_es.py --source "$source"
    else
        log "Reindexando TODAS as sources"
        echo ""
        python scripts/reindex_to_es.py
    fi
}

cmd_doctor() {
    header "═══════════════════════════════════════════════════"
    header "  DOCTOR - DIAGNÓSTICO DO AMBIENTE"
    header "═══════════════════════════════════════════════════"
    echo ""
    
    local issues=0
    
    # 1. Docker
    log "1. Verificando Docker..."
    if command -v docker &>/dev/null; then
        ok "   ✓ Docker instalado"
        if docker compose version &>/dev/null; then
            ok "   ✓ Docker Compose disponível"
        else
            error "   ✗ Docker Compose não encontrado"
            issues=$((issues + 1))
        fi
    else
        error "   ✗ Docker não instalado"
        issues=$((issues + 1))
    fi
    echo ""
    
    # 2. Python / venv
    log "2. Verificando Python..."
    if [[ -d ".venv" ]]; then
        ok "   ✓ Virtual environment existe"
        if [[ -f ".venv/bin/activate" ]]; then
            ok "   ✓ Script de ativação presente"
        else
            error "   ✗ Script de ativação não encontrado"
            issues=$((issues + 1))
        fi
    else
        error "   ✗ Virtual environment não encontrado"
        error "     Execute: uv venv  ou  python -m venv .venv"
        issues=$((issues + 1))
    fi
    echo ""
    
    # 3. Portas
    log "3. Verificando portas..."
    for port in 5432 9200 6379 8080; do
        if ss -tlnH 2>/dev/null | grep -qE ":${port}\b"; then
            pid=$(fuser "${port}/tcp" 2>/dev/null | xargs 2>/dev/null || true)
            proc=$(ps -p "$pid" -o comm= 2>/dev/null || echo "?")
            warn "   ⚠️  Porta $port ocupada por $proc"
        else
            ok "   ✓ Porta $port livre"
        fi
    done
    echo ""
    
    # 4. Containers
    log "4. Verificando containers..."
    for container in gabi-postgres gabi-elasticsearch gabi-redis gabi-tei; do
        if docker ps --format '{{.Names}}' | grep -qE "^${container}$"; then
            ok "   ✓ $container rodando"
        else
            warn "   ⚠️  $container não encontrado"
        fi
    done
    echo ""
    
    # 5. Arquivos essenciais
    log "5. Verificando arquivos essenciais..."
    for file in sources.yaml pyproject.toml README.md; do
        if [[ -f "$file" ]]; then
            ok "   ✓ $file"
        else
            error "   ✗ $file não encontrado"
            issues=$((issues + 1))
        fi
    done
    echo ""
    
    # 6. Scripts auxiliares
    log "6. Verificando scripts auxiliares..."
    for script in infra_reset.sh check_prerequisites.sh kill_zombies.sh setup_env.sh; do
        if [[ -x "$SCRIPT_DIR/$script" ]]; then
            ok "   ✓ $script"
        else
            warn "   ⚠️  $script não encontrado ou não executável"
        fi
    done
    echo ""
    
    # Resumo
    header "═══════════════════════════════════════════════════"
    if [[ $issues -eq 0 ]]; then
        ok "  ✓ Tudo certo! Ambiente parece saudável."
    else
        warn "  ⚠️  $issues problema(s) encontrado(s)"
        echo ""
        log "Para corrigir problemas comuns, execute:"
        log "  ./scripts/dev.sh reset"
    fi
    header "═══════════════════════════════════════════════════"
}

cmd_help() {
    cat << 'EOF'
GABI - Development Environment Manager

Uso: ./scripts/dev.sh [command] [options]

Comandos:
  reset                    Hard reset completo (docker, cache, processos)
  infra-up                 Sobe infraestrutura Docker
  infra-down               Derruba infraestrutura Docker
  infra-status             Mostra status dos containers e portas
  env-setup                Configura variáveis de ambiente
  ingest [source]          Executa ingestão (opcional: source específica)
  test [pattern]           Roda testes (opcional: pattern)
  shell                    Abre shell com ambiente configurado
  logs [service]           Mostra logs (postgres|elasticsearch|redis|tei)
  reindex [source]         Reindexa PostgreSQL → Elasticsearch
  doctor                   Diagnóstico completo do ambiente
  help                     Mostra esta ajuda

Exemplos:
  # Reset completo e subir infra
  ./scripts/dev.sh reset && ./scripts/dev.sh infra-up

  # Ingerir apenas tcu_normas
  ./scripts/dev.sh ingest tcu_normas

  # Reindexar tcu_normas para Elasticsearch
  ./scripts/dev.sh reindex tcu_normas

  # Rodar testes específicos
  ./scripts/dev.sh test tests/unit/test_discovery.py

  # Ver logs do TEI em tempo real
  ./scripts/dev.sh logs tei

  # Diagnóstico completo
  ./scripts/dev.sh doctor

Dicas:
  - Sempre use 'reset' antes de começar um novo ciclo de desenvolvimento
  - 'shell' abre um terminal com todas as variáveis configuradas
  - 'doctor' verifica se tudo está ok sem fazer alterações

EOF
}

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

case "${1:-help}" in
    reset)
        cmd_reset
        ;;
    infra-up)
        cmd_infra_up
        ;;
    infra-down)
        cmd_infra_down
        ;;
    infra-status)
        cmd_infra_status
        ;;
    env-setup)
        cmd_env_setup
        ;;
    ingest)
        shift
        cmd_ingest "$@"
        ;;
    test)
        shift
        cmd_test "$@"
        ;;
    shell)
        cmd_shell
        ;;
    logs)
        shift
        cmd_logs "$@"
        ;;
    reindex)
        shift
        cmd_reindex "$@"
        ;;
    doctor)
        cmd_doctor
        ;;
    help|--help|-h|*)
        cmd_help
        ;;
esac
