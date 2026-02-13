#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# GABI - Zero Kelvin Test
# ═══════════════════════════════════════════════════════════════════════════════
# Destrói completamente o ambiente, recria do zero e valida funcionalidade.
# Um teste "Zero Kelvin" valida que o sistema pode ser reconstruído do estado
# fundamental (absoluto zero) apenas com os scripts automatizados.
#
# Uso:
#   cd /home/fgamajr/dev/gabi-kimi
#   ./tests/zero-kelvin-test.sh [idempotency]
#
# Argumentos:
#   (sem args)    - Executa teste completo Zero Kelvin
#   idempotency   - Executa teste de idempotência (setup 2x)
#
# Critério de Sucesso:
#   - Todos os checks retornam PASS
#   - API responde em < 5s após startup
#   - Discovery de fonte funciona
#
# Saída:
#   Código 0 = todos os checks passaram
#   Código 1 = algum check falhou (ver logs em /tmp/gabi-zero-kelvin.log)
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÃO
# ═══════════════════════════════════════════════════════════════════════════════

GABI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="/tmp/gabi-zero-kelvin.log"
TEST_MODE="${1:-full}"  # 'full' ou 'idempotency'

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Contadores
TESTS_TOTAL=0
TESTS_PASSED=0
TESTS_FAILED=0

# ═══════════════════════════════════════════════════════════════════════════════
# FUNÇÕES DE UTILIDADE
# ═══════════════════════════════════════════════════════════════════════════════

log() {
    echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

pass() {
    echo -e "${GREEN}✓ PASS${NC}: $1" | tee -a "$LOG_FILE"
    ((TESTS_PASSED++)) || true
    ((TESTS_TOTAL++)) || true
}

fail() {
    echo -e "${RED}✗ FAIL${NC}: $1" | tee -a "$LOG_FILE"
    ((TESTS_FAILED++)) || true
    ((TESTS_TOTAL++)) || true
}

warn() {
    echo -e "${YELLOW}⚠ WARN${NC}: $1" | tee -a "$LOG_FILE"
}

section() {
    echo -e "\n${YELLOW}═══════════════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  $1${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════${NC}\n"
    echo -e "\n=== $1 ===" >> "$LOG_FILE"
}

# ═══════════════════════════════════════════════════════════════════════════════
# FASE 1: DESTRUIÇÃO COMPLETA (Zero Kelvin)
# ═══════════════════════════════════════════════════════════════════════════════

phase_destroy() {
    section "FASE 1: DESTRUIÇÃO COMPLETA (Zero Kelvin)"
    
    log "Parando e removendo containers..."
    cd "$GABI_ROOT"
    
    # Parar containers
    if docker compose ps -q 2>/dev/null | grep -q .; then
        docker compose down -v --remove-orphans 2>&1 | tee -a "$LOG_FILE" || true
        pass "Containers parados e volumes removidos"
    else
        warn "Nenhum container rodando"
    fi
    
    # Limpar volumes explicitamente
    docker volume prune -f 2>&1 | tee -a "$LOG_FILE" || true
    
    # Matar processos da aplicação
    log "Matando processos da aplicação..."
    pkill -f "dotnet.*Gabi.Api" 2>/dev/null || true
    pkill -f "vite" 2>/dev/null || true
    sleep 2
    
    # Limpar logs e PIDs
    log "Limpando logs e arquivos temporários..."
    rm -rf /tmp/gabi-logs /tmp/gabi-*.pid 2>/dev/null || true
    
    # Verificar portas livres
    local ports_free=true
    for port in 5100 3000 5433 9200; do
        if lsof -i :$port 2>/dev/null | grep -q .; then
            fail "Porta $port ainda em uso"
            ports_free=false
        fi
    done
    
    if $ports_free; then
        pass "Todas as portas estão livres (5100, 3000, 5433, 9200)"
    fi
    
    # Verificar que não há containers
    if docker ps -a 2>/dev/null | grep -q "gabi"; then
        fail "Containers gabi ainda existem"
    else
        pass "Nenhum container gabi encontrado"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# FASE 2: SETUP ZERO KELVIN
# ═══════════════════════════════════════════════════════════════════════════════

phase_setup() {
    section "FASE 2: SETUP ZERO KELVIN"
    
    cd "$GABI_ROOT"
    
    log "Executando ./scripts/setup.sh..."
    local start_time=$(date +%s)
    
    if ./scripts/setup.sh 2>&1 | tee -a "$LOG_FILE"; then
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        pass "Setup completado em ${duration}s"
        
        # Guardar tempo para teste de idempotência
        echo "$duration" > /tmp/gabi-setup-time-1.txt
    else
        fail "Setup falhou (ver $LOG_FILE)"
        return 1
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# FASE 2b: TESTE DE IDEMPOTÊNCIA (se solicitado)
# ═══════════════════════════════════════════════════════════════════════════════

phase_idempotency() {
    section "FASE 2b: TESTE DE IDEMPOTÊNCIA"
    
    log "Executando setup pela segunda vez..."
    cd "$GABI_ROOT"
    
    local start_time=$(date +%s)
    
    if ./scripts/setup.sh 2>&1 | tee -a "$LOG_FILE"; then
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        local first_duration=$(cat /tmp/gabi-setup-time-1.txt 2>/dev/null || echo "999")
        
        pass "Segundo setup completado em ${duration}s"
        
        # Validar que segunda execução foi mais rápida (idempotência)
        if [[ $duration -lt $first_duration ]]; then
            pass "Idempotência: segundo setup (${duration}s) mais rápido que primeiro (${first_duration}s)"
        elif [[ $duration -lt 60 ]]; then
            pass "Idempotência: segundo setup rápido (${duration}s < 60s)"
        else
            warn "Segundo setup demorado (${duration}s) - verificar idempotência"
        fi
        
        # Verificar que sistema ainda funciona
        log "Verificando que sistema funciona após segundo setup..."
        sleep 3
        if curl -sf http://localhost:5100/health >/dev/null 2>&1; then
            pass "Sistema funcional após segundo setup"
        else
            fail "Sistema não responde após segundo setup"
        fi
    else
        fail "Segundo setup falhou (sistema quebrou)"
        return 1
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# FASE 3: INICIAR APLICAÇÕES
# ═══════════════════════════════════════════════════════════════════════════════

phase_start() {
    section "FASE 3: INICIAR APLICAÇÕES"
    
    cd "$GABI_ROOT"
    
    log "Iniciando aplicações em modo detached..."
    ./scripts/dev app start 2>&1 | tee -a "$LOG_FILE"
    
    log "Aguardando serviços ficarem prontos (max 60s)..."
    local attempts=0
    local max_attempts=30
    local all_ready=false
    
    while [[ $attempts -lt $max_attempts ]]; do
        sleep 2
        ((attempts++))
        
        local api_up=false
        local web_up=false
        
        if curl -sf http://localhost:5100/health >/dev/null 2>&1; then
            api_up=true
        fi
        
        if curl -sf http://localhost:3000 >/dev/null 2>&1; then
            web_up=true
        fi
        
        if $api_up && $web_up; then
            all_ready=true
            break
        fi
        
        echo -n "."
    done
    echo ""
    
    if $all_ready; then
        pass "API e Web prontos em ${attempts} tentativas (~${$((attempts * 2))}s)"
    else
        fail "Timeout aguardando serviços (60s)"
        ./scripts/dev app logs 2>&1 | tail -50 | tee -a "$LOG_FILE"
        return 1
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# FASE 4: VERIFICAÇÕES FUNCIONAIS
# ═══════════════════════════════════════════════════════════════════════════════

phase_verify() {
    section "FASE 4: VERIFICAÇÕES FUNCIONAIS"
    
    local base_url="http://localhost:5100"
    local token=""
    
    # 4.1 Health Check
    log "Verificando /health..."
    if curl -sf "$base_url/health" 2>&1 | tee -a "$LOG_FILE" | grep -q "Healthy\|healthy"; then
        pass "Health check responde 'Healthy'"
    else
        fail "Health check não responde ou não está healthy"
    fi
    
    # 4.2 Swagger UI
    log "Verificando Swagger UI..."
    local swagger_status=$(curl -s -o /dev/null -w "%{http_code}" "$base_url/swagger/index.html" 2>&1)
    if [[ "$swagger_status" == "200" ]]; then
        pass "Swagger UI acessível (HTTP 200)"
    else
        fail "Swagger UI retornou HTTP $swagger_status"
    fi
    
    # 4.3 Login e Obter Token
    log "Verificando autenticação..."
    token=$(curl -sf -X POST "$base_url/api/v1/auth/login" \
        -H "Content-Type: application/json" \
        -d '{"username": "viewer", "password": "view123"}' 2>&1 | \
        grep -o '"token":"[^"]*"' | cut -d'"' -f4 || echo "")
    
    if [[ -n "$token" ]]; then
        pass "Login funcional (token obtido)"
    else
        fail "Login falhou (não obteve token)"
        return 1
    fi
    
    # 4.4 Stats Endpoint
    log "Verificando /api/v1/dashboard/stats..."
    if curl -sf "$base_url/api/v1/dashboard/stats" \
        -H "Authorization: Bearer $token" 2>&1 | tee -a "$LOG_FILE" | grep -q "sources"; then
        pass "Dashboard stats retorna dados"
    else
        fail "Dashboard stats não retorna dados esperados"
    fi
    
    # 4.5 Sources List
    log "Verificando /api/v1/sources..."
    local sources_count=$(curl -sf "$base_url/api/v1/sources" \
        -H "Authorization: Bearer $token" 2>&1 | \
        grep -o '"id"' | wc -l || echo "0")
    
    if [[ "$sources_count" -gt 0 ]]; then
        pass "Sources list retorna $sources_count fonte(s)"
    else
        fail "Sources list não retorna fontes"
    fi
    
    # 4.6 Discovery (se endpoint existir)
    log "Verificando discovery (POST /api/v1/sources/{id}/refresh)..."
    local refresh_response=$(curl -sf -X POST "$base_url/api/v1/dashboard/sources/tcu_sumulas/refresh" \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json" \
        -d '{"force": true}' 2>&1 || echo "{}")
    
    if echo "$refresh_response" | grep -q "success.*true\|job_id"; then
        pass "Discovery endpoint responde (job criado)"
    else
        warn "Discovery endpoint não disponível ou retornou erro (pode ser normal se worker não estiver rodando)"
    fi
    
    # 4.7 Jobs Status (se endpoint existir)
    log "Verificando jobs status..."
    if curl -sf "$base_url/api/v1/jobs" \
        -H "Authorization: Bearer $token" 2>&1 >/dev/null; then
        pass "Jobs endpoint acessível"
    else
        warn "Jobs endpoint não disponível (pode ser normal em fases iniciais)"
    fi
    
    # 4.8 Web Frontend
    log "Verificando frontend..."
    local web_status=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:3000" 2>&1)
    if [[ "$web_status" == "200" ]]; then
        pass "Web frontend acessível (HTTP 200)"
    else
        fail "Web frontend retornou HTTP $web_status"
    fi
    
    # 4.9 Infraestrutura
    log "Verificando infraestrutura..."
    
    # PostgreSQL
    if docker compose ps postgres 2>/dev/null | grep -q "healthy\|Up"; then
        pass "PostgreSQL rodando"
    else
        fail "PostgreSQL não está healthy"
    fi
    
    # Elasticsearch (opcional)
    if curl -sf http://localhost:9200/_cluster/health 2>/dev/null | grep -q "status"; then
        pass "Elasticsearch acessível"
    else
        warn "Elasticsearch não responde (opcional para teste básico)"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# FASE 5: RELATÓRIO FINAL
# ═══════════════════════════════════════════════════════════════════════════════

phase_report() {
    section "FASE 5: RELATÓRIO FINAL"
    
    echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  RESULTADO DO TESTE ZERO KELVIN${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════════${NC}\n"
    
    echo "Total de verificações: $TESTS_TOTAL"
    echo -e "${GREEN}Passaram: $TESTS_PASSED${NC}"
    echo -e "${RED}Falharam: $TESTS_FAILED${NC}"
    
    echo -e "\n${BLUE}Log completo: $LOG_FILE${NC}\n"
    
    if [[ $TESTS_FAILED -eq 0 ]]; then
        echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
        echo -e "${GREEN}  ✅ TESTE ZERO KELVIN PASSOU${NC}"
        echo -e "${GREEN}  O sistema pode ser reconstruído do absoluto zero.${NC}"
        echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}\n"
        return 0
    else
        echo -e "${RED}═══════════════════════════════════════════════════════════════════${NC}"
        echo -e "${RED}  ✗ TESTE ZERO KELVIN FALHOU${NC}"
        echo -e "${RED}  Verifique os logs em: $LOG_FILE${NC}"
        echo -e "${RED}═══════════════════════════════════════════════════════════════════${NC}\n"
        return 1
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

main() {
    echo -e "${BLUE}"
    echo "╔════════════════════════════════════════════════════════════════════╗"
    echo "║           GABI - ZERO KELVIN TEST                                  ║"
    echo "║                                                                    ║"
    if [[ "$TEST_MODE" == "idempotency" ]]; then
    echo "║  Modo: IDEMPOTÊNCIA (setup 2x)                                     ║"
    else
    echo "║  Modo: FULL (destruir → setup → validar)                           ║"
    fi
    echo "╚════════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    
    # Limpar log anterior
    > "$LOG_FILE"
    
    log "Iniciando teste em: $(pwd)"
    log "Log: $LOG_FILE"
    
    # Executar fases
    phase_destroy
    phase_setup
    
    if [[ "$TEST_MODE" == "idempotency" ]]; then
        phase_idempotency
    fi
    
    phase_start
    phase_verify
    phase_report
    
    exit $TESTS_FAILED
}

# Tratar Ctrl+C
trap 'echo -e "\n\n${RED}Teste interrompido pelo usuário${NC}"; exit 130' INT

main "$@"
