# =============================================================================
# GABI - Gerador Automático de Boletins por Inteligência Artificial
# Makefile - Automação de tarefas de desenvolvimento
# =============================================================================

# Variáveis configuráveis
PYTHON := python3
PIP := pip
PYTEST := pytest
RUFF := ruff
MYPY := mypy
ALEMBIC := alembic
UVICORN := uvicorn
CELERY := celery
DOCKER_COMPOSE := docker compose

# Cores para output (detecta se terminal suporta)
ifdef COMSPEC
	# Windows
	RED :=
	GREEN :=
	YELLOW :=
	BLUE :=
	RESET :=
else
	# Unix/Linux/Mac
	RED := \033[0;31m
	GREEN := \033[0;32m
	YELLOW := \033[0;33m
	BLUE := \033[0;34m
	RESET := \033[0m
endif

# Diretórios
SRC_DIR := src/gabi
TESTS_DIR := tests
ALEMBIC_DIR := alembic

# =============================================================================
# Targets Principais
# =============================================================================

.PHONY: help
help: ## Mostra esta ajuda com todos os comandos disponíveis
	@echo "$(BLUE)╔════════════════════════════════════════════════════════════════╗$(RESET)"
	@echo "$(BLUE)║              GABI - Makefile Commands                          ║$(RESET)"
	@echo "$(BLUE)╚════════════════════════════════════════════════════════════════╝$(RESET)"
	@echo ""
	@echo "$(GREEN)Setup e Instalação:$(RESET)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -E 'install' | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-20s$(RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(GREEN)Testes:$(RESET)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -E 'test' | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-20s$(RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(GREEN)Qualidade de Código:$(RESET)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -E 'lint|format|type|check' | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-20s$(RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(GREEN)Docker e Infraestrutura:$(RESET)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -E 'docker' | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-20s$(RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(GREEN)Banco de Dados:$(RESET)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -E 'migrate|db-' | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-20s$(RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(GREEN)Execução:$(RESET)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -E 'run|worker|all' | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-20s$(RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(GREEN)Utilitários:$(RESET)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | grep -E 'clean|init' | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-20s$(RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(BLUE)Dica:$(RESET) Use 'make check' para executar todas as verificações antes de commitar."

# =============================================================================
# Instalação e Setup
# =============================================================================

.PHONY: install
install: ## Instala dependências de produção (requirements.txt)
	@echo "$(BLUE)📦 Instalando dependências de produção...$(RESET)"
	$(PIP) install -r requirements.txt
	@echo "$(GREEN)✅ Dependências instaladas com sucesso!$(RESET)"

.PHONY: install-dev
install-dev: ## Instala dependências de desenvolvimento (+ dev extras)
	@echo "$(BLUE)📦 Instalando dependências de desenvolvimento...$(RESET)"
	$(PIP) install -r requirements.txt
	$(PIP) install -r requirements-dev.txt
	@echo "$(GREEN)✅ Dependências de desenvolvimento instaladas!$(RESET)"

.PHONY: install-uv
install-uv: ## Instala usando uv (mais rápido, se disponível)
	@echo "$(BLUE)📦 Instalando com uv...$(RESET)"
	@which uv > /dev/null 2>&1 || (echo "$(YELLOW)⚠️  uv não encontrado. Instalando uv...$(RESET)" && pip install uv)
	uv pip install -r requirements.txt
	uv pip install -r requirements-dev.txt
	@echo "$(GREEN)✅ Dependências instaladas com uv!$(RESET)"

.PHONY: init
init: ## Inicializa ambiente de desenvolvimento completo
	@echo "$(BLUE)🚀 Inicializando ambiente GABI...$(RESET)"
	$(MAKE) install-dev
	$(MAKE) docker-up
	@echo "$(YELLOW)⏳ Aguardando serviços iniciarem...$(RESET)"
	@sleep 10
	$(MAKE) migrate
	@echo "$(GREEN)✅ Ambiente inicializado! Use 'make run' para iniciar a API.$(RESET)"

# =============================================================================
# Testes
# =============================================================================

.PHONY: test
test: ## Roda testes com pytest (rápido, sem cobertura)
	@echo "$(BLUE)🧪 Executando testes...$(RESET)"
	$(PYTEST) $(TESTS_DIR) -v --tb=short

.PHONY: test-cov
test-cov: ## Roda testes com relatório de cobertura
	@echo "$(BLUE)🧪 Executando testes com cobertura...$(RESET)"
	$(PYTEST) $(TESTS_DIR) -v --cov=$(SRC_DIR) --cov-report=term-missing --cov-report=html --cov-report=xml
	@echo "$(GREEN)✅ Relatório de cobertura gerado em htmlcov/ e coverage.xml$(RESET)"

.PHONY: test-unit
test-unit: ## Roda apenas testes unitários
	@echo "$(BLUE)🧪 Executando testes unitários...$(RESET)"
	$(PYTEST) $(TESTS_DIR)/unit -v --tb=short

.PHONY: test-integration
test-integration: ## Roda apenas testes de integração
	@echo "$(BLUE)🧪 Executando testes de integração...$(RESET)"
	$(PYTEST) $(TESTS_DIR)/integration -v --tb=short

.PHONY: test-e2e
test-e2e: ## Roda testes end-to-end (requer infraestrutura)
	@echo "$(BLUE)🧪 Executando testes E2E...$(RESET)"
	$(PYTEST) $(TESTS_DIR)/e2e -v --tb=short

.PHONY: test-watch
test-watch: ## Roda testes em modo watch (requer pytest-watch)
	@echo "$(BLUE)👁️  Iniciando modo watch...$(RESET)"
	ptw $(TESTS_DIR) -- -v --tb=short

# =============================================================================
# Qualidade de Código
# =============================================================================

.PHONY: lint
lint: ## Roda ruff check em todo o código
	@echo "$(BLUE)🔍 Executando linter (ruff check)...$(RESET)"
	$(RUFF) check $(SRC_DIR) $(TESTS_DIR)

.PHONY: lint-fix
lint-fix: ## Roda ruff check com auto-fix
	@echo "$(BLUE)🔧 Executando linter com auto-fix...$(RESET)"
	$(RUFF) check --fix $(SRC_DIR) $(TESTS_DIR)

.PHONY: format
format: ## Formata código com ruff format
	@echo "$(BLUE)🎨 Formatando código...$(RESET)"
	$(RUFF) format $(SRC_DIR) $(TESTS_DIR)

.PHONY: format-check
format-check: ## Verifica formatação sem modificar arquivos
	@echo "$(BLUE)🔍 Verificando formatação...$(RESET)"
	$(RUFF) format --check $(SRC_DIR) $(TESTS_DIR)

.PHONY: typecheck
typecheck: ## Roda mypy para verificação de tipos
	@echo "$(BLUE)🔍 Verificando tipos (mypy)...$(RESET)"
	$(MYPY) $(SRC_DIR)

.PHONY: check
check: ## Executa TODAS as verificações (lint + format + typecheck + test)
	@echo "$(BLUE)═══════════════════════════════════════════════════════$(RESET)"
	@echo "$(BLUE)  Executando verificações completas$(RESET)"
	@echo "$(BLUE)═══════════════════════════════════════════════════════$(RESET)"
	@echo ""
	@echo "$(YELLOW)1/4 - Verificando formatação...$(RESET)"
	$(MAKE) format-check || (echo "$(RED)❌ Falha na formatação. Execute 'make format'$(RESET)" && exit 1)
	@echo ""
	@echo "$(YELLOW)2/4 - Executando linter...$(RESET)"
	$(MAKE) lint || (echo "$(RED)❌ Falha no lint. Execute 'make lint-fix'$(RESET)" && exit 1)
	@echo ""
	@echo "$(YELLOW)3/4 - Verificando tipos...$(RESET)"
	$(MAKE) typecheck || (echo "$(RED)❌ Falha na verificação de tipos$(RESET)" && exit 1)
	@echo ""
	@echo "$(YELLOW)4/4 - Executando testes...$(RESET)"
	$(MAKE) test || (echo "$(RED)❌ Falha nos testes$(RESET)" && exit 1)
	@echo ""
	@echo "$(GREEN)═══════════════════════════════════════════════════════$(RESET)"
	@echo "$(GREEN)  ✅ Todas as verificações passaram!$(RESET)"
	@echo "$(GREEN)═══════════════════════════════════════════════════════$(RESET)"

# =============================================================================
# Docker e Infraestrutura
# =============================================================================

.PHONY: docker-up
docker-up: ## Sobe infraestrutura com docker-compose.local.yml
	@echo "$(BLUE)🐳 Iniciando containers Docker...$(RESET)"
	$(DOCKER_COMPOSE) -f docker-compose.local.yml up -d
	@echo "$(GREEN)✅ Containers iniciados!$(RESET)"
	@echo "$(YELLOW)   PostgreSQL: localhost:5432$(RESET)"
	@echo "$(YELLOW)   Elasticsearch: localhost:9200$(RESET)"
	@echo "$(YELLOW)   Redis: localhost:6379$(RESET)"

.PHONY: docker-down
docker-down: ## Derruba containers Docker
	@echo "$(BLUE)🛑 Parando containers Docker...$(RESET)"
	$(DOCKER_COMPOSE) -f docker-compose.local.yml down
	@echo "$(GREEN)✅ Containers parados!$(RESET)"

.PHONY: docker-logs
docker-logs: ## Mostra logs dos containers (follow mode)
	@echo "$(BLUE)📋 Mostrando logs (Ctrl+C para sair)...$(RESET)"
	$(DOCKER_COMPOSE) -f docker-compose.local.yml logs -f

.PHONY: docker-logs-api
docker-logs-api: ## Mostra logs apenas da API
	$(DOCKER_COMPOSE) -f docker-compose.local.yml logs -f api

.PHONY: docker-logs-worker
docker-logs-worker: ## Mostra logs apenas do worker
	$(DOCKER_COMPOSE) -f docker-compose.local.yml logs -f worker

.PHONY: docker-ps
docker-ps: ## Lista containers em execução
	@echo "$(BLUE)📦 Containers em execução:$(RESET)"
	$(DOCKER_COMPOSE) -f docker-compose.local.yml ps

.PHONY: docker-build
docker-build: ## Builda imagens Docker
	@echo "$(BLUE)🔨 Buildando imagens Docker...$(RESET)"
	$(DOCKER_COMPOSE) -f docker-compose.local.yml build

.PHONY: docker-clean
docker-clean: ## Remove containers, volumes e imagens órfãs
	@echo "$(BLUE)🧹 Limpando recursos Docker...$(RESET)"
	$(DOCKER_COMPOSE) -f docker-compose.local.yml down -v --remove-orphans
	docker system prune -f
	@echo "$(GREEN)✅ Docker limpo!$(RESET)"

# =============================================================================
# Banco de Dados e Migrações
# =============================================================================

.PHONY: migrate
migrate: ## Executa migrações pendentes (alembic upgrade head)
	@echo "$(BLUE)🗄️  Executando migrações...$(RESET)"
	cd $(ALEMBIC_DIR) && $(ALEMBIC) upgrade head
	@echo "$(GREEN)✅ Migrações aplicadas!$(RESET)"

.PHONY: migrate-create
migrate-create: ## Cria nova migração (use: make migrate-create MSG="descricao")
ifndef MSG
	@echo "$(RED)❌ Erro: Defina a mensagem da migração$(RESET)"
	@echo "$(YELLOW)   Uso: make migrate-create MSG='add user table'$(RESET)"
	@exit 1
endif
	@echo "$(BLUE)📝 Criando migração: $(MSG)...$(RESET)"
	cd $(ALEMBIC_DIR) && $(ALEMBIC) revision --autogenerate -m "$(MSG)"
	@echo "$(GREEN)✅ Migração criada em $(ALEMBIC_DIR)/versions/$(RESET)"

.PHONY: migrate-down
migrate-down: ## Reverte última migração (downgrade -1)
	@echo "$(YELLOW)⚠️  Revertendo última migração...$(RESET)"
	cd $(ALEMBIC_DIR) && $(ALEMBIC) downgrade -1
	@echo "$(GREEN)✅ Migração revertida!$(RESET)"

.PHONY: migrate-down-all
migrate-down-all: ## Reverte TODAS as migrações (downgrade base)
	@echo "$(YELLOW)⚠️  Revertendo TODAS as migrações...$(RESET)"
	cd $(ALEMBIC_DIR) && $(ALEMBIC) downgrade base
	@echo "$(GREEN)✅ Todas as migrações revertidas!$(RESET)"

.PHONY: migrate-history
migrate-history: ## Mostra histórico de migrações
	@echo "$(BLUE)📜 Histórico de migrações:$(RESET)"
	cd $(ALEMBIC_DIR) && $(ALEMBIC) history --verbose

.PHONY: migrate-current
migrate-current: ## Mostra migração atual
	@echo "$(BLUE)📍 Migração atual:$(RESET)"
	cd $(ALEMBIC_DIR) && $(ALEMBIC) current

.PHONY: db-reset
db-reset: ## Reseta banco de dados (cuidado: apaga todos os dados!)
	@echo "$(RED)⚠️  ATENÇÃO: Isso irá apagar TODOS os dados do banco!$(RESET)"
	@read -p "Digite 'RESET' para confirmar: " confirm && [ $$confirm = "RESET" ] || (echo "$(YELLOW)Operação cancelada$(RESET)" && exit 1)
	$(MAKE) migrate-down-all
	$(MAKE) migrate
	@echo "$(GREEN)✅ Banco de dados resetado!$(RESET)"

.PHONY: db-shell
db-shell: ## Abre shell do PostgreSQL (requer psql)
	@echo "$(BLUE)🐘 Conectando ao PostgreSQL...$(RESET)"
	psql $${GABI_DATABASE_URL:-postgresql://gabi:gabi@localhost:5432/gabi}

.PHONY: db-seed
db-seed: ## Executa seeds de dados iniciais
	@echo "$(BLUE)🌱 Executando seeds...$(RESET)"
	$(PYTHON) -m scripts.seed

# =============================================================================
# Execução da Aplicação
# =============================================================================

.PHONY: run
run: ## Roda API localmente com auto-reload (desenvolvimento)
	@echo "$(BLUE)🚀 Iniciando API em modo desenvolvimento...$(RESET)"
	@echo "$(YELLOW)   Acesse: http://localhost:8000$(RESET)"
	@echo "$(YELLOW)   Docs: http://localhost:8000/docs$(RESET)"
	@echo "$(YELLOW)   Health: http://localhost:8000/health$(RESET)"
	@echo ""
	cd src && $(UVICORN) gabi.main:app --reload --host 0.0.0.0 --port 8000

.PHONY: run-prod
run-prod: ## Roda API em modo produção (sem reload)
	@echo "$(BLUE)🚀 Iniciando API em modo produção...$(RESET)"
	cd src && $(UVICORN) gabi.main:app --host 0.0.0.0 --port 8000 --workers 4

.PHONY: worker
worker: ## Roda Celery worker localmente
	@echo "$(BLUE)⚙️  Iniciando Celery Worker...$(RESET)"
	cd src && $(CELERY) -A gabi.worker worker -l info -Q default,priority --concurrency=2

.PHONY: worker-beat
worker-beat: ## Roda Celery beat (scheduler)
	@echo "$(BLUE)⏰ Iniciando Celery Beat...$(RESET)"
	cd src && $(CELERY) -A gabi.worker beat -l info

.PHONY: flower
flower: ## Inicia Flower (monitoramento Celery)
	@echo "$(BLUE)🌸 Iniciando Flower...$(RESET)"
	@echo "$(YELLOW)   Acesse: http://localhost:5555$(RESET)"
	cd src && $(CELERY) -A gabi.worker flower --port=5555

.PHONY: all
all: ## Inicia toda a stack localmente (docker + migrate + api + worker)
	@echo "$(BLUE)🚀 Iniciando stack completa...$(RESET)"
	$(MAKE) docker-up
	@sleep 5
	$(MAKE) migrate
	@echo "$(GREEN)✅ Infraestrutura pronta!$(RESET)"
	@echo "$(YELLOW)   Iniciando API e Worker em paralelo...$(RESET)"
	@echo "$(YELLOW)   (Use Ctrl+C para parar)$(RESET)"
	@trap '$(MAKE) docker-down' EXIT; \
	(make run & make worker)

# =============================================================================
# Pipeline e Ingestão
# =============================================================================

.PHONY: pipeline-run
pipeline-run: ## Executa pipeline de ingestão manualmente
	@echo "$(BLUE)🔄 Executando pipeline de ingestão...$(RESET)"
	$(PYTHON) -m gabi.pipeline.orchestrator

.PHONY: pipeline-source
pipeline-source: ## Executa pipeline para uma fonte específica (use: make pipeline-source NAME=tcu_acordaos)
ifndef NAME
	@echo "$(RED)❌ Erro: Defina o nome da fonte$(RESET)"
	@echo "$(YELLOW)   Uso: make pipeline-source NAME=tcu_acordaos$(RESET)"
	@exit 1
endif
	@echo "$(BLUE)🔄 Executando pipeline para fonte: $(NAME)...$(RESET)"
	$(PYTHON) -m gabi.pipeline.orchestrator --source $(NAME)

# =============================================================================
# Limpeza e Manutenção
# =============================================================================

.PHONY: clean
clean: ## Limpa arquivos temporários, caches e build artifacts
	@echo "$(BLUE)🧹 Limpando arquivos temporários...$(RESET)"
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true
	find . -type f -name "coverage.xml" -delete 2>/dev/null || true
	rm -rf build/ dist/ *.egg-info/ .eggs/ 2>/dev/null || true
	@echo "$(GREEN)✅ Limpeza concluída!$(RESET)"

.PHONY: clean-all
clean-all: clean docker-clean ## Limpa tudo (incluindo Docker)
	@echo "$(GREEN)✅ Limpeza completa realizada!$(RESET)"

# =============================================================================
# Deploy e Release
# =============================================================================

.PHONY: build
build: ## Builda pacote para distribuição
	@echo "$(BLUE)📦 Buildando pacote...$(RESET)"
	$(PYTHON) -m build
	@echo "$(GREEN)✅ Pacote buildado em dist/$(RESET)"

.PHONY: version
version: ## Mostra versão atual do projeto
	@echo "$(BLUE)📌 Versão do GABI:$(RESET)"
	@grep -E '^version|^\[project\]' pyproject.toml | head -5

# =============================================================================
# CI/CD Helpers
# =============================================================================

.PHONY: ci-test
ci-test: ## Executa testes em modo CI (com cobertura mínima)
	@echo "$(BLUE)🧪 Executando testes em modo CI...$(RESET)"
	$(PYTEST) $(TESTS_DIR) -v --cov=$(SRC_DIR) --cov-fail-under=80 --tb=short

.PHONY: ci-lint
ci-lint: ## Executa lint em modo CI (sem auto-fix)
	@echo "$(BLUE)🔍 Executando lint em modo CI...$(RESET)"
	$(RUFF) check $(SRC_DIR) $(TESTS_DIR)
	$(RUFF) format --check $(SRC_DIR) $(TESTS_DIR)

# =============================================================================
# Targets Padrão
# =============================================================================

.DEFAULT_GOAL := help
