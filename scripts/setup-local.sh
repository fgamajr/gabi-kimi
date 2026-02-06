#!/bin/bash
#
# Script de setup para ambiente de desenvolvimento local do GABI
# GABI - Gerador Automático de Boletins por Inteligência Artificial
#

set -e  # Sai em caso de erro

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Variáveis
PYTHON_MIN_VERSION="3.11"
VENV_DIR=".venv"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Funções auxiliares
print_header() {
    echo -e "${BLUE}"
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║           GABI - Setup de Ambiente de Desenvolvimento            ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

print_step() {
    echo -e "${BLUE}➜${NC} $1"
}

print_success() {
    echo -e "${GREEN}✔${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✖${NC} $1"
}

# Verifica versão do Python
check_python_version() {
    print_step "Verificando versão do Python..."
    
    if ! command -v python3 &> /dev/null; then
        if ! command -v python &> /dev/null; then
            print_error "Python não encontrado. Por favor, instale o Python ${PYTHON_MIN_VERSION}+"
            exit 1
        fi
        PYTHON_CMD="python"
    else
        PYTHON_CMD="python3"
    fi
    
    PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)
    
    if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]); then
        print_error "Python ${PYTHON_VERSION} encontrado, mas é necessário Python ${PYTHON_MIN_VERSION}+"
        exit 1
    fi
    
    print_success "Python ${PYTHON_VERSION} encontrado"
}

# Cria ambiente virtual se não existir
setup_venv() {
    print_step "Configurando ambiente virtual..."
    
    cd "$PROJECT_ROOT"
    
    if [ ! -d "$VENV_DIR" ]; then
        $PYTHON_CMD -m venv "$VENV_DIR"
        print_success "Ambiente virtual criado em ${VENV_DIR}"
    else
        print_warning "Ambiente virtual já existe em ${VENV_DIR}"
    fi
    
    # Ativa o ambiente virtual
    source "$VENV_DIR/bin/activate"
    print_success "Ambiente virtual ativado"
}

# Instala dependências
install_dependencies() {
    print_step "Instalando dependências..."
    
    # Atualiza pip
    pip install --upgrade pip setuptools wheel
    
    # Instala em modo desenvolvimento
    pip install -e ".[dev]"
    
    print_success "Dependências instaladas com sucesso"
}

# Configura arquivo .env
setup_env() {
    print_step "Configurando arquivo de ambiente (.env)..."
    
    cd "$PROJECT_ROOT"
    
    if [ ! -f ".env" ]; then
        if [ -f ".env.example" ]; then
            cp .env.example .env
            print_success "Arquivo .env criado a partir de .env.example"
            print_warning "⚠️  IMPORTANTE: Edite o arquivo .env com suas configurações!"
        else
            print_warning "Arquivo .env.example não encontrado. Criando .env básico..."
            cat > .env << 'EOF'
# GABI - Configurações de Ambiente
ENV=development
DEBUG=true

# Segurança
SECRET_KEY=change-me-in-production-please-use-a-secure-random-key

# Database
DATABASE_URL=postgresql+asyncpg://gabi:gabi@localhost:5432/gabi
DATABASE_POOL_SIZE=20

# Redis
REDIS_URL=redis://localhost:6379/0

# Elasticsearch
ELASTICSEARCH_URL=http://localhost:9200
ELASTICSEARCH_INDEX_PREFIX=gabi

# OpenRouter (LLM)
OPENROUTER_API_KEY=your-openrouter-api-key-here
OPENROUTER_MODEL=anthropic/claude-3.5-sonnet

# Tavily (Search)
TAVILY_API_KEY=your-tavily-api-key-here

# SMTP (opcional)
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=

# S3/MinIO (opcional)
S3_ENDPOINT=http://localhost:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET=gabi-documents
EOF
            print_success "Arquivo .env básico criado"
            print_warning "⚠️  IMPORTANTE: Edite o arquivo .env com suas configurações reais!"
        fi
    else
        print_warning "Arquivo .env já existe"
    fi
}

# Sobe Docker Compose
start_docker() {
    print_step "Iniciando serviços Docker..."
    
    cd "$PROJECT_ROOT"
    
    if command -v docker-compose &> /dev/null || command -v docker &> /dev/null; then
        if [ -f "docker-compose.local.yml" ]; then
            docker-compose -f docker-compose.local.yml up -d
            print_success "Serviços Docker iniciados"
            
            # Aguarda serviços ficarem prontos
            print_step "Aguardando serviços ficarem prontos..."
            sleep 5
        else
            print_warning "Arquivo docker-compose.local.yml não encontrado"
        fi
    else
        print_warning "Docker não encontrado. Pulando etapa Docker."
    fi
}

# Executa migrações
run_migrations() {
    print_step "Executando migrações do banco de dados..."
    
    cd "$PROJECT_ROOT"
    
    # Verifica se alembic.ini existe
    if [ -f "gabi/alembic.ini" ]; then
        cd gabi && alembic upgrade head || print_warning "Migrações falharam - verifique se o banco está acessível"
        print_success "Migrações executadas"
    else
        print_warning "Arquivo alembic.ini não encontrado. Pulando migrações."
    fi
}

# Mensagem final
print_footer() {
    echo ""
    echo -e "${GREEN}"
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║              ✅ Setup concluído com sucesso!                      ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo ""
    echo "Próximos passos:"
    echo ""
    echo "  1. Ative o ambiente virtual:"
    echo -e "     ${YELLOW}source .venv/bin/activate${NC}"
    echo ""
    echo "  2. Edite as configurações no arquivo .env"
    echo ""
    echo "  3. Execute os testes:"
    echo -e "     ${YELLOW}make test${NC}"
    echo ""
    echo "  4. Inicie a aplicação:"
    echo -e "     ${YELLOW}make run${NC}"
    echo ""
    echo "  5. Ou use Docker:"
    echo -e "     ${YELLOW}make docker-up${NC}"
    echo ""
    echo "Comandos úteis:"
    echo -e "  ${YELLOW}make help${NC}      - Lista todos os comandos disponíveis"
    echo -e "  ${YELLOW}make check${NC}     - Executa todas as verificações de código"
    echo -e "  ${YELLOW}make test${NC}      - Executa testes com coverage"
    echo ""
    echo -e "${BLUE}Documentação:${NC} https://github.com/your-org/gabi"
    echo ""
}

# Main
main() {
    print_header
    
    check_python_version
    setup_venv
    install_dependencies
    setup_env
    start_docker
    run_migrations
    
    print_footer
}

# Executa o script
main "$@"
