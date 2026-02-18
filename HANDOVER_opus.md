# 🔄 HANDOVER DOCUMENT — GABI-SYNC

**Date**: 2026-02-15  
**Project**: GABI — Sistema de Ingestão e Busca Jurídica (TCU)  
**Stack**: .NET 8 / PostgreSQL 15 / Elasticsearch 8 / Redis 7 / Hangfire / Docker / Fly.io  
**Repo**: `/home/fgamajr/dev/gabi-kimi` — Solution `GabiSync.sln`

---

## 1. CURRENT STATE — What Works Today

### 1.1 Solution Structure (10 projects)

| Project | Role | State |
|---------|------|-------|
| `Gabi.Api` | REST API (Minimal API, port 5100) | ✅ Production-ready |
| `Gabi.Contracts` | Shared DTOs, interfaces, enums (68 files) | ✅ Solid |
| `Gabi.Discover` | Discovery engine (StaticUrl, UrlPattern) | 🟡 Partial — WebCrawl/ApiPagination return empty |
| `Gabi.Fetch` | Content fetching module | 🔴 **Skeleton only** (3 files, no logic) |
| `Gabi.Ingest` | Ingest pipeline (parse, transform) | 🔴 Structure exists, **no real parsing** |
| `Gabi.Jobs` | Job factory + state machine | 🟡 Basic — `JobFactory`, `JobStateMachine` exist |
| `Gabi.Postgres` | EF Core context, entities, migrations, repos | ✅ Solid (68 files) |
| `Gabi.Sync` | Sync engine | 🟡 Basic orchestration only |
| `Gabi.Web` | Frontend SPA (Vite, vanilla JS) | ✅ Dashboard functional |
| `Gabi.Worker` | Hangfire Worker (background jobs) | ✅ Running, but stubs inside |

### 1.2 Infrastructure (Docker Compose)

| Service | Image | Host Port | Status |
|---------|-------|-----------|--------|
| PostgreSQL | `postgres:15-alpine` | 5433 | ✅ Healthy |
| Elasticsearch | `elasticsearch:8.11.0` | 9200 | ✅ Healthy (xpack disabled) |
| Redis | `redis:7-alpine` | **6380** (not 6379!) | ✅ Healthy |
| API | `Dockerfile` (src/Gabi.Api/) | 5100 | ✅ Optional profile `api` |
| Worker | `Dockerfile` (root) | — | ✅ Optional profile `worker` |
| Web | `node:20-alpine` | 3000 | ✅ Optional profile `web` |

### 1.3 Pipeline Phases — Actual Execution Reality

```
Seed ──────► Discovery ──────► Fetch ──────► Ingest
  ✅ Works      🟡 Partial      🟠 Stub       🟠 Stub
```

| Phase | What it actually does | What's missing |
|-------|----------------------|----------------|
| **Seed** | Loads `sources_v2.yaml` → persists 13 sources into PostgreSQL. Records `seed_runs`. Retry per source. | — Works correctly |
| **Discovery** | `StaticUrl` returns 1 link. `UrlPattern` expands year range (1992–current → 35 links for `tcu_acordaos`). Persists to `discovered_links`, creates `fetch_items`, records `discovery_runs`. | `WebCrawl` → `yield break` (empty). `ApiPagination` → `yield break` (empty). |
| **Fetch** | Iterates `fetch_items` with status "pending"/"failed", marks them "completed", creates a `DocumentEntity` per item. **Does NOT actually download any content.** | No HTTP download. No CSV streaming. No content storage. |
| **Ingest** | Marks documents "completed" and "ingested". **Does NOT parse, hash, chunk, embed, or index.** | Everything. This is a pass-through stub. |

### 1.4 Queue System — Hangfire

- **Storage**: PostgreSQL (same database as app data via `Hangfire.PostgreSql`)
- **Queues**: `seed`, `discovery`, `fetch`, `ingest`, `default`
- **Worker count**: configurable (default 2)
- **Retry**: `[AutomaticRetry(Attempts = 3, DelaysInSeconds = new[] { 2, 8, 30 })]` on `GabiJobRunner`
- **Dashboard**: `/hangfire` endpoint on API (behind `HangfireDashboardAuthFilter`)
- **Job executor pattern**: `IGabiJobRunner` dispatches to `IJobExecutor` implementations by `JobType`

**Executors registered**:
| Executor | JobType | Status |
|----------|---------|--------|
| `CatalogSeedJobExecutor` | `catalog_seed` | ✅ Real logic |
| `SourceSyncJobExecutor` | `source_sync` | 🟡 Basic |
| `SourceDiscoveryJobExecutor` | `source_discovery` | ✅ Real logic (uses `DiscoveryEngine`) |
| `FetchJobExecutor` | `fetch` | 🟠 Stub — marks status, no download |
| `IngestJobExecutor` | `ingest` | 🟠 Stub — marks status, no processing |

### 1.5 API Security

- **JWT Bearer Auth**: login at `/api/v1/auth/login`
- **Users**: `operator` / `op123` (read+write), `viewer` / `view123` (read-only)
- **RBAC policies**: `RequireViewer`, `RequireOperator`
- **Rate limiting**: 100 req/min read, 10 req/min write
- **Security headers**: HSTS, X-Content-Type-Options, CSP, etc.
- **CORS**: restricted to dashboard origins
- **Global exception handler**: no stack traces leaked

### 1.6 Test Coverage

| Test Project | Exists | Content |
|-------------|--------|---------|
| `Gabi.Api.Tests` | ✅ | 7 files |
| `Gabi.Discover.Tests` | ✅ | 10 files — includes `DiscoveryEngineTests` |
| `Gabi.Fetch.Tests` | ✅ | 7 files |
| `Gabi.Jobs.Tests` | ✅ | 8 files |
| `Gabi.Postgres.Tests` | ✅ | 8 files |
| `Gabi.Sync.Tests` | ✅ | 2 files |
| `zero-kelvin-test.sh` | ✅ | End-to-end Docker-based test script |

---

## 2. WHAT WE'VE DONE (Completed Phases)

### Phase 1 — Foundation ✅
- .NET 8 solution with 6 initial projects, clean architecture, layered dependencies
- 21 contract files (enums, records, DTOs)

### Phase 2 — Docker + Discovery ✅
- Docker Compose with Postgres, ES, Redis
- `DiscoveryEngine` with `StaticUrl` and `UrlPattern` strategies
- 37 URLs discovered across 3 sources (tcu_acordaos: 35, tcu_normas: 1, tcu_sumulas: 1)
- EF Core entities, migrations, repositories (bulk upsert, SKIP LOCKED)
- Background job queue (first custom, then migrated to Hangfire)

### Phase 3 — Dashboard + Security ✅
- Full dashboard API (stats, jobs, pipeline, health, safra, links)
- JWT auth + RBAC + rate limiting + security headers
- Frontend SPA with pipeline overview, sources table, job progress, link details
- Hangfire dashboard at `/hangfire`

### Phase 3.5 — Seed + Phase Orchestration ✅
- Async seed via `POST /api/v1/dashboard/seed` (Worker processes)
- Phase trigger: `POST /api/v1/dashboard/sources/{sourceId}/phases/{phase}`
- `seed_runs`, `discovery_runs`, `fetch_runs` tracking tables
- `fetch_items` table bridging discovery → fetch → documents

---

## 3. WHAT'S MISSING — Critical Gaps

### 🔴 3.1 NO OBSERVABILITY

| Gap | Detail |
|-----|--------|
| **Serilog only in API** | `Gabi.Api/Program.cs` has `UseSerilog()` + `CompactJsonFormatter`. **`Gabi.Worker` has zero Serilog** — only basic `ILogger` with console simple formatter. |
| **No structured logging in Worker** | Worker is the most critical process (runs all jobs). Uses `Microsoft.Extensions.Logging` with plain text console, no JSON, no correlation IDs. |
| **No log aggregation** | No Seq, no ELK, no centralized log sink. Logs only go to stdout. |
| **No Prometheus / metrics** | `docs/architecture/OBSERVABILITY.md` describes a plan for Prometheus metrics, but **zero implementation** exists. |
| **No OpenTelemetry tracing** | No distributed tracing. No span correlation between API → Hangfire → Worker. |
| **Hangfire dashboard** | Exists at `/hangfire` but only accessible locally with auth filter. No external monitoring integration. |

### 🔴 3.2 NO CI/CD

| Gap | Detail |
|-----|--------|
| **No `.github/workflows/`** | Directory doesn't exist. Zero GitHub Actions. |
| **No build pipeline** | No automated `dotnet build`, `dotnet test`, Docker build. |
| **No deployment automation** | `fly.toml` and `fly.api.toml` exist for Fly.io, but no automated deploy. |
| **No environment promotion** | No staging → production workflow. |

### 🔴 3.3 NO DEAD-LETTER QUEUE

| Gap | Detail |
|-----|--------|
| **Hangfire retry only** | After 3 retries (2s, 8s, 30s), jobs go to Hangfire "Failed" state. |
| **No DLQ table** | `roadmap.md` mentions "Dead Letter Queue ✅" but **no DLQ entity, table, or logic exists in code**. |
| **No failed job analysis** | No way to inspect, replay, or alert on permanently failed jobs. |
| **No poisoned message handling** | If a job crashes Hangfire, no circuit breaker protects the queue. |

### 🔴 3.4 FETCH IS A STUB

The `FetchJobExecutor` **does not download any content**. It:
1. Gets `fetch_items` with `status=pending/failed`
2. Marks them `status=completed`
3. Creates a `DocumentEntity` with `Title = item.Url` (the URL string, not actual content)
4. Sets `ProcessingStage = "fetch_completed"`

**What's needed**: HTTP client with streaming, CSV download, response caching, ETag/Last-Modified support.

### 🔴 3.5 INGEST IS A STUB

The `IngestJobExecutor` **does not process any content**. It:
1. Gets documents with `status=pending`
2. Marks them `status=completed`, `ProcessingStage=ingested`

**What's needed**: CSV parsing, content extraction, normalization, hashing (SHA-256), deduplication, chunking, embedding, Elasticsearch indexing.

### 🔴 3.6 DISCOVERY LOGIC GAPS

| Source Type | Expected Links | What Happens |
|-------------|---------------|--------------|
| `tcu_acordaos` (url_pattern) | 35 links (1992–2026) | ✅ Correct |
| `tcu_sumulas` / `tcu_normas` / other CSV (static_url) | 1 link each | ✅ Correct |
| `tcu_publicacoes` (web_crawl) | Multiple PDF links | 🔴 Returns **0 links** (`yield break`) |
| `tcu_notas_tecnicas_ti` (web_crawl) | Multiple PDF links | 🔴 Returns **0 links** (`yield break`) |
| `camara_leis_ordinarias` (api_pagination) | Paginated results | 🔴 Returns **0 links** (`yield break`) |

> **Important**: Running discovery for any `web_crawl` or `api_pagination` source succeeds silently (status "completed", `LinksTotal=0`) because the engine has a failsafe that treats 0 links as success. This masks the fact that these strategies aren't implemented.

---

## 4. WHAT SHOULD BE DONE — Prioritized Roadmap

### Priority 1: Production Readiness 🏗️

| # | Task | Effort | Impact |
|---|------|--------|--------|
| 1.1 | **Add Serilog to Worker** — same as API: `UseSerilog()`, structured JSON, correlation ID per job | 2h | 🔴 Critical |
| 1.2 | **Add CI/CD** — GitHub Actions: build → test → Docker build → push. Fly.io deploy on release tag | 4h | 🔴 Critical |
| 1.3 | **Dead-letter queue** — `dlq_entries` table, move failed jobs after max retries, API to list/replay | 4h | 🔴 Critical |
| 1.4 | **Health check endpoint for Worker** — expose readiness/liveness for Docker/Fly.io | 1h | 🟡 Important |

### Priority 2: Real Fetch Implementation 📥

| # | Task | Effort |
|---|------|--------|
| 2.1 | HTTP client with streaming (`HttpClient` + `Stream`) | 4h |
| 2.2 | ETag / Last-Modified change detection (skip if unchanged) | 2h |
| 2.3 | CSV streaming parser (pipe-delimited, handle 500MB+ files) | 6h |
| 2.4 | Wire real fetch into `FetchJobExecutor` | 2h |

### Priority 3: Real Ingest Implementation 🔄

| # | Task | Effort |
|---|------|--------|
| 3.1 | CSV row → document parser (use field mappings from `sources_v2.yaml`) | 6h |
| 3.2 | Content normalizer (strip_quotes, strip_html, etc.) | 4h |
| 3.3 | SHA-256 hashing + dedup (`ContentHasher`, `DeduplicationService`) | 4h |
| 3.4 | Elasticsearch bulk indexing | 4h |
| 3.5 | Chunking for embeddings (if TEI container is available) | 6h |

### Priority 4: Complete Discovery Strategies 🕷️

| # | Task | Effort |
|---|------|--------|
| 4.1 | `WebCrawlStrategy` — HTTP crawl + CSS selectors + pagination | 8h |
| 4.2 | `ApiPaginationStrategy` — REST API pagination for Câmara | 4h |
| 4.3 | PDF downloader for `tcu_publicacoes` / `tcu_notas_tecnicas_ti` | 6h |

### Priority 5: Observability Stack 📊

| # | Task | Effort |
|---|------|--------|
| 5.1 | Serilog sinks: Seq or Elasticsearch for centralized logs | 4h |
| 5.2 | Prometheus metrics (job throughput, latency, error rates) | 6h |
| 5.3 | OpenTelemetry tracing (API → Hangfire → Worker spans) | 6h |
| 5.4 | Grafana dashboards for monitoring | 4h |

---

## 5. KEY ARCHITECTURAL DETAILS

### 5.1 Data Flow

```
sources_v2.yaml
      │
      ▼ (Seed — CatalogSeedJobExecutor)
┌─────────────────┐
│ source_registry  │  — cached YAML config in PostgreSQL
└────────┬────────┘
         │
         ▼ (Discovery — SourceDiscoveryJobExecutor)
┌─────────────────────┐
│  discovered_links    │  — URLs found, with UrlHash (SHA256), statuses
│  discovery_runs      │  — audit trail per discovery execution
└────────┬────────────┘
         │
         ▼ (Auto-created by discovery)
┌─────────────────────┐
│  fetch_items         │  — 1:1 with discovered_links, tracks fetch attempts
│  fetch_runs          │  — audit trail per fetch execution
└────────┬────────────┘
         │
         ▼ (Fetch → creates documents)
┌─────────────────────┐
│  documents           │  — one per fetched item (currently shell records)
└─────────────────────┘
```

### 5.2 Hangfire Job Flow

```
API (enqueue)                        Worker (process)
─────────────                        ────────────────
POST /dashboard/seed        →  Hangfire Queue "seed"     →  CatalogSeedJobExecutor
POST /sources/{id}/refresh  →  Hangfire Queue "discovery" →  SourceDiscoveryJobExecutor
POST /sources/{id}/phases/fetch → Hangfire Queue "fetch"  →  FetchJobExecutor (stub)
POST /sources/{id}/phases/ingest → Hangfire Queue "ingest" → IngestJobExecutor (stub)
```

- API registers job in `job_registry` table → enqueues via `IBackgroundJobClient`
- Worker picks up → `GabiJobRunner.RunAsync()` → finds matching `IJobExecutor` → executes
- Progress updates written to `job_registry` (ProgressPercent, ProgressMessage)
- Frontend polls `/api/v1/jobs/{sourceId}/status` for live progress

### 5.3 Source Configuration (sources_v2.yaml)

- **13 sources total** (11 active, 2 inactive: `stf_decisoes`, `stj_acordaos`)
- **8 CSV sources** — pipe-delimited, some 500MB+ (tcu_normas is 587MB)
- **2 web crawl sources** — PDF downloads (not implemented)
- **1 API source** — Câmara dos Deputados REST API (not implemented)
- YAML defines: identity, discovery strategy, fetch protocol/format, parse field mappings, transform rules, pipeline schedule
- The YAML is very detailed but **parse/transform configs are not consumed by code yet**

### 5.4 Database (PostgreSQL via EF Core)

Key tables: `source_registry`, `discovered_links`, `fetch_items`, `documents`, `discovery_runs`, `fetch_runs`, `seed_runs`, `job_registry`, `audit_logs`

- Migrations auto-run in containers when `GABI_RUN_MIGRATIONS=true`
- Hangfire creates its own schema tables
- `UrlHash` on `discovered_links` uses SHA256 for dedup

### 5.5 Authentication

- Hard-coded users in `appsettings.json` (not a user store)
- JWT tokens with role claims
- No refresh tokens, no OAuth, no external identity provider

---

## 6. ANCHORAGE POINTS — DO NOT MISS

> [!CAUTION]
> **These are the critical invariants and gotchas that MUST be respected when modifying this codebase.**

### 6.1 Redis Port is 6380, NOT 6379
The compose maps `6380:6379` to avoid conflicts. All host-side references must use port **6380**. Inside Docker network, services use `redis:6379`.

### 6.2 Zero Kelvin Test is the Integration Gate
`tests/zero-kelvin-test.sh` destroys everything and rebuilds from scratch. Any change must pass this test. It validates: health, swagger, login, seed, discovery.

### 6.3 Discovery "Success" with 0 Links is Intentional
`SourceDiscoveryJobExecutor` treats `LinksTotal=0` as success (status="completed"). This is a failsafe for unimplemented strategies. **Do NOT change this** until WebCrawl/ApiPagination are implemented—it would break discovery for 3 sources.

### 6.4 Soft Delete Only, Never Physical Delete
Architecture invariant: `removed_from_source_at` field for documents that disappear from source. Never `DELETE FROM documents`.

### 6.5 SHA-256 Fingerprint Standard
All content hashing uses SHA-256 producing a 64-char hex string. Defined in contracts as `DocumentFingerprint`. UrlHash on `discovered_links` is also SHA256(url).

### 6.6 Sources YAML is the Source of Truth
`sources_v2.yaml` defines everything about sources. Seed loads it into PostgreSQL. The YAML parse/transform/pipeline sections are **designed for future consumption** — the field mapping structure (columns → document fields) is ready but not wired.

### 6.7 API and Worker Share the Same PostgreSQL
Both Hangfire (queue storage) and app data (sources, links, documents, runs) live in the same `gabi` database. Connection string is identical across API and Worker.

### 6.8 Worker Has No Serilog
`Gabi.Worker/Program.cs` uses `Host.CreateApplicationBuilder()` which only has `Microsoft.Extensions.Logging`. It does NOT call `UseSerilog()`. The API does. **This is the #1 observability gap**.

### 6.9 FetchJobExecutor Creates Documents Without Content
When fetch "completes", it creates `DocumentEntity` records where `Title = item.Url` and `ContentUrl = item.Url`. There is **no actual downloaded content**. Any downstream logic expecting `Content` to contain real text will fail.

### 6.10 Hangfire Auto-Retry vs. Polly Retry
Two retry mechanisms coexist:
- `GabiJobRunner`: `[AutomaticRetry(Attempts=3)]` — Hangfire-level retry
- `SourceDiscoveryJobExecutor`: Polly `ResiliencePipeline` with exponential backoff — application-level retry
This means a failing discovery job can be retried up to **3 × 4 = 12 times** (3 Hangfire + 3 Polly retries per Hangfire attempt + 1 initial). **Consolidate these.**

### 6.11 API Uses StubGabiJobRunner
In the API process, `IGabiJobRunner` is registered as `StubGabiJobRunner` (only serializes the call for Hangfire). The real `GabiJobRunner` lives in `Gabi.Worker`. Don't try to execute jobs inside the API process.

---

## 7. EXPECTED DISCOVERY RESULTS BY SOURCE

| Source ID | Strategy | Expected Links | Notes |
|-----------|----------|---------------|-------|
| `tcu_acordaos` | `url_pattern` | **35** | 1992–2026 (year = "current" resolves to `DateTime.UtcNow.Year`) |
| `tcu_normas` | `static_url` | **1** | Single CSV (587MB) |
| `tcu_sumulas` | `static_url` | **1** | Single CSV |
| `tcu_jurisprudencia_selecionada` | `static_url` | **1** | Single CSV |
| `tcu_resposta_consulta` | `static_url` | **1** | Single CSV |
| `tcu_informativo_lc` | `static_url` | **1** | Single CSV |
| `tcu_boletim_jurisprudencia` | `static_url` | **1** | Single CSV |
| `tcu_boletim_pessoal` | `static_url` | **1** | Single CSV |
| `tcu_publicacoes` | `web_crawl` | **0** ⚠️ | Strategy not implemented |
| `tcu_notas_tecnicas_ti` | `web_crawl` | **0** ⚠️ | Strategy not implemented |
| `camara_leis_ordinarias` | `api_pagination` | **0** ⚠️ | Strategy not implemented |
| `stf_decisoes` | — | ⏸️ | Inactive |
| `stj_acordaos` | — | ⏸️ | Inactive |
| **TOTAL (active)** | | **42 links** | 35 + 7×1 + 3×0 |

---

## 8. FILE MAP — Key Files for New Developers

| File | Purpose |
|------|---------|
| `src/Gabi.Worker/Program.cs` | Worker entry point — Hangfire setup, DI, queue config |
| `src/Gabi.Worker/Jobs/GabiJobRunner.cs` | Central job dispatcher — routes `jobType` to `IJobExecutor` |
| `src/Gabi.Worker/Jobs/SourceDiscoveryJobExecutor.cs` | Discovery execution — the most complete executor |
| `src/Gabi.Worker/Jobs/FetchJobExecutor.cs` | **STUB** — needs real HTTP download |
| `src/Gabi.Worker/Jobs/IngestJobExecutor.cs` | **STUB** — needs real content processing |
| `src/Gabi.Api/Program.cs` | API entry — all endpoints, Serilog, middleware pipeline |
| `src/Gabi.Discover/DiscoveryEngine.cs` | Strategy dispatch — switch on `DiscoveryMode` |
| `src/Gabi.Postgres/GabiDbContext.cs` | EF Core context — all entity configurations |
| `sources_v2.yaml` | Source definitions (13 sources, field mappings, pipeline config) |
| `docker-compose.yml` | Infrastructure + optional app profiles |
| `tests/zero-kelvin-test.sh` | Integration gate — destroy+rebuild+verify |
| `docs/architecture/INVARIANTS.md` | 8 architectural invariants |
| `PIPELINE_COMPLETO_ROADMAP.md` | Detailed pipeline design (proposed, not implemented) |

---

## 9. QUICK REFERENCE — Common Operations

```bash
# Start infra
./scripts/dev infra up

# Run API locally
dotnet run --project src/Gabi.Api --urls "http://localhost:5100"

# Run Worker locally (needs infra running)
dotnet run --project src/Gabi.Worker

# Full Docker (API + Worker + Infra)
docker compose --profile api --profile worker up -d

# Get auth token
TOKEN=$(curl -s -X POST http://localhost:5100/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"operator","password":"op123"}' | jq -r .token)

# Seed sources (must run first)
curl -X POST http://localhost:5100/api/v1/dashboard/seed \
  -H "Authorization: Bearer $TOKEN"

# Run discovery for a source
curl -X POST "http://localhost:5100/api/v1/dashboard/sources/tcu_sumulas/phases/discovery" \
  -H "Authorization: Bearer $TOKEN"

# Check job status
curl http://localhost:5100/api/v1/jobs/tcu_sumulas/status \
  -H "Authorization: Bearer $TOKEN"

# Run Zero Kelvin test
./tests/zero-kelvin-test.sh
```

---

*This document was generated by exhaustive code analysis on 2026-02-15. It reflects the **actual code state**, not aspirational documentation.*
