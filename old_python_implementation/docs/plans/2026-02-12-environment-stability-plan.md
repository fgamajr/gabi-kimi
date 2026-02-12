# Plano de Estabilização do Ambiente GABI

## Data: 2026-02-12
## Objetivo: Eliminar inconsistências entre sessões de desenvolvimento

---

## Problemas Identificados

| # | Problema | Causa Raiz | Impacto |
|---|----------|------------|---------|
| 1 | Docker state residue | Containers órfãos, redes, volumes não removidos | Estado contaminado entre runs |
| 2 | Systemd service conflicts | Redis/PostgreSQL host competem com containers | Port binding falha silenciosamente |
| 3 | Python cache | `__pycache__` persiste código antigo | Mudanças não refletem |
| 4 | Processos zumbis | API/Celery anteriores seguram portas | "Address already in use" |
| 5 | Working directory | Scripts mudam de diretório inconsistentemente | `ModuleNotFoundError` |
| 6 | Environment leakage | Variáveis persistem entre sessões | Config desatualizada |

---

## Soluções por Problema

### 1. Docker State Residue

**Solução:** Script `scripts/infra_reset.sh` idempotente

```bash
#!/bin/bash
# Destrói TUDO relacionado ao GABI no Docker

# Parar e remover containers (incluindo órfãos)
docker compose --profile infra --profile all down -v --remove-orphans 2>/dev/null || true

# Remover containers órfãos manualmente (por nome)
for container in gabi-postgres gabi-elasticsearch gabi-redis gabi-tei; do
    docker rm -f "$container" 2>/dev/null || true
done

# Limpar redes órfãas
docker network prune -f 2>/dev/null || true

# Limpar volumes não utilizados
docker volume prune -f 2>/dev/null || true

# Limpar sistema (imagens dangling)
docker system prune -f 2>/dev/null || true

# Resetar diretórios de dados
sudo rm -rf data/postgres/* data/elasticsearch/* data/redis/* 2>/dev/null || true
mkdir -p data/{postgres,elasticsearch,redis,tei/model}
chmod 777 data/elasticsearch

echo "✓ Infraestrutura resetada completamente"
```

**Critério de sucesso:** `docker ps -a | grep gabi` retorna vazio após reset

---

### 2. Systemd Service Conflicts

**Solução:** Script `scripts/check_prerequisites.sh` com validação rigorosa

```bash
#!/bin/bash
# Verifica e resolve conflitos de portas

REQUIRED_PORTS=(5432 9200 6379 8080 8000)
PORT_NAMES=("PostgreSQL" "Elasticsearch" "Redis" "TEI" "API")

for i in "${!REQUIRED_PORTS[@]}"; do
    port="${REQUIRED_PORTS[$i]}"
    name="${PORT_NAMES[$i]}"
    
    # Verificar se porta está em uso
    if ss -tlnH 2>/dev/null | grep -qE ":${port}\b"; then
        pid=$(fuser "${port}/tcp" 2>/dev/null | xargs)
        proc_name=$(ps -p "$pid" -o comm= 2>/dev/null || echo "unknown")
        
        echo "⚠️  Porta $port ($name) ocupada por: $proc_name (PID $pid)"
        
        # Tentar identificar se é systemd
        if systemctl is-active --quiet "$proc_name" 2>/dev/null; then
            echo "   Detectado serviço systemd. Parando..."
            sudo systemctl stop "$proc_name"
            sleep 2
        fi
        
        # Verificar novamente
        if ss -tlnH 2>/dev/null | grep -qE ":${port}\b"; then
            echo "   Matando processo $pid..."
            kill -9 "$pid" 2>/dev/null || sudo kill -9 "$pid" 2>/dev/null
            sleep 1
        fi
        
        # Verificação final
        if ss -tlnH 2>/dev/null | grep -qE ":${port}\b"; then
            echo "❌ Não foi possível liberar a porta $port"
            echo "   Resolva manualmente: sudo fuser -k ${port}/tcp"
            exit 1
        fi
        
        echo "✓ Porta $port liberada"
    fi
done

echo "✓ Todas as portas necessárias estão livres"
```

**Critério de sucesso:** Script falha explicitamente se portas não podem ser liberadas

---

### 3. Python Cache

**Solução:** Adicionar ao `scripts/infra_reset.sh`:

```bash
# Limpar Python cache
echo "Limpando Python cache..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true
find . -name "*.pyo" -delete 2>/dev/null || true
find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true

# Limpar mypy cache
rm -rf .mypy_cache 2>/dev/null || true
```

**Critério de sucesso:** `find . -type d -name "__pycache__" | wc -l` retorna 0

---

### 4. Processos Zumbis

**Solução:** Script `scripts/kill_zombies.sh`:

```bash
#!/bin/bash
# Mata todos os processos relacionados ao GABI

echo "Procurando processos GABI..."

# Padrões de processos a matar
PATTERNS=("gabi" "celery" "uvicorn" "python.*gabi")

for pattern in "${PATTERNS[@]}"; do
    pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    if [[ -n "$pids" ]]; then
        echo "Encontrados PIDs para '$pattern': $pids"
        echo "$pids" | xargs kill -TERM 2>/dev/null || true
        sleep 2
        # Forçar kill se ainda existirem
        pids=$(pgrep -f "$pattern" 2>/dev/null || true)
        if [[ -n "$pids" ]]; then
            echo "$pids" | xargs kill -KILL 2>/dev/null || sudo kill -KILL $pids 2>/dev/null || true
        fi
    fi
done

echo "✓ Processos limpos"
```

**Critério de sucesso:** `pgrep -f "gabi|celery|uvicorn" | wc -l` retorna 0

---

### 5. Working Directory

**Solução:** Refatorar scripts para usar `PROJECT_DIR` consistentemente

**Em cada script, adicionar no início:**

```bash
#!/bin/bash
set -euo pipefail

# Detectar diretório do projeto (funciona independente de onde é chamado)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Validar estrutura
if [[ ! -f "$PROJECT_DIR/pyproject.toml" ]]; then
    echo "❌ Erro: Não parece ser o diretório do projeto GABI"
    echo "   pyproject.toml não encontrado em: $PROJECT_DIR"
    exit 1
fi

# Mudar para o diretório do projeto
cd "$PROJECT_DIR"
echo "📁 Diretório do projeto: $PROJECT_DIR"

# Todos os comandos agora são relativos a PROJECT_DIR
```

**Critério de sucesso:** Script funciona corretamente independente do diretório de execução

---

### 6. Environment Leakage

**Solução:** Script `scripts/setup_env.sh` que garante ambiente limpo:

```bash
#!/bin/bash
# Configura ambiente limpo e consistente

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Limpar variáveis que possam estar poluídas
unset PYTHONPATH 2>/dev/null || true
unset GABI_DATABASE_URL 2>/dev/null || true
unset GABI_ELASTICSEARCH_URL 2>/dev/null || true
unset GABI_REDIS_URL 2>/dev/null || true
unset GABI_EMBEDDINGS_URL 2>/dev/null || true

# Carregar .env se existir
if [[ -f "$PROJECT_DIR/.env" ]]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# Configurar variáveis padrão (sobrescrevem as do .env se necessário)
export PYTHONPATH="$PROJECT_DIR/src"
export GABI_DATABASE_URL="${GABI_DATABASE_URL:-postgresql+asyncpg://gabi:gabi_dev_password@localhost:5432/gabi}"
export GABI_ELASTICSEARCH_URL="${GABI_ELASTICSEARCH_URL:-http://localhost:9200}"
export GABI_REDIS_URL="${GABI_REDIS_URL:-redis://localhost:6379/0}"
export GABI_EMBEDDINGS_URL="${GABI_EMBEDDINGS_URL:-http://localhost:8080}"
export GABI_AUTH_ENABLED="${GABI_AUTH_ENABLED:-false}"
export PYTHONUNBUFFERED=1

echo "✓ Ambiente configurado:"
echo "   PYTHONPATH=$PYTHONPATH"
echo "   DATABASE_URL=$GABI_DATABASE_URL"
echo "   ELASTICSEARCH_URL=$GABI_ELASTICSEARCH_URL"
```

**Critério de sucesso:** Variáveis são sempre definidas explicitamente, nunca herdadas

---

## Orquestrador Principal

**Script `scripts/dev.sh`** - Interface unificada para todas as operações:

```bash
#!/bin/bash
# GABI Development Environment Manager
# Uso: ./scripts/dev.sh [command] [options]
#
# Commands:
#   reset       - Destrói tudo e recria do zero (hard reset)
#   infra-up    - Sobe infraestrutura (Docker containers)
#   infra-down  - Derruba infraestrutura
#   env-setup   - Configura ambiente Python
#   ingest      - Executa ingestão
#   test        - Roda testes
#   shell       - Abre shell com ambiente configurado

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[dev.sh]${NC} $*"; }
ok() { echo -e "${GREEN}[dev.sh]${NC} $*"; }
warn() { echo -e "${YELLOW}[dev.sh]${NC} $*"; }
error() { echo -e "${RED}[dev.sh]${NC} $*" >&2; }

cmd_reset() {
    log "Executando HARD RESET..."
    
    # 1. Matar processos
    log "1. Matando processos zumbis..."
    ./scripts/kill_zombies.sh || true
    
    # 2. Verificar portas
    log "2. Verificando conflitos de porta..."
    ./scripts/check_prerequisites.sh || exit 1
    
    # 3. Reset Docker
    log "3. Resetando infraestrutura Docker..."
    ./scripts/infra_reset.sh || exit 1
    
    # 4. Limpar cache Python
    log "4. Limpando cache Python..."
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -name "*.pyc" -delete 2>/dev/null || true
    
    # 5. Setup ambiente
    log "5. Configurando ambiente..."
    source ./scripts/setup_env.sh
    
    ok "✓ Hard reset completo!"
}

cmd_infra_up() {
    log "Subindo infraestrutura..."
    docker compose --profile infra up -d
    
    # Aguardar healthy
    log "Aguardando containers ficarem healthy..."
    sleep 5
    docker ps --format 'table {{.Names}}\t{{.Status}}'
}

cmd_infra_down() {
    log "Derrubando infraestrutura..."
    docker compose --profile infra --profile all down
}

cmd_env_setup() {
    source ./scripts/setup_env.sh
    ok "Ambiente configurado para sessão atual"
}

cmd_ingest() {
    local source="${1:-}"
    source ./scripts/setup_env.sh
    
    if [[ -n "$source" ]]; then
        log "Ingerindo source: $source"
        python -m gabi.cli ingest --source "$source" --max-docs-per-source 0
    else
        log "Ingerindo todas as sources..."
        python -m gabi.cli ingest-schedule --sources-file sources.yaml
    fi
}

cmd_test() {
    source ./scripts/setup_env.sh
    python -m pytest tests/ --ignore=tests/integration/test_indexer.py -v
}

cmd_shell() {
    source ./scripts/setup_env.sh
    source .venv/bin/activate
    exec bash
}

# Main
case "${1:-help}" in
    reset) cmd_reset ;;
    infra-up) cmd_infra_up ;;
    infra-down) cmd_infra_down ;;
    env-setup) cmd_env_setup ;;
    ingest) cmd_ingest "${2:-}" ;;
    test) cmd_test ;;
    shell) cmd_shell ;;
    help|*)
        echo "GABI Development Environment Manager"
        echo ""
        echo "Uso: ./scripts/dev.sh [command] [options]"
        echo ""
        echo "Commands:"
        echo "  reset              Hard reset completo (docker, cache, processos)"
        echo "  infra-up           Sobe infraestrutura Docker"
        echo "  infra-down         Derruba infraestrutura Docker"
        echo "  env-setup          Configura variáveis de ambiente"
        echo "  ingest [source]    Executa ingestão (opcional: source específica)"
        echo "  test               Roda testes"
        echo "  shell              Abre shell com ambiente configurado"
        echo ""
        echo "Exemplo:"
        echo "  ./scripts/dev.sh reset && ./scripts/dev.sh infra-up"
        echo "  ./scripts/dev.sh ingest tcu_normas"
        ;;
esac
```

---

## Checklist de Implementação

### Fase 1: Scripts Individuais (Prioridade Alta)
- [ ] Criar `scripts/infra_reset.sh`
- [ ] Criar `scripts/check_prerequisites.sh`
- [ ] Criar `scripts/kill_zombies.sh`
- [ ] Criar `scripts/setup_env.sh`

### Fase 2: Orquestrador (Prioridade Alta)
- [ ] Criar `scripts/dev.sh` com todos os comandos
- [ ] Adicionar validação de diretório em todos os scripts
- [ ] Testar cada comando individualmente

### Fase 3: Integração (Prioridade Média)
- [ ] Refatorar `start.sh` para usar os novos scripts
- [ ] Refatorar `start_ingestion.sh` para usar os novos scripts
- [ ] Adicionar `--remove-orphans` em todos os `docker compose down`

### Fase 4: Documentação (Prioridade Média)
- [ ] Atualizar README.md com novo workflow
- [ ] Documentar `scripts/dev.sh` no AGENTS.md
- [ ] Criar troubleshooting guide

---

## Critérios de Sucesso

1. **Idempotência**: Executar `dev.sh reset` 3x seguidas produz o mesmo resultado
2. **Reprodutibilidade**: Qualquer pessoa pode clonar o repo e rodar:
   ```bash
   ./scripts/dev.sh reset
   ./scripts/dev.sh infra-up
   ./scripts/dev.sh ingest tcu_normas
   ```
   e obter o mesmo resultado
3. **Validação explícita**: Cada script valida pré-condições e falha com mensagem clara
4. **Não-interferência**: Rodar em paralelo com outro projeto (portas diferentes) não causa conflitos

---

## Métricas de Qualidade

- Tempo de reset completo: < 30 segundos
- Tempo de infra-up (com download): < 2 minutos
- Taxa de sucesso do cross-check: 100% (5/5 tentativas consecutivas)
