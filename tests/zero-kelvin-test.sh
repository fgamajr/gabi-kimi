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
#   (sem args)    - Modo docker-only (recomendado): só Docker, sem dotnet/npm no host
#   docker-only   - Idem (explícito)
#   full          - Modo legado: setup.sh + app no host (requer dotnet/npm)
#   idempotency   - Idempotência no modo full (setup 2x)
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
TEST_MODE="${1:-docker-only}"  # 'docker-only' (default) | 'full' | 'idempotency'

# Pipeline evidence (for report)
PIPELINE_SEED_STATUS="" PIPELINE_SEED_N="" PIPELINE_SEED_IDS=""
PIPELINE_DISCOVERY_STATUS="" PIPELINE_DISCOVERY_JOBS="" PIPELINE_DISCOVERY_LINKS="" PIPELINE_DISCOVERY_SOURCE=""
PIPELINE_FETCH_STATUS="" PIPELINE_FETCH_LINKS="" PIPELINE_FETCH_SOURCE=""

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
    
    # Garantir que containers do projeto não seguram portas (Redis=6380, etc.)
    log "Parando containers que usam portas do projeto..."
    for port in 6380 5433 9200 5100 3000; do
        docker ps -q --filter "publish=$port" 2>/dev/null | xargs -r docker stop 2>/dev/null || true
    done
    sleep 2

    # Liberar portas: matar qualquer processo que ainda esteja usando (Redis, etc.)
    log "Liberando portas 6380, 5433, 9200, 5100, 3000..."
    for port in 6380 5433 9200 5100 3000; do
        if lsof -i :$port >/dev/null 2>&1 || ss -tlnp 2>/dev/null | grep -q ":$port "; then
            if command -v fuser >/dev/null 2>&1; then
                fuser -k "$port/tcp" 2>/dev/null || true
            else
                pids=$(lsof -ti :$port 2>/dev/null)
                [[ -n "$pids" ]] && echo "$pids" | xargs kill -9 2>/dev/null || true
            fi
            sleep 1
        fi
    done
    sleep 2

    # Verificar portas livres
    local ports_free=true
    for port in 6380 5100 3000 5433 9200; do
        if lsof -i :$port 2>/dev/null | grep -q .; then
            fail "Porta $port ainda em uso (rode o teste com sudo para liberar processos do sistema)"
            ports_free=false
        fi
    done

    if $ports_free; then
        pass "Todas as portas estão livres (6380, 5100, 3000, 5433, 9200)"
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
    
    if [[ "$TEST_MODE" == "docker-only" ]]; then
        # Modo Docker-only: não usar dotnet/npm do host; só compose
        log "Modo docker-only: subindo infra e buildando imagens..."
        local start_time=$(date +%s)
        
        if lsof -i :6380 >/dev/null 2>&1 || ss -tlnp 2>/dev/null | grep -q ':6380 '; then
            fail "Porta 6380 já está em uso. Libere com: docker stop \$(docker ps -q --filter publish=6380) ou pare o processo que usa a porta."
            return 1
        fi
        
        if ! docker compose up -d 2>&1 | tee -a "$LOG_FILE"; then
            fail "docker compose up -d falhou"
            return 1
        fi
        log "Aguardando Postgres e Redis healthy..."
        local infra_ok=false
        for i in $(seq 1 45); do
            if docker compose exec -T postgres pg_isready -U gabi -d gabi >/dev/null 2>&1 && \
               docker compose exec -T redis redis-cli ping >/dev/null 2>&1; then
                infra_ok=true
                break
            fi
            sleep 1
        done
        if ! $infra_ok; then
            fail "Infra (Postgres/Redis) não ficou healthy. Verifique: docker compose ps"
            return 1
        fi
        
        log "Buildando API e Worker..."
        if ! docker compose build api worker 2>&1 | tee -a "$LOG_FILE"; then
            fail "Build das imagens api/worker falhou"
            return 1
        fi
        
        log "Subindo API e Worker (profiles api + worker)..."
        docker compose --profile api --profile worker up -d 2>&1 | tee -a "$LOG_FILE"
        
        log "Aguardando API em /health (até 90s)..."
        local attempts=0
        while [[ $attempts -lt 45 ]]; do
            if curl -sf --max-time 3 http://localhost:5100/health >/dev/null 2>&1; then
                pass "Setup docker-only completado (API pronta)"
                local end_time=$(date +%s)
                echo $((end_time - start_time)) >> "$LOG_FILE"
                return 0
            fi
            sleep 2
            ((attempts++)) || true
        done
        fail "Timeout aguardando API após docker compose up"
        return 1
    fi
    
    # Modo full: setup.sh (requer dotnet/npm no host)
    log "Executando ./scripts/setup.sh..."
    local start_time=$(date +%s)
    
    if ./scripts/setup.sh 2>&1 | tee -a "$LOG_FILE"; then
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        pass "Setup completado em ${duration}s"
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
    
    if [[ "$TEST_MODE" == "docker-only" ]]; then
        log "Modo docker-only: API e Worker já estão up; verificando API..."
        if curl -sf --max-time 5 http://localhost:5100/health >/dev/null 2>&1; then
            pass "API pronta (container)"
        else
            fail "API não responde em localhost:5100"
            return 1
        fi
        return 0
    fi
    
    log "Iniciando aplicações em modo detached (host)..."
    ./scripts/dev app start 2>&1 | tee -a "$LOG_FILE"
    
    log "Aguardando serviços ficarem prontos (max 60s)..."
    local attempts=0
    local max_attempts=30
    local all_ready=false
    
    while [[ $attempts -lt $max_attempts ]]; do
        sleep 2
        ((attempts++)) || true
        
        local api_up=false
        local web_up=false
        
        curl -sf http://localhost:5100/health >/dev/null 2>&1 && api_up=true
        curl -sf http://localhost:3000 >/dev/null 2>&1 && web_up=true
        
        if $api_up && $web_up; then
            all_ready=true
            break
        fi
        echo -n "."
    done
    echo ""
    
    if $all_ready; then
        pass "API e Web prontos em ${attempts} tentativas (~$((attempts * 2))s)"
    else
        fail "Timeout aguardando serviços (60s)"
        ./scripts/dev app logs 2>&1 | tail -50 | tee -a "$LOG_FILE"
        return 1
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# FASE 4: VERIFICAÇÕES FUNCIONAIS + PIPELINE (Seed / Discovery / Fetch)
# ═══════════════════════════════════════════════════════════════════════════════

phase_verify() {
    section "FASE 4: VERIFICAÇÕES FUNCIONAIS"
    
    local base_url="http://localhost:5100"
    local token_viewer=""
    local token_operator=""
    
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
    
    # 4.3 Login (viewer + operator para pipeline)
    log "Verificando autenticação..."
    token_viewer=$(curl -sf -X POST "$base_url/api/v1/auth/login" \
        -H "Content-Type: application/json" \
        -d '{"username": "viewer", "password": "view123"}' 2>&1 | \
        grep -o '"token":"[^"]*"' | cut -d'"' -f4 || echo "")
    token_operator=$(curl -sf -X POST "$base_url/api/v1/auth/login" \
        -H "Content-Type: application/json" \
        -d '{"username": "operator", "password": "op123"}' 2>&1 | \
        grep -o '"token":"[^"]*"' | cut -d'"' -f4 || echo "")
    
    if [[ -n "$token_viewer" ]]; then
        pass "Login funcional (token obtido)"
    else
        fail "Login falhou (não obteve token)"
        return 1
    fi
    
    if [[ -z "$token_operator" ]]; then
        fail "Login operator falhou (necessário para seed/refresh)"
        return 1
    fi
    
    # 4.4 Stats
    log "Verificando /api/v1/dashboard/stats..."
    if curl -sf "$base_url/api/v1/dashboard/stats" \
        -H "Authorization: Bearer $token_viewer" 2>&1 | tee -a "$LOG_FILE" | grep -q "sources"; then
        pass "Dashboard stats retorna dados"
    else
        fail "Dashboard stats não retorna dados esperados"
    fi
    
    # ═══ Pipeline: Seed ─────────────────────────────────────────────────────
    section "FASE 4b: PIPELINE – Seed / Discovery / Fetch"
    
    log "Pipeline – Seed (POST /api/v1/dashboard/seed)..."
    local seed_http_code
    seed_http_code=$(curl -s -o /tmp/gabi-seed-response.json -w "%{http_code}" -X POST "$base_url/api/v1/dashboard/seed" \
        -H "Authorization: Bearer $token_operator" -H "Content-Type: application/json" 2>/dev/null || echo "000")
    
    if [[ "$seed_http_code" == "200" ]]; then
        # Seed é assíncrono (job catalog_seed no Worker): aguardar seed_runs ser preenchido (até 60s)
        log "Aguardando Worker concluir seed (poll GET /api/v1/dashboard/seed/last)..."
        local seed_done=false
        for _ in $(seq 1 20); do
            if curl -sf "$base_url/api/v1/dashboard/seed/last" -H "Authorization: Bearer $token_viewer" 2>/dev/null | grep -q '"status"'; then
                seed_done=true
                break
            fi
            sleep 3
        done
        if ! $seed_done; then
            fail "Seed – Worker não concluiu seed em 60s (GET /dashboard/seed/last sem registro)"
            PIPELINE_SEED_STATUS="FAIL"
            PIPELINE_SEED_N="0"
        else
            local sources_json
            sources_json=$(curl -sf "$base_url/api/v1/sources" -H "Authorization: Bearer $token_viewer" 2>/dev/null || echo "[]")
            local n_sources
            n_sources=$(echo "$sources_json" | grep -o '"id"' | wc -l || echo "0")
            if [[ "${n_sources:-0}" -ge 1 ]]; then
                pass "Seed – ${n_sources} fontes registradas"
                PIPELINE_SEED_STATUS="PASS"
                PIPELINE_SEED_N="$n_sources"
                PIPELINE_SEED_IDS=$(echo "$sources_json" | grep -o '"id"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/.*"\([^"]*\)" *$/\1/' | head -10 | tr '\n' ',' | sed 's/,$//')
            else
                fail "Seed – nenhuma fonte registrada após seed"
                PIPELINE_SEED_STATUS="FAIL"
                PIPELINE_SEED_N="0"
            fi
        fi
    else
        fail "Seed – API retornou HTTP $seed_http_code"
        PIPELINE_SEED_STATUS="FAIL"
        PIPELINE_SEED_N="0"
    fi
    
    # Primeira fonte para discovery/fetch (ex.: tcu_sumulas)
    local pipeline_source_id="tcu_sumulas"
    log "Pipeline – Discovery (POST .../sources/${pipeline_source_id}/refresh)..."
    local refresh_code refresh_body
    refresh_code=$(curl -s -o /tmp/gabi-refresh-response.json -w "%{http_code}" -X POST "$base_url/api/v1/dashboard/sources/${pipeline_source_id}/refresh" \
        -H "Authorization: Bearer $token_operator" -H "Content-Type: application/json" -d '{"force": true}' 2>/dev/null || echo "000")
    refresh_body=$(cat /tmp/gabi-refresh-response.json 2>/dev/null || echo "{}")
    
    if [[ "$refresh_code" == "200" ]] && echo "$refresh_body" | grep -q "success.*true\|job_id"; then
        pass "Discovery – job criado para ${pipeline_source_id}"
        PIPELINE_DISCOVERY_STATUS="PASS"
        PIPELINE_DISCOVERY_SOURCE="$pipeline_source_id"
    else
        fail "Discovery – refresh falhou (HTTP $refresh_code)"
        PIPELINE_DISCOVERY_STATUS="FAIL"
        PIPELINE_DISCOVERY_SOURCE="$pipeline_source_id"
    fi
    
    local jobs_json
    jobs_json=$(curl -sf "$base_url/api/v1/dashboard/jobs" -H "Authorization: Bearer $token_viewer" 2>/dev/null || echo "[]")
    local n_jobs
    n_jobs=$(echo "$jobs_json" | grep -o '"jobId"\|"id"' | wc -l || echo "0")
    PIPELINE_DISCOVERY_JOBS="${n_jobs:-0}"
    
    log "Aguardando Worker processar (30s)..."
    sleep 30
    
    log "Pipeline – Fetch (GET .../sources/${pipeline_source_id}/links)..."
    local links_code links_body
    links_code=$(curl -s -o /tmp/gabi-links-response.json -w "%{http_code}" "$base_url/api/v1/sources/${pipeline_source_id}/links" \
        -H "Authorization: Bearer $token_viewer" 2>/dev/null || echo "000")
    links_body=$(cat /tmp/gabi-links-response.json 2>/dev/null || echo "{}")
    
    if [[ "$links_code" == "200" ]]; then
        local n_links
        n_links=$(echo "$links_body" | grep -o '"totalItems"[[:space:]]*:[[:space:]]*[0-9]*' | grep -o '[0-9]*$' | head -1)
        [[ -n "${n_links:-}" ]] || n_links=$(echo "$links_body" | grep -o '"url"' | wc -l)
        [[ -n "${n_links:-}" ]] || n_links=0
        pass "Fetch – ${n_links} links para ${pipeline_source_id}"
        PIPELINE_FETCH_STATUS="PASS"
        PIPELINE_FETCH_LINKS="${n_links:-0}"
        PIPELINE_FETCH_SOURCE="$pipeline_source_id"
        PIPELINE_DISCOVERY_LINKS="${n_links:-0}"
    else
        fail "Fetch – API/links retornou HTTP $links_code"
        PIPELINE_FETCH_STATUS="FAIL"
        PIPELINE_FETCH_LINKS="0"
        PIPELINE_FETCH_SOURCE="$pipeline_source_id"
    fi
    
    # 4.5 Jobs endpoint
    if curl -sf "$base_url/api/v1/jobs" -H "Authorization: Bearer $token_viewer" 2>&1 >/dev/null; then
        pass "Jobs endpoint acessível"
    else
        warn "Jobs endpoint não disponível"
    fi
    
    # 4.6 Web Frontend (opcional em docker-only)
    log "Verificando frontend..."
    local web_status
    web_status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "http://localhost:3000" 2>&1 || echo "000")
    if [[ "$web_status" == "200" ]]; then
        pass "Web frontend acessível (HTTP 200)"
    else
        if [[ "$TEST_MODE" == "docker-only" ]]; then
            warn "Web frontend não acessível (normal se profile web não foi usado)"
        else
            fail "Web frontend retornou HTTP $web_status"
        fi
    fi
    
    # 4.7 Infraestrutura
    log "Verificando infraestrutura..."
    if docker compose ps postgres 2>/dev/null | grep -q "healthy\|Up"; then
        pass "PostgreSQL rodando"
    else
        fail "PostgreSQL não está healthy"
    fi
    if curl -sf http://localhost:9200/_cluster/health 2>/dev/null | grep -q "status"; then
        pass "Elasticsearch acessível"
    else
        warn "Elasticsearch não responde (opcional)"
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
    
    # Resumo documentável do pipeline (evidência Seed / Discovery / Fetch)
    echo -e "\n${YELLOW}Pipeline (evidência para documentação):${NC}"
    echo "  Seed:     ${PIPELINE_SEED_STATUS:-n/a} – ${PIPELINE_SEED_N:-0} fontes registradas${PIPELINE_SEED_IDS:+ [ids: ${PIPELINE_SEED_IDS}]}"
    echo "  Discovery: ${PIPELINE_DISCOVERY_STATUS:-n/a} – job(s) ${PIPELINE_DISCOVERY_JOBS:-0} para ${PIPELINE_DISCOVERY_SOURCE:-n/a}, links: ${PIPELINE_DISCOVERY_LINKS:-n/a}"
    echo "  Fetch:     ${PIPELINE_FETCH_STATUS:-n/a} – ${PIPELINE_FETCH_LINKS:-n/a} links para ${PIPELINE_FETCH_SOURCE:-n/a}"
    echo ""
    echo "Pipeline (evidência):" >> "$LOG_FILE"
    echo "  Seed:     ${PIPELINE_SEED_STATUS:-n/a} – ${PIPELINE_SEED_N:-0} fontes [ids: ${PIPELINE_SEED_IDS:-}]" >> "$LOG_FILE"
    echo "  Discovery: ${PIPELINE_DISCOVERY_STATUS:-n/a} – jobs ${PIPELINE_DISCOVERY_JOBS:-0}, links ${PIPELINE_DISCOVERY_LINKS:-0}" >> "$LOG_FILE"
    echo "  Fetch:     ${PIPELINE_FETCH_STATUS:-n/a} – ${PIPELINE_FETCH_LINKS:-0} links" >> "$LOG_FILE"
    
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
        echo "║  Modo: IDEMPOTÊNCIA (setup 2x, full)                             ║"
    elif [[ "$TEST_MODE" == "docker-only" ]]; then
        echo "║  Modo: DOCKER-ONLY (sem dotnet/npm no host)                       ║"
    else
        echo "║  Modo: FULL (destruir → setup.sh → validar)                       ║"
    fi
    echo "╚════════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    
    # Limpar log anterior
    > "$LOG_FILE"
    
    log "Iniciando teste em: $(pwd)"
    log "Log: $LOG_FILE"
    
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
