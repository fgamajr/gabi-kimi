# GABI - Sistema de Ingestão e Busca Jurídica TCU

Sistema de ingestão, processamento e busca de dados jurídicos do Tribunal de Contas da União.

## 🚀 Quick Start

### Opção 1: Tudo com Docker (recomendado para Zero Kelvin / CI)

Sobe infra + API + Worker só com Docker (sem dotnet/npm no host):

```bash
./scripts/dev infra up          # Postgres, Elasticsearch, Redis (portas 5433, 9200, 6380)
docker compose --profile api --profile worker up -d   # Build e sobe API (5100) e Worker
```

- **API:** http://localhost:5100  
- **Worker:** processa jobs (discovery, fetch, ingest) em background  

Para popular as fontes: `POST /api/v1/dashboard/seed` (token operator). Ver [Seed e fontes](#-seed-e-fontes).

### Opção 2: Desenvolvimento local (infra Docker + API/Web no host)

**Terminal 1 – Infra:**
```bash
./scripts/dev infra up
```

**Terminal 2 – API** (a partir da **raiz do repositório**):
```bash
dotnet run --project src/Gabi.Api --urls "http://localhost:5100"
```
Se a porta 5100 estiver em uso: `pkill -f "dotnet.*Gabi.Api"` ou use `--urls "http://localhost:5101"`.

**Terminal 3 – Web** (Node 18+):
```bash
cd src/Gabi.Web && npm run dev
```

Ou em um único fluxo (infra + app em foreground): `./scripts/dev app up` (Ctrl+C para parar).

### Acessos

| Serviço        | URL |
|----------------|-----|
| Web Frontend   | http://localhost:3000 |
| API            | http://localhost:5100 |
| Swagger UI     | http://localhost:5100/swagger |
| Health Check   | http://localhost:5100/health |

### Parar tudo

```bash
./scripts/dev infra down    # Para containers (mantém volumes)
./scripts/dev app stop      # Para API + Web se rodando no host
pkill -f "dotnet.*Gabi.Api"
pkill -f "vite"
```

### Problemas comuns

- **"Project file does not exist"** — Execute comandos a partir da **raiz do repositório**, não de dentro de `src/Gabi.Api`.
- **Porta 5100 em uso** — `pkill -f "dotnet.*Gabi.Api"` ou use `--urls "http://localhost:5101"`.
- **Porta 6380 em uso** — Redis do projeto usa **6380** no host (evitar conflito com Redis do sistema em 6379). Libere com `fuser -k 6380/tcp` ou pare o container que publica 6380.
- **Web: "Unexpected reserved word"** — Vite 5 exige **Node 18+**. Use `nvm install 20 && nvm use 20` se necessário.

---

## 🌱 Seed e fontes

As fontes são definidas em **`sources_v2.yaml`**. O seed é **assíncrono**: a API enfileira um job `catalog_seed` e o **Worker** carrega o YAML, persiste cada fonte no Postgres (com retry por fonte) e grava o resultado em **`seed_runs`** (para a fase de discovery saber que o catálogo está pronto).

1. **Disparar o seed** — `POST /api/v1/dashboard/seed` (token **operator**). Resposta inclui `job_id`; o Worker processa em background.
2. **Última execução do seed** — `GET /api/v1/dashboard/seed/last` (token **viewer**). Retorna o último registro de `seed_runs` (ou 404 se nunca rodou).
3. **Listar fontes** — `GET /api/v1/sources` (token **viewer** ou operator). Retorna `data[]` com as fontes já persistidas.
4. **Docker** — A API e o Worker usam `GABI_SOURCES_PATH=/app/sources_v2.yaml`; o compose monta `./sources_v2.yaml` nesse caminho.

---

## 🔄 Pipeline (fases)

O pipeline é **Seed → Discovery → Fetch → Ingest**. A API expõe:

- **`GET /api/v1/dashboard/pipeline/phases`** — Lista fases (seed, discovery, fetch, ingest) com `trigger_endpoint` e descrição.
- **`POST /api/v1/dashboard/seed`** — Executa o seed (carrega fontes do YAML para o banco).
- **`POST /api/v1/dashboard/sources/{sourceId}/phases/{phase}`** — Dispara uma fase para uma fonte (`phase`: `discovery`, `fetch` ou `ingest`). Retorna `job_id`; o **Worker** processa em background e atualiza progresso (consultável via jobs/status).

O Worker (Docker profile `worker`) executa os jobs (catalog_seed, discovery, fetch, ingest); fetch e ingest estão em modo stub até implementação futura.

---

## 📡 Referência da API (endpoints e exemplos)

Base URL: `http://localhost:5100`. Endpoints protegidos exigem **JWT**: `Authorization: Bearer <token>`. Obtenha o token em `POST /api/v1/auth/login`. Usuários: `operator` / `op123` (pode disparar seed/refresh/fases), `viewer` / `view123` (somente leitura).

### Tabela de endpoints

| Método | Endpoint | Auth | Descrição |
|--------|----------|------|-----------|
| POST | `/api/v1/auth/login` | — | Login (retorna token) |
| GET | `/health` | — | Health check (live) |
| GET | `/health/ready` | — | Readiness (inclui Postgres) |
| GET | `/api/v1/sources` | viewer | Lista todas as fontes |
| GET | `/api/v1/sources/{sourceId}` | viewer | Detalhes de uma fonte |
| POST | `/api/v1/sources/{sourceId}/refresh` | operator | Enfileira discovery (refresh) |
| GET | `/api/v1/jobs` | viewer | Lista jobs de sync + índices ES |
| GET | `/api/v1/stats` | viewer | Stats do sistema (fontes, docs, ES) |
| GET | `/api/v1/pipeline` | viewer | Estágios do pipeline |
| GET | `/api/v1/jobs/{sourceId}/status` | viewer | Status do job de uma fonte |
| GET | `/api/v1/dashboard/stats` | viewer | Stats do dashboard (frontend) |
| GET | `/api/v1/dashboard/jobs` | viewer | Jobs recentes (frontend) |
| GET | `/api/v1/dashboard/pipeline` | viewer | Pipeline (frontend) |
| GET | `/api/v1/dashboard/health` | viewer | Saúde dos serviços |
| POST | `/api/v1/dashboard/sources/{sourceId}/refresh` | operator | Refresh (discovery) da fonte |
| POST | `/api/v1/dashboard/seed` | operator | Enfileira job de seed (YAML → DB) |
| GET | `/api/v1/dashboard/seed/last` | viewer | Última execução do seed |
| GET | `/api/v1/dashboard/pipeline/phases` | viewer | Fases (seed, discovery, fetch, ingest) |
| POST | `/api/v1/dashboard/sources/{sourceId}/phases/{phase}` | operator | Dispara fase (discovery \| fetch \| ingest) |
| GET | `/api/v1/dashboard/safra` | viewer | Safra (opcional `?sourceId=`) |
| GET | `/api/v1/sources/{sourceId}/links` | viewer | Links da fonte (paginado) |
| GET | `/api/v1/sources/{sourceId}/links/{linkId}` | viewer | Detalhe de um link |

---

### 1. Autenticação

```bash
curl -s -X POST http://localhost:5100/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"operator","password":"op123"}'
```

**Resposta (200):** `{"success":true,"token":"eyJ...","expiresAt":"...","role":"Operator"}`  
**401:** credenciais inválidas. **429:** rate limit (aguarde antes de tentar de novo).

Guarde o token para os exemplos abaixo, por exemplo: `TOKEN=$(curl -s -X POST ... | jq -r .token)`.

---

### 2. Health (públicos)

```bash
curl -s http://localhost:5100/health
# Resposta: Healthy

curl -s http://localhost:5100/health/ready
# Resposta: JSON com status de cada check (live + postgres)
```

---

### 3. Fontes

```bash
# Listar fontes
curl -s http://localhost:5100/api/v1/sources -H "Authorization: Bearer $TOKEN"
```
**Resposta (200):** `{"data":[{"id":"tcu_acordaos","name":"TCU - Acórdãos","provider":"TCU","strategy":"url_pattern","enabled":true,"documentCount":0,"sourceType":"url_pattern"},...],"version":"v1"}`

```bash
# Detalhes de uma fonte
curl -s http://localhost:5100/api/v1/sources/tcu_sumulas -H "Authorization: Bearer $TOKEN"
```
**Resposta (200):** `{"data":{"id":"tcu_sumulas","name":"...","description":"...","links":[],"metadata":{...}},"version":"v1"}`  
**404:** fonte não encontrada.

```bash
# Refresh (discovery) – enfileira job
curl -s -X POST "http://localhost:5100/api/v1/sources/tcu_sumulas/refresh" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json"
```
**Resposta (200):** `{"data":{"sourceId":"tcu_sumulas","progressPercent":0,"estimatedTimeRemaining":"00:00:00"},"version":"v1"}`  
**404:** fonte não encontrada.

---

### 4. Jobs e stats

```bash
# Listar jobs (sync jobs + índices ES)
curl -s http://localhost:5100/api/v1/jobs -H "Authorization: Bearer $TOKEN"
```
**Resposta (200):** `{"data":{"jobs":[],"totalElasticDocuments":0,"elasticIndexes":[]},"version":"v1"}`

```bash
# Stats do sistema
curl -s http://localhost:5100/api/v1/stats -H "Authorization: Bearer $TOKEN"
```
**Resposta (200):** `{"data":{"totalSources":13,"totalDocuments":0,"elasticStatus":"...","indexes":[]},"version":"v1"}`

```bash
# Estágios do pipeline
curl -s http://localhost:5100/api/v1/pipeline -H "Authorization: Bearer $TOKEN"
```
**Resposta (200):** `{"data":[{"name":"Discovery","status":"Active"|"Idle",...}],"version":"v1"}`

```bash
# Status do job de uma fonte
curl -s http://localhost:5100/api/v1/jobs/tcu_sumulas/status -H "Authorization: Bearer $TOKEN"
```
**Resposta (200):** `{"data":{"jobId":"...","sourceId":"tcu_sumulas","status":"completed","progressPercent":100,...},"version":"v1"}` ou `{"data":null,"version":"v1"}` se não houver job.

---

### 5. Dashboard (contrato frontend)

```bash
# Stats do dashboard
curl -s http://localhost:5100/api/v1/dashboard/stats -H "Authorization: Bearer $TOKEN"
```
**Resposta (200):** `{"sources":[...],"totalDocuments":0,"syncStatus":{...},"ragStats":{...}}`

```bash
# Jobs recentes
curl -s http://localhost:5100/api/v1/dashboard/jobs -H "Authorization: Bearer $TOKEN"
```
**Resposta (200):** `{"syncJobs":[],"totalElasticDocuments":0,"elasticIndexes":[]}`

```bash
# Pipeline (estágios)
curl -s http://localhost:5100/api/v1/dashboard/pipeline -H "Authorization: Bearer $TOKEN"
```
**Resposta (200):** Lista de estágios com nome e status.

```bash
# Saúde dos serviços (Postgres, ES, Redis)
curl -s http://localhost:5100/api/v1/dashboard/health -H "Authorization: Bearer $TOKEN"
```
**Resposta (200):** `{"status":"Healthy","timestamp":"...","services":{"postgresql":{...},"elasticsearch":{...},"redis":{...}}}`

---

### 6. Seed e pipeline (fases)

```bash
# Disparar seed (job assíncrono; Worker persiste YAML no banco)
curl -s -X POST http://localhost:5100/api/v1/dashboard/seed \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json"
```
**Resposta (200):** `{"success":true,"job_id":"<uuid>","message":"Seed job enqueued. Worker will load sources from YAML..."}`  
Se já houver seed em andamento: `"message":"Seed already in progress..."`.

```bash
# Última execução do seed (para saber se o catálogo está pronto para discovery)
curl -s http://localhost:5100/api/v1/dashboard/seed/last -H "Authorization: Bearer $TOKEN"
```
**Resposta (200):** `{"id":"...","job_id":"...","completed_at":"...","sources_total":13,"sources_seeded":13,"sources_failed":0,"status":"completed","error_summary":null}`  
**404:** nenhum seed concluído ainda.

```bash
# Listar fases do pipeline (como disparar cada uma)
curl -s http://localhost:5100/api/v1/dashboard/pipeline/phases -H "Authorization: Bearer $TOKEN"
```
**Resposta (200):** `[{"id":"seed","name":"Seed","description":"Carregar fontes do YAML no banco","availability":"available","trigger_endpoint":"POST /api/v1/dashboard/seed"},...]`

```bash
# Disparar uma fase para uma fonte (discovery | fetch | ingest)
curl -s -X POST "http://localhost:5100/api/v1/dashboard/sources/tcu_sumulas/phases/discovery" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json"
```
**Resposta (200):** `{"success":true,"job_id":"<uuid>","message":"discovery queued for tcu_sumulas"}`  
**400:** `phase` deve ser `discovery`, `fetch` ou `ingest`.

```bash
# Refresh (discovery) via dashboard
curl -s -X POST "http://localhost:5100/api/v1/dashboard/sources/tcu_sumulas/refresh" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"force":true}'
```
**Resposta (200):** `{"success":true,"job_id":"...","message":"..."}`

---

### 7. Safra e links

```bash
# Safra (opcional: ?sourceId=tcu_sumulas)
curl -s "http://localhost:5100/api/v1/dashboard/safra?sourceId=tcu_sumulas" \
  -H "Authorization: Bearer $TOKEN"
```
**Resposta (200):** Objeto com anos/safras e estatísticas.

```bash
# Links de uma fonte (paginado: ?page=1&pageSize=10)
curl -s "http://localhost:5100/api/v1/sources/tcu_sumulas/links?page=1&pageSize=5" \
  -H "Authorization: Bearer $TOKEN"
```
**Resposta (200):** `{"items":[],"totalItems":0,"page":1,"pageSize":5}`  
**404:** fonte não encontrada.

```bash
# Detalhe de um link
curl -s http://localhost:5100/api/v1/sources/tcu_sumulas/links/123 \
  -H "Authorization: Bearer $TOKEN"
```
**Resposta (200):** Objeto com url, status, pipeline, etc. **404:** link não encontrado.

---

## 🧊 Teste Zero Kelvin

Valida que o sistema pode ser reconstruído do zero (containers, volumes e processos destruídos) e que o pipeline básico funciona só com Docker.

### Modo padrão: Docker-only (recomendado)

Não usa `dotnet`/`npm` no host. O script:

1. **Destrói** containers, volumes e libera portas (6380, 5433, 9200, 5100, 3000), inclusive com `fuser -k` se necessário.
2. **Sobe** infra (`docker compose up -d`), faz build da API e do Worker e sobe com `--profile api --profile worker`.
3. **Verifica** health, Swagger, login, dashboard stats e **evidências do pipeline**: Seed (fontes registradas), Discovery (job criado/processado), Fetch.

```bash
./tests/zero-kelvin-test.sh
# ou explicitamente:
./tests/zero-kelvin-test.sh docker-only
```

### Modo legado (com dotnet/npm no host)

```bash
./tests/zero-kelvin-test.sh full      # Destroy + setup.sh + app no host
./tests/zero-kelvin-test.sh idempotency   # Idempotência do modo full (setup 2x)
```

### Critérios de sucesso

| Verificação | Esperado |
|-------------|----------|
| Health API | `curl http://localhost:5100/health` → `Healthy` |
| Swagger | `curl -I http://localhost:5100/swagger/index.html` → 200 |
| Dashboard stats | `GET /api/v1/dashboard/stats` (com token) → JSON com `sources` |
| Seed | `POST /api/v1/dashboard/seed` → 200; depois `GET /api/v1/sources` com fontes |
| Discovery | Job de discovery criado e processado pelo Worker |

**Portas usadas no teste:** 6380 (Redis no host), 5433 (Postgres), 9200 (Elasticsearch), 5100 (API), 3000 (Web). O Redis do projeto está em **6380** no host para não conflitar com Redis do sistema (6379).

**EF e migrations (Zero Kelvin):** Com `GABI_RUN_MIGRATIONS=true` (já definido no `docker-compose` para a API), na subida do container a API executa `DbContext.Database.Migrate()` e aplica **todas** as migrations do projeto `Gabi.Postgres` em ordem, incluindo a que cria a tabela `seed_runs`. Não é necessário rodar `dotnet ef` nem criar tabelas manualmente; o teste Zero Kelvin sobe do zero e o banco fica pronto para o seed e o pipeline.

### Checklist e idempotência

- [Checklist detalhado](docs/zero-kelvin-checklist.md) com passos e debugging.  
- No modo **full**, `./scripts/setup.sh` e `./scripts/dev app start/stop` são idempotentes (migrations, containers e processos não duplicam).

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

## ✅ Infraestrutura

| Serviço          | Host      | Porta | Observação |
|------------------|-----------|-------|------------|
| 🐘 PostgreSQL    | localhost | 5433  | `docker compose` mapeia 5433→5432 |
| 🔍 Elasticsearch | localhost | 9200  | health: `curl http://localhost:9200/_cluster/health` |
| 🔄 Redis         | localhost | **6380** | Mapeado 6380→6379 no host para não conflitar com Redis do sistema |

```bash
# Banco
psql postgresql://gabi:gabi_dev_password@localhost:5433/gabi

# Redis (no host use porta 6380; dentro do compose os serviços usam redis:6379)
docker compose exec redis redis-cli ping
# ou, se Redis estiver exposto: redis-cli -p 6380 ping
```

---

## 📁 Estrutura do Projeto

```
.
├── src/
│   ├── Gabi.Api/            # REST API (Minimal API); migrations na startup se GABI_RUN_MIGRATIONS=true
│   ├── Gabi.Contracts/      # Contratos e interfaces
│   ├── Gabi.Discover/       # Motor de discovery
│   ├── Gabi.Ingest/         # Fetch e Parse
│   ├── Gabi.Postgres/       # EF Core + PostgreSQL (migrations)
│   ├── Gabi.Sync/           # Engine de sync
│   ├── Gabi.Web/            # Frontend (Vite)
│   └── Gabi.Worker/         # Worker (jobs discovery/fetch/ingest)
├── tests/                    # Testes (ex.: zero-kelvin-test.sh)
├── scripts/                  # ./scripts/dev (infra | app | db)
├── docker-compose.yml       # Infra + profiles api / worker
├── Dockerfile                # Worker (Fly.io ready)
├── fly.toml                  # Configuração Fly.io
└── sources_v2.yaml           # Definição das fontes (seed via API)
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
- **Vanilla JS** (ou React conforme o projeto) - Theming com CSS Custom Properties

### Infra
- **Docker** - Containerização
- **Fly.io** - Deploy em produção

## 📖 Documentação

- [Docker Setup](DOCKER.md) - Guia completo de Docker
- [Layout de Deploy](docs/infrastructure/DEPLOY_LAYOUT.md) - Dev / staging / prod
- [Deploy Fly.io](docs/infrastructure/FLY_DEPLOY.md) - Apps separados (API + Worker) e checklist
- [Avaliação de Infraestrutura](docs/infrastructure/INFRA_EVALUATION.md) - Veredito, health checks, logging, recomendações
- [Roadmap](roadmap.md) - Progresso do projeto
- [Checklist Zero Kelvin](docs/zero-kelvin-checklist.md) - Passos manuais e debugging

**Referências antigas (deprecado/removido):** uso de `dev-start.sh` / `dev-up.sh` / `dev-down.sh` foi substituído por `./scripts/dev` (infra | app | db). Redis no host passou de 6379 para **6380** para evitar conflito com Redis do sistema. Stats do dashboard: usar `GET /api/v1/dashboard/stats` (autenticado); `GET /api/v1/stats` continua disponível para dados gerais do sistema.

## 📝 Licença

Projeto privado - TCU
