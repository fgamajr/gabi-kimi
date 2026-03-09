---
phase: 12-fly-io-pre-flight
plan: 04
subsystem: docs
tags: [search-api, ux-principles, postgres, cost-tracking, watchdog, holiday-calendar, rrf]

# Dependency graph
requires:
  - phase: 12-03
    provides: "Enrichment pipeline architecture in unified pipeline document"
provides:
  - "Search API architecture with citizen/professional modes and RRF hybrid scoring"
  - "Progressive disclosure UX principles as pipeline design constraints"
  - "Postgres DDL for auditor_profiles, workspaces, workspace_documents (UUID PKs)"
  - "Cost tracking framework with daily/monthly budget controls"
  - "Holiday-aware watchdog specification with Brazilian calendar"
affects: [search-implementation, enrichment-implementation, cost-monitoring]

# Tech tracking
tech-stack:
  added: []
  patterns: ["citizen-professional-mode-split", "rrf-hybrid-scoring", "budget-controlled-enrichment"]

key-files:
  created: []
  modified:
    - docs/runbooks/AUTONOMOUS_DOU_PIPELINE_PROMPT.md

key-decisions:
  - "RRF constant k=60 for hybrid search ranking"
  - "Daily budget default $2.00, monthly cap $30.00 for enrichment cost control"
  - "Holiday calculation via dateutil easter() for variable Brazilian holidays"
  - "Postgres tables use UUID PKs with gen_random_uuid() matching existing auth schema"

patterns-established:
  - "Citizen-default search: professional mode requires explicit opt-in"
  - "Cost-aware operations: budget check before each enrichment/embedding batch"
  - "Holiday-aware scheduling: skip alerts on Brazilian national holidays"

requirements-completed: [DOC-12, DOC-13]

# Metrics
duration: 3min
completed: 2026-03-09
---

# Phase 12 Plan 04: Search API, UX, Cost, and Watchdog Architecture Summary

**Search API with citizen/professional modes and RRF hybrid scoring, progressive disclosure UX constraints, Postgres user tables (UUID PKs), cost budget controls, and holiday-aware watchdog spec**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-09T19:56:39Z
- **Completed:** 2026-03-09T19:59:47Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Documented search API architecture with citizen mode (default, 90%) and professional mode (10%) with distinct query fields and endpoints
- Added hybrid search specification with Reciprocal Rank Fusion (RRF) formula and BM25/vector fallback behavior
- Documented progressive disclosure UX principles as pipeline design constraints (mobile-first, citizen default, two audiences, shareable content)
- Added Postgres DDL for auditor_profiles, workspaces, and workspace_documents tables with UUID primary keys and quoted auth."user" foreign key references
- Documented cost tracking framework with per-module estimates, daily/monthly budget controls, cost_log SQLite DDL, and cost-aware operational rules
- Added holiday-aware watchdog specification with full Brazilian national holiday calendar (fixed + variable) and watchdog behavior matrix

## Task Commits

Each task was committed atomically:

1. **Task 1: Add search API, UX principles, Postgres extensions, cost tracking, and watchdog spec** - `72f3746` (feat)

## Files Created/Modified
- `docs/runbooks/AUTONOMOUS_DOU_PIPELINE_PROMPT.md` - Added 6 new sections: holiday-aware watchdog, search API architecture, progressive disclosure UX principles, additional Postgres tables, cost tracking and budget controls (+223 lines, 517 -> 740)

## Decisions Made
- RRF constant k=60 (standard value that prevents high-ranked documents from dominating)
- Daily enrichment budget defaults to $2.00, monthly cap to $30.00 -- conservative defaults for a small-scale operation
- Holiday calculation uses dateutil easter() to derive variable holidays (Carnival, Good Friday, Corpus Christi) from Easter Sunday
- All Postgres tables use UUID PKs with gen_random_uuid() to match existing auth schema conventions

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Unified pipeline document now contains complete architectural reference for all planned features
- Ready for implementation phases: search API, enrichment pipeline, cost tracking, watchdog hardening
- All new sections clearly marked as SPECIFICATIONS FOR FUTURE IMPLEMENTATION

## Self-Check: PASSED

- FOUND: docs/runbooks/AUTONOMOUS_DOU_PIPELINE_PROMPT.md
- FOUND: .planning/phases/12-fly-io-pre-flight/12-04-SUMMARY.md
- FOUND: commit 72f3746

---
*Phase: 12-fly-io-pre-flight*
*Completed: 2026-03-09*
