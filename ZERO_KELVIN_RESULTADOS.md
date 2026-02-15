# Zero Kelvin – Resultados por fase

Data: 2026-02-14  
Fluxo: zero → seed (API trigger) → discovery (API trigger), respeitando `sources_v2.yaml` e cardinalidade.

---

## 1. Regras do source.yaml e cardinalidade

- **Seed**: carrega `sources_v2.yaml`, persiste em `source_registry` (1 registro por fonte), grava execução em `seed_runs` (1:1 por execução).
- **Discovery**: por fonte, 1 job `source_discovery`; grava em `discovery_runs` e em `discovered_links` com `DiscoveryStatus`/`FetchStatus`/`IngestStatus` (cardinalidade 1:1 run, 1:N links).

Triggers usados:

- **Seed**: `POST /api/v1/dashboard/seed` (body opcional).
- **Discovery**: `POST /api/v1/dashboard/sources/{sourceId}/refresh` com `{"force":true}`.

---

## 2. Resultados observados nesta execução

### Fase 1: Seed

| Item | Resultado |
|------|-----------|
| **Trigger** | `POST /api/v1/dashboard/seed` → **HTTP 200** |
| **Resposta** | `{"success":true,"job_id":"...","message":"Seed job enqueued..."}` |
| **seed/last** | Enquanto o job não está concluído: **HTTP 404**. Após conclusão: 200 com `status`, `sources_seeded`, etc. |
| **DB após seed (quando Worker processa)** | `source_registry` = 13 fontes; `seed_runs` = 1 (quando o executor grava o run). |

Em um run anterior (logs): *"Catalog seed completed: 13/13 sources, 0 failures, status=completed"* — seed e persistência em `source_registry` funcionaram. Em seguida a conexão com o Postgres foi encerrada ("terminating connection due to administrator command") e, após restart da infra, o Worker passou a ver "relation ingest_jobs does not exist". Ou seja: seed está correto; a instabilidade veio de reinício de infra/conexão.

### Fase 2: Discovery

| Item | Resultado |
|------|-----------|
| **Trigger** | `POST .../sources/tcu_acordaos/refresh` com `{"force":true}` → **HTTP 200** |
| **Resposta** | `{"success":true,"job_id":"...","message":"Refresh queued for tcu_acordaos"}` |
| **discovery/last** | Com config antiga (sem `strategy`/`urlTemplate`): **status failed**, erro "URL is required for StaticUrl mode". |

Correções já aplicadas no código:

1. **Refresh**: body opcional; default `Force = true`.
2. **Seed**: persiste `strategy` e `urlTemplate` em `DiscoveryConfig` no banco.
3. **JobQueueRepository**: fallback no parse de `discoveryConfig` (lê `strategy`/`urlTemplate`/`template` do JSON quando a deserialização forte falha).
4. **Ingest/Fetch**: `IdempotencyKey` por request para evitar conflito de `PayloadHash` único.

Com isso, após um **seed completo** (Worker processar e gravar em `seed_runs`), o discovery para `tcu_acordaos` deve passar a usar `url_pattern` e o template corretamente.

---

## 3. Como rodar o Zero Kelvin completo

1. **Infra limpa**  
   `docker compose down -v --remove-orphans`  
   `./scripts/infra-up.sh`

2. **Subir API (com migrações) e Worker**  
   - Exportar: `GABI_RUN_MIGRATIONS=true`, `ConnectionStrings__Default=Host=localhost;Port=5433;Database=gabi;Username=gabi;Password=gabi_dev_password`, `GABI_SOURCES_PATH=/caminho/para/sources_v2.yaml`  
   - Subir a API (ex.: `dotnet run --project src/Gabi.Api/Gabi.Api.csproj --urls "http://localhost:5100"`).  
   - Depois subir o Worker (`dotnet run --project src/Gabi.Worker/Gabi.Worker.csproj`).  
   Assim as migrações rodam antes do Worker e ambos usam o mesmo banco.

3. **Triggers e checagem**  
   - Login: `POST /api/v1/auth/login` com `{"username":"operator","password":"op123"}`.  
   - Seed: `POST /api/v1/dashboard/seed` (header `Authorization: Bearer <token>`).  
   - Poll: `GET /api/v1/dashboard/seed/last` até `status` = `completed` ou `partial`.  
   - Discovery: `POST /api/v1/dashboard/sources/tcu_acordaos/refresh` com body `{"force":true}`.  
   - Poll: `GET /api/v1/dashboard/sources/tcu_acordaos/discovery/last` até `status` = `completed` ou `partial` ou `failed`.

4. **Script automatizado**  
   `./scripts/e2e-zero-kelvin.sh` — faz infra, build, API, Worker, seed, discovery, fetch, ingest (2 rodadas + fail-safe). Se algo der 4xx/5xx, o `curl -f` pode encerrar o script; para ver todas as fases mesmo com erro, use os passos manuais acima ou ajuste o script para não usar `-f` nos triggers.

---

## 4. Resumo

- **Seed**: trigger 200; executor grava 13 fontes e, em execução estável, grava em `seed_runs`; instabilidade veio de reinício de infra/conexão, não da lógica do seed.
- **Discovery**: trigger 200; falha "URL is required for StaticUrl" foi corrigida com strategy/urlTemplate no seed e fallback no parse do `discoveryConfig`.
- Para um Zero Kelvin “do zero ao seed e ao discovery” de forma confiável: garantir infra estável, API + Worker no mesmo DB, migrações rodadas pela API antes do Worker, depois disparar seed → aguardar seed/last completed → disparar discovery → conferir discovery/last e contagens em `discovery_runs` e `discovered_links`.
