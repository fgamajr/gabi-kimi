---
phase: 16-tear-down
plan: 03
subsystem: api
tags: [fastapi, react-query, typescript, scada, pipeline]

requires:
  - phase: 16-02
    provides: "BM25-only pipeline with scheduler job control and status tracking"
provides:
  - "GET /registry/plant-status aggregated SCADA dashboard endpoint"
  - "POST /pipeline/stage/{name}/pause|resume|trigger per-stage control"
  - "POST /pipeline/pause-all and resume-all master control"
  - "PlantStatus, PlantStage, PlantStorage, PlantTotals TypeScript types"
  - "React Query hooks: usePlantStatus, useStagePause, useStageResume, useStageTrigger, usePauseAll, useResumeAll"
affects: [16-04, frontend-dashboard]

tech-stack:
  added: []
  patterns: ["SCADA aggregation endpoint collects from registry + scheduler + main", "Stage state derivation: PAUSED > ERROR > IDLE > AUTO priority"]

key-files:
  created: []
  modified:
    - src/backend/worker/api.py
    - src/frontend/web/src/types/pipeline.ts
    - src/frontend/web/src/lib/workerApi.ts
    - src/frontend/web/src/hooks/usePipeline.ts
    - tests/test_pipeline/test_worker_api.py

key-decisions:
  - "Stage state derived from is_job_enabled + master_paused + failed_count, not just scheduler job dict"
  - "PENDING_GROUPS and FAILURE_GROUPS dicts map file statuses to pipeline stages for queue_depth/failed_count"

patterns-established:
  - "Plant-status endpoint aggregates all dashboard data in single response for SCADA panel"
  - "Stage control routes delegate to existing scheduler set_job_enabled/trigger_phase"

requirements-completed: [DASH-01, DASH-02]

duration: 3min
completed: 2026-03-11
---

# Phase 16 Plan 03: Plant-Status API Summary

**Single aggregation endpoint returning stages, storage, totals for SCADA dashboard with per-stage pause/resume/trigger control and TypeScript hooks**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-11T03:28:53Z
- **Completed:** 2026-03-11T03:31:38Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- GET /registry/plant-status returns all 7 pipeline stages with state derivation (AUTO/PAUSED/ERROR/IDLE), queue_depth, failed_count, throughput, storage, totals
- Per-stage control: POST /pipeline/stage/{name}/pause|resume|trigger delegates to existing scheduler infrastructure
- PlantStatus TypeScript types and 6 React Query hooks ready for SCADA dashboard frontend consumption
- 24 tests passing (9 new plant-status/stage tests + 15 existing)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create plant-status endpoint and stage control routes**
   - `f58e2f33` (test) - TDD RED: failing tests for plant-status and stage control
   - `cf06e87e` (feat) - TDD GREEN: implement endpoints, all tests passing
2. **Task 2: Define PlantStatus TypeScript types and workerApi methods** - `c6689ee7` (feat)

## Files Created/Modified
- `src/backend/worker/api.py` - Plant-status aggregation endpoint + stage control routes (pause/resume/trigger/pause-all/resume-all)
- `tests/test_pipeline/test_worker_api.py` - 9 new tests for plant-status shape, state derivation, stage control
- `src/frontend/web/src/types/pipeline.ts` - PlantStatus, PlantStage, PlantStorage, PlantTotals, StageState types
- `src/frontend/web/src/lib/workerApi.ts` - getPlantStatus, stagePause, stageResume, stageTrigger, pauseAll, resumeAll methods
- `src/frontend/web/src/hooks/usePipeline.ts` - usePlantStatus, useStagePause, useStageResume, useStageTrigger, usePauseAll, useResumeAll hooks

## Decisions Made
- Stage state derivation checks `is_job_enabled()` dict first (not just scheduler job object), since test environment may not have scheduler jobs but `_job_enabled` dict still tracks disabled state
- PENDING_GROUPS maps BM25_INDEXED to both embed and verify stages (dual-path from 16-02 design)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed stage state derivation for missing scheduler jobs**
- **Found during:** Task 1 (TDD GREEN phase)
- **Issue:** `_derive_stage_state` checked `job.get("enabled")` but job was None when scheduler has no registered jobs (test env), causing IDLE instead of PAUSED for disabled stages
- **Fix:** Added `is_job_enabled(phase_id)` check at top of `_derive_stage_state` to consult the `_job_enabled` dict directly, independent of scheduler job presence
- **Files modified:** src/backend/worker/api.py
- **Verification:** All 9 new tests pass including `test_plant_status_stage_state_paused`
- **Committed in:** cf06e87e (Task 1 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Essential for correctness. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Backend API ready for SCADA dashboard frontend (16-04)
- All types and hooks in place for React component consumption
- Existing pipeline runs and scheduler data flows through plant-status aggregation

---
*Phase: 16-tear-down*
*Completed: 2026-03-11*
