#!/bin/bash
# =============================================================================
# GABI - Script de Migração
# Wrapper idempotente para executar migrações do Alembic
# =============================================================================

set -e

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
RESET='\033[0m'

# Configurações
VENV_DIR=".venv"
ALEMBIC_DIR="alembic"
ALEMBIC_INI="${ALEMBIC_DIR}/alembic.ini"

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

# =============================================================================
# Ativação do Virtual Environment
# =============================================================================

activate_venv() {
    log_step "Ativando Ambiente Virtual"
    
    # Guarda o diretório do script
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
    
    cd "$PROJECT_ROOT"
    
    # Verifica se já está em um virtual environment
    if [[ -n "${VIRTUAL_ENV:-}" ]]; then
        log_info "Virtual environment já ativo: ${VIRTUAL_ENV}"
        return 0
    fi
    
    # Procura o virtual environment
    if [[ -d "$VENV_DIR" ]]; then
        log_info "Ativando virtual environment em ./${VENV_DIR}..."
        # shellcheck source=/dev/null
        source "${VENV_DIR}/bin/activate"
        log_success "Virtual environment ativado"
    elif [[ -d "venv" ]]; then
        log_info "Ativando virtual environment em ./venv..."
        # shellcheck source=/dev/null
        source "venv/bin/activate"
        log_success "Virtual environment ativado"
    else
        log_warn "Nenhum virtual environment encontrado. Tentando usar Python do sistema..."
        
        # Verifica se o alembic está disponível
        if ! command -v alembic &> /dev/null; then
            log_error "Alembic não encontrado. Por favor, ative um virtual environment ou instale as dependências."
            exit 1
        fi
    fi
}

# =============================================================================
# Verificação de Pré-requisitos
# =============================================================================

check_prerequisites() {
    log_step "Verificando Pré-requisitos"
    
    # Verifica se o diretório alembic existe
    if [[ ! -d "$ALEMBIC_DIR" ]]; then
        log_error "Diretório '${ALEMBIC_DIR}' não encontrado"
        log_info "Verifique se você está no diretório raiz do projeto"
        exit 1
    fi
    
    # Verifica se o alembic.ini existe
    if [[ ! -f "$ALEMBIC_INI" ]]; then
        log_error "Arquivo '${ALEMBIC_INI}' não encontrado"
        log_info "Verifique se as migrações estão configuradas corretamente"
        exit 1
    fi
    
    # Verifica se o alembic está disponível
    if ! command -v alembic &> /dev/null; then
        log_error "Comando 'alembic' não encontrado"
        log_info "Por favor, instale as dependências do projeto"
        exit 1
    fi
    
    log_success "Todos os pré-requisitos atendidos"
}

# =============================================================================
# Verificação da Conexão com o Banco
# =============================================================================

check_database() {
    log_step "Verificando Conexão com o Banco de Dados"
    
    # Tenta obter a versão atual do alembic (isso testa a conexão)
    log_info "Testando conexão com o banco..."
    
    if ! alembic -c "$ALEMBIC_INI" current &> /dev/null; then
        log_warn "Não foi possível conectar ao banco de dados"
        log_info "Verifique se o PostgreSQL está rodando e as configurações em .env"
        
        # Pergunta se deseja continuar
        read -p "Deseja continuar mesmo assim? [s/N]: " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Ss]$ ]]; then
            log_info "Operação cancelada pelo usuário"
            exit 0
        fi
    else
        log_success "Conexão com o banco estabelecida"
    fi
}

# =============================================================================
# Execução das Migrações
# =============================================================================

run_migrations() {
    log_step "Executando Migrações"
    
    log_info "Executando 'alembic upgrade head'..."
    echo ""
    
    # Executa a migração
    if alembic -c "$ALEMBIC_INI" upgrade head; then
        echo ""
        log_success "Migrações aplicadas com sucesso"
    else
        echo ""
        log_error "Falha ao aplicar migrações"
        exit 1
    fi
}

# =============================================================================
# Verificação Pós-migração
# =============================================================================

verify_migrations() {
    log_step "Verificando Migrações"
    
    log_info "Versão atual do banco:"
    alembic -c "$ALEMBIC_INI" current
    
    echo ""
    log_info "Histórico de migrações (últimas 5):"
    alembic -c "$ALEMBIC_INI" history --verbose | head -n 20 || true
    
    log_success "Verificação concluída"
}

# =============================================================================
# Função de Help
# =============================================================================

show_help() {
    cat << 'EOF'
Uso: migrate.sh [OPÇÃO]

Script para executar migrações do banco de dados usando Alembic.

OPÇÕES:
    -h, --help      Mostra esta ajuda
    -c, --check     Apenas verifica o status das migrações (não executa)
    -v, --verbose   Modo verbose (mais detalhes)
    --dry-run       Simula a execução sem aplicar mudanças

EXEMPLOS:
    bash scripts/migrate.sh           # Executa as migrações
    bash scripts/migrate.sh --check   # Verifica status atual
    make migrate                      # Alternativa via Makefile

INFORMAÇÕES:
    - Requer Python 3.11+
    - Requer virtual environment ativo ou instalado
    - Requer PostgreSQL rodando e configurado em .env
EOF
}

# =============================================================================
# Parse de Argumentos
# =============================================================================

DRY_RUN=false
CHECK_ONLY=false
VERBOSE=false

parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                exit 0
                ;;
            -c|--check)
                CHECK_ONLY=true
                shift
                ;;
            -v|--verbose)
                VERBOSE=true
                shift
                ;;
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            *)
                log_error "Opção desconhecida: $1"
                show_help
                exit 1
                ;;
        esac
    done
}

# =============================================================================
# Execução Principal
# =============================================================================

main() {
    parse_args "$@"
    
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${RESET}"
    echo -e "${BLUE}║        GABI - Script de Migração                              ║${RESET}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${RESET}"
    echo ""
    
    # Ativa o virtual environment
    activate_venv
    
    # Verifica pré-requisitos
    check_prerequisites
    
    # Modo check-only
    if [[ "$CHECK_ONLY" == true ]]; then
        log_step "Modo Verificação"
        log_info "Status atual das migrações:"
        alembic -c "$ALEMBIC_INI" current
        echo ""
        log_info "Migrações pendentes:"
        alembic -c "$ALEMBIC_INI" history --verbose || true
        exit 0
    fi
    
    # Verifica conexão com banco
    check_database
    
    # Modo dry-run
    if [[ "$DRY_RUN" == true ]]; then
        log_step "Modo Simulação (Dry Run)"
        log_info "Mostrando o que seria executado:"
        alembic -c "$ALEMBIC_INI" upgrade head --sql || true
        exit 0
    fi
    
    # Executa as migrações
    run_migrations
    
    # Verifica o resultado
    verify_migrations
    
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${RESET}"
    echo -e "${GREEN}║        ✅ Migrações Concluídas com Sucesso                    ║${RESET}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${RESET}"
    echo ""
}

# Executa o main se o script for executado diretamente
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
