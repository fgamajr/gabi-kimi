# GABI - Project Instructions

## Architecture (ADR-001)

Strict layered architecture. Layers can only reference LOWER layers.

```
Layer 5: Orchestration  → Gabi.Worker, Gabi.Api
Layer 4: Domain Logic   → Gabi.Discover, Gabi.Fetch, Gabi.Ingest, Gabi.Sync
Layer 2-3: Infrastructure → Gabi.Postgres
Layer 0-1: Contracts    → Gabi.Contracts (ZERO project references)
```

## Memory Constraint

Production runs on 1GB RAM (Fly.io). Effective budget: **300MB**.
Always use streaming (`IAsyncEnumerable<T>`, `Stream`) instead of buffering (`ToList()`, `ReadAsStringAsync()`).

## Documentation (Context7)

When working with EF Core, Npgsql, Hangfire, or Dapper APIs, use context7 to fetch current documentation before writing code.

## Key Rules

- Migrations must be additive-only; indexes require `CONCURRENTLY`
- Domain projects (Layer 4) must NOT reference Gabi.Postgres or EF Core
- Interfaces and DTOs live in Gabi.Contracts; implementations in their respective layer
- Pipeline stages must stream with `IAsyncEnumerable<T>` and support `CancellationToken`
- DI registration happens in Layer 5 (Worker/Api `Program.cs`)
