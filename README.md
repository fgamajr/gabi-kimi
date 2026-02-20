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

### Opção 2: Desenvolvimento local (infra Docker + API no host)

**Terminal 1 – Infra:**
```bash
./scripts/dev infra up
```

**Terminal 2 – API** (a partir da **raiz do repositório**):
```bash
dotnet run --project src/Gabi.Api --urls "http://localhost:5100"
```
Se a porta 5100 estiver em uso: `pkill -f "dotnet.*Gabi.Api"` ou use `--urls "http://localhost:5101"`.

Ou em um único fluxo (infra + app em foreground): `./scripts/dev app up` (Ctrl+C para parar).

### Acessos

| Serviço        | URL |
|----------------|-----|
| API            | http://localhost:5100 |
| Swagger UI     | http://localhost:5100/swagger |
| Health Check   | http://localhost:5100/health |

### Parar tudo

```bash
./scripts/dev infra down    # Para containers (mantém volumes)
./scripts/dev app stop      # Para API se rodando no host
pkill -f "dotnet.*Gabi.Api"
```

### Problemas comuns

- **"Project file does not exist"** — Execute comandos a partir da **raiz do repositório**, não de dentro de `src/Gabi.Api`.
- **Porta 5100 em uso** — `pkill -f "dotnet.*Gabi.Api"` ou use `--urls "http://localhost:5101"`.
- **Porta 6380 em uso** — Redis do projeto usa **6380** no host (evitar conflito com Redis do sistema em 6379). Libere com `fuser -k 6380/tcp` ou pare o container que publica 6380.
- **Frontend** — O `Gabi.Web` foi retirado do fluxo operacional atual para foco em backend e pipeline.

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

O Worker (Docker profile `worker`) executa os jobs (`catalog_seed`, `discovery`, `fetch`, `ingest`) com execução assíncrona em background.

---

## Backend-Only (API essencial)

No foco atual, o sistema opera sem frontend. O núcleo essencial da API para o backend é:

1. `POST /api/v1/auth/login` (JWT)
2. `POST /api/v1/dashboard/seed`
3. `GET /api/v1/dashboard/seed/last`
4. `POST /api/v1/dashboard/sources/{sourceId}/phases/{phase}`
5. `GET /api/v1/dashboard/sources/{sourceId}/discovery/last`
6. `GET /api/v1/dashboard/sources/{sourceId}/fetch/last`
7. `GET /api/v1/sources/{sourceId}/links`
8. `GET /api/v1/dlq*` e `POST /api/v1/dlq/{id}/replay` (operação/recovery)

Observação:
1. Endpoints legados de dashboard/frontend já foram removidos do runtime principal.
2. Scripts e runbooks operacionais devem usar somente os endpoints essenciais listados acima.

---

## 🛡️ Stabilization Program (Feb 2026)

Resumo do que foi endurecido no pipeline durante o programa de estabilização:

### Concluído

- **Discovery payload robustness (P0)**  
  `JobPayloadParser` agora aceita payload JSON normal e double-encoded; `url_pattern` é inferido quando necessário para evitar fallback indevido em `static_url`.

- **Materialização discovery -> fetch_items (P0)**  
  Discovery garante criação/validação de `fetch_items` para links persistidos, com invariantes explícitos no fluxo.

- **DLQ JSON serialization (P0)**  
  Persistência DLQ trata payload e stack trace em JSON válido para `jsonb`, evitando erro de sintaxe no Postgres.

- **Retry policy unificada (P1)**  
  Uma única fonte de verdade: `Hangfire:RetryPolicy` em `appsettings`.  
  Worker registra um único `AutomaticRetry` global e `DlqFilter` usa a mesma configuração.

- **Compose/runtime consistency (P1)**  
  `docker compose config` limpo e fluxo padrão com profiles (`api`, `worker`) sem warning de orphan no uso normal.

- **Native capped stress mode (P1)**  
  Fetch suporta cap nativo por fonte via payload `max_docs_per_source`, com parada graciosa e status final `capped`.

### Resultado de stress (Zero Kelvin)

- Execução completa `docker-20k` em `tcu_acordaos`:  
  `docs=20000` (exato), `fetch_runs.status='capped'`, sem OOM.
- Pico de memória observado no worker: **253 MiB**.
- Baseline operacional atual (`all-sources`, cap=200, modo sequencial+isolamento):  
  **PASS=26, WARN=0, FAIL=0**, `peak_mem=246.7 MiB`  
  (evidência: `/tmp/zk-all-200-fix3.json`).

### Zero-Kelvin targeted (novo)

Agora o script suporta execução targeted por flags:

```bash
# Discovery only (source-specific)
./tests/zero-kelvin-test.sh docker-only \
  --source tcu_sumulas \
  --phase discovery \
  --report-json /tmp/gabi-zk-target.json

# Full stress (discovery + fetch capped) com monitor de memória
./tests/zero-kelvin-test.sh docker-only \
  --source tcu_acordaos \
  --phase full \
  --max-docs 20000 \
  --monitor-memory \
  --report-json /tmp/gabi-zk-20k.json
```

Flags suportadas:
- `--source <id>`
- `--phase <discovery|fetch|full>`
- `--max-docs <n>`
- `--monitor-memory`
- `--report-json <path>`

Saída estruturada (JSON): inclui testes, métricas de pipeline, docs processados, pico de memória, breakdown de status e resumo de erro.

### Modelo de armazenamento (decisão atual)

Regra principal:
1. **Fonte da verdade = conteúdo textual extraído + metadados no Postgres**.
2. **Não persistir bruto** (`pdf/html/video/audio`) no Postgres por padrão.

Implicações:
1. `documents.Content` guarda texto normalizado.
2. metadados semânticos e operacionais ficam em `documents.Metadata`.
3. S3/object storage é **opcional** (auditoria/replay), não obrigatório.

Observação importante:
1. S3 **não** hospeda containers; para compute seguimos com Docker/Fly.io.

### Fontes multimídia (direção)

O pipeline continua em 4 fases (`discovery -> fetch -> ingest -> index`) também para vídeo/áudio.  
Para isso, a direção é introduzir `content_profile` no YAML:
1. `text` (fontes textuais tradicionais)
2. `document` (documentos estruturados)
3. `media` (vídeo/áudio)

Para `content_profile=media`:
1. discovery coleta links e metadados da sessão;
2. fetch pode operar em `metadata_only` no início (sem baixar mídia bruta);
3. ingest produz conteúdo textual (transcrição quando existir) + metadados;
4. index segue o mesmo fluxo semântico das demais fontes.

### Como disparar fetch com cap nativo

```bash
TOKEN=$(curl -s -X POST http://localhost:5100/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"operator","password":"op123"}' | jq -r .token)

curl -s -X POST "http://localhost:5100/api/v1/dashboard/sources/tcu_acordaos/phases/fetch" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"max_docs_per_source":20000}'
```

Variáveis úteis de telemetria/guardrails no Worker:
- `GABI_FETCH_MAX_FIELD_CHARS` (default `262144`)  
  Limite de tamanho de campo CSV; excedente é truncado com warning.
- `GABI_FETCH_TELEMETRY_EVERY_ROWS` (default `1000`)  
  Intervalo de logs de telemetria (`rows`, `docs`, truncações, heap, RSS, cgroup).

### Prova runtime retry -> DLQ (determinística)

Evidência coletada em execução real:

- Job de discovery forçado a falhar por config inválida (`static_url` sem `url`).
- Logs mostraram múltiplas falhas do mesmo `job_id`.
- `DlqFilter` registrou: `failed after 3 attempts, moving to Dead Letter Queue`.
- `dlq_entries` recebeu registro com:
  - `JobType=RunAsync`
  - `ErrorType=ArgumentException`
  - `RetryCount=3`
- `hangfire.state` mostrou `failed_states=4` para o job (falha inicial + retries).

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
| GET | `/api/v1/jobs/{sourceId}/status` | viewer | Status do job de uma fonte |
| POST | `/api/v1/dashboard/seed` | operator | Enfileira job de seed (YAML → DB) |
| GET | `/api/v1/dashboard/seed/last` | viewer | Última execução do seed |
| GET | `/api/v1/dashboard/pipeline/phases` | viewer | Fases (seed, discovery, fetch, ingest) |
| POST | `/api/v1/dashboard/sources/{sourceId}/phases/{phase}` | operator | Dispara fase (discovery \| fetch \| ingest) |
| GET | `/api/v1/dashboard/sources/{sourceId}/discovery/last` | viewer | Última discovery da fonte |
| GET | `/api/v1/dashboard/sources/{sourceId}/fetch/last` | viewer | Último fetch da fonte |
| GET | `/api/v1/sources/{sourceId}/links` | viewer | Links da fonte (paginado) |
| GET | `/api/v1/sources/{sourceId}/links/{linkId}` | viewer | Detalhe de um link |
| POST | `/api/v1/media/upload` | operator | Upload/ingest de mídia (assíncrono, retorna 202) |
| GET | `/api/v1/media/{id}` | viewer | Status do item de mídia |
| GET | `/api/v1/dlq` | viewer | Lista DLQ |
| GET | `/api/v1/dlq/stats` | viewer | Estatísticas DLQ |
| GET | `/api/v1/dlq/{id}` | viewer | Detalhe DLQ |
| POST | `/api/v1/dlq/{id}/replay` | operator | Reprocessa entrada DLQ |

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

---

### 4. Pipeline operacional (seed, fases, status)

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

---

### 5. Links e DLQ

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

```bash
# Listar DLQ (e estatísticas)
curl -s http://localhost:5100/api/v1/dlq -H "Authorization: Bearer $TOKEN"
curl -s http://localhost:5100/api/v1/dlq/stats -H "Authorization: Bearer $TOKEN"
```

### Política de recuperação (atual)

1. Falhas transitórias tentam retry local (quando aplicável) + retry global do Hangfire.
2. Esgotando retries, o job vai para `failed`/`DLQ`.
3. Recuperação é **manual** via replay (`POST /api/v1/dlq/{id}/replay`) ou novo trigger de fase.
4. Não há requeue automático infinito por padrão.

---

## 🧊 Teste Zero Kelvin

Valida que o sistema pode ser reconstruído do zero (containers, volumes e processos destruídos) e que o pipeline básico funciona só com Docker.

### Modo padrão: Docker-only (recomendado)

Não usa `dotnet`/`npm` no host. O script:

1. **Destrói** containers, volumes e libera portas (6380, 5433, 9200, 5100, 3000), inclusive com `fuser -k` se necessário.
2. **Sobe** infra (`docker compose up -d`), faz build da API e do Worker e sobe com `--profile api --profile worker`.
3. **Verifica** health, Swagger, login e **evidências do pipeline**: Seed (fontes registradas), Discovery (job criado/processado), Fetch.

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
| Seed | `POST /api/v1/dashboard/seed` → 200; depois `GET /api/v1/sources` com fontes |
| Discovery | Job de discovery criado e processado pelo Worker |

Para rodadas `--source all --phase full` (cap curto), o modo operacional atual usa isolamento sequencial por fonte:
1. flush de fila entre fontes;
2. limpeza de dados por fonte;
3. tolerância a discovery longa em fontes de alta cardinalidade (ex.: Câmara) sem travar a suíte.

Isso torna o resultado comparável e reprodutível para gate de estabilidade.

**Portas usadas no teste:** 6380 (Redis no host), 5433 (Postgres), 9200 (Elasticsearch), 5100 (API). O Redis do projeto está em **6380** no host para não conflitar com Redis do sistema (6379).

**EF e migrations (Zero Kelvin):** Com `GABI_RUN_MIGRATIONS=true` (já definido no `docker-compose` para a API), na subida do container a API executa `DbContext.Database.Migrate()` e aplica **todas** as migrations do projeto `Gabi.Postgres` em ordem, incluindo a que cria a tabela `seed_runs`. Não é necessário rodar `dotnet ef` nem criar tabelas manualmente; o teste Zero Kelvin sobe do zero e o banco fica pronto para o seed e o pipeline.

### Checklist e idempotência

- [Checklist detalhado](docs/zero-kelvin-checklist.md) com passos e debugging.  
- No modo **full**, `./scripts/setup.sh` e `./scripts/dev app start/stop` são idempotentes (migrations, containers e processos não duplicam).

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

### Infra
- **Docker** - Containerização
- **Fly.io** - Deploy em produção

## 📖 Documentação

- [Docker Setup](DOCKER.md) - Guia completo de Docker
- [Layout de Deploy](docs/infrastructure/DEPLOY_LAYOUT.md) - Dev / staging / prod
- [Deploy Fly.io](docs/infrastructure/FLY_DEPLOY.md) - Apps separados (API + Worker) e checklist
- [Avaliação de Infraestrutura](docs/infrastructure/INFRA_EVALUATION.md) - Veredito, health checks, logging, recomendações
- [Plano Consolidado v5](PLANO_CONSOLIDADO_V5.md) - Roadmap técnico e evidências de estabilização
- [Checklist Zero Kelvin](docs/zero-kelvin-checklist.md) - Passos manuais e debugging

**Referências antigas (deprecado/removido):** uso de `dev-start.sh` / `dev-up.sh` / `dev-down.sh` foi substituído por `./scripts/dev` (infra | app | db). Redis no host passou de 6379 para **6380** para evitar conflito com Redis do sistema.

## 📝 Licença

Projeto privado - TCU
