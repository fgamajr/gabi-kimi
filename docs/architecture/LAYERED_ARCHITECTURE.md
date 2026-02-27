# GABI Layered Architecture

This document is the prose companion to the architecture tests in `tests/Gabi.Architecture.Tests`.
For quick-start commands and configuration, see [`CLAUDE.md`](../../CLAUDE.md).

---

## Layer Diagram

```
┌──────────────────────────────────────────────────────────┐
│  Layer 5 — Orchestration                                 │
│  Gabi.Api           Gabi.Worker                          │
│  (REST API, DI      (Hangfire server, job executors,     │
│   wiring, hosting)   DI wiring, telemetry)               │
└───────────────────────────┬──────────────────────────────┘
                            │ depends on ↓
┌──────────────────────────────────────────────────────────┐
│  Layer 4 — Domain Logic                                  │
│  Gabi.Discover   Gabi.Fetch   Gabi.Ingest                │
│  Gabi.Sync       Gabi.Jobs                               │
│  (pipeline stages; MUST NOT reference Gabi.Postgres      │
│   or any EF Core type directly)                          │
└───────────────────────────┬──────────────────────────────┘
                            │ depends on ↓
┌──────────────────────────────────────────────────────────┐
│  Layer 2–3 — Infrastructure                              │
│  Gabi.Postgres                                           │
│  (EF Core DbContext, entity classes, repository impls)   │
└───────────────────────────┬──────────────────────────────┘
                            │ depends on ↓
┌──────────────────────────────────────────────────────────┐
│  Layer 0–1 — Contracts                                   │
│  Gabi.Contracts                                          │
│  (interfaces, DTOs, enums, StatusVocabulary — ZERO       │
│   external Gabi.* dependencies)                          │
└──────────────────────────────────────────────────────────┘
```

### Dependency Rules

| From (higher layer) | May depend on | Must NOT depend on |
|---------------------|---------------|--------------------|
| `Gabi.Api` / `Gabi.Worker` | Any lower layer | — |
| `Gabi.Discover` / `Gabi.Fetch` / `Gabi.Ingest` / `Gabi.Sync` / `Gabi.Jobs` | `Gabi.Contracts` only | `Gabi.Postgres`, EF Core |
| `Gabi.Postgres` | `Gabi.Contracts` | `Gabi.Discover`, `Gabi.Fetch`, `Gabi.Ingest`, `Gabi.Sync`, `Gabi.Jobs` |
| `Gabi.Contracts` | Nothing | Any other `Gabi.*` project |

**Enforcement:** `tests/Gabi.Architecture.Tests` runs on every CI build.
After any change to project references, run: `dotnet test tests/Gabi.Architecture.Tests`

### Practical Guidelines

- New **interface or DTO** → `Gabi.Contracts`
- New **repository interface** needed by Layer 4 → define in `Gabi.Contracts`, implement in `Gabi.Postgres`, wire in Layer 5 DI
- New **job executor** → class in `Gabi.Worker/Jobs/`, register in `Gabi.Worker/Program.cs`
- Domain code that needs DB → define `IRepository` in `Gabi.Contracts`, implement in `Gabi.Postgres`, inject via DI in `Gabi.Worker` / `Gabi.Api`

---

## Pipeline Flow

```
sources_v2.yaml
      │
      ▼
┌─────────────┐
│    Seed     │  catalog_seed Hangfire job — loads YAML → PostgreSQL source registry
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Discovery  │  Per-source strategy (url_pattern, static_url, api_pagination, dynamic)
│             │  Output: URLs → discovered_links table
└──────┬──────┘
       │
       ▼
┌─────────────┐
│    Fetch    │  HTTP download (CSV / PDF / HTML / API)
│             │  Max capped by max_docs_per_source; graceful stop at "capped" status
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Ingest    │  Parse → Normalize → SHA-256 fingerprint (dedup)
│             │  → Chunk → Embed (384-dim TEI) → Index (Postgres + Elasticsearch)
└─────────────┘
```

Each stage is driven by a Hangfire job. Stages are idempotent: running twice without external change must not create duplicate documents (SHA-256 fingerprint guards this).

---

## Source Pipeline State Machine

States written to `source_pipeline_states.state`:

```
                ┌─────────┐
         ┌─────▶│  idle   │◀──────────────────┐
         │      └────┬────┘                   │
         │           │ job enqueued            │
         │           ▼                        │ phase completed
         │      ┌─────────┐                   │ (success / partial / capped)
         │      │ running │───────────────────┘
         │      └────┬────┘
         │           │
         │      ┌────▼────┐    operator resume
         │      │ paused  │◀────────────────────┐
         │      └────┬────┘                     │
         │           │ operator stop            │
         │           ▼                          │
         │      ┌─────────┐                     │
         │      │ stopped │─────────────────────┘
         │      └─────────┘
         │
         │      ┌─────────┐
         └──────│ failed  │  (manual intervention required)
                └─────────┘
```

| State | Meaning | Set by |
|-------|---------|--------|
| `idle` | No pipeline activity; no operator action | `GabiJobRunner` on phase completion |
| `running` | Actively executing a phase | `GabiJobRunner` at job start |
| `paused` | Operator paused; jobs yield gracefully | Dashboard `PauseSourceAsync` |
| `stopped` | Operator explicitly stopped; requires restart | Dashboard `StopSourceAsync` |
| `failed` | Unhandled exception; manual review needed | `GabiJobRunner` on uncaught exception |

**Job executor pause/stop check:** `GabiDbContext.IsSourcePausedOrStoppedAsync` returns `true` for both `paused` and `stopped`. Executors call this in their inner loops and exit early when it returns true.

---

## Key Invariants

- [ ] `sources_v2.yaml` is the **only** definition of sources — no URLs hardcoded in C# code
- [ ] All `api_pagination` discovery adapters require explicit `endpoint_template` in YAML; C# throws `ArgumentException` if absent
- [ ] Pipeline execution is **idempotent** — SHA-256 fingerprint prevents duplicate documents
- [ ] Embedding vectors are always **384 dimensions** — do not change
- [ ] **PostgreSQL is authoritative**; Elasticsearch is a derived index
- [ ] Memory limit: **300 MB** for background processing — no `ToListAsync()` on unbounded queries; use `IAsyncEnumerable`
- [ ] `CancellationToken` is propagated through all async methods
- [ ] DLQ recovery is **manual** via `POST /api/v1/dlq/{id}/replay` — no automatic infinite requeue
- [ ] Retry policy has a **single source of truth**: `Hangfire:RetryPolicy` in `appsettings`
- [ ] Layer 4 projects (`Gabi.Sync`, `Gabi.Jobs`, `Gabi.Discover`, `Gabi.Fetch`, `Gabi.Ingest`) must not reference `Gabi.Postgres`
- [ ] All pipeline state strings use `Status.*` constants from `Gabi.Contracts.Common.StatusVocabulary`

---

## Verification

```bash
dotnet test tests/Gabi.Architecture.Tests   # enforces all layer rules — must pass on every commit
dotnet build GabiSync.sln                   # zero errors required before merging
```
