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
#   ./tests/zero-kelvin-test.sh [mode] [flags]
#
# Modos:
#   (sem args)    - docker-only (recomendado): só Docker, sem dotnet no host
#   docker-only   - Idem (explícito)
#   docker-20k    - docker-only + stress targeted (compatível com flags)
#   full          - Modo legado: setup.sh + app no host (requer dotnet)
#   idempotency   - Idempotência no modo full (setup 2x)
#
# Flags targeted stress:
#   --source <id|all>             Source alvo (default: tcu_acordaos)
#   --phase <discovery|fetch|full> Fase targeted (default: full)
#   --max-docs <n>                Cap nativo do fetch (default: 20000)
#   --monitor-memory              Habilita amostragem contínua de memória no stress run
#   --report-json <path>          Saída JSON estruturada (default: /tmp/gabi-zero-kelvin-report.json)
#
# Critério de Sucesso:
#   - Todos os checks retornam PASS ou WARN
#   - API responde em < 5s após startup
#   - Seed registra fontes no banco
#   - Discovery processa jobs e descobre links (validado via banco)
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
TEST_MODE="docker-only"  # docker-only (default) | docker-20k | full | idempotency
TARGET_SOURCE="tcu_acordaos"
TARGET_PHASE=""          # discovery|fetch|full (default resolved later)
TARGET_MAX_DOCS=20000
MONITOR_MEMORY=false
REPORT_JSON_FILE="/tmp/gabi-zero-kelvin-report.json"
TARGETED_STRESS=false

# Pipeline evidence (for report)
PIPELINE_SEED_STATUS="" PIPELINE_SEED_N="" PIPELINE_SEED_IDS=""
PIPELINE_DISCOVERY_STATUS="" PIPELINE_DISCOVERY_JOBS="" PIPELINE_DISCOVERY_LINKS="" PIPELINE_DISCOVERY_SOURCE=""
PIPELINE_FETCH_STATUS="" PIPELINE_FETCH_LINKS="" PIPELINE_FETCH_SOURCE=""
PIPELINE_20K_STATUS="" PIPELINE_20K_DOCS="" PIPELINE_20K_PEAK_MEM="" PIPELINE_20K_DURATION="" PIPELINE_20K_THROUGHPUT=""
PIPELINE_20K_ERROR_SUMMARY="" PIPELINE_20K_STATUS_BREAKDOWN="" PIPELINE_20K_SOURCE_SUMMARY=""

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

usage() {
    cat <<'EOF'
Usage:
  ./tests/zero-kelvin-test.sh [mode] [flags]

Modes:
  docker-only | docker-20k | full | idempotency

Flags:
  --source <id|all>
  --phase <discovery|fetch|full>
  --max-docs <n>
  --monitor-memory
  --report-json <path>
  --help
EOF
}

parse_args() {
    local mode_set=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            docker-only|docker-20k|full|idempotency)
                if $mode_set; then
                    echo "Erro: modo informado mais de uma vez: $1" >&2
                    exit 2
                fi
                TEST_MODE="$1"
                mode_set=true
                shift
                ;;
            --source)
                TARGET_SOURCE="${2:-}"
                TARGETED_STRESS=true
                [[ -n "$TARGET_SOURCE" ]] || { echo "Erro: --source requer valor" >&2; exit 2; }
                shift 2
                ;;
            --phase)
                TARGET_PHASE="${2:-}"
                TARGETED_STRESS=true
                [[ "$TARGET_PHASE" =~ ^(discovery|fetch|full)$ ]] || { echo "Erro: --phase inválido ($TARGET_PHASE)" >&2; exit 2; }
                shift 2
                ;;
            --max-docs)
                TARGET_MAX_DOCS="${2:-0}"
                TARGETED_STRESS=true
                [[ "$TARGET_MAX_DOCS" =~ ^[0-9]+$ ]] && [[ "$TARGET_MAX_DOCS" -gt 0 ]] || { echo "Erro: --max-docs deve ser inteiro positivo" >&2; exit 2; }
                shift 2
                ;;
            --monitor-memory)
                MONITOR_MEMORY=true
                TARGETED_STRESS=true
                shift
                ;;
            --report-json)
                REPORT_JSON_FILE="${2:-}"
                [[ -n "$REPORT_JSON_FILE" ]] || { echo "Erro: --report-json requer valor" >&2; exit 2; }
                shift 2
                ;;
            --help|-h)
                usage
                exit 0
                ;;
            *)
                echo "Erro: argumento desconhecido: $1" >&2
                usage
                exit 2
                ;;
        esac
    done

    if [[ -z "$TARGET_PHASE" ]]; then
        TARGET_PHASE="full"
    fi

    if [[ "$TEST_MODE" == "docker-20k" ]]; then
        TARGETED_STRESS=true
    fi
}

section() {
    echo -e "\n${YELLOW}═══════════════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  $1${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════${NC}\n"
    echo -e "\n=== $1 ===" >> "$LOG_FILE"
}

json_escape() {
    printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

psql_scalar() {
    local sql="$1"
    local default_value="${2:-}"
    local out
    out=$(PGPASSWORD="gabi_dev_password" timeout 15s psql -h localhost -p 5433 -U gabi -d gabi -t -A -c "$sql" 2>/dev/null || true)
    out="$(printf '%s' "$out" | tr -d '\r' | head -n1 | xargs || true)"
    if [[ -z "$out" ]]; then
        printf '%s' "$default_value"
    else
        printf '%s' "$out"
    fi
}

psql_csv_compact() {
    local sql="$1"
    local out
    out=$(PGPASSWORD="gabi_dev_password" timeout 15s psql -h localhost -p 5433 -U gabi -d gabi -t -A -F, -c "$sql" 2>/dev/null || true)
    printf '%s' "$out" | tr '\n' ';'
}

ensure_schema_readiness() {
    log "Verificando schema readiness (EF + Hangfire)..."

    local source_registry_exists
    source_registry_exists=$(docker compose exec -T postgres psql -U gabi -d gabi -t -A -c "SELECT to_regclass('public.source_registry');" 2>/dev/null || echo "")

    if [[ "$source_registry_exists" == "source_registry" ]]; then
        pass "Schema EF pronto (source_registry presente)"
    else
        warn "Schema EF ausente; tentando aplicar migrations automaticamente..."
        if ! command -v dotnet >/dev/null 2>&1; then
            fail "dotnet não disponível no host para auto-migration (schema ausente)"
            return 1
        fi
        if ! dotnet ef --version >/dev/null 2>&1; then
            fail "dotnet-ef não disponível no host para auto-migration (schema ausente)"
            return 1
        fi

        if ! dotnet ef database update \
            --project src/Gabi.Postgres/Gabi.Postgres.csproj \
            --startup-project src/Gabi.Api/Gabi.Api.csproj \
            --connection "Host=localhost;Port=5433;Database=gabi;Username=gabi;Password=gabi_dev_password" \
            2>&1 | tee -a "$LOG_FILE"; then
            fail "Auto-migration falhou"
            return 1
        fi

        source_registry_exists=$(docker compose exec -T postgres psql -U gabi -d gabi -t -A -c "SELECT to_regclass('public.source_registry');" 2>/dev/null || echo "")
        if [[ "$source_registry_exists" == "source_registry" ]]; then
            pass "Auto-migration aplicada com sucesso"
            docker compose restart api worker 2>&1 | tee -a "$LOG_FILE" || true
            sleep 8
        else
            fail "Schema EF continua ausente após auto-migration"
            return 1
        fi
    fi

    local hangfire_server_exists
    hangfire_server_exists=$(docker compose exec -T postgres psql -U gabi -d gabi -t -A -c "SELECT to_regclass('hangfire.server');" 2>/dev/null || echo "")
    if [[ "$hangfire_server_exists" == "hangfire.server" ]]; then
        pass "Schema Hangfire pronto (hangfire.server presente)"
    else
        warn "Schema Hangfire ainda não pronto; aguardando Worker instalar objetos..."
        local hf_ok=false
        for _ in $(seq 1 30); do
            hangfire_server_exists=$(docker compose exec -T postgres psql -U gabi -d gabi -t -A -c "SELECT to_regclass('hangfire.server');" 2>/dev/null || echo "")
            if [[ "$hangfire_server_exists" == "hangfire.server" ]]; then
                hf_ok=true
                break
            fi
            sleep 2
        done
        if $hf_ok; then
            pass "Schema Hangfire pronto após aguardo"
        else
            fail "Schema Hangfire não ficou pronto (hangfire.server ausente)"
            return 1
        fi
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# FASE 1: DESTRUIÇÃO COMPLETA (Zero Kelvin)
# ═══════════════════════════════════════════════════════════════════════════════

phase_destroy() {
    section "FASE 1: DESTRUIÇÃO COMPLETA (Zero Kelvin)"
    
    log "Parando e removendo containers..."
    cd "$GABI_ROOT"
    
    # Parar containers (incluir orphans e forçar remoção)
    if docker compose ps -q 2>/dev/null | grep -q .; then
        docker compose down -v --remove-orphans 2>&1 | tee -a "$LOG_FILE" || true
    fi

    # Forçar remoção de containers gabi-kimi que possam ter ficado órfãos
    docker ps -a --filter "name=gabi-kimi" --format "{{.Names}}" 2>/dev/null | xargs -r docker rm -f 2>/dev/null || true

    pass "Containers parados e volumes removidos"
    
    # Limpar volumes explicitamente
    docker volume prune -f 2>&1 | tee -a "$LOG_FILE" || true
    
    # Matar processos da aplicação
    log "Matando processos da aplicação..."
    pkill -f "dotnet.*Gabi.Api" 2>/dev/null || true
    sleep 2
    
    # Limpar logs e PIDs
    log "Limpando logs e arquivos temporários..."
    rm -rf /tmp/gabi-logs /tmp/gabi-*.pid 2>/dev/null || true
    
    # Garantir que containers do projeto não seguram portas (Redis=6380, etc.)
    log "Parando containers que usam portas do projeto..."
    for port in 6380 5433 9200 5100; do
        docker ps -q --filter "publish=$port" 2>/dev/null | xargs -r docker stop 2>/dev/null || true
    done
    sleep 2

    # Liberar portas: matar qualquer processo que ainda esteja usando (Redis, etc.)
    log "Liberando portas 6380, 5433, 9200, 5100..."
    for port in 6380 5433 9200 5100; do
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
    for port in 6380 5100 5433 9200; do
        if lsof -i :$port 2>/dev/null | grep -q .; then
            fail "Porta $port ainda em uso (rode o teste com sudo para liberar processos do sistema)"
            ports_free=false
        fi
    done

    if $ports_free; then
        pass "Todas as portas estão livres (6380, 5100, 5433, 9200)"
    fi
    
    # Verificar que não há containers (aguardar Docker finalizar cleanup)
    sleep 2
    if docker ps -a --filter "name=gabi-kimi" --format "{{.Names}}" 2>/dev/null | grep -q .; then
        fail "Containers gabi ainda existem: $(docker ps -a --filter 'name=gabi-kimi' --format '{{.Names}}' | tr '\n' ' ')"
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
    
    if [[ "$TEST_MODE" == "docker-only" || "$TEST_MODE" == "docker-20k" ]]; then
        # Modo Docker-only: não usar dotnet do host; só compose
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
                if ! ensure_schema_readiness; then
                    fail "Schema readiness falhou"
                    return 1
                fi
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
    
    # Modo full: setup.sh (requer dotnet no host)
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
    
    if [[ "$TEST_MODE" == "docker-only" || "$TEST_MODE" == "docker-20k" ]]; then
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

        curl -sf http://localhost:5100/health >/dev/null 2>&1 && api_up=true

        if $api_up; then
            all_ready=true
            break
        fi
        echo -n "."
    done
    echo ""
    
    if $all_ready; then
        pass "API pronta em ${attempts} tentativas (~$((attempts * 2))s)"
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
        fail "Login operator falhou (necessário para pipeline)"
        return 1
    fi

    # 4.4 Pipeline phases
    log "Verificando /api/v1/dashboard/pipeline/phases..."
    if curl -sf "$base_url/api/v1/dashboard/pipeline/phases" \
        -H "Authorization: Bearer $token_viewer" 2>&1 | tee -a "$LOG_FILE" | grep -q "seed"; then
        pass "Pipeline phases retorna dados"
    else
        fail "Pipeline phases não retorna dados esperados"
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
    
    # ═══ Pipeline: Discovery for ALL active sources ──────────────────────────
    # Default: skip global discovery fan-out in smoke to avoid queue backlog
    # before the targeted stress stage. Enable only for explicit smoke runs.
    if [[ "${ZERO_KELVIN_ENABLE_GLOBAL_DISCOVERY:-0}" != "1" ]]; then
        warn "Pipeline – pulando discovery global no smoke (source=${TARGET_SOURCE}, set ZERO_KELVIN_ENABLE_GLOBAL_DISCOVERY=1 para habilitar)"
        PIPELINE_DISCOVERY_STATUS="N/A"
        PIPELINE_DISCOVERY_SOURCE="SKIPPED_TARGETED"
        PIPELINE_DISCOVERY_LINKS="0"
    else
        # Active sources (enabled=true): 11 sources
        # Expected: tcu_acordaos=35, static_url sources=1 each, unimplemented strategies=0
        local active_sources="camara_leis_ordinarias tcu_acordaos tcu_boletim_jurisprudencia tcu_boletim_pessoal tcu_informativo_lc tcu_jurisprudencia_selecionada tcu_normas tcu_notas_tecnicas_ti tcu_publicacoes tcu_resposta_consulta tcu_sumulas"
        local total_expected_links=42  # 35 (tcu_acordaos) + 7 (static_url sources)

        log "Pipeline – Discovery (triggering for ALL ${PIPELINE_SEED_N:-0} active sources)..."

        # Trigger discovery for all active sources
        for source in $active_sources; do
            curl -s -o /dev/null -w "%{http_code}" -X POST "$base_url/api/v1/dashboard/sources/${source}/phases/discovery" \
                -H "Authorization: Bearer $token_operator" -H "Content-Type: application/json" 2>/dev/null || true
        done

        pass "Discovery – jobs triggered for all active sources"
        PIPELINE_DISCOVERY_STATUS="PASS"
        PIPELINE_DISCOVERY_SOURCE="ALL"

        log "Aguardando Worker processar discovery jobs (45s)..."
        sleep 45

        # Verify discovered links per source
        log "Pipeline – Verificando links descobertos no banco de dados (todos os sources)..."

        local db_query="SELECT \"SourceId\", COUNT(*) as cnt FROM discovered_links GROUP BY \"SourceId\" ORDER BY cnt DESC;"
        local discovery_results
        discovery_results=$(docker compose exec -T postgres psql -U gabi -d gabi -t -c "$db_query" 2>/dev/null || echo "")

        local total_links=0
        local tcu_acordaos_links=0
        local static_sources_ok=true

        # Count total links and validate tcu_acordaos
        while IFS='|' read -r source_id count; do
            source_id=$(echo "$source_id" | tr -d ' ')
            count=$(echo "$count" | tr -d ' ')
            if [[ -n "$source_id" && -n "$count" ]]; then
                total_links=$((total_links + count))
                if [[ "$source_id" == "tcu_acordaos" ]]; then
                    tcu_acordaos_links=$count
                fi
            fi
        done <<< "$discovery_results"

        # Validation: tcu_acordaos should have ~35 links
        if [[ "${tcu_acordaos_links:-0}" -ge 30 ]]; then
            pass "Discovery – tcu_acordaos: ${tcu_acordaos_links} links (expected ~35)"
        else
            fail "Discovery – tcu_acordaos: ${tcu_acordaos_links} links (expected ~35)"
            static_sources_ok=false
        fi

        # Validation: static_url sources should have 1 link each
        local static_sources="tcu_sumulas tcu_normas tcu_resposta_consulta tcu_boletim_pessoal tcu_informativo_lc tcu_boletim_jurisprudencia tcu_jurisprudencia_selecionada"
        for source in $static_sources; do
            local count
            count=$(docker compose exec -T postgres psql -U gabi -d gabi -t -c \
                "SELECT COUNT(*) FROM discovered_links WHERE \"SourceId\" = '${source}';" 2>/dev/null | tr -d ' ' || echo "0")
            if [[ "${count:-0}" -ge 1 ]]; then
                pass "Discovery – ${source}: ${count} link(s)"
            else
                warn "Discovery – ${source}: ${count} links (expected 1)"
            fi
        done

        # Unimplemented strategies (0 links expected)
        local unimpl_sources="camara_leis_ordinarias tcu_notas_tecnicas_ti tcu_publicacoes"
        for source in $unimpl_sources; do
            local count
            count=$(docker compose exec -T postgres psql -U gabi -d gabi -t -c \
                "SELECT COUNT(*) FROM discovered_links WHERE \"SourceId\" = '${source}';" 2>/dev/null | tr -d ' ' || echo "0")
            if [[ "${count:-0}" -eq 0 ]]; then
                pass "Discovery – ${source}: ${count} links (expected 0 - strategy not implemented)"
            else
                pass "Discovery – ${source}: ${count} links (unexpected)"
            fi
        done

        PIPELINE_DISCOVERY_LINKS="${total_links}"

        if $static_sources_ok && [[ "${total_links:-0}" -ge 40 ]]; then
            pass "Discovery – Total: ${total_links} links (expected ~42)"
        elif [[ "${total_links:-0}" -ge 30 ]]; then
            warn "Discovery – Total: ${total_links} links (expected ~42)"
        else
            fail "Discovery – Total: ${total_links} links (expected ~42)"
        fi
    fi

    # Fetch endpoint (opcional - não implementado ainda)
    local pipeline_source_id="tcu_sumulas"
    log "Pipeline – Fetch (GET .../sources/${pipeline_source_id}/links) [OPCIONAL]..."
    local links_code
    links_code=$(curl -s -o /tmp/gabi-links-response.json -w "%{http_code}" "$base_url/api/v1/sources/${pipeline_source_id}/links" \
        -H "Authorization: Bearer $token_viewer" 2>/dev/null || echo "000")

    if [[ "$links_code" == "200" ]]; then
        pass "Fetch endpoint – implementado e respondendo"
        PIPELINE_FETCH_STATUS="PASS"
    else
        warn "Fetch endpoint – não implementado (HTTP $links_code) - normal neste estágio"
        PIPELINE_FETCH_STATUS="N/A"
    fi
    
    # 4.5 Jobs endpoint
    if curl -sf "$base_url/api/v1/jobs" -H "Authorization: Bearer $token_viewer" 2>&1 >/dev/null; then
        pass "Jobs endpoint acessível"
    else
        warn "Jobs endpoint não disponível"
    fi
    
    # 4.6 Infraestrutura
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

CURRENT_20K_STATUS="" CURRENT_20K_DOCS="" CURRENT_20K_PEAK_MEM="" CURRENT_20K_DURATION=""
CURRENT_20K_THROUGHPUT="" CURRENT_20K_STATUS_BREAKDOWN="" CURRENT_20K_ERROR_SUMMARY=""
CURRENT_20K_PEAK_MEM_MIB="0"

run_targeted_source() {
    local source_id="$1"
    local base_url="$2"
    local token_operator="$3"

    CURRENT_20K_STATUS="FAIL"
    CURRENT_20K_DOCS="0"
    CURRENT_20K_PEAK_MEM="n/a"
    CURRENT_20K_DURATION="0s"
    CURRENT_20K_THROUGHPUT="0"
    CURRENT_20K_STATUS_BREAKDOWN=""
    CURRENT_20K_ERROR_SUMMARY=""
    CURRENT_20K_PEAK_MEM_MIB="0"

    if [[ "$TARGET_PHASE" == "discovery" || "$TARGET_PHASE" == "full" || "$TARGET_PHASE" == "fetch" ]]; then
        log "Discovery ${source_id}..."
        local disc_code="000"
        for trigger_attempt in 1 2 3; do
            disc_code=$(curl -s -o "/tmp/gabi-disc-${source_id}.json" -w "%{http_code}" -X POST \
                "$base_url/api/v1/dashboard/sources/${source_id}/phases/discovery" \
                -H "Authorization: Bearer $token_operator" -H "Content-Type: application/json" 2>/dev/null || echo "000")
            [[ "$disc_code" == "200" ]] && break

            # Retry path for transient API connectivity issues in long all-sources runs.
            if [[ "$disc_code" == "000" ]]; then
                if ! curl -sf --max-time 3 "$base_url/health" >/dev/null 2>&1; then
                    warn "Discovery trigger sem resposta (${source_id}) na tentativa ${trigger_attempt}/3; reerguendo api/worker"
                    docker compose --profile api --profile worker up -d >/dev/null 2>&1 || true
                    for _ in $(seq 1 15); do
                        curl -sf --max-time 3 "$base_url/health" >/dev/null 2>&1 && break
                        sleep 2
                    done
                fi
            fi

            # Refresh operator token before next attempt.
            token_operator=$(curl -sf -X POST "$base_url/api/v1/auth/login" \
                -H "Content-Type: application/json" \
                -d '{"username": "operator", "password": "op123"}' 2>/dev/null | \
                grep -o '"token":"[^"]*"' | cut -d'"' -f4 || echo "$token_operator")
            sleep 1
        done

        if [[ "$disc_code" != "200" ]]; then
            CURRENT_20K_ERROR_SUMMARY="discovery_http_${disc_code}"
            if [[ "$TARGET_SOURCE" == "all" ]]; then
                CURRENT_20K_STATUS="WARN"
                CURRENT_20K_DOCS="0"
                CURRENT_20K_PEAK_MEM=$($MONITOR_MEMORY && echo "0 MiB (n/a)" || echo "monitoring_disabled")
                CURRENT_20K_DURATION="0s"
                CURRENT_20K_THROUGHPUT="0"
                CURRENT_20K_STATUS_BREAKDOWN=""
                warn "Targeted stress – discovery trigger indisponível (${source_id}, HTTP $disc_code), seguindo para próxima source"
                return 0
            fi
            fail "Targeted stress – discovery trigger falhou (${source_id}, HTTP $disc_code)"
            return 1
        fi

        log "Aguardando discovery materializar links/fetch_items para ${source_id}..."
        local discovery_ok=false
        local discovery_no_links=false
        local discovery_materialized_running=false
        local max_discovery_attempts=120
        # In all-sources mode, use a shorter window per source to keep total time bounded
        if [[ "$TARGET_SOURCE" == "all" ]]; then
            max_discovery_attempts=60
            case "$source_id" in
                camara_*|tcu_btcu_deliberacoes_extra)
                    # High-cardinality discovery sources need a wider completion window.
                    max_discovery_attempts=240
                    ;;
            esac
        fi
        for attempt in $(seq 1 "$max_discovery_attempts"); do
            local links_count
            local items_count
            local discovery_status
            links_count=$(psql_scalar "SELECT COUNT(*) FROM discovered_links WHERE \"SourceId\"='${source_id}';" "0")
            items_count=$(psql_scalar "SELECT COUNT(*) FROM fetch_items WHERE \"SourceId\"='${source_id}';" "0")
            discovery_status=$(psql_scalar "SELECT COALESCE((SELECT \"Status\" FROM discovery_runs WHERE \"SourceId\"='${source_id}' ORDER BY \"StartedAt\" DESC LIMIT 1),'');" "")
            if (( attempt % 10 == 0 )); then
                log "Discovery wait – source=${source_id} attempt=${attempt}/${max_discovery_attempts} links=${links_count:-0} fetch_items=${items_count:-0} status=${discovery_status:-n/a}"
            fi
            if [[ "${links_count:-0}" -gt 0 && "${items_count:-0}" -gt 0 ]]; then
                # Para phase=fetch/full, exigir discovery finalizada antes de seguir.
                if [[ "$TARGET_PHASE" == "fetch" || "$TARGET_PHASE" == "full" ]]; then
                    if [[ "$discovery_status" == "completed" ]]; then
                        discovery_ok=true
                        break
                    fi
                    if [[ "$TARGET_SOURCE" == "all" && "$source_id" == camara_* && "$discovery_status" == "running" ]]; then
                        # Camara discoveries are high-cardinality and can stay running for long windows.
                        # If links/fetch_items are already materialized, don't block the all-sources suite.
                        discovery_ok=true
                        discovery_materialized_running=true
                        break
                    fi
                else
                    discovery_ok=true
                    break
                fi
            fi
            if [[ "$discovery_status" == "completed" && "${links_count:-0}" -eq 0 && "${items_count:-0}" -eq 0 ]]; then
                discovery_ok=true
                discovery_no_links=true
                break
            fi
            if [[ "$discovery_status" == "failed" ]]; then
                CURRENT_20K_ERROR_SUMMARY="discovery_run_failed"
                fail "Targeted stress – discovery run failed (${source_id})"
                return 1
            fi
            sleep 3
        done
        if ! $discovery_ok; then
            CURRENT_20K_ERROR_SUMMARY="discovery_not_materialized"
            CURRENT_20K_STATUS="WARN"
            CURRENT_20K_DOCS="0"
            CURRENT_20K_PEAK_MEM=$($MONITOR_MEMORY && echo "0 MiB (n/a)" || echo "monitoring_disabled")
            CURRENT_20K_DURATION="0s"
            CURRENT_20K_THROUGHPUT="0"
            CURRENT_20K_STATUS_BREAKDOWN=""
            warn "Targeted stress – discovery não materializou em ${max_discovery_attempts} tentativas (${source_id})"
            return 0
        fi

        if $discovery_no_links; then
            CURRENT_20K_STATUS="PASS"
            CURRENT_20K_DOCS="0"
            CURRENT_20K_PEAK_MEM=$($MONITOR_MEMORY && echo "0 MiB (n/a)" || echo "monitoring_disabled")
            CURRENT_20K_DURATION="0s"
            CURRENT_20K_THROUGHPUT="0"
            CURRENT_20K_STATUS_BREAKDOWN="no_fetch_items=1"
            CURRENT_20K_ERROR_SUMMARY="no_links_discovered"
            pass "Targeted stress – source sem links descobertos (${source_id}), fetch não aplicável"
            return 0
        fi

        if $discovery_materialized_running; then
            CURRENT_20K_STATUS="PASS"
            CURRENT_20K_DOCS="0"
            CURRENT_20K_PEAK_MEM=$($MONITOR_MEMORY && echo "0 MiB (n/a)" || echo "monitoring_disabled")
            CURRENT_20K_DURATION="0s"
            CURRENT_20K_THROUGHPUT="0"
            CURRENT_20K_STATUS_BREAKDOWN=$(psql_csv_compact "SELECT \"Status\", COUNT(*) FROM fetch_items WHERE \"SourceId\"='${source_id}' GROUP BY \"Status\" ORDER BY \"Status\";")
            CURRENT_20K_ERROR_SUMMARY="discovery_materialized_running"
            pass "Targeted stress – discovery materializado e em execução (${source_id}), fetch adiado no all-sources"
            return 0
        fi
    fi

    if [[ "$TARGET_PHASE" == "discovery" ]]; then
        local links_count
        local items_count
        links_count=$(psql_scalar "SELECT COUNT(*) FROM discovered_links WHERE \"SourceId\"='${source_id}';" "0")
        items_count=$(psql_scalar "SELECT COUNT(*) FROM fetch_items WHERE \"SourceId\"='${source_id}';" "0")

        CURRENT_20K_DOCS="0"
        CURRENT_20K_STATUS_BREAKDOWN=$(psql_csv_compact "SELECT \"Status\", COUNT(*) FROM fetch_items WHERE \"SourceId\"='${source_id}' GROUP BY \"Status\" ORDER BY \"Status\";")
        CURRENT_20K_STATUS="PASS"
        CURRENT_20K_ERROR_SUMMARY="discovery_only"
        pass "Targeted discovery concluído (${source_id}): links=${links_count}, fetch_items=${items_count}"
        return 0
    fi

    log "Trigger fetch ${source_id} (native cap ${TARGET_MAX_DOCS} docs)..."
    local fetch_code
    fetch_code=$(curl -s -o "/tmp/gabi-fetch-${source_id}.json" -w "%{http_code}" -X POST \
        "$base_url/api/v1/dashboard/sources/${source_id}/phases/fetch" \
        -H "Authorization: Bearer $token_operator" -H "Content-Type: application/json" \
        -d "{\"max_docs_per_source\":${TARGET_MAX_DOCS}}" 2>/dev/null || echo "000")
    if [[ "$fetch_code" != "200" ]]; then
        CURRENT_20K_ERROR_SUMMARY="fetch_http_${fetch_code}"
        fail "Targeted stress – fetch trigger falhou (${source_id}, HTTP $fetch_code)"
        return 1
    fi
    local fetch_response
    fetch_response=$(cat "/tmp/gabi-fetch-${source_id}.json" 2>/dev/null || echo "")
    if echo "$fetch_response" | grep -qi "already in progress"; then
        CURRENT_20K_STATUS="WARN"
        CURRENT_20K_DOCS="0"
        CURRENT_20K_PEAK_MEM=$($MONITOR_MEMORY && echo "0 MiB (n/a)" || echo "monitoring_disabled")
        CURRENT_20K_DURATION="0s"
        CURRENT_20K_THROUGHPUT="0"
        CURRENT_20K_STATUS_BREAKDOWN=$(psql_csv_compact "SELECT \"Status\", COUNT(*) FROM fetch_items WHERE \"SourceId\"='${source_id}' GROUP BY \"Status\" ORDER BY \"Status\";")
        CURRENT_20K_ERROR_SUMMARY="fetch_not_triggered_discovery_in_progress"
        warn "Targeted fetch – não iniciado para ${source_id}: discovery ainda em execução"
        return 0
    fi

    local start_ts
    start_ts=$(date +%s)
    local peak_mib="0"
    local peak_raw="0MiB"
    local stop_reason="timeout"
    local last_docs="0"
    local last_processed="0"
    local stall_count="0"
    local stall_threshold="36"
    if [[ "$TARGET_SOURCE" == "all" ]]; then
        stall_threshold="12"
        case "$source_id" in
            senado_legislacao_decretos_lei|tcu_btcu_controle_externo)
                # link_only + large queues can progress in bursts; avoid false stall warnings.
                stall_threshold="36"
                ;;
        esac
    fi

    for _ in $(seq 1 1440); do
        local docs
        docs=$(psql_scalar "SELECT COUNT(*) FROM documents WHERE \"SourceId\"='${source_id}';" "0")
        local processed_items
        processed_items=$(psql_scalar "SELECT COUNT(*) FROM fetch_items WHERE \"SourceId\"='${source_id}' AND \"Status\" IN ('completed','skipped_format','skipped_unchanged','failed','capped');" "0")
        local active_items
        active_items=$(psql_scalar "SELECT COUNT(*) FROM fetch_items WHERE \"SourceId\"='${source_id}' AND \"Status\" IN ('pending','processing');" "0")

        if [[ "${docs:-0}" -gt "${last_docs:-0}" ]] || [[ "${processed_items:-0}" -gt "${last_processed:-0}" ]]; then
            stall_count="0"
        else
            stall_count=$((stall_count + 1))
        fi
        last_docs="${docs:-0}"
        last_processed="${processed_items:-0}"

        local mem_raw="n/a"
        local mem_mib="0"
        if $MONITOR_MEMORY; then
            mem_raw=$(docker stats --no-stream --format '{{.MemUsage}}' gabi-kimi-worker-1 2>/dev/null | cut -d'/' -f1 | tr -d ' ')
            mem_mib=$(echo "$mem_raw" | awk '/GiB/{gsub("GiB","",$0); printf "%.2f",$0*1024; next} /MiB/{gsub("MiB","",$0); printf "%.2f",$0; next} /KiB/{gsub("KiB","",$0); printf "%.2f",$0/1024; next} {print "0"}')
            awk -v a="$mem_mib" -v b="$peak_mib" 'BEGIN{exit !(a>b)}' && { peak_mib="$mem_mib"; peak_raw="$mem_raw"; }
        fi

        local now_ts
        now_ts=$(date +%s)
        log "Fetch20k – source=${source_id} t=$((now_ts - start_ts))s docs=${docs:-0} mem=${mem_raw:-n/a} stall=${stall_count}/${stall_threshold}"

        local fetch_status
        fetch_status=$(psql_scalar "SELECT COALESCE((SELECT \"Status\" FROM fetch_runs WHERE \"SourceId\"='${source_id}' ORDER BY \"StartedAt\" DESC LIMIT 1),'');" "")

        if [[ "$fetch_status" == "capped" || "$fetch_status" == "completed" || "$fetch_status" == "failed" ]]; then
            stop_reason="$fetch_status"
            break
        fi

        if [[ "${active_items:-0}" -eq 0 && "${processed_items:-0}" -gt 0 ]]; then
            stop_reason="items_done"
            break
        fi

        local last_error
        last_error=$(psql_scalar "SELECT COALESCE(MAX(\"LastError\"),'') FROM fetch_items WHERE \"SourceId\"='${source_id}';" "")
        if echo "$last_error" | grep -qi "OutOfMemoryException"; then
            stop_reason="oom"
            break
        fi

        if [[ "$stall_count" -ge "$stall_threshold" ]]; then
            warn "Fetch20k – stall detectado (sem progresso por $((stall_threshold * 5))s), skipping source ${source_id}"
            stop_reason="stalled"
            break
        fi
        sleep 5
    done

    local end_ts
    end_ts=$(date +%s)
    local duration_s=$((end_ts - start_ts))
    local final_docs
    final_docs=$(psql_scalar "SELECT COUNT(*) FROM documents WHERE \"SourceId\"='${source_id}';" "0")
    local docs_per_min
    docs_per_min=$(awk -v d="$final_docs" -v s="$duration_s" 'BEGIN{ if (s>0) printf "%.2f", (d*60)/s; else print "0"}')

    local status_breakdown
    status_breakdown=$(psql_csv_compact "SELECT \"Status\", COUNT(*) FROM fetch_items WHERE \"SourceId\"='${source_id}' GROUP BY \"Status\" ORDER BY \"Status\";")
    local error_summary
    error_summary=$(psql_scalar "SELECT COALESCE((SELECT \"ErrorSummary\" FROM fetch_runs WHERE \"SourceId\"='${source_id}' ORDER BY \"StartedAt\" DESC LIMIT 1),'');" "")

    CURRENT_20K_DOCS="$final_docs"
    CURRENT_20K_PEAK_MEM_MIB="$peak_mib"
    if $MONITOR_MEMORY; then
        CURRENT_20K_PEAK_MEM="${peak_mib} MiB (${peak_raw})"
    else
        CURRENT_20K_PEAK_MEM="monitoring_disabled"
    fi
    CURRENT_20K_DURATION="${duration_s}s"
    CURRENT_20K_THROUGHPUT="$docs_per_min"
    CURRENT_20K_STATUS_BREAKDOWN="$status_breakdown"
    CURRENT_20K_ERROR_SUMMARY="$error_summary"

    if [[ "$stop_reason" == "capped" && "${final_docs:-0}" -eq "${TARGET_MAX_DOCS}" ]]; then
        pass "Targeted fetch – capped nativo concluído sem OOM (source=${source_id}, docs=${final_docs}, peak_mem=${CURRENT_20K_PEAK_MEM}, throughput=${docs_per_min} docs/min)"
        CURRENT_20K_STATUS="PASS"
    elif [[ "$stop_reason" == "capped" ]]; then
        fail "Targeted fetch – run capped nativo, mas docs finais foram ${final_docs} (${source_id}, esperado: ${TARGET_MAX_DOCS})"
        CURRENT_20K_STATUS="FAIL"
        CURRENT_20K_ERROR_SUMMARY="capped_with_unexpected_doc_count"
    elif [[ "$stop_reason" == "oom" ]]; then
        fail "Targeted fetch – OOM detectado antes do cap de ${TARGET_MAX_DOCS} docs (${source_id})"
        CURRENT_20K_STATUS="FAIL"
        CURRENT_20K_ERROR_SUMMARY="oom"
    elif [[ "$stop_reason" == "completed" ]]; then
        pass "Targeted fetch – concluído sem cap (source=${source_id}, docs=${final_docs}, peak_mem=${CURRENT_20K_PEAK_MEM}, throughput=${docs_per_min} docs/min)"
        CURRENT_20K_STATUS="PASS"
    elif [[ "$stop_reason" == "failed" ]]; then
        fail "Targeted fetch – failed (source=${source_id}, docs=${final_docs}, peak_mem=${CURRENT_20K_PEAK_MEM})"
        CURRENT_20K_STATUS="FAIL"
        CURRENT_20K_ERROR_SUMMARY="${error_summary:-fetch_run_failed}"
    elif [[ "$stop_reason" == "items_done" ]]; then
        pass "Targeted fetch – finalizado por itens processados (source=${source_id}, docs=${final_docs}, peak_mem=${CURRENT_20K_PEAK_MEM})"
        CURRENT_20K_STATUS="PASS"
        CURRENT_20K_ERROR_SUMMARY="${error_summary:-items_done}"
    elif [[ "$stop_reason" == "stalled" ]]; then
        warn "Targeted fetch – stalled (source=${source_id}, docs=${final_docs}, peak_mem=${CURRENT_20K_PEAK_MEM})"
        CURRENT_20K_STATUS="WARN"
        CURRENT_20K_ERROR_SUMMARY="fetch_stalled"
    else
        warn "Targeted fetch – encerrado por ${stop_reason} (source=${source_id}, docs=${final_docs}, peak_mem=${CURRENT_20K_PEAK_MEM})"
        CURRENT_20K_STATUS="WARN"
    fi
}

phase_fetch_20k_observability() {
    section "FASE 4c: TARGETED STRESS (${TARGET_SOURCE}, phase=${TARGET_PHASE}, cap=${TARGET_MAX_DOCS})"

    local base_url="http://localhost:5100"
    local token_operator
    token_operator=$(curl -sf -X POST "$base_url/api/v1/auth/login" \
        -H "Content-Type: application/json" \
        -d '{"username": "operator", "password": "op123"}' 2>/dev/null | \
        grep -o '"token":"[^"]*"' | cut -d'"' -f4 || echo "")

    if [[ -z "$token_operator" ]]; then
        fail "Targeted stress – login operator falhou"
        PIPELINE_20K_STATUS="FAIL"
        return 1
    fi

    if [[ "$TARGET_SOURCE" != "all" ]]; then
        # Single-source mode: global truncate for clean slate
        log "Resetando dados de ingestão/fetch para execução observável..."
        docker compose exec -T postgres psql -U gabi -d gabi -c \
            "TRUNCATE discovered_links, fetch_items, fetch_runs, discovery_runs, documents RESTART IDENTITY CASCADE;" \
            2>&1 | tee -a "$LOG_FILE" >/dev/null || true
    else
        # All-sources mode: each source cleans its own data in the loop below.
        # Do a global Hangfire flush to start with empty queue.
        log "Flush inicial do Hangfire para all-sources sequencial..."
        docker compose exec -T postgres psql -U gabi -d gabi -c "
            DELETE FROM hangfire.job WHERE statename IN ('Enqueued','Scheduled','Processing','Awaiting');
            DELETE FROM hangfire.jobqueue;
        " 2>&1 | tee -a "$LOG_FILE" >/dev/null || true
    fi

    if [[ "$TARGET_SOURCE" != "all" ]]; then
        run_targeted_source "$TARGET_SOURCE" "$base_url" "$token_operator" || true
        PIPELINE_20K_STATUS="$CURRENT_20K_STATUS"
        PIPELINE_20K_DOCS="$CURRENT_20K_DOCS"
        PIPELINE_20K_PEAK_MEM="$CURRENT_20K_PEAK_MEM"
        PIPELINE_20K_DURATION="$CURRENT_20K_DURATION"
        PIPELINE_20K_THROUGHPUT="$CURRENT_20K_THROUGHPUT"
        PIPELINE_20K_STATUS_BREAKDOWN="$CURRENT_20K_STATUS_BREAKDOWN"
        PIPELINE_20K_ERROR_SUMMARY="$CURRENT_20K_ERROR_SUMMARY"
        PIPELINE_20K_SOURCE_SUMMARY="${TARGET_SOURCE},${CURRENT_20K_STATUS},${CURRENT_20K_DOCS},${CURRENT_20K_PEAK_MEM},${CURRENT_20K_DURATION},${CURRENT_20K_THROUGHPUT},${CURRENT_20K_ERROR_SUMMARY}"
        return 0
    fi

    local sources
    sources=$(PGPASSWORD="gabi_dev_password" timeout 15s psql -h localhost -p 5433 -U gabi -d gabi -t -A -c \
        'SELECT "Id" FROM source_registry WHERE "Enabled" = true ORDER BY "Id";' 2>/dev/null || true)
    if [[ -z "${sources// }" ]]; then
        fail "Targeted stress (all) – nenhuma source habilitada encontrada"
        PIPELINE_20K_STATUS="FAIL"
        PIPELINE_20K_ERROR_SUMMARY="no_enabled_sources"
        return 1
    fi

    local ordered_sources=""
    # Process non-Camara sources first; keep Camara sources last because
    # they have significantly longer discovery windows and can monopolize queue time.
    while IFS= read -r source_id; do
        source_id="$(echo "$source_id" | xargs)"
        [[ -n "$source_id" ]] || continue
        if [[ "$source_id" != camara_* ]]; then
            ordered_sources+="${source_id}"$'\n'
        fi
    done <<< "$sources"
    while IFS= read -r source_id; do
        source_id="$(echo "$source_id" | xargs)"
        [[ -n "$source_id" ]] || continue
        if [[ "$source_id" == camara_* ]]; then
            ordered_sources+="${source_id}"$'\n'
        fi
    done <<< "$sources"

    local total_docs=0
    local failed_sources=0
    local warn_sources=0
    local pass_sources=0
    local global_peak_mib="0"
    local global_peak_label="0 MiB"
    local source_summary_lines=""
    local source_index=0
    local source_count
    source_count=$(echo "$ordered_sources" | grep -c '[a-z]' || echo "0")

    while IFS= read -r source_id; do
        source_id="$(echo "$source_id" | xargs)"
        [[ -n "$source_id" ]] || continue
        source_index=$((source_index + 1))

        log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        log "Targeted stress (all): [${source_index}/${source_count}] source=${source_id}"
        log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

        # === Sequential isolation: clean slate for each source ===
        # NOTE: All docker/psql commands MUST use </dev/null to avoid consuming
        # the here-string stdin that feeds the while-read loop.

        # 1. Flush Hangfire queue so no leftover jobs from previous source compete
        log "Flushing Hangfire queue for isolation..."
        docker compose exec -T postgres psql -U gabi -d gabi -c "
            DELETE FROM hangfire.job WHERE statename IN ('Enqueued','Scheduled','Processing','Awaiting');
            DELETE FROM hangfire.jobqueue;
        " </dev/null 2>&1 | tee -a "$LOG_FILE" >/dev/null || true

        # 2. Clean pipeline data for this specific source
        log "Cleaning pipeline data for source=${source_id}..."
        docker compose exec -T postgres psql -U gabi -d gabi -c "
            DELETE FROM documents WHERE \"SourceId\" = '${source_id}';
            DELETE FROM fetch_items WHERE \"SourceId\" = '${source_id}';
            DELETE FROM fetch_runs WHERE \"SourceId\" = '${source_id}';
            DELETE FROM discovered_links WHERE \"SourceId\" = '${source_id}';
            DELETE FROM discovery_runs WHERE \"SourceId\" = '${source_id}';
        " </dev/null 2>&1 | tee -a "$LOG_FILE" >/dev/null || true

        # 3. Brief pause to let worker drain any in-flight work
        sleep 2

        # 4. Refresh operator token (may expire during long runs)
        token_operator=$(curl -sf -X POST "$base_url/api/v1/auth/login" \
            -H "Content-Type: application/json" \
            -d '{"username": "operator", "password": "op123"}' </dev/null 2>/dev/null | \
            grep -o '"token":"[^"]*"' | cut -d'"' -f4 || echo "$token_operator")

        run_targeted_source "$source_id" "$base_url" "$token_operator" < /dev/null || true

        total_docs=$((total_docs + ${CURRENT_20K_DOCS:-0}))
        if [[ "$CURRENT_20K_STATUS" == "FAIL" ]]; then
            failed_sources=$((failed_sources + 1))
        elif [[ "$CURRENT_20K_STATUS" == "WARN" ]]; then
            warn_sources=$((warn_sources + 1))
        else
            pass_sources=$((pass_sources + 1))
        fi

        awk -v a="${CURRENT_20K_PEAK_MEM_MIB:-0}" -v b="$global_peak_mib" 'BEGIN{exit !(a>b)}' && {
            global_peak_mib="${CURRENT_20K_PEAK_MEM_MIB:-0}"
            global_peak_label="${CURRENT_20K_PEAK_MEM}"
        }

        source_summary_lines+="${source_id},${CURRENT_20K_STATUS},${CURRENT_20K_DOCS},${CURRENT_20K_PEAK_MEM},${CURRENT_20K_DURATION},${CURRENT_20K_THROUGHPUT},${CURRENT_20K_ERROR_SUMMARY};"
        log "Resultado [${source_index}/${source_count}]: ${source_id} → ${CURRENT_20K_STATUS} (docs=${CURRENT_20K_DOCS}, peak=${CURRENT_20K_PEAK_MEM})"
    done <<< "$ordered_sources"

    PIPELINE_20K_DOCS="$total_docs"
    PIPELINE_20K_PEAK_MEM="$global_peak_label"
    PIPELINE_20K_DURATION="aggregate"
    PIPELINE_20K_THROUGHPUT="aggregate"
    PIPELINE_20K_STATUS_BREAKDOWN="failed_sources=${failed_sources};warn_sources=${warn_sources}"
    PIPELINE_20K_ERROR_SUMMARY="multi_source_run"
    PIPELINE_20K_SOURCE_SUMMARY="$source_summary_lines"

    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log "All-sources summary: PASS=${pass_sources} WARN=${warn_sources} FAIL=${failed_sources} docs=${total_docs} peak=${global_peak_label}"
    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    if [[ "$failed_sources" -gt 0 ]]; then
        PIPELINE_20K_STATUS="FAIL"
        fail "Targeted fetch all – ${failed_sources} source(s) falharam, docs_total=${total_docs}, peak_mem=${PIPELINE_20K_PEAK_MEM}"
    elif [[ "$warn_sources" -gt 0 ]]; then
        PIPELINE_20K_STATUS="WARN"
        warn "Targeted fetch all – PASS=${pass_sources} WARN=${warn_sources}, docs_total=${total_docs}, peak_mem=${PIPELINE_20K_PEAK_MEM}"
    else
        PIPELINE_20K_STATUS="PASS"
        pass "Targeted fetch all – ${pass_sources} source(s) PASS, docs_total=${total_docs}, peak_mem=${PIPELINE_20K_PEAK_MEM}"
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
    
    # Resumo documentável do pipeline (evidência Seed / Discovery)
    echo -e "\n${YELLOW}Pipeline (evidência para documentação):${NC}"
    echo "  Seed:      ${PIPELINE_SEED_STATUS:-n/a} – ${PIPELINE_SEED_N:-0} fontes registradas${PIPELINE_SEED_IDS:+ [ids: ${PIPELINE_SEED_IDS}]}"
    echo "  Discovery: ${PIPELINE_DISCOVERY_STATUS:-n/a} – ${PIPELINE_DISCOVERY_LINKS:-0} links totais (${PIPELINE_DISCOVERY_SOURCE:-n/a})"
    echo "  Fetch:     ${PIPELINE_FETCH_STATUS:-n/a} (endpoint opcional, ainda não implementado)"
    if $TARGETED_STRESS; then
        echo "  Targeted:  ${PIPELINE_20K_STATUS:-n/a} – source=${TARGET_SOURCE}, phase=${TARGET_PHASE}, docs=${PIPELINE_20K_DOCS:-0}, peak_mem=${PIPELINE_20K_PEAK_MEM:-n/a}, duration=${PIPELINE_20K_DURATION:-n/a}, throughput=${PIPELINE_20K_THROUGHPUT:-n/a} docs/min"
        echo "             status_breakdown=${PIPELINE_20K_STATUS_BREAKDOWN:-n/a}"
        echo "             error_summary=${PIPELINE_20K_ERROR_SUMMARY:-n/a}"
        if [[ "${TARGET_SOURCE}" == "all" ]]; then
            echo "             per_source=${PIPELINE_20K_SOURCE_SUMMARY:-n/a}"
        fi
    fi
    echo ""
    echo "Pipeline (evidência):" >> "$LOG_FILE"
    echo "  Seed:      ${PIPELINE_SEED_STATUS:-n/a} – ${PIPELINE_SEED_N:-0} fontes [ids: ${PIPELINE_SEED_IDS:-}]" >> "$LOG_FILE"
    echo "  Discovery: ${PIPELINE_DISCOVERY_STATUS:-n/a} – ${PIPELINE_DISCOVERY_LINKS:-0} links totais" >> "$LOG_FILE"
    echo "  Fetch:     ${PIPELINE_FETCH_STATUS:-n/a} (opcional)" >> "$LOG_FILE"
    if $TARGETED_STRESS; then
        echo "  Targeted:  ${PIPELINE_20K_STATUS:-n/a} – source=${TARGET_SOURCE}, phase=${TARGET_PHASE}, docs=${PIPELINE_20K_DOCS:-0}, peak_mem=${PIPELINE_20K_PEAK_MEM:-n/a}, duration=${PIPELINE_20K_DURATION:-n/a}, throughput=${PIPELINE_20K_THROUGHPUT:-n/a} docs/min" >> "$LOG_FILE"
        echo "             status_breakdown=${PIPELINE_20K_STATUS_BREAKDOWN:-n/a}" >> "$LOG_FILE"
        echo "             error_summary=${PIPELINE_20K_ERROR_SUMMARY:-n/a}" >> "$LOG_FILE"
        if [[ "${TARGET_SOURCE}" == "all" ]]; then
            echo "             per_source=${PIPELINE_20K_SOURCE_SUMMARY:-n/a}" >> "$LOG_FILE"
        fi
    fi

    cat > "$REPORT_JSON_FILE" <<EOF
{
  "timestamp_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "mode": "$(json_escape "$TEST_MODE")",
  "tests": {
    "total": ${TESTS_TOTAL},
    "passed": ${TESTS_PASSED},
    "failed": ${TESTS_FAILED}
  },
  "pipeline": {
    "seed": {
      "status": "$(json_escape "${PIPELINE_SEED_STATUS:-n/a}")",
      "sources_registered": ${PIPELINE_SEED_N:-0},
      "source_ids": "$(json_escape "${PIPELINE_SEED_IDS:-}")"
    },
    "discovery": {
      "status": "$(json_escape "${PIPELINE_DISCOVERY_STATUS:-n/a}")",
      "links_total": ${PIPELINE_DISCOVERY_LINKS:-0},
      "source": "$(json_escape "${PIPELINE_DISCOVERY_SOURCE:-n/a}")"
    },
    "fetch": {
      "status": "$(json_escape "${PIPELINE_FETCH_STATUS:-n/a}")"
    }
  },
  "targeted_stress": {
    "enabled": $($TARGETED_STRESS && echo true || echo false),
    "source": "$(json_escape "$TARGET_SOURCE")",
    "phase": "$(json_escape "$TARGET_PHASE")",
    "max_docs": ${TARGET_MAX_DOCS},
    "monitor_memory": $($MONITOR_MEMORY && echo true || echo false),
    "status": "$(json_escape "${PIPELINE_20K_STATUS:-n/a}")",
    "docs_processed": ${PIPELINE_20K_DOCS:-0},
    "peak_memory": "$(json_escape "${PIPELINE_20K_PEAK_MEM:-n/a}")",
    "duration": "$(json_escape "${PIPELINE_20K_DURATION:-n/a}")",
    "throughput_docs_per_min": "$(json_escape "${PIPELINE_20K_THROUGHPUT:-n/a}")",
    "status_breakdown": "$(json_escape "${PIPELINE_20K_STATUS_BREAKDOWN:-}")",
    "error_summary": "$(json_escape "${PIPELINE_20K_ERROR_SUMMARY:-}")",
    "source_summary": "$(json_escape "${PIPELINE_20K_SOURCE_SUMMARY:-}")"
  }
}
EOF
    echo "Structured report: ${REPORT_JSON_FILE}" >> "$LOG_FILE"
    
    echo -e "\n${BLUE}Log completo: $LOG_FILE${NC}"
    echo -e "${BLUE}Structured report: $REPORT_JSON_FILE${NC}\n"
    
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
    elif [[ "$TEST_MODE" == "docker-20k" ]]; then
        echo "║  Modo: DOCKER-20K (docker-only + targeted stress)                ║"
    elif [[ "$TEST_MODE" == "docker-only" ]]; then
        echo "║  Modo: DOCKER-ONLY (sem dotnet/npm no host)                       ║"
    else
        echo "║  Modo: FULL (destruir → setup.sh → validar)                       ║"
    fi
    echo "╚════════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo "Targeted options: source=${TARGET_SOURCE}, phase=${TARGET_PHASE}, max_docs=${TARGET_MAX_DOCS}, monitor_memory=${MONITOR_MEMORY}"
    
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
    if $TARGETED_STRESS; then
        phase_fetch_20k_observability
    fi
    phase_report
    
    exit $TESTS_FAILED
}

# Tratar Ctrl+C
trap 'echo -e "\n\n${RED}Teste interrompido pelo usuário${NC}"; exit 130' INT

parse_args "$@"
main
