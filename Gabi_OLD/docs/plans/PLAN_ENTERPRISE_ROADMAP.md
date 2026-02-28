# PLAN_ENTERPRISE_ROADMAP.md

**Date:** 2026-02-26
**Branch:** feat/fullpipeline
**Based on:** enterprise gap analysis + full code review (Program.cs, TeiEmbedder.cs, ElasticsearchDocumentIndexer.cs, SearchService.cs)

---

## What Is Already Implemented (Do Not Re-Build)

Confirmed present in code — prior gap analysis overstated these as missing:

| Component | Location | State |
|-----------|----------|-------|
| `embed` Hangfire queue | `Program.cs:119` | Declared in `options.Queues` |
| `EmbedAndIndexJobExecutor` | `Gabi.Worker/Jobs/` | Fully registered |
| `TeiEmbedder` | `Gabi.Ingest/TeiEmbedder.cs` | 384-dim, circuit breaker (5 failures → 30s open), sub-batch 32 |
| `ElasticsearchDocumentIndexer` | `Gabi.Ingest/ElasticsearchDocumentIndexer.cs` | Functional, per-document `_index` calls |
| `LocalDocumentIndexer` / `HashEmbedder` | `Gabi.Ingest/` | Dev fallbacks when env vars absent |
| Hybrid search (BM25 + kNN + RRF) | `Gabi.Api/SearchService.cs` | Implemented |
| `SourcePipelineStateEntity` | DB entity | Entity exists |

---

## Wave 1 — Critical (Close These First)

These are correctness or production-value blockers. All have surgical fixes.

### GAP-01 · Queue-specific concurrency — 2h

**Problem:** `Program.cs:116–120` registers a single `AddHangfireServer` with `WorkerCount = 2` for all six queues (`seed`, `discovery`, `fetch`, `ingest`, `embed`, `default`). The `embed` queue fan-out design is inert — embed jobs compete with ingest and fetch for the same 2 workers.

**Fix:** Two `AddHangfireServer` calls:

```csharp
// Pipeline stages: bounded concurrency, no OOM risk
builder.Services.AddHangfireServer(options =>
{
    options.ServerName = "pipeline-stages";
    options.WorkerCount = 1;
    options.Queues = new[] { "seed", "discovery", "fetch", "ingest", "default" };
});

// Embed pool: separate concurrency, can scale independently
builder.Services.AddHangfireServer(options =>
{
    options.ServerName = "embed-pool";
    options.WorkerCount = builder.Configuration.GetValue<int>("WorkerPool:EmbedWorkerCount", 3);
    options.Queues = new[] { "embed" };
});
```

Add `WorkerPool:EmbedWorkerCount` to `appsettings.json` (default `3`).

**Impact:** The embed fan-out finally runs in parallel. Without this, a 20k-doc ingest creates a backlog of embed jobs that are never processed concurrently regardless of how many embed jobs are enqueued.

---

### GAP-02 · Source state machine API — 4h

**Problem:** `SourcePipelineStateEntity` exists in the DB schema, and executor hooks call `IsSourcePausedOrStoppedAsync`. But nothing ever writes to that table. Pause/Resume/Stop are phantom features — there is no code path that sets a source state, and the hooks always return `false`.

**Fix (three pieces):**

1. **Service method** in `DashboardService` (or new `SourceControlService`):
   ```csharp
   Task SetSourceStateAsync(string sourceId, SourceControlAction action, CancellationToken ct);
   // action: Pause | Resume | Stop | Reset
   ```

2. **Write on job lifecycle** — `GabiJobRunner` (or the executor base) should set `ActivePhase` on start and clear it on completion/failure.

3. **Endpoint:**
   ```
   POST /api/v1/dashboard/sources/{sourceId}/control
   Body: { "action": "pause" | "resume" | "stop" | "reset" }
   Auth: operator
   ```

**Impact:** Without this, long-running ingest jobs on misconfigured sources cannot be stopped without restarting the Worker container.

---

### GAP-03 · BM25 searches title only — 1h

**Problem:** `SearchService.cs:135` has `.Fields("title")`. A query like `"cooperativa licitação"` misses everything stored in `contentPreview` and document bodies.

**Fix:** Multi-field BM25 with boosting:
```csharp
.MultiMatch(m => m
    .Query(request.Query)
    .Fields(new[] { "title^3", "contentPreview^2", "metadata.ementa^1.5" })
    .Type(TextQueryType.BestFields)
    .Fuzziness(new Fuzziness("AUTO")))
```

**Impact:** Recall improvement for all text queries. This is a one-line fix with outsized search quality impact.

---

### GAP-04 · No circuit breaker on ElasticsearchDocumentIndexer — 2h

**Problem:** `TeiEmbedder` has a circuit breaker (5 failures → 30s open). `ElasticsearchDocumentIndexer` has no equivalent. A flapping ES node causes unlimited sequential HTTP failures, each waiting for a full timeout, exhausting the Hangfire worker threads.

**Fix:** Port the same circuit breaker pattern from `TeiEmbedder` into `ElasticsearchDocumentIndexer`:
- Threshold: 5 consecutive failures
- Open duration: 30s (configurable via `Gabi:ElasticsearchCircuitBreakerSeconds`)
- Log state transitions at `Warning` level

---

### GAP-05 · ES bulk indexing — 3h

**Problem:** `ElasticsearchDocumentIndexer.IndexAsync` calls `_client.IndexAsync` once per document (line 100). Batches of 64 documents generate 64 HTTP round-trips to ES.

**Fix:** Add `BulkIndexAsync(IReadOnlyList<(IndexDocument, IReadOnlyList<IndexChunk>)> batch, CancellationToken ct)` to `IDocumentIndexer` interface (in `Gabi.Contracts`), implement it in `ElasticsearchDocumentIndexer` using `_client.BulkAsync`, and update `EmbedAndIndexJobExecutor` to call bulk when the batch size > 1.

Keep `IndexAsync` for single-doc backward compatibility. Architecture test: `IDocumentIndexer` still lives in Contracts; implementation stays in `Gabi.Ingest`.

---

## Wave 2 — Production Hardening

These don't block the data path but will cause production incidents.

### GAP-06 · Retry-After not parsed from 429 responses

Fetcher currently waits a hardcoded 15 minutes on 429. Parse the `Retry-After` header if present; clamp between 5s and 30m.

### GAP-07 · SourcePipelineState never written on job start/end

Even before GAP-02's control API, the `ActivePhase` field should be written when a job starts and cleared when it ends/fails. This makes dashboard status accurate at zero cost.

### GAP-08 · YAML `defaults.pipeline` not merged on Seed

New sources created via YAML don't inherit `coverage.strict`, `max_docs_per_source`, or `embed.batch_size` defaults unless explicitly set per-source. `CatalogSeedJobExecutor` must merge `defaults.pipeline` into each source entry during seed.

### GAP-09 · Redis and Elasticsearch running unauthenticated

`docker-compose.yml`: set `requirepass` on Redis and `ELASTIC_PASSWORD` + `xpack.security.enabled=true` on Elasticsearch. Add the corresponding credentials to `.env.example`.

Separately: document a secret rotation runbook (JWT key, DB password, API keys). Even a one-page runbook counts.

### GAP-10 · `GABI_EMBEDDINGS_URL` fail-fast only in Worker

`Program.cs:57–62` guards against missing `GABI_EMBEDDINGS_URL` in the Worker only. `Gabi.Api/Program.cs` does not. If the API starts without it, ingest jobs enqueued via the API will silently fall back to `HashEmbedder`.

Add the same guard to `Gabi.Api/Program.cs` in non-Development environments.

### GAP-11 · `Gabi.Ingest.Tests` does not exist

The most actively changed module (normalizer, chunker, embedder, indexer) has zero test coverage. This is the highest-risk untested surface area in the codebase.

Minimum viable test suite for the project:
- `CanonicalDocumentNormalizerTests` — field mapping, transform application, null/empty guards
- `FixedSizeChunkerTests` — boundary conditions, overlap, legal section boundaries
- `TeiEmbedderTests` — circuit breaker state transitions (mock HTTP), batch splitting at 32
- `ElasticsearchDocumentIndexerTests` — bulk vs single, failure handling, circuit breaker (mock ES)
- `EmbedAndIndexJobExecutorTests` — pause/backpressure hook respected, DLQ on embed failure

Use `Microsoft.AspNetCore.Mvc.Testing` or `Testcontainers.Elasticsearch` for the indexer integration tests.

---

## Wave 3 — Reliability & Correctness

### GAP-12 · PG ↔ ES consistency reconciliation

A document can be in Postgres with `es_indexed = true` but absent from Elasticsearch (ES restart, partial write failure). No mechanism detects or corrects this. Add a low-priority Hangfire recurring job (`reconcile` queue, daily) that:
1. Queries Postgres for documents with `es_indexed = true` in the last N days
2. Checks ES for their existence using `_mget`
3. Re-queues missing docs as `embed` jobs

### GAP-13 · NuGet audit + build hardening

Add to `Directory.Build.props`:
```xml
<PropertyGroup>
  <TreatWarningsAsErrors>true</TreatWarningsAsErrors>
  <Deterministic>true</Deterministic>
  <NuGetAudit>true</NuGetAudit>
  <NuGetAuditLevel>moderate</NuGetAuditLevel>
</PropertyGroup>
```

Fix any currently suppressed warnings before enabling `TreatWarningsAsErrors` (do a `dotnet build /p:TreatWarningsAsErrors=false -warnaserror` dry run first).

### GAP-14 · Zero-downtime migrations

Existing migrations create indexes without `CONCURRENTLY`. On tables with millions of rows, this takes an exclusive lock. New migrations should use raw SQL via `migrationBuilder.Sql`:
```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_documents_source_id ON documents(source_id);
```

Note: EF Core's `HasIndex()` generates `CREATE INDEX`, not `CREATE INDEX CONCURRENTLY`. Use raw SQL for all new index migrations.

### GAP-15 · Cross-source deduplication

SHA-256 fingerprinting is currently scoped per source. The same TCU acórdão available from both `tcu_acordaos` (CSV) and a hypothetical API source would produce two separate documents with the same content. Implement cross-source fingerprint dedup: before inserting a new document, check `WHERE fingerprint = @fp` across all sources. If found, link rather than duplicate.

### GAP-16 · Dynamic batch sizing for memory safety

`EmbedAndIndexJobExecutor` receives a fixed batch from `IngestJobExecutor`. Large PDFs with hundreds of chunks can push peak RSS above the 300 MB budget. Implement adaptive batching: start at the configured batch size, monitor `GC.GetTotalMemory()` after each batch, halve the batch size if heap exceeds 200 MB. Log the adjustment.

---

## Wave 4 — Engineering Quality

### GAP-17 · Testcontainers for integration tests

`Gabi.Api.Tests` and `Gabi.Postgres.Tests` use InMemory/SQLite. Real Postgres behavior (JSONB queries, ON CONFLICT, constraint violations, UUID generation) is not tested. Replace with `Testcontainers.PostgreSql` — the test startup cost is ~2s but the correctness guarantee is worth it.

### GAP-18 · Property-based testing (FsCheck)

Add FsCheck to `Gabi.Ingest.Tests` for:
- `FixedSizeChunker`: any text input → chunks reassemble to original content (no data loss)
- `CanonicalDocumentNormalizer`: fingerprint of normalized doc is deterministic across any field order
- `TeiEmbedder`: any batch ≤ 32 → no sub-batch splitting; any batch > 32 → splits correctly

### GAP-19 · Typed job payloads

`IngestJob.Payload`, `EmbedAndIndexJob`, and `DiscoveryJob` use `Dictionary<string, object>`. This is fragile — field renames cause silent runtime failures. Define typed record classes in `Gabi.Contracts/Jobs/` for each job payload and migrate the executors. Hangfire serializes these to JSON cleanly.

### GAP-20 · `IdempotencyKey` wired in `JobQueueRepository`

`IngestJob.IdempotencyKey` is set by callers but `HangfireJobQueueRepository.EnqueueAsync` ignores it. Wire it: use Hangfire's `BackgroundJobClient.Create` with a state that sets a display name, and before enqueueing check if a job with the same key is already enqueued (query Hangfire's `Set` storage). This prevents duplicate discovery/fetch jobs if the operator clicks twice.

---

## Wave 5 — Observability & Security

### GAP-21 · Per-source pipeline metrics

`PipelineTelemetry` has a counter for `documents_ingested_total` but no error-rate, p95-latency, or per-stage gauges. Add:
- `gabi_pipeline_stage_duration_seconds{source_id, stage, status}` — histogram
- `gabi_pipeline_errors_total{source_id, stage, error_type}` — counter
- `gabi_embed_queue_depth` — gauge (query Hangfire storage)

### GAP-22 · Immutable audit log with hash chain

Gate 12 requires it. Add a `audit_log` table with an append-only trigger (PostgreSQL `REVOKE UPDATE, DELETE ON audit_log FROM gabi_app_user`) and a `event_hash` column (SHA-256 of `previous_hash || event_type || resource_id || created_at`). Surface a `GET /api/v1/audit` endpoint (admin only).

### GAP-23 · Blue/green deploy + backup/restore test

`fly.toml` deploys immediately. Add a `fly deploy --strategy=rolling` (or `bluegreen` for paid tier) to the deploy process. Separately, add a CI job that runs `pg_dump | pg_restore` into a temp DB and verifies row counts match. This is the only way to know backups actually work.

### GAP-24 · Source-level RBAC

Current roles (`viewer`, `operator`, `admin`) are global. Add a `source_permissions` table (`user_id`, `source_id`, `role`) and filter API results and job dispatch by it. Unneeded for a single-tenant TCU deployment but required for multi-tenant or delegated operation.

---

## Wave 6 — Advanced Features (P2)

These are architectural expansions, not bug fixes.

| Item | Description |
|------|-------------|
| **Media transcription** | `MediaTranscribeJobExecutor` exists but is a stub. Wire AWS Transcribe or Whisper for `youtube_channel` and audio sources. |
| **MCP/RAG layer** | `Gabi.Mcp` project stub exists. Implement MCP tool server exposing `search`, `get_document`, `list_sources` tools for LLM agent consumption. |
| **BGE-M3 upgrade** | Replace `paraphrase-multilingual-MiniLM-L12-v2` (384-dim) with BGE-M3 (1024-dim) when a measurable recall gap is identified. Requires full re-index + pgvector schema migration. Do not do preemptively. |
| **Data lineage API** | `lineage_nodes` / `lineage_edges` exist in the schema. Add `GET /api/v1/documents/{id}/lineage` to surface the discovery → fetch → ingest chain. |
| **Quality gate** | Reject documents with empty `content`, encoding garbage, or below a minimum field presence threshold. Add `IQualityGate` to Contracts; implement in Ingest; wire before indexing. |
| **Multi-region** | Fly.io read replicas + cross-region ES snapshot. Not relevant until the primary pipeline is stable. |

---

## Prioritized Execution Order

```
WEEK 1
  GAP-01  Queue concurrency split          (2h)  ← highest leverage fix
  GAP-03  BM25 multi-field                 (1h)  ← one line, big impact
  GAP-04  ES circuit breaker               (2h)
  GAP-05  ES bulk indexing                 (3h)
  GAP-02  Source state machine API         (4h)

WEEK 2
  GAP-11  Gabi.Ingest.Tests scaffold       (1 day)
  GAP-10  Fail-fast GABI_EMBEDDINGS_URL    (1h)
  GAP-07  Write ActivePhase on job events  (2h)
  GAP-08  YAML defaults merge on seed      (2h)
  GAP-09  Redis + ES auth in compose       (1h)

WEEK 3
  GAP-13  NuGet audit + TreatWarningsAsErrors
  GAP-14  CONCURRENTLY index migrations
  GAP-16  Dynamic batch sizing
  GAP-12  PG ↔ ES reconciliation job

WEEK 4+
  GAP-17  Testcontainers
  GAP-18  FsCheck property tests
  GAP-19  Typed job payloads
  GAP-20  IdempotencyKey dedup
  GAP-21  Per-source metrics
  GAP-22  Audit log hash chain
  GAP-23  Deploy + backup tests
  GAP-15  Cross-source dedup

LATER
  GAP-24  Source-level RBAC
  Wave 6  Media, MCP, BGE-M3, lineage, quality gate
```

---

## Note on Embedding Dimensions (384 vs Larger)

`paraphrase-multilingual-MiniLM-L12-v2` at 384 dimensions is **sufficient** for the current use case:

- Multilingual MiniLM has strong Portuguese coverage
- The BM25+kNN+RRF hybrid compensates for embedding model gaps in domain-specific legal vocabulary
- 384-dim keeps memory and latency low at the TEI container level

Upgrade path (P2, not P0): switch to **BGE-M3** (1024-dim, multilingual, state-of-the-art on BEIR benchmarks) when you can measure recall@10 on a human-labeled Brazilian legal query set and see a gap. That upgrade requires:
1. Change TEI model tag in `docker-compose.yml`
2. Update pgvector column dimension (`ALTER TABLE` + rebuild HNSW index — expect hours on a full corpus)
3. Re-embed and re-index all documents
4. Update `ExpectedDimensions` constant in `TeiEmbedder.cs` and ES mapping

Do not do this preemptively.
