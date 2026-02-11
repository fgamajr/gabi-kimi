# GABI Incremental Refactor Plan

Date: 2026-02-11
Scope: refactor without rebuild, preserve behavior and compatibility.

## 1) Incremental Refactoring Steps

1. Stabilize API surface without breaking existing routes.
- Keep current endpoints intact.
- Add/route frontend-compatible endpoints under existing API namespace.
- Add stable pipeline control aliases (`start|stop|restart|status`) while preserving legacy `/control`.

2. Consolidate structure by responsibility (incremental, no mass move).
- `src/gabi/api/*`: only HTTP mapping/validation.
- `src/gabi/services/*`: business/search orchestration.
- `src/gabi/config.py` + `src/gabi/main.py`: environment/runtime bootstrap.
- `src/gabi/models/*`: persistence contracts.
- Keep old modules working; add deprecation notes before any relocation.

3. Hybrid retrieval hardening via service boundaries.
- Keep BM25 in Elasticsearch path.
- Keep dense vector retrieval path.
- Keep RRF fusion as combiner.
- Add reranking as optional post-fusion step with fallback.
- Standardize metadata keys and score provenance (`bm25`, `vector`, `rrf`, `rerank`).

4. Observability baseline.
- Structured JSON logs with request/correlation IDs.
- Phase timing fields persisted in execution stats.
- Health and readiness probes exposed with cloud-friendly aliases.

5. Fly.io readiness.
- Correct Docker build path in `fly.toml`.
- Remove contradictory embedding settings (1536) that conflict with current 384d pipeline.
- Keep env-driven configuration only; avoid local absolute paths.
- Validate volume mount usage and write paths.

## 2) Modified File Tree (this iteration)

- `src/gabi/api/router.py`
- `src/gabi/api/pipeline_control.py`
- `src/gabi/api/health.py`
- `src/gabi/pipeline/orchestrator.py`
- `docs/2026-02-11-incremental-refactor-plan.md`

## 3) Critical Changes Applied

### API routing and compatibility
- Included `dashboard_extended` router in API v1 under `/api/v1/dashboard/*`.
- Preserved old routers and paths.

### Stable pipeline control endpoints
- Added stable aliases in `pipeline_control`:
  - `POST /api/v1/pipeline-control/start`
  - `POST /api/v1/pipeline-control/stop`
  - `POST /api/v1/pipeline-control/restart`
  - `GET  /api/v1/pipeline-control/status`
- Kept existing `POST /api/v1/pipeline-control/control`.
- Fixed DB-session misuse in control endpoints (removed invalid `async with get_db_session()`).

### Observability
- Health endpoint now reports real runtime environment (`settings.environment.value`) and current version string.
- Added probe aliases:
  - `GET /live` -> liveness
  - `GET /ready` -> readiness
- Added pipeline timing metrics into orchestrator stats:
  - `phase_durations_ms.discovery`
  - `phase_durations_ms.change_detection`
  - `phase_durations_ms.processing_total`
  - `fetch_duration_ms_total`
  - `parse_duration_ms_total`

## 4) Backward Compatibility Notes

- Existing routes were not removed or renamed.
- New control aliases call the same control flow used by legacy endpoint.
- Existing health endpoints remain (`/health`, `/health/live`, `/health/ready`).

## 5) Fly.io Migration Checklist

1. Config sanity
- [ ] `fly.toml` points to the correct Dockerfile path for this repo.
- [ ] Embedding dimensions/env match runtime implementation (currently 384d).
- [ ] CORS/auth/rate limits are set by environment variables (no local assumptions).

2. Data plane
- [ ] PostgreSQL reachable from app and worker.
- [ ] Elasticsearch reachable with index creation policy defined.
- [ ] Redis reachable for cache/locks/control state.

3. Runtime
- [ ] Health probe path configured (`/health`), readiness probe (`/health/ready` or `/ready`).
- [ ] Worker process and API process are scaled independently.
- [ ] Persistent paths mounted only where write access is needed.

4. Search quality
- [ ] BM25 + vector + RRF smoke tests pass with real indices.
- [ ] Cross-encoder reranking can fail open (fallback to fused ranking).

5. Operations
- [ ] Logs are JSON and include request/correlation IDs.
- [ ] Alerts for DB/ES unavailability and high error rate are configured.

## 6) Potential Runtime Issues in Cloud

- In-memory pipeline controller state is process-local; multi-instance deployment may diverge state unless moved to Redis/DB.
- Some phase-control endpoints still have TODO queue integrations; actions may acknowledge before real execution wiring is complete.
- Concurrent stats mutation in orchestrator uses shared dict updates; under high concurrency, totals can drift slightly.
- Heavy cross-encoder models on CPU can increase latency and memory pressure; use timeout + fallback.
- If Elasticsearch or Redis is intermittent, readiness stays true (non-critical), but feature degradation must be surfaced in dashboard.
- Fly machines with auto-stop can increase cold-start latency for first requests.

## 7) Next Refactor Slice (recommended)

1. Move pipeline control source of truth to Redis/DB (not in-memory singleton).
2. Finalize queue-backed start/stop/restart execution wiring.
3. Introduce service-level interface for hybrid retrieval (`retrieval_service.py`) and make API consume one facade.
4. Add contract tests for frontend endpoints and control actions.
