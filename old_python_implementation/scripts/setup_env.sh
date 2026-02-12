#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# GABI - Environment Setup
# Configura variáveis de ambiente de forma limpa e consistente
# Uso: source ./scripts/setup_env.sh
# NOTA: Este script deve ser SOURCED, não executado!
# ═══════════════════════════════════════════════════════════════════════════════

# Detectar diretório do projeto
if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
elif [[ -n "${0:-}" ]]; then
    # Fallback para sh/zsh
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
else
    # Último recurso: assumir diretório atual
    PROJECT_DIR="$(pwd)"
fi

# Validar que estamos no diretório correto
if [[ ! -f "$PROJECT_DIR/pyproject.toml" ]]; then
    echo "❌ Erro: Não parece ser o diretório do projeto GABI" >&2
    echo "   pyproject.toml não encontrado em: $PROJECT_DIR" >&2
    return 1 2>/dev/null || exit 1
fi

# Cores (apenas se terminal interativo)
if [[ -t 2 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    BLUE='\033[0;34m'
    NC='\033[0m'
else
    RED=''; GREEN=''; BLUE=''; NC=''
fi

log() { echo -e "${BLUE}[env-setup]${NC} $*" >&2; }
ok() { echo -e "${GREEN}[env-setup]${NC} $*" >&2; }
error() { echo -e "${RED}[env-setup]${NC} $*" >&2; }

log "Configurando ambiente GABI..."
log "Diretório do projeto: $PROJECT_DIR"

# ═══════════════════════════════════════════════════════════════════════════════
# PASSO 1: Limpar variáveis que podem estar poluídas
# ═══════════════════════════════════════════════════════════════════════════════

# Desexportar e limpar variáveis críticas
for var in PYTHONPATH GABI_DATABASE_URL GABI_ELASTICSEARCH_URL GABI_REDIS_URL \
           GABI_EMBEDDINGS_URL GABI_AUTH_ENABLED GABI_FETCHER_SSRF_ENABLED; do
    unset $var 2>/dev/null || true
done

# ═══════════════════════════════════════════════════════════════════════════════
# PASSO 2: Carregar .env se existir (valores padrão do usuário)
# ═══════════════════════════════════════════════════════════════════════════════

if [[ -f "$PROJECT_DIR/.env" ]]; then
    log "Carregando variáveis de $PROJECT_DIR/.env"
    set -a
    # shellcheck source=/dev/null
    source "$PROJECT_DIR/.env"
    set +a
fi

# ═══════════════════════════════════════════════════════════════════════════════
# PASSO 3: Configurar variáveis com valores garantidos
# ═══════════════════════════════════════════════════════════════════════════════

# Detectar porta do PostgreSQL (do .env ou padrão)
PG_PORT="${GABI_POSTGRES_PORT:-5432}"

# Configurar variáveis essenciais (usando valores do .env ou defaults)
export PYTHONPATH="$PROJECT_DIR/src"
export GABI_DATABASE_URL="${GABI_DATABASE_URL:-postgresql+asyncpg://gabi:gabi_dev_password@localhost:${PG_PORT}/gabi}"
export GABI_ELASTICSEARCH_URL="${GABI_ELASTICSEARCH_URL:-http://localhost:9200}"
export GABI_REDIS_URL="${GABI_REDIS_URL:-redis://localhost:6379/0}"
export GABI_EMBEDDINGS_URL="${GABI_EMBEDDINGS_URL:-http://localhost:8080}"
export GABI_AUTH_ENABLED="${GABI_AUTH_ENABLED:-false}"
export GABI_FETCHER_SSRF_ENABLED="${GABI_FETCHER_SSRF_ENABLED:-false}"
export PYTHONUNBUFFERED=1

# ═══════════════════════════════════════════════════════════════════════════════
# PASSO 4: Verificar virtual environment
# ═══════════════════════════════════════════════════════════════════════════════

VENV_PATH="$PROJECT_DIR/.venv"

if [[ ! -d "$VENV_PATH" ]]; then
    error "❌ Virtual environment não encontrado: $VENV_PATH"
    error "   Execute: uv venv  ou  python -m venv .venv"
    return 1 2>/dev/null || exit 1
fi

if [[ ! -f "$VENV_PATH/bin/activate" ]]; then
    error "❌ Arquivo de ativação não encontrado: $VENV_PATH/bin/activate"
    return 1 2>/dev/null || exit 1
fi

# Ativar virtual environment
# shellcheck source=/dev/null
source "$VENV_PATH/bin/activate"

# Verificar que Python está vindo do venv
VENV_PYTHON="$(which python 2>/dev/null || echo "unknown")"
if [[ "$VENV_PYTHON" != "$VENV_PATH/bin/python" ]]; then
    warn "⚠️  Python pode não estar vindo do virtual environment"
    warn "   Esperado: $VENV_PATH/bin/python"
    warn "   Atual: $VENV_PYTHON"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# PASSO 5: Resumo
# ═══════════════════════════════════════════════════════════════════════════════

ok "✓ Ambiente configurado com sucesso!"
log ""
log "Configurações ativas:"
log "  PYTHONPATH=$PYTHONPATH"
log "  DATABASE_URL=$GABI_DATABASE_URL"
log "  ELASTICSEARCH_URL=$GABI_ELASTICSEARCH_URL"
log "  REDIS_URL=$GABI_REDIS_URL"
log "  EMBEDDINGS_URL=$GABI_EMBEDDINGS_URL"
log "  AUTH_ENABLED=$GABI_AUTH_ENABLED"
log ""
log "Python: $VENV_PYTHON"
log ""

# Se estiver sendo executado (não sourced), mostrar aviso
if [[ "${BASH_SOURCE[0]:-}" == "${0:-}" ]]; then
    error "⚠️  AVISO: Este script deve ser SOURCED, não executado!"
    error ""
    error "Uso correto:"
    error "  source ./scripts/setup_env.sh"
    error ""
    error "Ou:"
    error "  . ./scripts/setup_env.sh"
    error ""
    exit 1
fi

return 0
