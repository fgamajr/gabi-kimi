---
phase: 11-fly-io-migration-and-dashboard-and-extensibility
plan: 04
subsystem: worker
tags: [fastapi, apscheduler, cron, elasticsearch-snapshots, tigris, internal-api]

requires:
  - phase: 11-02
    provides: "SQLite Registry with state machine, CRUD, and get_db context manager"
  - phase: 11-03
    provides: "5 pipeline modules (run_discovery, run_download, run_extract, run_ingest, run_verify)"
provides:
  - "Worker FastAPI app on port 8081 with APScheduler cron orchestration"
  - "10 internal API endpoints for registry status, pipeline control, and health"
  - "Daily ES snapshot to Tigris S3-compatible storage"
  - "Scheduler pause/resume and manual phase trigger"
affects: [11-05-admin-dashboard, 11-06, 11-07]

tech-stack:
  added: [apscheduler]
  patterns: [fastapi-lifespan-scheduler, cron-job-wrapper-with-registry, module-level-registry-injection]

key-files:
  created:
    - src/backend/worker/main.py
    - src/backend/worker/scheduler.py
    - src/backend/worker/api.py
    - src/backend/worker/snapshots.py
    - tests/test_pipeline/test_worker_api.py
  modified: []

key-decisions:
  - "APScheduler AsyncIOScheduler with pause flag pattern instead of scheduler.pause/resume_job (simpler, applies to all jobs)"
  - "Module-level _registry injection pattern: main.py sets _registry on both api and scheduler modules during lifespan"
  - "Pipeline phase signatures differ: discovery/verify/ingest take es_url; download/extract do not"

patterns-established:
  - "Cron wrapper pattern: check _paused, create pipeline_run, call phase function, complete_pipeline_run"
  - "Module-level dependency injection: _registry set during FastAPI lifespan for route handlers"
  - "httpx.ASGITransport for integration testing FastAPI without starting a server"

requirements-completed: [PIPE-07, FLY-04]

duration: 3min
completed: 2026-03-09
---

# Phase 11 Plan 04: Worker Application Wiring Summary

**FastAPI worker on :8081 with APScheduler running 7 cron jobs (5 pipeline + retry + daily ES snapshot to Tigris) and 10 internal API endpoints**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-09T13:02:01Z
- **Completed:** 2026-03-09T13:05:06Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Worker entrypoint with FastAPI lifespan managing APScheduler lifecycle and registry initialization
- 7 cron jobs: discovery (23:00), download (23:30), extract (23:45), ingest (00:00), verify (01:00), retry (06:00), snapshot (02:00)
- 10 internal API routes for registry status, months, files, pipeline runs, logs, trigger, retry, pause/resume, and health
- ES snapshot module for daily Tigris S3 backups with graceful failure handling
- 7 integration tests via httpx ASGITransport (TDD: RED then GREEN)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create scheduler, snapshots module, and worker main entrypoint** - `74d8150` (feat)
2. **Task 2 RED: Add failing tests for worker internal API** - `4abb322` (test)
3. **Task 2 GREEN: Implement internal API routes** - `1180945` (feat)

## Files Created/Modified
- `src/backend/worker/main.py` - Worker entrypoint: FastAPI lifespan with APScheduler, heartbeat, registry init (107 lines)
- `src/backend/worker/scheduler.py` - APScheduler cron jobs wrapping pipeline modules + snapshot + retry (185 lines)
- `src/backend/worker/api.py` - 10 internal API routes for registry and pipeline control (128 lines)
- `src/backend/worker/snapshots.py` - ES snapshot management: Tigris S3 repo registration + daily snapshots (82 lines)
- `tests/test_pipeline/test_worker_api.py` - 7 integration tests via httpx ASGITransport (111 lines)

## Decisions Made
- Used module-level `_paused` flag pattern for scheduler pause/resume (simpler than per-job pause)
- Pipeline phase wrappers handle different function signatures (es_url for discovery/verify/ingest, not for download/extract)
- Registry injected into api and scheduler modules during FastAPI lifespan (module-level `_registry` variable)
- Installed APScheduler 3.11.2 (was missing from environment)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed missing APScheduler dependency**
- **Found during:** Task 1 (pre-execution check)
- **Issue:** APScheduler not installed in Python environment
- **Fix:** pip install apscheduler (3.11.2 installed)
- **Verification:** Import succeeds, scheduler configures correctly
- **Committed in:** 74d8150 (Task 1 commit)

**2. [Rule 2 - Missing Critical] Added api._registry injection in lifespan**
- **Found during:** Task 2 (integration tests)
- **Issue:** api.py routes need registry but plan only mentioned scheduler.set_registry; api module also needs it
- **Fix:** Added `api_mod._registry = registry` in main.py lifespan alongside set_registry()
- **Files modified:** src/backend/worker/main.py
- **Verification:** All 7 integration tests pass
- **Committed in:** 1180945 (Task 2 GREEN commit)

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 missing critical)
**Impact on plan:** Both fixes necessary for correct operation. No scope creep.

## Issues Encountered
None beyond the auto-fixed deviations above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Worker application fully wired and ready for Dockerfile deployment (Plan 01)
- Internal API ready for web proxy integration (dashboard Plan 05)
- All 10 endpoints functional and tested for admin dashboard consumption

---
## Self-Check: PASSED

All 5 created files verified on disk. All 3 task commits (74d8150, 4abb322, 1180945) verified in git log. 7/7 tests passing.

---
*Phase: 11-fly-io-migration-and-dashboard-and-extensibility*
*Completed: 2026-03-09*
