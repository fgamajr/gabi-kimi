# GEMINI.md - GABI (Sistema de Ingestão Jurídica TCU)

*Note: This file provides a comprehensive overview for AI agents. The canonical source for detailed agent instructions is `AGENTS.md`.*

## Project Overview

GABI (Sistema de Ingestão e Busca Jurídica TCU) is a backend legal document ingestion and search system for the Brazilian Federal Court of Auditors (TCU). It processes legal documents through a 4-phase pipeline: Seed → Discovery → Fetch → Ingest. The system is **backend-only** (frontend was removed). 

### Main Technologies
- **Backend:** .NET 8 (C# 12.0), Minimal API
- **Database:** PostgreSQL 15 (with EF Core, uuid-ossp, pg_trgm)
- **Search Engine:** Elasticsearch 8
- **Cache & Queues:** Redis 7, Hangfire
- **Configuration:** YamlDotNet for parsing `sources_v2.yaml`
- **Infrastructure:** Docker, Docker Compose, Fly.io

### Architecture
The project strictly follows a layered architecture with unbreakable invariants:
- **Layer 5 (Orchestration):** `Gabi.Worker`, `Gabi.Api`
- **Layer 4 (Domain Logic):** `Gabi.Discover`, `Gabi.Fetch`, `Gabi.Ingest`, `Gabi.Sync`, `Gabi.Jobs` (NEVER reference `Gabi.Postgres` or `EF Core`)
- **Layer 2-3 (Infrastructure):** `Gabi.Postgres`
- **Layer 0-1 (Contracts):** `Gabi.Contracts` (ZERO dependencies)

**Invariants:**
- No hardcoded URLs in code; all must be defined in `sources_v2.yaml`.
- Fingerprints are always SHA-256.
- PostgreSQL is the source of truth; Elasticsearch and vectors are derived.
- Execution must be idempotent (same input → same output).
- Soft deletes only (no physical deletions).
- Strict memory cap of 300MB for background processing (use streaming instead of buffering).

## Building and Running

Commands should be executed from the **repository root**.

### Infrastructure Setup
```bash
./scripts/dev infra up        # Start Postgres (5433), Elasticsearch (9200), Redis (6380), TEI (8080)
./scripts/dev infra down      # Stop containers (keeps volumes)
./scripts/dev infra destroy   # Destroy everything and reset
```

### Running the Application
```bash
# Option 1: Docker Compose (API + Worker) - Recommended for CI/Stress tests
docker compose --profile api --profile worker up -d

# Option 2: Local .NET API (with Docker Infra running)
dotnet run --project src/Gabi.Api --urls "http://localhost:5100"

# Stop API running on host
pkill -f "dotnet.*Gabi.Api"
```

### Building and Testing
```bash
# Build solution
dotnet build GabiSync.sln

# Run all tests
dotnet test GabiSync.sln

# Run specific tests by name or project
dotnet test --filter "FullyQualifiedName~HealthEndpoint_ReturnsSuccess"
dotnet test tests/Gabi.Api.Tests

# Architecture tests (MUST pass before commit, especially after layer changes)
dotnet test tests/Gabi.Architecture.Tests

# Full pipeline E2E validation (Docker-only, recommended)
./tests/zero-kelvin-test.sh docker-only
```

### Database Migrations
```bash
./scripts/dev db apply        # Run EF Core migrations
./scripts/dev db status       # Check migration state
./scripts/dev db create NAME  # Create a new migration
```

### Pipeline Execution (API Endpoints)
The system uses `operator`/`op123` for write actions and `viewer`/`view123` for read actions.
- **Login:** `POST /api/v1/auth/login`
- **Seed (Load sources):** `POST /api/v1/dashboard/seed`
- **Trigger Phase (Discovery/Fetch/Ingest):** `POST /api/v1/dashboard/sources/{sourceId}/phases/{phase}`

## Development Conventions

### Code Style
- **Target:** .NET 8.0, C# 12.0 (`ImplicitUsings` and `Nullable` enabled).
- **Naming Conventions:** 
  - Interfaces: `I{Name}` (e.g., `IDiscoveryEngine`)
  - Classes, Records, Methods: `PascalCase`
  - Parameters: `camelCase`
  - Private fields: `_camelCase`
- **Types:** Prefer `record` for DTOs and immutable contracts with `init` and `required` properties.
- **Namespaces:** Use file-scoped namespaces.
- **Imports:** Keep `DbContext` clean and configure entities using `IEntityTypeConfiguration<T>`.

### Async Patterns & Error Handling
- **ALWAYS** propagate `CancellationToken ct = default` through async methods.
- **NEVER** load unbounded collections into memory (300MB limit). Use streaming: `IAsyncEnumerable<T>`, `await foreach` with `.WithCancellation(ct)`.
- **Errors:** Categorize using `ErrorClassifier` (`Transient`, `Throttled`, `Permanent`, `Bug`) and throw `InvalidOperationException` for invalid state transitions.
- **Backpressure:** Job executors must check backpressure and source state (paused/stopped), and yield using `IJobQueueRepository.ScheduleAsync` when necessary.

### Testing Practices
- **Framework:** xUnit.
- **Shared Context:** Use `IClassFixture<T>`.
- **Method Naming:** `MethodName_Scenario_ExpectedResult`.
- Chaos tests and resilience validation (`./tests/chaos-test.sh`) are highly prioritized.

### Database & Migrations
- **ONLY additive migrations**; never modify existing ones. Create indices with `CONCURRENTLY`.

---

## v10 Hardening Plan

### Background

Code-quality audit run on 2026-02-26 identified 9 findings (2 critical, 3 high, 3 medium, 1 low). All 9 were verified as TRUE against the actual codebase. This section records each finding, the exact affected files, the remediation steps, and the acceptance criteria so that any AI agent can execute the fixes independently.

**Health score at time of audit:** ~62/100 (architectural violations and sync hazards are the main deductions).

Scope: source code only. No infrastructure, no `sources_v2.yaml` schema, no test framework changes unless explicitly noted.

---

### R-01: Layer Violations (Critical)

**Problem:** `Gabi.Sync` (Layer 4) and `Gabi.Jobs` (Layer 4) directly reference `Gabi.Postgres` (Layer 2–3) in their `.csproj` files, violating the invariant that domain projects must depend only on `Gabi.Contracts`. `Phase0Orchestrator` also imports concrete Postgres namespaces.

**Affected files:**
- `src/Gabi.Sync/Gabi.Sync.csproj:5` — `<ProjectReference Include="..\Gabi.Postgres\..." />`
- `src/Gabi.Jobs/Gabi.Jobs.csproj:12` — `<ProjectReference Include="..\Gabi.Postgres\..." />`
- `src/Gabi.Sync/Phase0/Phase0Orchestrator.cs:8-9` — `using Gabi.Postgres.Entities` / `using Gabi.Postgres.Repositories`

**Remediation:**
1. For every repository interface used in `Phase0Orchestrator`, confirm it exists in `Gabi.Contracts` (e.g. `IDiscoveredLinkRepository`). Add any missing interfaces to `Gabi.Contracts`.
2. Replace all concrete Postgres type usages in `Phase0Orchestrator` with the Contracts interfaces.
3. Remove the `<ProjectReference>` to `Gabi.Postgres` from `Gabi.Sync.csproj` and `Gabi.Jobs.csproj`.
4. Re-register the concrete implementations in `Gabi.Worker/Program.cs` (Layer 5) DI if not already done.

**Acceptance criteria:**
```bash
dotnet test tests/Gabi.Architecture.Tests   # all 3 tests must pass
dotnet build GabiSync.sln                   # zero errors
```

---

### R-02: Sync-over-Async in DlqFilter (Critical)

**Problem:** `DlqFilter.OnStateElection` is synchronous (Hangfire API constraint), but internally calls `MoveToDlqAsync` and blocks with `.GetAwaiter().GetResult()` at line 79. Under load this risks thread-pool starvation.

**Affected file:** `src/Gabi.Worker/Jobs/DlqFilter.cs:79`

**Remediation — Option A (preferred):** Convert `MoveToDlqAsync` to a synchronous method (`MoveToDlq`), replacing `SaveChangesAsync` with `SaveChanges`. The operation is a single, bounded DB write triggered only on job failure — synchronous EF is acceptable here.

**Remediation — Option B (mitigation):** If changing EF calls is judged risky, add an explicit comment documenting the constraint and the deliberate `.GetAwaiter().GetResult()` decision. Hangfire server has its own dedicated thread pool and this is a one-time-per-failure write.

The plan recommends Option A. Option B is acceptable only with documentation.

**Acceptance criteria:**
```bash
dotnet test tests/Gabi.Architecture.Tests
grep -rn 'GetAwaiter().GetResult()' src/   # zero matches after Option A
```

---

### R-03: Fire-and-Forget Constructor Async (High)

**Problem:** `PostgreSqlSourceCatalogService` fires `Task.Run(async () => await InitializeAsync())` inside its constructor (line 34) with no error tracking, no cancellation, and no startup gate. If YAML loading fails silently, the API serves traffic with no sources loaded.

**Affected file:** `src/Gabi.Api/Services/PostgreSqlSourceCatalogService.cs:34`

**Remediation:**
1. Remove the `Task.Run` from the constructor entirely.
2. Implement `IHostedService` on `PostgreSqlSourceCatalogService` (or create a thin `SourceCatalogStartupService : IHostedService` wrapper). Call `InitializeAsync` in `StartAsync`.
3. Register the hosted service in `Program.cs` so ASP.NET Core runs it during startup. Exceptions propagate and prevent the app from starting — this is the desired behavior.
4. Alternatively, implement the `IAsyncInitializable` pattern with a dedicated startup service if the project already uses one.

**Acceptance criteria:** Rename `sources_v2.yaml` to an invalid path and confirm the API process exits with a clear error on startup rather than starting silently.

---

### R-04: Hardcoded Status Strings (High)

**Problem:** Multiple files use raw string literals (`"idle"`, `"paused"`, `"stopped"`, `"running"`, `"failed"`) instead of `StatusVocabulary` constants, making the state machine brittle and refactoring dangerous.

**Affected files:**
- `src/Gabi.Postgres/GabiDbContextPipelineStateExtensions.cs:27` — `"paused"` and `"stopped"` literals
- `src/Gabi.Worker/Jobs/GabiJobRunner.cs:110` — `"failed"` and `"idle"` literals
- `src/Gabi.Worker/Jobs/GabiJobRunner.cs:255` — `"paused"` and `"stopped"` literals
- `src/Gabi.Api/Services/DashboardService.cs:755,789,838,844` — `"paused"`, `"running"`, `"idle"` literals

**Remediation:**
1. Locate `StatusVocabulary` in `Gabi.Contracts` (or create it there if absent) with `public static class StatusVocabulary` containing `public const string Idle = "idle"`, `Paused`, `Stopped`, `Running`, `Failed`.
2. Replace every raw string literal with the corresponding `StatusVocabulary.*` constant across all affected files.
3. Run a repo-wide search to catch any remaining instances.

**Acceptance criteria:**
```bash
grep -r '"idle"\|"paused"\|"stopped"\|"running"\|"failed"' src/ \
  --include="*.cs" | grep -v StatusVocabulary.cs
# Must return zero matches
```

---

### R-05: Stop/Idle State Semantic Mismatch (High)

**Problem:** `DashboardService.StopSourceAsync` (lines 838, 844) writes `"idle"` to `source_pipeline_states.state` when an operator stops a source. But `IsSourcePausedOrStoppedAsync` (line 27 in `GabiDbContextPipelineStateExtensions.cs`) only tests for `"paused"` and `"stopped"`. A stopped source is therefore indistinguishable from an idle source at the pipeline-check level, so new jobs are not blocked after a stop.

**Affected files:**
- `src/Gabi.Api/Services/DashboardService.cs:838,844`
- `src/Gabi.Postgres/GabiDbContextPipelineStateExtensions.cs:27`

**State machine (document and implement):**

| State | Meaning |
|-------|---------|
| `idle` | Pipeline not running; no operator action |
| `running` | Actively executing a phase |
| `paused` | Operator paused; can resume |
| `stopped` | Operator explicitly stopped; requires explicit restart |
| `failed` | Terminal failure; requires manual intervention |

**Remediation:**
1. Change `StopSourceAsync` to write `StatusVocabulary.Stopped` instead of `StatusVocabulary.Idle`.
2. Ensure `IsSourcePausedOrStoppedAsync` covers both `"paused"` and `"stopped"` (it already should once the write is corrected).
3. Fix after R-04 so both changes use constants.

**Acceptance criteria:** After calling `POST /api/v1/dashboard/sources/{id}/stop`, verify `source_pipeline_states.state = 'stopped'` in Postgres and that subsequent job enqueue is blocked.

---

### R-06: Hardcoded Fallback URLs in Discovery Adapter (Medium)

**Problem:** `ApiPaginationDiscoveryAdapter.cs` contains hardcoded production endpoint URL strings as code-level defaults (lines 494, 535, 1076, 1090). The invariant "no URLs hardcoded in code" is violated.

**Affected file:** `src/Gabi.Discover/ApiPaginationDiscoveryAdapter.cs:494,535,1076,1090`

**Remediation:**
1. Remove all default URL strings from the C# file.
2. Make `endpoint_template` a required field for sources using the `api_pagination` strategy.
3. Throw `ArgumentException("endpoint_template is required for api_pagination strategy")` when `endpoint_template` is absent, rather than falling back to a hardcoded URL.
4. Update `sources_v2.yaml` to explicitly declare `endpoint_template` for every `api_pagination` source (they likely already have it; verify).

**Acceptance criteria:** Remove `endpoint_template` from one source in `sources_v2.yaml`, trigger discovery, confirm an `ArgumentException` with a clear message is raised and the job fails gracefully (not silently).

---

### R-07: Service Locator Anti-Pattern in DashboardService (Medium)

**Problem:** `DashboardService` injects `IServiceProvider` and calls `CreateScope()` 19+ times to resolve `GabiDbContext` and repositories. This hides dependencies, breaks testability, and is a classic Service Locator anti-pattern.

**Root cause:** `DashboardService` is likely registered as Singleton (or outlives request scope), forcing manual scope creation to access Scoped services like `GabiDbContext`.

**Affected file:** `src/Gabi.Api/Services/DashboardService.cs` — constructor line 94 and ~19 `CreateScope` call sites.

**Remediation — Short-term:** Extract a private helper method `CreateOperationScope()` that returns a disposable tuple `(GabiDbContext db, IRepo repo)` to reduce the repetition and make intent explicit. Add an XML comment explaining the pattern.

**Remediation — Long-term (aligned with R-08):** Decompose `DashboardService` into per-domain Scoped services (`SeedService`, `DiscoveryService`, `PipelineStateService`, `SystemHealthService`). Each receives its dependencies via constructor injection. No `IServiceProvider` needed.

**Acceptance criteria:**
```bash
dotnet test tests/Gabi.Api.Tests   # all tests pass
# No _serviceProvider.CreateScope() in DashboardService (after long-term fix)
```

---

### R-08: God Object Decomposition (Medium)

**Problem:** Three files far exceed maintainable size, concentrating too many responsibilities:

| File | Lines | Responsibility bloat |
|------|-------|---------------------|
| `src/Gabi.Api/Services/DashboardService.cs` | 1297 | Seed, discovery, fetch, ingest, pipeline state, health, admin |
| `src/Gabi.Worker/Jobs/FetchJobExecutor.cs` | 2246 | HTTP fetch, CSV parsing, PDF extraction, HTML extraction, field mapping, dedup, chunking |
| `src/Gabi.Api/Program.cs` | 700 | All DI, middleware, endpoints, Hangfire, telemetry |

**Remediation — DashboardService:**
Split into: `SeedService`, `DiscoveryService`, `FetchDashboardService`, `PipelineStateService`, `SystemHealthService`. Retain a thin `DashboardService` façade only if callers depend on it.

**Remediation — FetchJobExecutor:**
Extract inner parsers into separate files under `src/Gabi.Worker/Jobs/Fetch/`:
- `CsvFetchParser.cs`
- `PdfFetchParser.cs`
- `HtmlFetchParser.cs`

`FetchJobExecutor` becomes an orchestrator that delegates to these parsers.

**Remediation — Program.cs:**
Add extension methods in `src/Gabi.Api/Configuration/`:
- `ServiceCollectionExtensions.AddPipelineServices()`
- `ServiceCollectionExtensions.AddHangfireServices()`
- `ServiceCollectionExtensions.AddObservabilityServices()`

**Acceptance criteria:** Each extracted class < 400 lines. `dotnet build GabiSync.sln` clean. All test suites pass.

---

### R-09: Missing Architecture Document (Low)

**Problem:** `CLAUDE.md` describes the layer model but `docs/architecture/LAYERED_ARCHITECTURE.md` does not exist. Architecture tests are the only enforcement mechanism; there is no prose documentation for onboarding.

**Remediation:** Create `docs/architecture/LAYERED_ARCHITECTURE.md` containing:
- Layer diagram with project names and allowed dependency directions
- Status state machine diagram: `idle → running → paused / stopped / failed → idle`
- Pipeline flow: Seed → Discovery → Fetch → Ingest → Embed → Index
- Key invariants as a checklist (mirrors the invariants in `CLAUDE.md`)

**Acceptance criteria:** File exists at `docs/architecture/LAYERED_ARCHITECTURE.md` and is linked from `CLAUDE.md` and this document.

---

### Implementation Order

Execute findings in this sequence to minimize risk and maximize early value:

1. **R-04 + R-05** — Status string constants and stop/idle mismatch. Low-risk string replacement with high blast-radius benefit if left to diverge further. Fix together since they share the same files.
2. **R-02** — DlqFilter sync-over-async. Isolated, well-bounded change. Easy to verify.
3. **R-03** — Fire-and-Forget constructor. Changes startup behavior; test startup failure path explicitly.
4. **R-01** — Layer violations. Requires moving interfaces and updating DI wiring. Run architecture tests after every individual file change.
5. **R-06** — Hardcoded fallback URLs. Requires coordinated change in both C# code and `sources_v2.yaml`.
6. **R-07** — Service Locator. Medium risk; extract incrementally using the short-term helper first.
7. **R-08** — God objects. Highest risk; extract one class at a time, run tests after each extraction.
8. **R-09** — Documentation. Can be done at any time; no code risk.

---

### Verification Checklist (post all fixes)

Run these commands after completing all remediations:

```bash
dotnet build GabiSync.sln                              # zero errors

dotnet test tests/Gabi.Architecture.Tests              # 3/3 pass
dotnet test tests/Gabi.Api.Tests                       # all pass
dotnet test GabiSync.sln                               # all pass

# Zero status string literals outside StatusVocabulary.cs
grep -r '"idle"\|"paused"\|"stopped"\|"running"\|"failed"' src/ \
  --include="*.cs" | grep -v StatusVocabulary.cs

# Zero blocking async calls
grep -rn 'GetAwaiter().GetResult()' src/

# Review any remaining Task.Run — each must have a documented justification
grep -rn 'Task\.Run' src/
```
