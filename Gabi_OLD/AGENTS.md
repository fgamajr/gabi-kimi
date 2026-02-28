# AGENTS.md - GABI (Sistema de Ingestão Jurídica TCU)

> **Fonte canônica para agentes de IA.** `CLAUDE.md` e `GEMINI.md` são wrappers que apontam para este arquivo.

---

## 🛠️ Build, Lint & Test Commands

```bash
# Build
dotnet build GabiSync.sln
dotnet build GabiSync.sln -c Release

# Format & Lint
dotnet format GabiSync.sln

# Run ALL tests
dotnet test GabiSync.sln

# Run SINGLE test by name
dotnet test --filter "FullyQualifiedName~HealthEndpoint_ReturnsSuccess"

# Run SINGLE test with detailed verbosity for debugging
dotnet test --filter "FullyQualifiedName~JobStateMachineTests" --logger "console;verbosity=detailed"

# Run tests by class
dotnet test --filter "FullyQualifiedName~JobStateMachineTests"

# Run specific test project
dotnet test tests/Gabi.Api.Tests

# Architecture tests (MUST pass before commit)
dotnet test tests/Gabi.Architecture.Tests

# Apply database migrations
./scripts/dev db apply
```

---

## 🏗️ Layered Architecture (STRICT)

```
Layer 5: Orchestration  → Gabi.Worker, Gabi.Api
Layer 4: Domain Logic   → Gabi.Discover, Gabi.Fetch, Gabi.Ingest, Gabi.Sync, Gabi.Jobs
Layer 2-3: Infra        → Gabi.Postgres
Layer 0-1: Contracts    → Gabi.Contracts (ZERO dependencies)
```

**UNBREAKABLE RULES:**
1. `Gabi.Contracts` has NO project references
2. Domain projects (Layer 4) NEVER reference `Gabi.Postgres` or `EF Core`
3. Communication via interfaces defined in `Gabi.Contracts`
4. DI registration happens in Layer 5 (`Program.cs`) via `ServiceCollectionExtensions`

---

## 📏 Code Style

### Project Settings
- `ImplicitUsings` and `Nullable` enabled in all `.csproj`
- Target: .NET 8.0, C# 12.0

### Naming Conventions
| Type | Convention | Example |
|------|------------|---------|
| Interface | `I{Name}` | `IDiscoveryEngine` |
| Class | PascalCase | `JobQueueRepository` |
| Record (DTO) | PascalCase | `IngestJob`, `SyncResult` |
| Method | PascalCase | `ExecuteDeltaAsync` |
| Parameter | camelCase | `sourceId`, `cancellationToken` |
| Private field | `_camelCase` | `_context`, `_logger` |

### Types & Models
- Prefer `record` for DTOs and immutable contracts.
- Use `init` setters for immutable properties, `required` for mandatory properties.
- **EF Core:** Keep `DbContext` clean. Configure entities using `IEntityTypeConfiguration<T>`.

```csharp
public record IngestJob
{
    public required Guid Id { get; init; }
    public string SourceId { get; init; } = string.Empty;
    public JobStatus Status { get; init; }
}
```

### Imports (File-scoped namespaces)
```csharp
using Gabi.Contracts.Jobs;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Postgres.Repositories;

public class JobQueueRepository : IJobQueueRepository
```

### Async Patterns
- **ALWAYS** propagate `CancellationToken`.
- **NEVER** buffer entire collections in memory (300MB limit).
- Use `IAsyncEnumerable<T>` for streaming.

```csharp
public async IAsyncEnumerable<Document> FetchAsync(
    [EnumeratorCancellation] CancellationToken ct = default)
{
    await foreach (var item in source.WithCancellation(ct))
        yield return Transform(item);
}
```

### Error Handling
- Use `ErrorClassifier` for categorizing exceptions (`Transient`, `Throttled`, `Permanent`, `Bug`).
- Throw `InvalidOperationException` for invalid state transitions.

---

## 🧪 Test Conventions

- Framework: xUnit
- Use `IClassFixture<T>` for shared context
- Test method naming: `MethodName_Scenario_ExpectedResult`

---

## 🗄️ Database & Migrations

- **ONLY additive migrations** - never modify existing migrations.
- Create indices with `CONCURRENTLY` to avoid locks.
- Command: `./scripts/dev db create NomeDaMigration` then `./scripts/dev db apply`

---

## 🔒 Invariants & Key Files

**INVARIANTS (NEVER violate):**
1. No hardcoded URLs in code - all from `sources_v2.yaml`.
2. Fingerprint always SHA-256.
3. PostgreSQL is source of truth; ES/vectors are derived.
4. Idempotent execution: same input → same output.
5. Soft delete only - no physical deletions.

**KEY FILES:**
- `sources_v2.yaml`: All data source definitions
- `docs/architecture/LAYERED_ARCHITECTURE.md`: Architecture details
- `docs/architecture/INVARIANTS.md`: Unbreakable system rules
- `docker-compose.yml`: Local infra (Postgres:5433, ES:9200, Redis:6380)

**Fetch SSRF mitigation (Worker):** URLs used for fetch are validated by `Gabi:Fetch:AllowedUrlPatterns` (wildcard patterns). Blocklist (metadata IPs, loopback, private nets) is always applied. If allowlist is empty, all fetch URLs are blocked. In production set explicit patterns (e.g. `https://*.gov.br/*`); in dev `appsettings.Development.json` may use `["https://*","http://*"]`.

**Search in production:** In production, search MUST use Elasticsearch + embeddings (TEI). The PG fallback (`ToLower().Contains`) is for dev/test only and can cause full table scan and DoS. Set `Gabi:Search:RequireElasticsearch=true` in production; if ES/embedder are not configured, `GET /api/v1/search` returns 503 with a clear error instead of falling back to PG.

**Chaos / Staging validation:** Experimentos de confiabilidade (PostgreSQL stall, tarpit, poison pill, ES outage, SIGTERM, DLQ replay, idempotency, clock skew) estão documentados em [docs/reliability/CHAOS_PLAYBOOK.md](docs/reliability/CHAOS_PLAYBOOK.md). O runner `./tests/chaos-test.sh` só executa quando `DOTNET_ENVIRONMENT` não é `Production`; use `timeout 900 ./tests/chaos-test.sh <n>` para limite de 15 min.

---

## ⚠️ Common Issues

| Issue | Solution |
|-------|----------|
| "Project file does not exist" | Run commands from repo root, not subdirectories |
| Port 5100 in use | `pkill -f "dotnet.*Gabi.Api"` |
| Port 6380 in use | `fuser -k 6380/tcp` |
| Architecture test fails | Check layer dependencies - domain shouldn't reference infra |