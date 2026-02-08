#!/bin/bash
# =============================================================================
# GABI - Setup Local de Desenvolvimento
# Script idempotente para configurar ambiente de desenvolvimento local
# =============================================================================

set -e

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
RESET='\033[0m'

# Configurações
PYTHON_MIN_VERSION="3.11"
VENV_DIR=".venv"
DOCKER_COMPOSE_FILE="docker-compose.local.yml"
ENV_EXAMPLE=".env.example"
ENV_FILE=".env"
ALEMBIC_DIR="alembic"

# =============================================================================
# Funções Auxiliares
# =============================================================================

log_info() {
    echo -e "${BLUE}ℹ️  $1${RESET}"
}

log_success() {
    echo -e "${GREEN}✅ $1${RESET}"
}

log_warn() {
    echo -e "${YELLOW}⚠️  $1${RESET}"
}

log_error() {
    echo -e "${RED}❌ $1${RESET}"
}

log_step() {
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${RESET}"
    echo -e "${BLUE}  $1${RESET}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${RESET}"
}

# Compara versões (retorna 0 se v1 >= v2)
version_ge() {
    printf '%s\n%s\n' "$2" "$1" | sort -V -C 2>/dev/null
}

# =============================================================================
# Verificação do Python
# =============================================================================

check_python() {
    log_step "1/7 - Verificando Python"
    
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 não encontrado. Por favor, instale Python ${PYTHON_MIN_VERSION}+"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    log_info "Python encontrado: ${PYTHON_VERSION}"
    
    if ! version_ge "$PYTHON_VERSION" "$PYTHON_MIN_VERSION"; then
        log_error "Python ${PYTHON_MIN_VERSION}+ é necessário. Versão atual: ${PYTHON_VERSION}"
        exit 1
    fi
    
    log_success "Python ${PYTHON_VERSION} é compatível (>= ${PYTHON_MIN_VERSION})"
}

# =============================================================================
# Criação do Virtual Environment
# =============================================================================

setup_venv() {
    log_step "2/7 - Configurando Virtual Environment"
    
    if [[ -d "$VENV_DIR" ]]; then
        log_warn "Virtual environment já existe em ./${VENV_DIR}"
        
        # Verifica se está ativado
        if [[ -z "${VIRTUAL_ENV:-}" ]]; then
            log_info "Ativando virtual environment..."
            # shellcheck source=/dev/null
            source "${VENV_DIR}/bin/activate"
        fi
    else
        log_info "Criando virtual environment em ./${VENV_DIR}..."
        python3 -m venv "$VENV_DIR"
        log_success "Virtual environment criado"
        
        log_info "Ativando virtual environment..."
        # shellcheck source=/dev/null
        source "${VENV_DIR}/bin/activate"
    fi
    
    # Atualiza pip
    log_info "Atualizando pip..."
    pip install --quiet --upgrade pip setuptools wheel
    
    log_success "Virtual environment pronto"
}

# =============================================================================
# Instalação de Dependências
# =============================================================================

install_dependencies() {
    log_step "3/7 - Instalando Dependências"
    
    # Verifica se há requirements.txt ou pyproject.toml
    if [[ -f "pyproject.toml" ]]; then
        log_info "Instalando via pip (pyproject.toml)..."
        pip install --quiet -e ".[dev]"
    elif [[ -f "requirements.txt" ]]; then
        log_info "Instalando dependências de requirements.txt..."
        pip install --quiet -r requirements.txt
        
        if [[ -f "requirements-dev.txt" ]]; then
            log_info "Instalando dependências de desenvolvimento..."
            pip install --quiet -r requirements-dev.txt
        fi
    else
        log_warn "Nenhum arquivo de dependências encontrado (pyproject.toml ou requirements.txt)"
    fi
    
    log_success "Dependências instaladas"
}

# =============================================================================
# Configuração do .env
# =============================================================================

setup_env() {
    log_step "4/7 - Configurando Variáveis de Ambiente"
    
    if [[ -f "$ENV_FILE" ]]; then
        log_warn "Arquivo ${ENV_FILE} já existe. Pulando..."
        return 0
    fi
    
    if [[ -f "$ENV_EXAMPLE" ]]; then
        log_info "Copiando ${ENV_EXAMPLE} → ${ENV_FILE}..."
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        log_success "Arquivo ${ENV_FILE} criado a partir de ${ENV_EXAMPLE}"
        log_warn "⚠️  IMPORTANTE: Edite ${ENV_FILE} com suas configurações reais!"
    else
        log_warn "Arquivo ${ENV_EXAMPLE} não encontrado. Criando ${ENV_FILE} básico..."
        cat > "$ENV_FILE" << 'EOF'
# GABI - Configurações de Ambiente Local
# Edite conforme necessário

# Ambiente
ENV=development
DEBUG=true

# Database
DATABASE_URL=postgresql://gabi:gabi@localhost:5432/gabi
DATABASE_POOL_SIZE=10

# Elasticsearch
ELASTICSEARCH_URL=http://localhost:9200
ELASTICSEARCH_INDEX=gabi_documents

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT / Auth
SECRET_KEY=change-me-in-production-use-strong-secret-key-here
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# API
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=1

# Embeddings
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DIMENSION=384
EMBEDDING_BATCH_SIZE=32

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
EOF
        log_success "Arquivo ${ENV_FILE} básico criado"
        log_warn "⚠️  IMPORTANTE: Revise e ajuste as configurações em ${ENV_FILE}!"
    fi
}

# =============================================================================
# Docker Compose
# =============================================================================

docker_up() {
    log_step "5/7 - Iniciando Serviços Docker"
    
    if ! command -v docker &> /dev/null; then
        log_error "Docker não encontrado. Por favor, instale o Docker."
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        log_error "Docker Compose não encontrado. Por favor, instale o Docker Compose."
        exit 1
    fi
    
    # Determina o comando correto do docker compose
    if docker compose version &> /dev/null 2>&1; then
        COMPOSE_CMD="docker compose"
    else
        COMPOSE_CMD="docker-compose"
    fi
    
    # Verifica se o arquivo existe
    if [[ ! -f "$DOCKER_COMPOSE_FILE" ]]; then
        log_warn "Arquivo ${DOCKER_COMPOSE_FILE} não encontrado"
        # Tenta encontrar alternativas
        if [[ -f "docker-compose.yml" ]]; then
            DOCKER_COMPOSE_FILE="docker-compose.yml"
            log_info "Usando docker-compose.yml como alternativa"
        elif [[ -f "docker/docker-compose.local.yml" ]]; then
            DOCKER_COMPOSE_FILE="docker/docker-compose.local.yml"
            log_info "Usando docker/docker-compose.local.yml como alternativa"
        else
            log_warn "Nenhum arquivo docker-compose encontrado. Pulando Docker..."
            return 0
        fi
    fi
    
    log_info "Iniciando containers com ${DOCKER_COMPOSE_FILE}..."
    $COMPOSE_CMD -f "$DOCKER_COMPOSE_FILE" up -d
    
    log_success "Containers Docker iniciados"
}

# =============================================================================
# Aguardar Serviços
# =============================================================================

wait_for_services() {
    log_step "6/7 - Aguardando Serviços Ficarem Prontos"
    
    local max_attempts=30
    local wait_time=2
    local attempt=1
    
    # Função para verificar se PostgreSQL está pronto
    check_postgres() {
        local db_url="${DATABASE_URL:-postgresql://gabi:gabi@localhost:5432/gabi}"
        pg_isready -h localhost -p 5432 &> /dev/null 2>&1 || return 1
        return 0
    }
    
    # Função para verificar se Elasticsearch está pronto
    check_elasticsearch() {
        curl -s http://localhost:9200/_cluster/health &> /dev/null || return 1
        return 0
    }
    
    # Função para verificar se Redis está pronto
    check_redis() {
        redis-cli ping &> /dev/null || return 1
        return 0
    }
    
    log_info "Aguardando PostgreSQL..."
    while ! check_postgres && [[ $attempt -le $max_attempts ]]; do
        echo -n "."
        sleep $wait_time
        ((attempt++))
    done
    echo ""
    
    if [[ $attempt -le $max_attempts ]]; then
        log_success "PostgreSQL pronto"
    else
        log_warn "Timeout aguardando PostgreSQL. Continuando mesmo assim..."
    fi
    
    attempt=1
    log_info "Aguardando Elasticsearch..."
    while ! check_elasticsearch && [[ $attempt -le $max_attempts ]]; do
        echo -n "."
        sleep $wait_time
        ((attempt++))
    done
    echo ""
    
    if [[ $attempt -le $max_attempts ]]; then
        log_success "Elasticsearch pronto"
    else
        log_warn "Timeout aguardando Elasticsearch. Continuando mesmo assim..."
    fi
    
    attempt=1
    log_info "Aguardando Redis..."
    while ! check_redis && [[ $attempt -le $max_attempts ]]; do
        echo -n "."
        sleep $wait_time
        ((attempt++))
    done
    echo ""
    
    if [[ $attempt -le $max_attempts ]]; then
        log_success "Redis pronto"
    else
        log_warn "Timeout aguardando Redis. Continuando mesmo assim..."
    fi
}

# =============================================================================
# Migrações
# =============================================================================

run_migrations() {
    log_step "7/7 - Executando Migrações"
    
    # Verifica se o diretório alembic existe
    if [[ ! -d "$ALEMBIC_DIR" ]]; then
        log_warn "Diretório ${ALEMBIC_DIR} não encontrado. Pulando migrações..."
        return 0
    fi
    
    # Verifica se há um script de migração
    if [[ -f "scripts/migrate.sh" ]]; then
        log_info "Executando script de migração..."
        bash scripts/migrate.sh
    elif [[ -f "${ALEMBIC_DIR}/alembic.ini" ]]; then
        log_info "Executando alembic upgrade head..."
        (cd "$ALEMBIC_DIR" && alembic upgrade head)
    else
        log_warn "Configuração do alembic não encontrada. Pulando migrações..."
        return 0
    fi
    
    log_success "Migrações aplicadas com sucesso"
}

# =============================================================================
# Execução Principal
# =============================================================================

main() {
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${RESET}"
    echo -e "${BLUE}║        GABI - Setup de Desenvolvimento Local                  ║${RESET}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${RESET}"
    echo ""
    
    # Guarda o diretório inicial
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
    
    cd "$PROJECT_ROOT"
    log_info "Diretório do projeto: ${PROJECT_ROOT}"
    
    # Executa as etapas
    check_python
    setup_venv
    install_dependencies
    setup_env
    docker_up
    wait_for_services
    run_migrations
    
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${RESET}"
    echo -e "${GREEN}║        ✅ Setup Completo! Ambiente Pronto                     ║${RESET}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${RESET}"
    echo ""
    log_info "Próximos passos:"
    echo ""
    echo "  1. Ative o virtual environment:"
    echo -e "     ${YELLOW}source .venv/bin/activate${RESET}"
    echo ""
    echo "  2. Inicie a API:"
    echo -e "     ${YELLOW}make run${RESET}"
    echo "     ou"
    echo -e "     ${YELLOW}cd src && uvicorn gabi.main:app --reload${RESET}"
    echo ""
    echo "  3. Acesse a documentação:"
    echo -e "     ${YELLOW}http://localhost:8000/docs${RESET}"
    echo ""
    echo "  4. Para executar migrações futuras:"
    echo -e "     ${YELLOW}make migrate${RESET}"
    echo "     ou"
    echo -e "     ${YELLOW}bash scripts/migrate.sh${RESET}"
    echo ""
}

# Executa o main se o script for executado diretamente
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
