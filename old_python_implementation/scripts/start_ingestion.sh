#!/bin/bash
set -euo pipefail

# =============================================================================
# Script de Ingestão GABI
# Recria TEI, limpa dados anteriores, re-seed sources e executa ingestão
# =============================================================================

# Configurações
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_NAME="gabi"
TEI_HEALTH_URL="http://localhost:8080/health"
TEI_EMBED_URL="http://localhost:8080/embed"
MAX_RETRIES=60
RETRY_INTERVAL=5
RUN_TESTS="${RUN_TESTS:-1}"
TEST_SCOPE="${TEST_SCOPE:-smoke}"
MAX_DOCS_PER_SOURCE="${MAX_DOCS_PER_SOURCE:-200}"
INGEST_SOURCE="${INGEST_SOURCE:-}"
SOURCES_FILE="${SOURCES_FILE:-sources.yaml}"
DISABLE_EMBEDDINGS="${DISABLE_EMBEDDINGS:-0}"
SOURCE_TIMEOUT_SECONDS="${SOURCE_TIMEOUT_SECONDS:-900}"
CONTINUE_ON_SOURCE_ERROR="${CONTINUE_ON_SOURCE_ERROR:-1}"
FAIL_ON_SOURCE_ERROR="${FAIL_ON_SOURCE_ERROR:-0}"
SKIP_CLEAN="${SKIP_CLEAN:-0}"
INGEST_MODE="${INGEST_MODE:-queued}"
STALE_MANIFEST_MINUTES="${STALE_MANIFEST_MINUTES:-120}"
LOG_DIR="${PROJECT_ROOT}/logs"
LOG_FILE="${LOG_DIR}/ingestion_$(date +%Y%m%d_%H%M%S).log"

# Cores para output (se terminal suportar)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Função de log com timestamp
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    case "$level" in
        INFO)  echo -e "${GREEN}[${timestamp}] [INFO]${NC} ${message}" ;;
        WARN)  echo -e "${YELLOW}[${timestamp}] [WARN]${NC} ${message}" ;;
        ERROR) echo -e "${RED}[${timestamp}] [ERROR]${NC} ${message}" >&2 ;;
        STEP)  echo -e "${BLUE}[${timestamp}] [STEP]${NC} ${message}" ;;
        *)     echo "[${timestamp}] [${level}] ${message}" ;;
    esac
}

# Função para verificar se um container está healthy
check_container_health() {
    local container_name="$1"
    local status
    
    status=$(docker inspect --format='{{.State.Health.Status}}' "${container_name}" 2>/dev/null || echo "unknown")
    
    if [[ "$status" == "healthy" ]]; then
        return 0
    else
        return 1
    fi
}

# Função para verificar se um container está rodando
check_container_running() {
    local container_name="$1"
    local state
    
    state=$(docker inspect --format='{{.State.Running}}' "${container_name}" 2>/dev/null || echo "false")
    
    if [[ "$state" == "true" ]]; then
        return 0
    else
        return 1
    fi
}

# Função para aguardar container ficar healthy
wait_for_container() {
    local container_name="$1"
    local timeout="${2:-300}"  # 5 minutos padrão
    local retries=$((timeout / RETRY_INTERVAL))
    
    log "INFO" "Aguardando ${container_name} ficar healthy (timeout: ${timeout}s)..."
    
    for i in $(seq 1 $retries); do
        if check_container_health "${container_name}"; then
            log "INFO" "✓ ${container_name} está healthy"
            return 0
        fi
        
        if check_container_running "${container_name}"; then
            log "WARN" "  ${container_name} rodando mas não healthy (${i}/${retries})"
        else
            log "WARN" "  ${container_name} não está rodando (${i}/${retries})"
        fi
        
        sleep $RETRY_INTERVAL
    done
    
    log "ERROR" "✗ ${container_name} não ficou healthy após ${timeout} segundos"
    docker logs "${container_name}" --tail 30 2>/dev/null || true
    return 1
}

# =============================================================================
# INÍCIO DO SCRIPT
# =============================================================================

cd "${PROJECT_ROOT}" || {
    log "ERROR" "Não foi possível entrar no diretório ${PROJECT_ROOT}"
    exit 1
}

log "STEP" "=========================================="
log "STEP" "Iniciando script de ingestão GABI"
log "STEP" "=========================================="

mkdir -p "${LOG_DIR}"
exec > >(tee -a "${LOG_FILE}") 2>&1
log "INFO" "Log da ingestão: ${LOG_FILE}"

# -----------------------------------------------------------------------------
# 1. VERIFICAÇÕES DE PRÉ-CONDIÇÃO
# -----------------------------------------------------------------------------
log "STEP" "Verificando pré-condições..."

# Verificar se docker está disponível
if ! command -v docker &> /dev/null; then
    log "ERROR" "Docker não encontrado. Por favor instale o Docker."
    exit 1
fi

# Verificar se docker compose está disponível
if ! docker compose version &> /dev/null; then
    log "ERROR" "Docker Compose não encontrado. Por favor instale o Docker Compose."
    exit 1
fi

# Verificar se .venv existe
if [[ ! -d ".venv" ]]; then
    log "ERROR" "Virtual environment .venv não encontrado!"
    log "ERROR" "Execute: uv venv ou python -m venv .venv"
    exit 1
fi
log "INFO" "✓ Virtual environment encontrado"

# Verificar containers essenciais
REQUIRED_CONTAINERS=("${PROJECT_NAME}-postgres" "${PROJECT_NAME}-elasticsearch" "${PROJECT_NAME}-redis")

for container in "${REQUIRED_CONTAINERS[@]}"; do
    log "INFO" "Verificando container: ${container}"
    
    if ! check_container_running "${container}"; then
        log "ERROR" "✗ Container ${container} não está rodando!"
        log "ERROR" "Execute primeiro: docker compose --profile infra up -d"
        exit 1
    fi
    
    if ! check_container_health "${container}"; then
        log "WARN" "Container ${container} rodando mas não está healthy"
        log "INFO" "Tentando aguardar..."
        if ! wait_for_container "${container}" 60; then
            log "ERROR" "Container ${container} não ficou healthy"
            exit 1
        fi
    else
        log "INFO" "✓ ${container} está healthy"
    fi
done

log "INFO" "✓ Todas as pré-condições verificadas com sucesso"

# -----------------------------------------------------------------------------
# 2. RECRIAR TEI
# -----------------------------------------------------------------------------
log "STEP" "Recriando container TEI..."

if ! docker compose --profile infra up -d tei --force-recreate; then
    log "ERROR" "Falha ao recriar container TEI"
    exit 1
fi

log "INFO" "✓ Container TEI recriado"

# -----------------------------------------------------------------------------
# 3. AGUARDAR TEI FICAR HEALTHY
# -----------------------------------------------------------------------------
log "STEP" "Aguardando TEI ficar healthy..."

for i in $(seq 1 $MAX_RETRIES); do
    if curl -sf "${TEI_HEALTH_URL}" > /dev/null 2>&1; then
        log "INFO" "✓ TEI está healthy e respondendo"
        break
    fi
    
    if [[ "$i" -eq $MAX_RETRIES ]]; then
        log "ERROR" "✗ TEI não ficou healthy após $((MAX_RETRIES * RETRY_INTERVAL)) segundos"
        log "ERROR" "Últimos logs do container:"
        docker logs "${PROJECT_NAME}-tei" --tail 30 2>/dev/null || true
        exit 1
    fi
    
    if [[ $((i % 10)) -eq 0 ]]; then
        log "INFO" "  Aguardando TEI... (${i}/${MAX_RETRIES})"
    fi
    
    sleep $RETRY_INTERVAL
done

# -----------------------------------------------------------------------------
# 4. TESTAR TEI COM TEXTO LONGO
# -----------------------------------------------------------------------------
log "STEP" "Testando TEI com texto longo (>128 tokens)..."

TEST_TEXT='{"inputs": "O Tribunal de Contas da União, no uso de suas atribuições constitucionais, legais e regimentais, considerando os fatos apurados no processo de fiscalização referente à aplicação dos recursos públicos federais, resolve aprovar o acórdão a seguir transcrito, que foi proferido pelo Plenário em sessão ordinária. O relator apresentou análise detalhada dos elementos probatórios coligidos durante a instrução processual, com fundamento nas disposições da Lei Orgânica do TCU. A unidade técnica competente emitiu parecer conclusivo sobre a regularidade das contas públicas examinadas neste exercício financeiro."}'

TEI_RESPONSE=$(curl -sf "${TEI_EMBED_URL}" -X POST \
    -H 'Content-Type: application/json' \
    -d "${TEST_TEXT}" 2>/dev/null) || {
    log "ERROR" "Falha ao conectar com TEI para teste de embedding"
    exit 1
}

# Verificar resposta válida
if command -v python3 &> /dev/null; then
    EMBEDDING_DIMS=$(echo "${TEI_RESPONSE}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d[0]))" 2>/dev/null) || {
        log "ERROR" "Resposta inválida do TEI"
        log "ERROR" "Resposta: ${TEI_RESPONSE}"
        exit 1
    }
    log "INFO" "✓ TEI OK: ${EMBEDDING_DIMS} dimensões (texto longo aceito)"
else
    log "WARN" "Python3 não disponível para validar resposta"
    log "INFO" "✓ TEI respondeu (texto longo)"
fi

# -----------------------------------------------------------------------------
# 5. CONFIGURAR AMBIENTE
# -----------------------------------------------------------------------------
log "STEP" "Configurando variáveis de ambiente..."

if [[ ! -f ".venv/bin/activate" ]]; then
    log "ERROR" "Arquivo de ativação do venv não encontrado"
    exit 1
fi

# shellcheck source=/dev/null
source .venv/bin/activate

# Load .env for local config (DB port, etc.)
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    set -a; source "${PROJECT_ROOT}/.env"; set +a
fi

PG_PORT="${GABI_POSTGRES_PORT:-5432}"
export GABI_DATABASE_URL="${GABI_DATABASE_URL:-postgresql+asyncpg://gabi:gabi_dev_password@localhost:${PG_PORT}/gabi}"
export GABI_AUTH_ENABLED=false
export GABI_FETCHER_SSRF_ENABLED=false
export GABI_ELASTICSEARCH_URL=http://localhost:9200
export GABI_EMBEDDINGS_URL=http://localhost:8080
export GABI_REDIS_URL=redis://localhost:6379/0
export PYTHONUNBUFFERED=1

log "INFO" "✓ Variáveis de ambiente configuradas"

# -----------------------------------------------------------------------------
# 6. LIMPAR DADOS DA RODADA ANTERIOR
# -----------------------------------------------------------------------------
if [[ "${SKIP_CLEAN}" == "1" ]]; then
    log "WARN" "Limpeza pulada (SKIP_CLEAN=1) — modo resume"
else
    log "STEP" "Limpando dados da rodada anterior..."

    if ! docker exec "${PROJECT_NAME}-postgres" psql -U gabi -d gabi -c "DELETE FROM document_chunks; DELETE FROM documents; DELETE FROM execution_manifests;" 2>/dev/null; then
        log "WARN" "Possível falha ao limpar dados (pode ser normal se tabelas estão vazias)"
    else
        log "INFO" "✓ Dados anteriores limpos"
    fi
fi

# -----------------------------------------------------------------------------
# 7. RE-SEED SOURCES
# -----------------------------------------------------------------------------
log "STEP" "Executando re-seed dos sources..."

if [[ ! -f "scripts/seed_sources.py" ]]; then
    log "ERROR" "Script seed_sources.py não encontrado"
    exit 1
fi

if ! PYTHONPATH=src python scripts/seed_sources.py; then
    log "ERROR" "Falha ao executar seed_sources.py"
    exit 1
fi

log "INFO" "✓ Sources re-seed concluído"

# -----------------------------------------------------------------------------
# 8. TEST GATE (OPCIONAL)
# -----------------------------------------------------------------------------
if [[ "${RUN_TESTS}" == "1" ]]; then
    log "STEP" "Executando testes antes da ingestão (escopo: ${TEST_SCOPE})..."
    set +e
    if [[ "${TEST_SCOPE}" == "full" ]]; then
        GABI_DATABASE_URL="${GABI_DATABASE_URL}" \
            python -m pytest tests/ --ignore=tests/integration/test_indexer.py --timeout=60 -q --tb=line
    else
        GABI_DATABASE_URL="${GABI_DATABASE_URL}" \
            python -m pytest tests/unit/test_discovery.py tests/unit/tasks/test_sync.py tests/unit/tasks/test_health.py -q --tb=line
    fi
    TEST_EXIT=$?
    set -e
    if [[ "${TEST_EXIT}" -ne 0 ]]; then
        log "ERROR" "Test gate falhou (exit ${TEST_EXIT}). Abortando ingestão."
        exit "${TEST_EXIT}"
    fi
    log "INFO" "✓ Test gate aprovado"
else
    log "WARN" "Test gate desabilitado (RUN_TESTS=0)"
fi

# -----------------------------------------------------------------------------
# 9. EXECUTAR INGESTÃO
# -----------------------------------------------------------------------------
if [[ "${INGEST_MODE}" == "queued" ]]; then
    log "STEP" "Iniciando ingestão em modo enfileirado (INGEST_MODE=queued)..."
    if ! PYTHONPATH=src python -m gabi.cli reset-stale-manifests --stale-minutes "${STALE_MANIFEST_MINUTES}"; then
        log "WARN" "Falha ao resetar manifests travados; continuando agendamento"
    fi

    if [[ -n "${INGEST_SOURCE}" ]]; then
        SCHEDULE_CMD=(python -m gabi.cli ingest-schedule --sources-file "${SOURCES_FILE}" --source "${INGEST_SOURCE}" --max-docs-per-source "${MAX_DOCS_PER_SOURCE}")
    else
        SCHEDULE_CMD=(python -m gabi.cli ingest-schedule --sources-file "${SOURCES_FILE}" --max-docs-per-source "${MAX_DOCS_PER_SOURCE}")
    fi
    if [[ "${DISABLE_EMBEDDINGS}" == "1" ]]; then
        SCHEDULE_CMD+=(--disable-embeddings)
        log "WARN" "Embeddings desabilitados (DISABLE_EMBEDDINGS=1)"
    fi

    if ! PYTHONPATH=src "${SCHEDULE_CMD[@]}"; then
        log "ERROR" "Falha no agendamento de ingestão"
        exit 1
    fi
    log "INFO" "✓ Ingestão enfileirada com sucesso"
    log "INFO" "MODO QUEUED: este script agenda os jobs e termina sem aguardar processamento completo."
    log "STEP" "=========================================="
    log "STEP" "Script de ingestão finalizado com sucesso!"
    log "STEP" "=========================================="
    exit 0
fi

run_ingest_source() {
    local source_id="$1"
    local -a cmd=(python -m gabi.cli ingest --source "${source_id}" --max-docs-per-source "${MAX_DOCS_PER_SOURCE}")
    local rc

    if [[ "${DISABLE_EMBEDDINGS}" == "1" ]]; then
        cmd+=(--disable-embeddings)
    fi

    if command -v timeout >/dev/null 2>&1; then
        set +e
        timeout --signal=TERM --kill-after=30 "${SOURCE_TIMEOUT_SECONDS}" env PYTHONPATH=src "${cmd[@]}"
        rc=$?
        set -e
    else
        log "WARN" "'timeout' não encontrado; executando sem timeout por source"
        set +e
        PYTHONPATH=src "${cmd[@]}"
        rc=$?
        set -e
    fi

    return "${rc}"
}

if [[ "${DISABLE_EMBEDDINGS}" == "1" ]]; then
    log "WARN" "Embeddings desabilitados (DISABLE_EMBEDDINGS=1)"
fi

if [[ -n "${INGEST_SOURCE}" ]]; then
    log "STEP" "Iniciando ingestão da source ${INGEST_SOURCE} (max ${MAX_DOCS_PER_SOURCE} docs, timeout ${SOURCE_TIMEOUT_SECONDS}s)..."
    if ! run_ingest_source "${INGEST_SOURCE}"; then
        log "ERROR" "Falha durante ingestão da source ${INGEST_SOURCE}"
        exit 1
    fi
else
    log "STEP" "Iniciando ingestão por source (max ${MAX_DOCS_PER_SOURCE} docs/source, timeout ${SOURCE_TIMEOUT_SECONDS}s)..."
    SOURCE_IDS=$(python -c 'import yaml,sys; d=yaml.safe_load(open("'"${SOURCES_FILE}"'","r",encoding="utf-8")) or {}; print(" ".join((d.get("sources") or {}).keys()))')
    if [[ -z "${SOURCE_IDS}" ]]; then
        log "ERROR" "Nenhuma source encontrada em ${SOURCES_FILE}"
        exit 1
    fi

    FAILED_SOURCES=()
    SUCCESS_COUNT=0

    for source_id in ${SOURCE_IDS}; do
        log "INFO" "Ingerindo source: ${source_id}"
        if run_ingest_source "${source_id}"; then
            SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
            log "INFO" "✓ Source concluída: ${source_id}"
            continue
        fi

        rc=$?
        if [[ "${rc}" -eq 124 || "${rc}" -eq 137 ]]; then
            log "WARN" "Timeout na source ${source_id} após ${SOURCE_TIMEOUT_SECONDS}s"
        else
            log "WARN" "Source ${source_id} falhou com exit code ${rc}"
        fi
        FAILED_SOURCES+=("${source_id}")

        if [[ "${CONTINUE_ON_SOURCE_ERROR}" != "1" ]]; then
            log "ERROR" "Abortando por falha (CONTINUE_ON_SOURCE_ERROR=0)"
            exit 1
        fi
    done

    if [[ "${#FAILED_SOURCES[@]}" -gt 0 ]]; then
        log "WARN" "Ingestão parcial: ${SUCCESS_COUNT} sources OK, ${#FAILED_SOURCES[@]} falharam/travaram"
        log "WARN" "Sources com erro: ${FAILED_SOURCES[*]}"
        if [[ "${FAIL_ON_SOURCE_ERROR}" == "1" ]]; then
            log "ERROR" "Finalizando com erro por FAIL_ON_SOURCE_ERROR=1"
            exit 1
        fi
    else
        log "INFO" "✓ Todas as sources processadas com sucesso"
    fi
fi

log "INFO" "✓ Ingestão finalizada"

# -----------------------------------------------------------------------------
# 10. RELATÓRIO PÓS-INGESTÃO
# -----------------------------------------------------------------------------
log "STEP" "Gerando resumo pós-ingestão..."

docker exec "${PROJECT_NAME}-postgres" psql -U gabi -d gabi -c \
    "SELECT source_id, status, started_at, completed_at FROM execution_manifests ORDER BY started_at DESC LIMIT 20;" || true

docker exec "${PROJECT_NAME}-postgres" psql -U gabi -d gabi -c \
    "SELECT sr.name, sr.status, sr.document_count, COUNT(d.id) AS actual_docs FROM source_registry sr LEFT JOIN documents d ON d.source_id = sr.id AND d.is_deleted = false WHERE sr.deleted_at IS NULL GROUP BY sr.name, sr.status, sr.document_count ORDER BY actual_docs DESC;" || true

docker exec "${PROJECT_NAME}-postgres" psql -U gabi -d gabi -c \
    "SELECT COUNT(*) AS total_docs FROM documents WHERE is_deleted = false;" || true

docker exec "${PROJECT_NAME}-postgres" psql -U gabi -d gabi -c \
    "SELECT COUNT(*) AS total_chunks FROM document_chunks WHERE is_deleted = false;" || true

docker exec "${PROJECT_NAME}-postgres" psql -U gabi -d gabi -c \
    "SELECT COUNT(*) AS total_embeddings FROM document_chunks WHERE is_deleted = false AND embedding IS NOT NULL;" || true

# -----------------------------------------------------------------------------
# FIM
# -----------------------------------------------------------------------------
log "STEP" "=========================================="
log "STEP" "Script de ingestão finalizado com sucesso!"
log "STEP" "=========================================="

exit 0
