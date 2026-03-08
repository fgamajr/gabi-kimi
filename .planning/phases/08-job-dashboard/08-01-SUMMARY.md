---
phase: 08-job-dashboard
plan: "01"
subsystem: frontend
tags: react, admin, jobs, audit-log, table, dialog

requires:
  - phase: 07-upload-ui
    provides: Admin upload page, auth
  - phase: 02-job-control-schema
    provides: GET /api/admin/jobs, GET /api/admin/jobs/{id}
provides:
  - Job list page at /admin/jobs (filename, status, submitted, completed, article count)
  - Job detail dialog with per-article breakdown (ingested, dup, failed) and error_message
  - Upload history as read-only audit log (no delete); link from Upload to Jobs
affects: Phase 9 Live Status and Retry (job list is base for retry/SSE)

tech-stack:
  added: getAdminJobsList, getAdminJobDetail in api.ts
  patterns: Table + Dialog for list/detail; date-fns for locale formatting

key-files:
  created: src/frontend/web/src/pages/AdminJobsPage.tsx
  modified: src/frontend/web/src/lib/api.ts, src/frontend/web/src/App.tsx, src/frontend/web/src/components/layout/AppShell.tsx, src/frontend/web/src/pages/AdminUploadPage.tsx

key-decisions:
  - "Detail as modal (Dialog) instead of separate page to keep context"
  - "Audit log: no delete in backend or UI; list is immutable history"
  - "Article count in table: articles_found if set, else sum of ingested+dup+failed"

patterns-established:
  - "Admin jobs: list then click row to open detail with breakdown and error_message"

requirements-completed: [JOBS-01, JOBS-02, JOBS-03, JOBS-06]

duration: 20
completed: "2026-03-08"
---

# Phase 8 Plan 01: Job Dashboard Summary

**Job list table with filename, status, submitted/completed time, article count; detail dialog with per-article breakdown and human-readable error_message; upload history as read-only audit log (JOBS-01, 02, 03, 06).**

## Performance

- **Duration:** ~20 min
- **Tasks:** 1 (dashboard + API + nav)
- **Files modified/created:** 5

## Accomplishments

- **api.ts:** `AdminJobListItem`, `AdminJobDetail`, `getAdminJobsList(limit, offset)`, `getAdminJobDetail(jobId)` using resolveApiUrl and fetchJSON (credentials via apiFetch).
- **AdminJobsPage:** Table columns: filename, status (Badge), submitted (created_at), completed (completed_at), article count (articles_found or sum). Click row opens Dialog: filename, status, dates, uploaded_by, breakdown (total, ingested, dup, failed), error_message in a highlighted block. Copy: "Histórico de envios (somente leitura, audit log)" and link "Novo upload" to /admin/upload.
- **Route:** /admin/jobs with ProtectedRoute admin. Nav: "Jobs" in dropdown and rail; Upload page: "Ver jobs" link to /admin/jobs.
- **Audit (JOBS-06):** Backend has no delete endpoint; UI is read-only; job list is immutable history.

## Task Commits

1. **Job Dashboard (API, page, route, nav, link)** - `66e42ff` (feat)

## Files Created/Modified

- `src/frontend/web/src/pages/AdminJobsPage.tsx` - list table + detail dialog
- `src/frontend/web/src/lib/api.ts` - jobs types and fetch helpers
- `src/frontend/web/src/App.tsx` - route /admin/jobs
- `src/frontend/web/src/components/layout/AppShell.tsx` - Jobs in menu and nav
- `src/frontend/web/src/pages/AdminUploadPage.tsx` - link "Ver jobs"

## Decisions Made

- Status labels in Portuguese in Badge (Na fila, Processando, Concluído, Parcial, Falhou).
- Detail fetches job by id on row click; error_message shown as-is from backend (worker already sends human-readable messages).

## Deviations from Plan

None - plan executed as specified.

## Issues Encountered

None.

## Self-Check: PASSED

- AdminJobsPage, api jobs helpers, route and nav present. Commit 66e42ff verified.

---
*Phase: 08-job-dashboard*
*Completed: 2026-03-08*
