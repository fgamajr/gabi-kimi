---
name: gabi-pipeline
description: Applies GABI ETL pipeline rules: streaming, memory budget, backpressure, and job executor patterns. Use when implementing or modifying pipeline stages (Seed, Discovery, Fetch, Ingest, Embed, Index), job executors, Hangfire jobs, or when the user mentions streaming, backpressure, memory limit, or pipeline flow.
---

# GABI Pipeline Skill

Use when changing **pipeline stages**, **job executors**, or **data flow** (Seed → Discovery → Fetch → Ingest → Embed → Index).

## Pipeline Order

1. **Seed** — Loads `sources_v2.yaml` into DB.
2. **Discovery** — Discovers URLs/links per source (adapters: `static_url`, `url_pattern`, `api_pagination`, `web_crawl`).
3. **Fetch** — Fetches raw content; streaming, no full in-memory buffer.
4. **Ingest** — Normalizes, projects media, fans out to **embed_and_index** jobs.
5. **Embed + Index** — Chunk → embed (TEI or HashEmbedder) → index (ES or Local); runs as separate jobs per batch.

## Non-Negotiable Rules

### Memory (300MB effective budget)

- **Never** load full collections into memory (e.g. no `ToListAsync()` on unbounded queries).
- Use **streaming**: `IAsyncEnumerable<T>`, `await foreach` with `WithCancellation(ct)`.
- Prefer yielding one item at a time; batch only when the API requires it (e.g. embed batch size cap).

### CancellationToken

- **Always** propagate `CancellationToken` through async methods (default `CancellationToken ct = default`).
- Use `WithCancellation(ct)` on `IAsyncEnumerable` consumption.

### Idempotency and source of truth

- Same input → same output; use fingerprint (e.g. SHA-256) and upsert (e.g. `ON CONFLICT`).
- PostgreSQL is source of truth; Elasticsearch/vectors are derived.
- No hardcoded URLs; source definitions live in `sources_v2.yaml`.

### Backpressure and pause

- Job executors can check **backpressure** (e.g. max pending fetch/ingest/embed) and **source state** (paused/stopped).
- When over limit or paused: yield (e.g. return yielded) and schedule a delayed retry via `IJobQueueRepository.ScheduleAsync`; do not spin or block.

## Job Executors (Worker)

- Each job type has an executor (e.g. `SourceDiscoveryJobExecutor`, `FetchJobExecutor`, `IngestJobExecutor`, `EmbedAndIndexJobExecutor`).
- Executors receive `IngestJob` (or equivalent), report progress via `IProgress<JobProgress>`, return `JobResult` with status and metadata.
- Register executors and queues in `Gabi.Worker` `Program.cs`; job types map to Hangfire queues (e.g. `embed_and_index` → `embed` queue).

## Where Things Live

- **Source config:** `sources_v2.yaml` (and DB after seed). Pipeline defaults (backpressure, embed batch) in `defaults.pipeline`.
- **Interfaces:** `Gabi.Contracts` (e.g. `IJobQueueRepository`, discovery/fetch/ingest contracts).
- **Implementations:** Layer 4 (Discover, Fetch, Ingest, Sync, Jobs) + Layer 2–3 (Postgres). Orchestration and DI in Layer 5 (Api, Worker).

## Quick Checklist for Pipeline Code

- [ ] No unbounded `.ToListAsync()` or equivalent; use streaming where data can be large.
- [ ] `CancellationToken` passed and used in async loops.
- [ ] New or modified executor: respects pause/backpressure and uses `ScheduleAsync` for retry when yielding.
- [ ] Config (URLs, caps, backpressure) from YAML/config, not hardcoded.

## Additional Resources

- Repo root [AGENTS.md](../../AGENTS.md) — Async Patterns, Invariants, pipeline overview.
- Pipeline and backpressure details: [reference.md](reference.md).
