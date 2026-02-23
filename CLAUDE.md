# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Canonical repository instructions for AI agents live in `AGENTS.md` (Portuguese). This file summarizes what matters for day-to-day coding.

## Project Overview

**GABI** is a legal data ingestion and search system for Brazil's TCU (Tribunal de Contas da União). It crawls, fetches, parses, and indexes legal documents through a pipeline: **Seed → Discovery → Fetch → Ingest → Index**.

Stack: .NET 8 / C# 12, PostgreSQL 15, Elasticsearch 8.11, Redis 7, Hangfire 1.8, EF Core 8, Docker, Fly.io.

## Build & Test Commands

```bash
# Build
dotnet build GabiSync.sln

# Run all tests
dotnet test GabiSync.sln

# Run a single test project
dotnet test tests/Gabi.Api.Tests

# Run a single test by name
dotnet test tests/Gabi.Api.Tests --filter "FullyQualifiedName~BasicEndpointTests"

# Start infrastructure (Postgres :5433, Elasticsearch :9200, Redis :6380)
./scripts/dev infra up

# Run API locally (from repo root, never from src/Gabi.Api)
dotnet run --project src/Gabi.Api --urls "http://localhost:5100"

# Apply database migrations
./scripts/dev db apply

# Create a new migration
./scripts/dev db create <MigrationName>

# Full E2E test (destroys everything, rebuilds from zero)
./tests/zero-kelvin-test.sh
```

## Architecture (Strict Layering)

Dependencies flow downward only. **Never** add upward references.

```
Layer 5: Orchestration   → Gabi.Api, Gabi.Worker       (DI wiring, HTTP, Hangfire)
Layer 4: Domain Logic    → Gabi.Discover, Gabi.Fetch,   (business rules, adapters)
                           Gabi.Ingest, Gabi.Sync, Gabi.Jobs
Layer 2-3: Infrastructure → Gabi.Postgres               (EF Core, repositories, migrations)
Layer 0-1: Contracts     → Gabi.Contracts               (interfaces, DTOs, enums — ZERO deps)
```

**Hard rules:**
- `Gabi.Contracts` has zero project references
- Layer 4 projects must NOT reference `Gabi.Postgres` or EF Core directly
- All public interfaces live in `Gabi.Contracts`; implementations in domain projects
- DI registration happens only in Layer 5 (`Program.cs` of Api/Worker)

## Non-Negotiable Constraints

### Memory Budget: 300 MB
All data processing must stream. Use `IAsyncEnumerable<T>` with `[EnumeratorCancellation]`. Never materialize large collections (`ToList()`, `ToArray()`, `ReadAsStringAsync()` on large payloads).

### Migrations: Additive Only
- Never modify existing migration files
- Create indexes with `CONCURRENTLY` to avoid table locks
- API auto-applies migrations on startup when `GABI_RUN_MIGRATIONS=true`

### CancellationToken Propagation
Every async method must accept and forward `CancellationToken ct = default`.

## Code Conventions

- `ImplicitUsings` and `Nullable` enabled across all projects
- Prefer `record` for DTOs and immutable contracts, `init` setters for immutable properties
- English for code identifiers, Portuguese for documentation and user-facing strings
- Interfaces in `Gabi.Contracts`, implementations in domain projects

## Key Configuration

| Service       | Host Port | Container Port |
|---------------|-----------|----------------|
| PostgreSQL    | 5433      | 5432           |
| Elasticsearch | 9200      | 9200           |
| Redis         | 6380      | 6379           |
| API           | 5100      | 8080           |

Test credentials (JWT): `operator`/`op123` (read+write), `viewer`/`view123` (read-only), `admin`/`admin123` (full).

## Dev CLI (`./scripts/dev`)

```bash
./scripts/dev setup           # One-time setup
./scripts/dev infra up/down   # Start/stop Docker services (keeps volumes)
./scripts/dev infra destroy   # Stop + remove volumes (destructive)
./scripts/dev app up          # Run API in foreground
./scripts/dev app start/stop  # Run/stop API in background
./scripts/dev db apply        # Apply migrations
./scripts/dev db create Name  # Create new migration
./scripts/dev db reset        # Drop + recreate DB (destructive)
```

## Common Pitfalls

- **"Project file does not exist"**: Run commands from repo root, not from `src/Gabi.Api`
- **Port 5100 in use**: `pkill -f "dotnet.*Gabi.Api"` or use `--urls "http://localhost:5101"`
- **Port 6380 in use**: Project Redis uses 6380 (not 6379) to avoid system Redis conflicts
