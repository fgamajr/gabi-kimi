# V10 Gaps Remediation Plan

This document outlines the actionable execution plan to address the remaining `P1.5` and `P2` items identified in `PLANO_CONSOLIDADO_V10.md` as of the February 27, 2026 audit. The gaps have been grouped into logical phases based on risk, system stability, and required effort.

## Phase 1: Critical Guardrails, Memory Safety & Hot Paths (Priority: High)
*Goal: Fix architecture tests to prevent regression, plug OOM vulnerabilities, and remove N+1 queries from hot paths.*

| ID | Component | Action Item |
|:---|:---|:---|
| **ARCH-01** | `Gabi.Architecture.Tests` | **[DONE]** Fix `DomainLayer_ShouldNotReference_Infrastructure` to properly evaluate domain types (currently vacuous). Ensure the test assembly actually loads the domain layers via `Assembly.Load` or direct references. |
| **IO-14** | `FetchJobExecutor` | **[DONE]** Add `Content-Length` check and `ReadAllBytesWithLimitAsync` guard to `FetchAndParseJsonApiAsync` before calling `JsonDocument.ParseAsync` to prevent large-payload OOM crashes. (Verified already implemented) |
| **IO-10** | `PipelineStatsService` | **[DONE]** Fix N+1 queries in `GetStatsAsync()`. Utilize `GetBySourcesAsync` and an in-memory `GroupBy` (similar to the fix applied in `PostgreSqlSourceCatalogService`). (Verified already implemented) |
| **IO-11/12** | `SourceQueryService` | **[DONE]** Fix N+1 document count queries in `GetLinksAsync()` (guardrail and normal paths). Add `GetDocumentCountBulkAsync(linkIds)` to repositories to batch count resolution. (Verified already implemented) |
| **EH-08** | `EmbedAndIndexJobExecutor` | **[DONE]** Fix double-embedding race condition. Add `embed_and_index` to the set evaluated by `EnforceSingleInFlightPerSource()`. |

## Phase 2: Data Integrity & Error Handling
*Goal: Prevent silent data loss and missing telemetry on failures across the system.*

| ID | Component | Action Item |
|:---|:---|:---|
| **EH-03** | WAL Projection | **[DONE]** Add Polly per-event retry policy to `WriteToDlqAsync` in `LogicalReplicationProjectionWorker` to prevent non-consecutive transient failures from permanently losing documents. |
| **EH-04** | WAL Projection | **[DONE]** Fix checkpoint race condition in `PersistCheckpointAsync`. Ensure `conn.SetReplicationStatus` is **never** called if the local checkpoint save fails. |
| **IO-15** | `GenericPaginatedDiscoveryDriver` | **[DONE]** Fix silent `yield break` on API failure. (Verified already throwing an exception) |
| **EH-01/02** | Telemetry/Config | **[DONE]** Add `LogError` explicitly inside `catch` blocks that currently fail-open silently (`GabiJobRunner.cs`, `PostgreSqlSourceCatalogService`, `SystemHealthService`, `SourceDiscoveryJobExecutor`, `PipelineStatsService`, `SourceQueryService`). |
| **EH-05** | `SearchService` | **[DONE]** Flag embedding failures explicitly in the response DTO (`embeddingFailed: true`) when falling back to BM25-only search. |
| **EH-06** | API Layer | **[DONE]** Standardize all endpoint error responses to use a unified `ApiError(code, msg)` format instead of anonymous objects or varying middleware types. |

## Phase 3: Architectural Boundaries & I/O Hygiene
*Goal: Enforce anti-corruption layers and remove hardcoded API configurations.*

| ID | Component | Action Item |
|:---|:---|:---|
| **IO-03** | `MediaTranscribeJobExecutor` | Critical Boundary Fix: Extract OpenAI API direct calls into an `ITranscriptionService` inside `Gabi.Contracts`, implemented by an adapter. Remove inline reading of `OPENAI_API_KEY`. |
| **IO-04** | `YouTubeDiscoveryDriver` | Move hardcoded Google APIs URLs to configuration/Contracts. Avoid `internal static` rigidity. |
| **IO-05** | `PostgreSqlSourceCatalogService` | Decompose to fix SRP violation. Extract an `ISourceYamlLoader` for loading YAML files, keeping the service focused purely on persistence coordination. |
| **IO-01/02/06** | Configuration | Remove hardcoded `localhost:4317` (OTLP), `localhost:7233` (Temporal), and `localhost:9200` (ES) defaults from code. Fix Development configuration port 6379 -> 6380 for Redis. |
| **IO-13** | Dashboard Services | Remove hardcoded `"coming_soon"` strings for the implemented phases (Ingest, Processing, Embedding, Indexing) in `PipelineStatsService` and `SourceQueryService`. |

## Phase 4: Code Health & Scalability (Tech Debt)
*Goal: Remove dead code, replace magic strings, and prepare the job scheduler for global scale.*

| ID | Component | Action Item |
|:---|:---|:---|
| **SYNC-01** | `Gabi.Sync.Jobs` / Repositories | Remove dead code: delete unreferenced `Gabi.Sync.Jobs.JobQueueRepository`, `JobWorkerService`, and the obsolete `Gabi.Postgres.Repositories.JobQueueRepository`. Ensure `HangfireJobQueueRepository` is the sole implementation. |
| **IO-07** | Broad Codebase | Replace >40 occurrences of magic string literals (`"failed"`, `"pending"`, `"running"`) with their equivalent constants from `StatusVocabulary`. |
| **SCAL-01** | Pipeline Admission | Add global admission control (e.g., `TotalPendingFetch`) to prevent Hangfire from queueing millions of jobs across all sources simultaneously. |
| **SCAL-02** | `HangfireJobQueueRepository` | Add transaction lock to `ScheduleAsync` to eliminate the indirect deduplication race condition between enqueueing and check steps. |
| **IO-08/09** | God Objects | Refactor `Gabi.Api/Program.cs` (>700 lines) by extracting endpoint maps to extension methods. Evaluate extracting responsibilities from `FetchJobExecutor.cs` (>1100 lines). |

## Next Steps

1. Review and refine this plan.
2. Select a Phase to begin implementation (Phase 1 is highly recommended to establish safe testing and stability bounds).
3. Track progress incrementally through this markdown document.
