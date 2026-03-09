---
phase: 11-fly-io-migration-and-dashboard-and-extensibility
plan: 05
subsystem: api, ui
tags: [fastapi, httpx, proxy, react-query, typescript, zustand, fly-io]

# Dependency graph
requires:
  - phase: 11-04
    provides: "Worker API endpoints (registry, pipeline, scheduler) on :8081"
provides:
  - "Web /api/worker/* proxy route forwarding to worker.internal:8081"
  - "TypeScript types for pipeline data (FileRecord, PipelineRun, LogEntry, etc.)"
  - "workerApi.ts typed fetch client for all worker endpoints"
  - "React Query hooks with 30s auto-refresh for dashboard data layer"
  - "Web fly.toml ES_URL and WORKER_URL env vars for .internal networking"
affects: [11-06, 11-07]

# Tech tracking
tech-stack:
  added: [zustand]
  patterns: [httpx-proxy, react-query-auto-refresh, typed-api-client]

key-files:
  created:
    - src/frontend/web/src/types/pipeline.ts
    - src/frontend/web/src/lib/workerApi.ts
    - src/frontend/web/src/hooks/usePipeline.ts
  modified:
    - src/backend/apps/web_server.py
    - ops/deploy/web/fly.toml
    - src/frontend/web/package.json

key-decisions:
  - "Worker proxy uses httpx.AsyncClient with 10s timeout and 503 fallback on ConnectError"
  - "No admin auth guard on proxy route — worker is internal-only, proxy is convenience layer"

patterns-established:
  - "httpx proxy pattern: catch-all api_route forwarding to .internal service"
  - "workerApi pattern: typed fetchJson wrapper with URLSearchParams for query filters"
  - "React Query hooks: 30s refetchInterval + invalidateQueries on mutations"

requirements-completed: [FLY-03, DASH-07]

# Metrics
duration: 3min
completed: 2026-03-09
---

# Phase 11 Plan 05: Web Proxy and Dashboard Data Layer Summary

**Web-to-worker httpx proxy, fly.toml .internal DNS env vars, and full React Query data layer with 30s auto-refresh**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-09T13:07:23Z
- **Completed:** 2026-03-09T13:10:34Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- Web FastAPI server proxies /api/worker/* requests to worker.internal:8081 via httpx with 10s timeout
- Web fly.toml updated with ES_URL and WORKER_URL env vars for Fly.io .internal networking
- TypeScript types define all pipeline data structures (FileRecord, PipelineRun, LogEntry, RegistryStatus, HealthStatus, MonthData)
- workerApi.ts provides 10 typed API functions covering health, registry, pipeline, and control endpoints
- React Query hooks with 30s auto-refresh and mutation invalidation ready for dashboard UI

## Task Commits

Each task was committed atomically:

1. **Task 1: Add worker proxy route to web server and update web fly.toml** - `2611717` (feat)
2. **Task 2: Create pipeline TypeScript types, API client, and React Query hooks** - `b09fd3f` (feat)

## Files Created/Modified
- `src/backend/apps/web_server.py` - Added WORKER_BASE config and /api/worker/* proxy route
- `ops/deploy/web/fly.toml` - Added ES_URL and WORKER_URL env vars
- `src/frontend/web/src/types/pipeline.ts` - TypeScript interfaces for all pipeline data structures
- `src/frontend/web/src/lib/workerApi.ts` - Typed API client for worker proxy endpoints
- `src/frontend/web/src/hooks/usePipeline.ts` - React Query hooks with 30s auto-refresh
- `src/frontend/web/package.json` - Added zustand dependency

## Decisions Made
- Worker proxy uses httpx.AsyncClient with 10s timeout; returns 503 JSON on ConnectError
- No admin auth guard on proxy route since worker is only accessible via .internal networking anyway
- Installed zustand for future dashboard state management needs

## Deviations from Plan

None - plan executed exactly as written. Frontend files (types, workerApi, usePipeline) were already present in the working tree from a prior session and matched the plan specification exactly.

## Issues Encountered
- Python import-based verification could not run locally due to missing asyncpg dependency; verified route presence via syntax check and grep instead

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Proxy, types, API client, and hooks are ready for dashboard UI components (Plan 06)
- PipelinePage.tsx references a not-yet-created PipelineTimeline component (expected in Plan 06)

## Self-Check: PASSED

All 5 created/modified files verified on disk. Both task commits (2611717, b09fd3f) verified in git log.

---
*Phase: 11-fly-io-migration-and-dashboard-and-extensibility*
*Completed: 2026-03-09*
