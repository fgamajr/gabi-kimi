# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
# Build entire solution
dotnet build GabiSync.sln

# Run all tests (excluding external endpoint contracts by default)
dotnet test GabiSync.sln --filter "Category!=External"

# Run only external integration contracts (opt-in)
dotnet test GabiSync.sln --filter "Category=External"

# Run a single test project
dotnet test tests/Gabi.Api.Tests
dotnet test tests/Gabi.Discover.Tests
dotnet test tests/Gabi.Postgres.Tests

# Run a single test class or method
dotnet test tests/Gabi.Api.Tests --filter "FullyQualifiedName~BasicEndpointTests"
dotnet test tests/Gabi.Postgres.Tests --filter "FullyQualifiedName~FetchItemRepositoryTests.SomeMethod"

# Run API locally (requires infra up)
dotnet run --project src/Gabi.Api --urls "http://localhost:5100"
```

## Dev CLI (`./scripts/dev`)

```bash
./scripts/dev infra up        # Start Postgres (5433), Elasticsearch (9200), Redis (6380)
./scripts/dev infra down      # Stop containers (keep volumes)
./scripts/dev infra destroy   # Stop + delete volumes
./scripts/dev app up          # Run API foreground on :5100 (Ctrl+C to stop)
./scripts/dev db apply        # Apply EF migrations
./scripts/dev db create Name  # Create new migration
./scripts/dev db status       # List migrations
```

Full Docker (no dotnet on host):
```bash
docker compose --profile api --profile worker up -d
```

## Architecture (ADR-001)

Strict layered architecture. Layers can only reference LOWER layers.

```
Layer 5: Orchestration  → Gabi.Worker, Gabi.Api
Layer 4: Domain Logic   → Gabi.Discover, Gabi.Fetch, Gabi.Ingest, Gabi.Sync
Layer 2-3: Infrastructure → Gabi.Postgres
Layer 0-1: Contracts    → Gabi.Contracts (ZERO project references)
```

**Pipeline flow:** Seed → Discovery → Fetch → Ingest. The API enqueues jobs; the Worker (Hangfire) executes them.

**Source definitions** live in `sources_v2.yaml` at the repo root. The API reads this file (via `GABI_SOURCES_PATH` env or walking up from ContentRoot). Discovery strategies: `static_url`, `url_pattern`, `api_pagination` (with drivers: `btcu_api_v1`, `camara_api_v1`, `senado_legislacao_api_v1`), `web_crawl`.

## Memory Constraint

Production runs on 1GB RAM (Fly.io). Effective budget: **300MB**.
Always use streaming (`IAsyncEnumerable<T>`, `Stream`) instead of buffering (`ToList()`, `ReadAsStringAsync()`).

## Key Rules

- Migrations must be additive-only; indexes require `CONCURRENTLY`
- Domain projects (Layer 4) must NOT reference Gabi.Postgres or EF Core
- Interfaces and DTOs live in Gabi.Contracts; implementations in their respective layer
- Pipeline stages must stream with `IAsyncEnumerable<T>` and support `CancellationToken`
- DI registration happens in Layer 5 (Worker/Api `Program.cs`)

## Documentation (Context7)

When working with EF Core, Npgsql, Hangfire, or Dapper APIs, use context7 to fetch current documentation before writing code.

## Infrastructure

| Service       | Host Port | Notes |
|---------------|-----------|-------|
| PostgreSQL 15 | 5433      | `psql postgresql://gabi:gabi_dev_password@localhost:5433/gabi` |
| Elasticsearch 8 | 9200   | Single-node, no security |
| Redis 7       | 6380      | **6380** on host (avoids conflict with system Redis on 6379) |

Migrations auto-apply on API startup when `GABI_RUN_MIGRATIONS=true` (set in docker-compose).

## Auth

Test users: `operator`/`op123` (read-write), `viewer`/`view123` (read-only). JWT via `POST /api/v1/auth/login`.

## Zero-Kelvin Test

Full E2E validation that rebuilds the system from scratch:

```bash
./tests/zero-kelvin-test.sh                        # docker-only (default)
./tests/zero-kelvin-test.sh docker-only \
  --source tcu_sumulas --phase discovery            # targeted source
./tests/zero-kelvin-test.sh docker-only \
  --source tcu_acordaos --phase full --max-docs 200 # capped stress test
```

## Test Projects

All use **xUnit** with `Microsoft.NET.Test.Sdk`. Key libraries: `FluentAssertions`, `Moq`, EF Core InMemory provider. Coverage via `coverlet.collector`.

Convention: tests that hit real external HTTP endpoints must include `[Trait("Category", "External")]`.
