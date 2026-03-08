---
phase: 10-legacy-cleanup
plan: "01"
subsystem: cleanup
tags: alpine, react, frontend, static

requires:
  - phase: 07-upload-ui
  - phase: 08-job-dashboard
provides:
  - Single frontend: React SPA only; no legacy Alpine.js
  - Backend serves only src/frontend/web (dist or index for dev)
affects: (none — final phase)

tech-stack:
  added: (none)
  patterns: WEB_DIR always React app dir; no fallback to web/

key-files:
  created: (none)
  modified: src/backend/apps/web_server.py, .planning/PROJECT.md, .planning/codebase/*.md
  deleted: web/index.html

key-decisions:
  - "Remove web/ entirely (file + empty dir); backend never references legacy dir"
  - "SPA_INDEX remains dist/index.html if present else index.html for dev without build"

patterns-established:
  - "Single frontend: React SPA at src/frontend/web/; backend serves it exclusively"

requirements-completed: [CLEN-01]

duration: 15
completed: "2026-03-08"
---

# Phase 10 Plan 01: Legacy Cleanup Summary

**Alpine.js frontend removed; backend serves only React SPA from src/frontend/web (CLEN-01).**

## Performance

- **Duration:** ~15 min
- **Tasks:** 1 (removal + backend + docs)
- **Files modified/deleted:** 6 + web/index.html deleted

## Accomplishments

- **Deleted:** `web/index.html` (Alpine.js landing); removed empty `web/` directory.
- **Backend:** `web_server.py` now uses only `WEB_DIR = _ROOT_DIR / "src" / "frontend" / "web"`; removed `_LEGACY_WEB_DIR` and fallback logic. SPA_INDEX is `dist/index.html` if built, else `index.html` for dev.
- **Docs:** PROJECT.md (Alpine removal done, React decision outcome); STRUCTURE.md (removed web/ from tree and directory purposes); ARCHITECTURE.md (single frontend); CONCERNS.md (legacy frontend resolved).

## Task Commits

1. **Legacy cleanup** - `3a81111` (feat)

## Files Created/Modified

- `src/backend/apps/web_server.py` - React-only frontend path
- `.planning/PROJECT.md` - checklist and decisions
- `.planning/codebase/STRUCTURE.md` - web/ removed
- `.planning/codebase/ARCHITECTURE.md` - single frontend
- `.planning/codebase/CONCERNS.md` - legacy concern resolved
- Deleted: `web/index.html`

## Decisions Made

- Empty `web/` directory removed after deleting index.html.

## Deviations from Plan

None.

## Issues Encountered

None.

## Self-Check: PASSED

- web/index.html deleted; backend uses only React dir; docs updated. Commit 3a81111 verified.

---
*Phase: 10-legacy-cleanup*
*Completed: 2026-03-08*
*Milestone: GABI Admin Upload complete*
