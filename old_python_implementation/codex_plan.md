# Codex Plan - GABI Control Panel, API Alignment, MCP Rebuild, and Production Rollout

Date: 2026-02-11

## Executive Decision
Recommendation for Task 4: **do not move everything to Fly.io immediately**. Build and validate the new control-plane + retrieval stack locally (or in a production-like staging), then promote to Fly.io in controlled waves.

Why:
- We are changing control semantics (start/restart/stop by phase), API contract, MCP behavior, and retrieval architecture at the same time.
- A direct "big bang" production move multiplies rollback risk and makes root-cause isolation hard.
- Fastest safe path is local/staging hardening -> canary on Fly.io -> full migration.

---

## Current State Snapshot (from code inspection)
- Backend already has typed endpoints under `/api/v1/dashboard` (`stats`, `pipeline`, `activity`, `health`) plus source/admin routes.
- Frontend in `/home/fgamajr/dev/user-first-view` currently uses **mock data only** (`src/lib/dashboard-data.ts`), no API client wiring yet.
- Existing source sync endpoint creates manifests but still has TODO for actual execution trigger in some flows.
- Existing MCP server is generic and not yet focused on the exact new split you requested (exact lexical by legal type + hybrid semantic retrieval with richer controls).

---

## Scope by Task

## Task 1 - Recreate API to match frontend control-panel requirements
Goal: provide a control-plane API that supports monitoring and **button-driven phase operations**.

### 1.1 API Contract First (OpenAPI-driven)
Create/adjust a contract with these endpoint groups:
- `GET /api/v1/control/overview`
  - Aggregated metrics for cards (documents, indexed docs, active sources, recent failures, queue depth).
- `GET /api/v1/control/pipeline`
  - Stage-by-stage progress and health (discovery, fetch, parse, chunk, embed, index).
- `GET /api/v1/control/jobs`
  - Active and recent runs with filter by source, phase, status.
- `GET /api/v1/control/sources`
  - Source list + status + counts.
- `POST /api/v1/control/actions/start`
- `POST /api/v1/control/actions/restart`
- `POST /api/v1/control/actions/stop`
  - Payload supports: `scope` (`source` | `run` | `phase`), `source_id`, `run_id`, `phase`, `reason`, `force`.
- `GET /api/v1/control/actions/{action_id}`
  - Action acknowledgement + execution result.
- Optional live channel:
  - `GET /api/v1/control/stream` (SSE/WebSocket) for live status updates.

### 1.2 Orchestration and State Machine
Implement explicit control semantics in backend services:
- Action table (`pipeline_actions`) with idempotency key and audit fields.
- Run/phase state transitions with validation:
  - Allowed: `pending -> running -> completed/failed/cancelled`.
  - `restart` creates a new run with `resume_from` or phase checkpoint strategy.
- Stop handling:
  - Graceful cancellation token per run/phase.
  - Timeout + forced stop fallback.
- Auditability:
  - Every control action logged with actor, timestamp, previous state, new state.

### 1.3 Compatibility Strategy
- Keep existing `/dashboard` endpoints for now.
- Add `control/*` endpoints as the canonical contract for the new panel.
- Deprecate old routes only after frontend migration is complete.

Acceptance criteria:
- Every panel button maps to a backend action endpoint.
- Start/restart/stop produce deterministic run state changes.
- Full audit trail and error reason for rejected actions.

---

## Task 2 - Connect frontend and API
Goal: replace mock dashboard with live backend integration.

### 2.1 Frontend integration steps (`/home/fgamajr/dev/user-first-view`)
- Add API client layer (`src/lib/api.ts`) with base URL/env (`VITE_API_BASE_URL`).
- Replace `mockStats`, `mockJobs`, `mockPipelineStages` with request hooks (React Query recommended).
- Add action handlers for start/restart/stop buttons with optimistic UI + retry-safe UX.
- Add polling or SSE for near-real-time updates.
- Add error and offline states in `SystemHealth`, `PipelineOverview`, `ActivityFeed`, `SourcesTable`.

### 2.2 Contract mapping
- Align frontend `PipelineStage` types with backend enum values.
- Normalize timestamps/timezone formatting.
- Ensure status mapping is exact (`active/idle/error`, `in_progress/synced/failed`, etc.).

### 2.3 Security
- Token propagation (Bearer) and refresh strategy.
- Role-based UI gating for destructive actions (stop/restart).

Acceptance criteria:
- Dashboard loads with live data only (no mock dependency).
- Actions from UI trigger backend and update UI state within acceptable delay.
- Clear error feedback for unauthorized/invalid transitions.

---

## Task 3 - Delete old MCP(s), create new retrieval-centric MCP
Goal: rebuild MCP around **exact lexical retrieval by legal corpus type** + **hybrid semantic retrieval**.

### 3.1 Decommission plan
- Inventory current MCP tools/resources and consumers.
- Remove/disable obsolete MCP endpoints/tools behind feature flag.
- Preserve backward compatibility window only if a consumer still depends on old tools.

### 3.2 New MCP design
New tools (proposed):
- `search_exact`
  - Elasticsearch/BM25-first exact search with analyzers tuned by corpus (`normas`, `acordaos`, `publicacoes`, `leis`).
- `search_hybrid`
  - BM25 + dense embeddings + fusion + rerank.
- `get_document`
  - Canonical doc fetch with metadata and provenance.
- `explain_retrieval`
  - Returns match rationale (lexical terms, vector score, rerank score).

New resources (proposed):
- `corpus://{type}/stats`
- `retrieval://last-query/{id}`
- `embedding://health`

### 3.3 Retrieval quality upgrades from `vision.md` (priority order)
1. Cross-encoder reranking (implement now; highest impact/effort ratio).
2. Vision-language document understanding (pilot for scanned/complex PDFs).
3. GraphRAG (phase 2; high ROI, higher complexity).
4. SPLADE learned sparse embeddings (phase 3; after PT-BR evaluation data exists).

Acceptance criteria:
- MCP returns exact-match and hybrid results with traceable scoring.
- Reranker measurably improves relevance on a held-out legal query set.
- Old MCP paths are removed or formally deprecated with migration notes.

---

## Task 4 - Fly.io production rollout strategy
Goal: deploy safely without losing observability/control.

## 4.1 Rollout sequence (recommended)
1. Local/staging parity:
- Finalize API v2 control endpoints.
- Wire frontend to live backend.
- Validate start/restart/stop behavior with integration tests.

2. Fly.io staging app:
- Deploy API + worker + MCP as separate process groups/apps.
- Run migrations and smoke tests.
- Confirm dashboards and control actions under realistic load.

3. Canary production:
- Route a small subset of sources/traffic.
- Monitor failure rate, action latency, retrieval relevance, queue growth.

4. Full cutover:
- Move remaining workloads.
- Keep rollback path for one release window.

## 4.2 Infra notes to include during implementation
- Separate web API and long-running workers on Fly.io.
- Persist queue/state in managed Redis/Postgres.
- Add observability baseline: structured logs, metrics, traces, alert thresholds.
- Validate current `fly.toml` paths/process commands against actual repo modules before deploy.

Acceptance criteria:
- No blind cutover.
- Canary proves stable control actions and retrieval quality before full migration.
- Rollback instructions tested.

---

## Delivery Plan (execution order)
1. Freeze API contract for control panel (`control/*`) and generate OpenAPI docs.
2. Implement backend control actions + state machine + audit persistence.
3. Replace frontend mock layer with real API integration and action buttons.
4. Rebuild MCP for exact + hybrid retrieval, add reranking.
5. Run retrieval and control-plane validation suite.
6. Deploy to Fly.io staging, then canary, then full rollout.

---

## Testing and Validation Matrix
- API contract tests: schema + status codes + auth rules.
- Orchestration tests: valid/invalid state transitions, stop/restart idempotency.
- Frontend integration tests: loading, action feedback, failure states.
- Retrieval eval: NDCG@k / Recall@k before-vs-after reranker.
- Production readiness checks: migrations, health probes, alert routing, rollback drill.

---

## Risks and Mitigations
- Risk: concurrent refactor of API + MCP + deployment.
  - Mitigation: phased delivery and feature flags.
- Risk: stop/restart semantics causing inconsistent run states.
  - Mitigation: strict transition guards + action audit log + idempotency.
- Risk: retrieval regressions after architecture changes.
  - Mitigation: offline benchmark suite and canary relevance checks.

---

## Immediate Next Implementation Step
Implement **Task 1 contract and control action backend skeleton first** (including start/restart/stop endpoints and action persistence), because Tasks 2-4 depend on it.
