# GEMINI.md - GABI (Sistema de Ingestão Jurídica TCU)

*Note: This file provides a comprehensive overview for AI agents. The canonical source for detailed agent instructions is `AGENTS.md`.*

## Project Overview

GABI (Sistema de Ingestão e Busca Jurídica TCU) is a system for ingesting, processing, and searching legal data from the Tribunal de Contas da União (TCU). It is a backend-focused system built with a layered architecture in .NET 8, utilizing a robust pipeline (Seed → Discovery → Fetch → Ingest) to process data asynchronously from various sources.

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
- No hardcoded URLs; all must be defined in `sources_v2.yaml`.
- Fingerprints are always SHA-256.
- PostgreSQL is the source of truth; Elasticsearch and vectors are derived.
- Execution must be idempotent (same input → same output).
- Soft deletes only (no physical deletions).
- Strict memory cap of 300MB for background processing.

## Building and Running

Commands should be executed from the **repository root**.

### Infrastructure Setup
```bash
./scripts/dev infra up      # Starts Postgres (5433), Elasticsearch (9200), Redis (6380)
./scripts/dev infra down    # Stops containers (keeps volumes)
```

### Running the Application
```bash
# Option 1: Docker Compose (API + Worker) - Recommended for CI/Stress tests
docker compose --profile api --profile worker up -d

# Option 2: Local .NET API (with Docker Infra)
dotnet run --project src/Gabi.Api --urls "http://localhost:5100"

# Option 3: Unified flow (Infra + App in foreground)
./scripts/dev app up
```

### Building and Testing
```bash
# Build
dotnet build GabiSync.sln

# Run all tests
dotnet test GabiSync.sln

# Run specific tests
dotnet test --filter "FullyQualifiedName~HealthEndpoint_ReturnsSuccess"
dotnet test tests/Gabi.Architecture.Tests  # MUST pass before commit

# Apply database migrations
./scripts/dev db apply
```

### Pipeline Execution (API Endpoints)
The system uses `operator`/`op123` for write actions and `viewer`/`view123` for read actions.
- **Seed (Load sources):** `POST /api/v1/dashboard/seed`
- **Trigger Phase (Discovery/Fetch/Ingest):** `POST /api/v1/dashboard/sources/{sourceId}/phases/{phase}`
- **Zero Kelvin Test:** `./tests/zero-kelvin-test.sh docker-only` (validates infrastructure and pipeline end-to-end)

## Development Conventions

### Code Style
- **Target:** .NET 8.0, C# 12.0 (`ImplicitUsings` and `Nullable` enabled).
- **Naming:** `I{Name}` for Interfaces, `PascalCase` for Classes/Records/Methods, `camelCase` for parameters, `_camelCase` for private fields.
- **Types:** Prefer `record` for DTOs and immutable contracts with `init` and `required` properties.
- **Namespaces:** Use file-scoped namespaces.

### Async Patterns & Error Handling
- **ALWAYS** propagate `CancellationToken`.
- **NEVER** buffer entire collections in memory; strictly use `IAsyncEnumerable<T>` for streaming processing to respect memory limits.
- **Errors:** Categorize using `ErrorClassifier` (`Transient`, `Throttled`, `Permanent`, `Bug`) and throw `InvalidOperationException` for invalid state transitions.

### Testing Practices
- **Framework:** xUnit.
- **Shared Context:** Use `IClassFixture<T>`.
- **Method Naming:** `MethodName_Scenario_ExpectedResult`.
- Chaos tests and resilience validation (`./tests/chaos-test.sh`) are highly prioritized.

### Database & Migrations
- **ONLY additive migrations**; never modify existing ones. Create indices with `CONCURRENTLY`.
- Keep `DbContext` clean and configure entities using `IEntityTypeConfiguration<T>`.