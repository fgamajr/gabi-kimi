# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**GABI** is a backend legal document ingestion and search system for the Brazilian Federal Court of Auditors (TCU). It processes legal documents through a 4-phase pipeline: Seed → Discovery → Fetch → Ingest. The system is **backend-only** (frontend was removed). Tech stack: .NET 8, PostgreSQL 15, Elasticsearch 8, Redis 7, Hangfire, Docker Compose.

## Commands

All commands are run from the **repository root** (never from inside a project subfolder).

### Infrastructure

```bash
./scripts/dev infra up        # Start Postgres (5433), Elasticsearch (9200), Redis (6380), TEI (8080)
./scripts/dev infra down      # Stop containers, keep volumes
./scripts/dev infra destroy   # Destroy everything and reset
```

### Running the API

```bash
# Option A: Local host (infra must be up)
dotnet run --project src/Gabi.Api --urls "http://localhost:5100"

# Option B: Full Docker (infra + API + Worker)
docker compose --profile api --profile worker up -d

# Stop API running on host
pkill -f "dotnet.*Gabi.Api"
```

### Database Migrations

```bash
./scripts/dev db apply        # Run EF Core migrations (or set GABI_RUN_MIGRATIONS=true for auto-run)
./scripts/dev db status       # Check migration state
./scripts/dev db create NAME  # Create a new migration
```

### Running Tests

```bash
# All tests
dotnet test GabiSync.sln

# Single test by name
dotnet test --filter "FullyQualifiedName~HealthEndpoint_ReturnsSuccess"

# Single test with detailed output (debugging)
dotnet test --filter "FullyQualifiedName~JobStateMachineTests" --logger "console;verbosity=detailed"

# By project
dotnet test tests/Gabi.Api.Tests
dotnet test tests/Gabi.Postgres.Tests
dotnet test tests/Gabi.Architecture.Tests   # mandatory after layer/dep changes

# Build solution
dotnet build GabiSync.sln

# Full pipeline E2E validation (Docker-only, recommended)
./tests/zero-kelvin-test.sh docker-only

# Targeted pipeline test (single source/phase)
./tests/zero-kelvin-test.sh docker-only \
  --source tcu_acordaos \
  --phase full \
  --max-docs 20000 \
  --monitor-memory \
  --report-json /tmp/gabi-zk.json
```

**Validation checklist after code changes:**
1. `dotnet build GabiSync.sln`
2. `dotnet test tests/Gabi.Architecture.Tests` ← if you touched project dependencies or layers
3. `dotnet test tests/<affected project>`
4. `./tests/zero-kelvin-test.sh docker-only` ← for pipeline-impacting changes

**Test conventions:** xUnit; naming `MethodName_Scenario_ExpectedResult`; shared context via `IClassFixture<T>`; API integration tests use `CustomWebApplicationFactory`.

**Migration rules:** additive only — never edit existing migrations; use `CONCURRENTLY` for new indexes.

### Direct API Calls (requires `./scripts/dev infra up` + API running)

```bash
TOKEN=$(curl -s -X POST http://localhost:5100/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"operator","password":"op123"}' | jq -r .token)

curl -s -X POST http://localhost:5100/api/v1/dashboard/seed \
  -H "Authorization: Bearer $TOKEN"

curl -s -X POST "http://localhost:5100/api/v1/dashboard/sources/tcu_sumulas/phases/discovery" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json"
```

## Architecture

### Layer Model (Strict — enforced by architecture tests)

| Layer | Projects | Dependency Rule |
|-------|----------|-----------------|
| 0–1 | `Gabi.Contracts` | **Zero** references to any other `Gabi.*` project |
| 2–3 | `Gabi.Postgres` | Infrastructure: EF Core, repositories |
| 4 | `Gabi.Discover`, `Gabi.Fetch`, `Gabi.Ingest`, `Gabi.Sync`, `Gabi.Jobs` | Domain logic — **must not** reference `Gabi.Postgres` or EF Core |
| 5 | `Gabi.Api`, `Gabi.Worker` | Orchestration: DI registration, hosting — wires Layer 4 + Postgres |

**Dependency direction:** higher layers depend on lower only. Layer 4 depends only on Contracts; Layer 5 wires Layer 4 + Postgres.

Practical rules:
- New **interface or DTO** → `Gabi.Contracts`
- New **repository** → interface in Contracts, implementation in `Gabi.Postgres`
- New **job executor** → class in `Gabi.Worker`, contract in Contracts if needed; DI registration in Worker `Program.cs`
- Domain code needing DB → define `IRepository` in Contracts, implement in Postgres, inject in Worker/Api

After any change to project references or new projects, run:
```bash
dotnet test tests/Gabi.Architecture.Tests
```

### Pipeline Flow

1. **Seed** — YAML (`sources_v2.yaml`) → PostgreSQL via `catalog_seed` Hangfire job
2. **Discovery** — URL/document discovery per source strategy (`url_pattern`, `static_url`, `dynamic`)
3. **Fetch** — HTTP download with native capping (`max_docs_per_source`), graceful stop at `capped` status
4. **Ingest** — Parse → normalize → SHA-256 fingerprint (dedup) → chunk → embed (384-dim via TEI) → index (Postgres + Elasticsearch)

**API and Worker are independent services** — both connect to the same PostgreSQL and Redis. Scale them separately. Hangfire uses PostgreSQL as its backend.

### Key Source Projects

| Project | Purpose |
|---|---|
| `Gabi.Api` | REST API entry point, job enqueueing, JWT roles (viewer/operator/admin) |
| `Gabi.Worker` | Hangfire server executing catalog_seed/discovery/fetch/ingest jobs |
| `Gabi.Sync` | Orchestration engine, retry policy, DLQ filter |
| `Gabi.Postgres` | EF Core DbContext, migrations, all repositories |
| `Gabi.Discover` | URL discovery strategies, change detection cache |
| `Gabi.Fetch` | HTTP fetch with retry, CSV/document streaming, memory telemetry |
| `Gabi.Ingest` | Parse, normalize, fingerprint, chunk, embed, index |
| `Gabi.Contracts` | Shared interfaces — no external dependencies; do not add any |
| `Gabi.Jobs` | Hangfire job executor definitions |

### Storage Model

- **PostgreSQL** is the canonical source of truth (`documents.Content` holds normalized text, `documents.Metadata` holds JSON metadata)
- **Elasticsearch** is a derived index — Postgres always wins on conflict
- Raw binaries (PDF/HTML/video) are **not** persisted by default
- S3 is optional (audit/replay only)

### Infrastructure Ports

| Service | Host Port | Note |
|---|---|---|
| PostgreSQL | **5433** | Mapped 5433→5432 inside container |
| Elasticsearch | 9200 | |
| Redis | **6380** | Mapped 6380→6379 to avoid conflict with system Redis on 6379 |
| TEI (embeddings) | 8080 | paraphrase-multilingual-MiniLM-L12-v2, 384 dimensions |
| Gabi.Api | 5100 | Profile: `api` |

## Pipeline Coding Rules

These apply whenever implementing or modifying any pipeline stage (Discovery, Fetch, Ingest, Embed, Index) or job executor.

### Memory — 300 MB effective budget

- **Never** load unbounded collections into memory. No `ToListAsync()` on unbounded queries.
- Use **streaming**: `IAsyncEnumerable<T>`, `await foreach` with `.WithCancellation(ct)`.
- Batch only when the downstream API requires it (e.g. TEI embed batch size cap).

### CancellationToken

- **Always** propagate `CancellationToken ct = default` through async methods.
- Use `.WithCancellation(ct)` on every `IAsyncEnumerable` consumption loop.

### Backpressure and pause

- Job executors must check backpressure (max pending jobs) and source state (paused/stopped).
- When over limit or paused: yield and schedule a delayed retry via `IJobQueueRepository.ScheduleAsync`. Never spin or block.

### Job executor pattern

- Each stage has a dedicated executor class (e.g. `SourceDiscoveryJobExecutor`, `FetchJobExecutor`, `IngestJobExecutor`).
- Executors receive a job payload, report progress via `IProgress<JobProgress>`, return `JobResult` with status and metadata.
- Register in `Gabi.Worker` `Program.cs` only.

### Quick checklist for pipeline code

- [ ] No unbounded `.ToListAsync()` — streaming where data can grow
- [ ] `CancellationToken` passed and used in all async loops
- [ ] Executor respects pause/backpressure and uses `ScheduleAsync` when yielding
- [ ] Config values (URLs, caps, backpressure thresholds) come from YAML/appsettings, not hardcoded

## Key Invariants

- `sources_v2.yaml` is the **only** definition of sources — no URLs or source logic hardcoded in C# code
- Pipeline execution must be idempotent: running twice without external change must not create duplicate documents (SHA-256 fingerprint ensures this)
- Embedding vectors are always **384 dimensions** — do not change this
- PostgreSQL is always authoritative; Elasticsearch is a derived index
- DLQ recovery is **manual** via `POST /api/v1/dlq/{id}/replay` — there is no automatic infinite requeue
- Retry policy has a **single source of truth**: `Hangfire:RetryPolicy` in `appsettings`

## Configuration

Copy `.env.example` to `.env` and set:
- `ConnectionStrings__Default` — PostgreSQL connection string
- `GABI_SOURCES_PATH` — path to `sources_v2.yaml` (default `/app/sources_v2.yaml` in Docker)
- `GABI_EMBEDDINGS_URL` — TEI endpoint (required in production)
- `GABI_RUN_MIGRATIONS=true` — auto-run EF migrations on API startup (set in docker-compose)
- `JWT_KEY` — JWT signing key
- Optional: `YOUTUBE_API_KEY`, `YOUTUBE_CHANNEL_ID`, `GABI_INLABS_COOKIE`

Worker telemetry env vars:
- `GABI_FETCH_MAX_FIELD_CHARS` (default `262144`) — CSV field size limit before truncation
- `GABI_FETCH_TELEMETRY_EVERY_ROWS` (default `1000`) — telemetry log interval

## Governance (`.antigravity/`)

The `.antigravity/` directory contains multi-agent swarm coordination documents (contracts, file ownership, gates). These are **planning/documentation artifacts** — the actual implementation is in C# (not Python). The invariants and pipeline contracts defined there represent the intended design and should guide new development.
