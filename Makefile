# GABI - Gerador Automático de Boletins por Inteligência Artificial
# Makefile para automação de tarefas de desenvolvimento

.PHONY: install dev-install test lint format format-check typecheck check docker-up docker-down docker-logs docker-build migrate migrate-create setup-local clean help

PYTHON := python3.11
VENV_DIR := .venv
PACKAGE_DIR := gabi

# Default target
.DEFAULT_GOAL := help

# ============================================================================
# Instalação
# ============================================================================

install: ## Instala o pacote em modo produção (pip install -e .)
	pip install -e .

dev-install: ## Instala o pacote em modo desenvolvimento com dependências extras (pip install -e ".[dev]")
	pip install -e ".[dev]"

# ============================================================================
# Testes
# ============================================================================

test: ## Executa testes com pytest e coverage
	pytest --cov=$(PACKAGE_DIR) --cov-report=term-missing --cov-report=html -v

test-fast: ## Executa testes rápidos (sem coverage)
	pytest -x -v

test-watch: ## Executa testes em modo watch (requere pytest-watch)
	ptw -- -v

# ============================================================================
# Qualidade de Código
# ============================================================================

lint: ## Executa linter (ruff check)
	ruff check $(PACKAGE_DIR) tests

format: ## Formata o código (ruff format)
	ruff format $(PACKAGE_DIR) tests

format-check: ## Verifica formatação sem alterar arquivos (ruff format --check)
	ruff format --check $(PACKAGE_DIR) tests

typecheck: ## Executa verificação de tipos (mypy)
	mypy $(PACKAGE_DIR)

check: lint format-check typecheck test ## Executa TODAS as verificações: lint, format-check, typecheck e test

# ============================================================================
# Docker
# ============================================================================

docker-up: ## Sobe os containers Docker em modo detached (docker-compose -f docker-compose.local.yml up -d)
	docker-compose -f docker-compose.local.yml up -d

docker-down: ## Derruba os containers Docker
	docker-compose down

docker-logs: ## Mostra logs dos containers em tempo real
	docker-compose logs -f

docker-build: ## Reconstrói as imagens Docker
	docker-compose build

docker-ps: ## Lista containers em execução
	docker-compose ps

docker-clean: ## Remove containers, volumes e imagens órfãs
	docker-compose down -v --remove-orphans
	docker system prune -f

# ============================================================================
# Migrações de Banco de Dados (Alembic)
# ============================================================================

migrate: ## Executa migrações pendentes (alembic upgrade head)
	cd $(PACKAGE_DIR) && alembic upgrade head

migrate-create: ## Cria nova migração automaticamente (alembic revision --autogenerate)
	@read -p "Descrição da migração: " msg; \
	cd $(PACKAGE_DIR) && alembic revision --autogenerate -m "$$msg"

migrate-downgrade: ## Reverte última migração (alembic downgrade -1)
	cd $(PACKAGE_DIR) && alembic downgrade -1

migrate-history: ## Mostra histórico de migrações
	cd $(PACKAGE_DIR) && alembic history --verbose

# ============================================================================
# Setup Local
# ============================================================================

setup-local: ## Configura ambiente de desenvolvimento local completo
	chmod +x scripts/setup-local.sh && ./scripts/setup-local.sh

# ============================================================================
# Limpeza
# ============================================================================

clean: ## Remove arquivos temporários (__pycache__, .pyc, etc)
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	rm -f .coverage 2>/dev/null || true
	rm -rf build/ dist/ 2>/dev/null || true
	@echo "🧹 Limpeza concluída!"

clean-all: clean ## Remove também o ambiente virtual
	rm -rf $(VENV_DIR)
	@echo "🧹 Ambiente virtual removido!"

# ============================================================================
# Utilidades
# ============================================================================

requirements: ## Gera requirements.txt a partir do pyproject.toml
	pip freeze > requirements.txt

security-check: ## Executa verificação de segurança nas dependências (requere pip-audit)
	pip-audit

update-deps: ## Atualiza dependências para versões mais recentes compatíveis
	pip install --upgrade -e ".[dev]"

# ============================================================================
# Execução
# ============================================================================

run: ## Executa a aplicação em modo desenvolvimento
	cd $(PACKAGE_DIR) && uvicorn main:app --reload --host 0.0.0.0 --port 8000

run-prod: ## Executa a aplicação em modo produção
	cd $(PACKAGE_DIR) && uvicorn main:app --host 0.0.0.0 --port 8000

worker: ## Inicia o worker Celery
	cd $(PACKAGE_DIR) && celery -A worker worker --loglevel=info

# ============================================================================
# Ajuda
# ============================================================================

help: ## Mostra esta mensagem de ajuda
	@echo "╔══════════════════════════════════════════════════════════════════╗"
	@echo "║           GABI - Gerador Automático de Boletins por IA           ║"
	@echo "║                       Makefile - Comandos                        ║"
	@echo "╚══════════════════════════════════════════════════════════════════╝"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Uso: make <comando>"
	@echo ""
	@echo "Exemplos comuns:"
	@echo "  make setup-local    # Configuração inicial do ambiente"
	@echo "  make check          # Verificações completas antes do commit"
	@echo "  make test           # Executa testes com coverage"
	@echo "  make docker-up      # Sobe infraestrutura Docker"
