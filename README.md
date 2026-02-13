# GABI - Sistema de Ingestão e Busca Jurídica TCU

Sistema de ingestão, processamento e busca de dados jurídicos do Tribunal de Contas da União.

## 🚀 Quick Start

### Opção 1: Tudo de uma vez (recomendado)

```bash
./scripts/dev-start.sh
```

Isso inicia:
- Infraestrutura Docker (Postgres, Elasticsearch, Redis)
- API (http://localhost:5100)
- Web Frontend (http://localhost:3000)

Pressione `Ctrl+C` para parar tudo.

### Opção 2: Separado (para debugging)

**Terminal 1 - Infra:**
```bash
./scripts/dev-up.sh
```

**Terminal 2 - API:** (sempre a partir da **raiz do repositório**)
```bash
dotnet run --project src/Gabi.Api --urls "http://localhost:5100"
```
Se a porta 5100 já estiver em uso, mate o processo (`pkill -f "dotnet.*Gabi.Api"`) ou use outra: `--urls "http://localhost:5101"`.

**Terminal 3 - Web:** (requer **Node 18+** — Vite 5 usa top-level await)
```bash
cd src/Gabi.Web && npm run dev
```
Se aparecer `SyntaxError: Unexpected reserved word` no web.log, atualize o Node: `nvm install 20 && nvm use 20` (ou instale Node 18+).

### Acessos

| Serviço | URL |
|---------|-----|
| Web Frontend | http://localhost:3000 |
| API | http://localhost:5100 |
| Swagger UI | http://localhost:5100/swagger |
| Health Check | http://localhost:5100/health |

### Problemas comuns

- **"Project file does not exist"** — Rode `dotnet run --project src/Gabi.Api` a partir da **raiz do repositório** (`~/dev/gabi-kimi`), não de dentro de `src/Gabi.Api`.
- **"Address already in use" (5100)** — Outra instância da API ou outro processo está na porta. Pare com `pkill -f "dotnet.*Gabi.Api"` ou use outra porta: `dotnet run --project src/Gabi.Api --urls "http://localhost:5101"`.
- **Web para com "Unexpected reserved word" / SyntaxError no web.log** — Vite 5 exige **Node 18+**. Verifique com `node -v`; se for &lt; 18, use `nvm install 20 && nvm use 20` (ou instale Node 18+).

### Parar Tudo

```bash
./scripts/dev-down.sh  # Para infra Docker
pkill -f "dotnet.*Gabi.Api"  # Para API
pkill -f "vite"  # Para Web
```

---

## 🧊 Teste Zero Kelvin

O **Teste Zero Kelvin** valida que o sistema pode ser reconstruído do absoluto zero — sem containers, sem banco, sem caches. É o teste definitivo de reproducibilidade do ambiente de desenvolvimento.

### O que é

Como a temperatura zero Kelvin é o estado fundamental da matéria, este teste leva o sistema ao seu estado fundamental (completamente destruído) e verifica se consegue subir e funcionar 100% apenas com os scripts automatizados.

### Como executar (Automatizado)

```bash
# Teste completo Zero Kelvin (recomendado)
./tests/zero-kelvin-test.sh

# Teste de idempotência (setup 2x)
./tests/zero-kelvin-test.sh idempotency
```

### Como executar (Manual)

```bash
# 1. Destruir tudo (remover containers, volumes, processos, logs)
docker compose down -v --remove-orphans
./scripts/app-stop.sh
rm -rf /tmp/gabi-logs /tmp/gabi-*.pid

# 2. Setup Zero Kelvin (reconstruir do zero)
./scripts/setup.sh

# 3. Iniciar aplicações em modo detached (background)
./scripts/dev app start

# 4. Verificar status
./scripts/dev app status
```

### Critérios de sucesso

| Verificação | Comando | Esperado |
|-------------|---------|----------|
| Health API | `curl http://localhost:5100/health` | `Healthy` |
| Swagger | `curl http://localhost:5100/swagger` | `200 OK` |
| Stats API | `curl http://localhost:5100/api/v1/stats` | JSON válido |
| Web UI | `curl http://localhost:3000` | `200 OK` |
| PostgreSQL | `docker compose ps postgres` | `healthy` |
| Elasticsearch | `curl http://localhost:9200/_cluster/health` | `status:green` |

### Checklist completo

Veja o [checklist detalhado](docs/zero-kelvin-checklist.md) com todos os passos, comandos exatos e debugging.

### Por que é importante

- **CI/CD**: Garante que pipelines de build funcionam em ambientes limpos
- **Onboarding**: Novos devs conseguem subir o sistema sem conhecimento tribal
- **Reproducibilidade**: Elimina "funciona na minha máquina"
- **Backup & Restore**: Valida que o sistema pode ser recriado em caso de desastre

### ♻️ Idempotência

Os scripts do Zero Kelvin são **idempotentes** — podem ser executados múltiplas vezes sem efeitos colaterais:

```bash
# Rodar 3x seguidas: o resultado final é o mesmo
./scripts/setup.sh && ./scripts/setup.sh && ./scripts/setup.sh
```

Isso significa que:
- **Migrações**: Só aplicam novas migrations (já aplicadas são ignoradas)
- **Containers**: Docker Compose recria apenas o que mudou
- **Dependências**: NPM instala apenas pacotes faltantes
- **Processos**: Scripts de stop matam apenas processos que existem

#### Teste de Idempotência

```bash
# Teste rápido de idempotência
./scripts/setup.sh        # Primeira vez (lento)
./scripts/setup.sh        # Segunda vez (rápido, sem alterações)
./scripts/dev app start   # Inicia
./scripts/dev app start   # Não duplica processos
./scripts/dev app stop    # Para
./scripts/dev app stop    # Segunda vez: "nada para parar"
```

A idempotência torna o sistema **previsível** e **seguro** para automação.

---

## 🎨 Frontend

O frontend é uma SPA em Vite que consome a API:

| Funcionalidade | Descrição |
|----------------|-----------|
| **Listagem** | Grid de cards com nome, provedor, estratégia e status |
| **Status Badge** | ● Ativo (verde) / ● Inativo (cinza) |
| **Detalhes** | Painel lateral com metadados e links descobertos |
| **Refresh** | Botão "Atualizar" por fonte ou "Atualizar Tudo" |
| **Discovery** | Executa descoberta de URLs em tempo real |

---

## ✅ Infraestrutura Rodando!

Todos os serviços estão **saudáveis** e prontos:

| Serviço          | Host      | Porta | Status                |
|------------------|-----------|-------|----------------------|
| 🐘 PostgreSQL    | localhost | 5433  | accepting connections |
| 🔍 Elasticsearch | localhost | 9200  | healthy              |
| 🔄 Redis         | localhost | 6379  | PONG                 |

### 🧪 Teste rápido:

```bash
# Conectar ao banco
psql postgresql://gabi:gabi_dev_password@localhost:5433/gabi

# Ver ES
curl http://localhost:9200/_cluster/health

# Testar Redis
docker compose exec redis redis-cli ping
```

---

## 📁 Estrutura do Projeto

```
.
├── src/
│   ├── Gabi.Api/            # REST API (Minimal API)
│   ├── Gabi.Contracts/      # Contratos e interfaces
│   ├── Gabi.Discover/       # Motor de discovery
│   ├── Gabi.Ingest/         # Fetch e Parse
│   ├── Gabi.Postgres/       # EF Core + PostgreSQL
│   ├── Gabi.Sync/           # Engine de sync
│   ├── Gabi.Web/            # Frontend React + Vite + TypeScript
│   └── Gabi.Worker/         # Entry point (Worker Service)
├── tests/                    # Testes
├── scripts/                  # Scripts de conveniência
├── docker/
│   └── postgres/init/        # Scripts SQL de inicialização
├── docker-compose.yml        # Infraestrutura + Apps opcionais
├── Dockerfile                # Worker (Fly.io ready)
├── fly.toml                  # Configuração Fly.io
└── sources_v2.yaml           # Configuração das fontes
```

## 🛠️ Tecnologias

### Backend
- **.NET 8** - Plataforma principal
- **Minimal API** - REST API (Gabi.Api)
- **PostgreSQL 15** - Banco de dados (uuid-ossp, pg_trgm)
- **Elasticsearch 8** - Motor de busca
- **Redis 7** - Cache e filas
- **YamlDotNet** - Parser de sources_v2.yaml

### Frontend
- **Vite** - Build tool
- **Vanilla JS** - Sem framework (manter leve)
- **CSS Custom Properties** - Theming

### Infra
- **Docker** - Containerização
- **Fly.io** - Deploy em produção

## 📖 Documentação

- [Docker Setup](DOCKER.md) - Guia completo de Docker
- [Layout de Deploy](docs/infrastructure/DEPLOY_LAYOUT.md) - Dev / staging / prod
- [Deploy Fly.io](docs/infrastructure/FLY_DEPLOY.md) - Apps separados (API + Worker) e checklist
- [Avaliação de Infraestrutura](docs/infrastructure/INFRA_EVALUATION.md) - Veredito, health checks, logging, recomendações
- [Roadmap](roadmap.md) - Progresso do projeto

## 📝 Licença

Projeto privado - TCU
