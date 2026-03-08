---
phase: 09-live-status-and-retry
plan: "01"
subsystem: backend, frontend
tags: sse, event-source, retry, admin, jobs

requires:
  - phase: 08-job-dashboard
    provides: Job list/detail UI, get_job
  - phase: 06-zip-processing
    provides: process_upload_job, worker
provides:
  - GET /api/admin/jobs/{id}/stream: SSE stream of job status until completed/failed/partial (JOBS-05)
  - POST /api/admin/jobs/{id}/retry: re-queue failed/partial job (JOBS-04)
  - Frontend: EventSource in job detail when queued/processing; Retry button when failed/partial
affects: Phase 10 Legacy Cleanup

tech-stack:
  added: retry_job in worker_jobs; StreamingResponse job stream; EventSource in React
  patterns: SSE polling (1s) of get_job; retry resets status to queued and enqueues task

key-files:
  created: (none)
  modified: src/backend/apps/worker_jobs.py, src/backend/apps/web_server.py, src/frontend/web/src/lib/api.ts, src/frontend/web/src/pages/AdminJobsPage.tsx

key-decisions:
  - "SSE stream: poll get_job every 1s and send as event (no worker progress_message column); closes when status terminal"
  - "Retry: retry_job() does direct UPDATE to queued and clears error/counts; then enqueue process_upload_job"
  - "EventSource: open only when detail.id is non-terminal; dependency [detail?.id] to avoid re-opening on every event"

patterns-established:
  - "Job stream URL same-origin so EventSource sends cookies; retry button calls POST then updates detail"

requirements-completed: [JOBS-04, JOBS-05]

duration: 25
completed: "2026-03-08"
---

# Phase 9 Plan 01: Live Status and Retry Summary

**SSE endpoint streams job status until terminal; POST retry re-queues failed/partial jobs; frontend EventSource for live updates and Retry button (JOBS-04, JOBS-05).**

## Performance

- **Duration:** ~25 min
- **Tasks:** 1 (backend stream+retry + frontend)
- **Files modified:** 4

## Accomplishments

- **worker_jobs.retry_job(job_id):** Returns None if job not found or status not failed/partial. Otherwise UPDATE set status=queued, clear error_message, error_detail, completed_at, article counts; RETURNING row.
- **GET /api/admin/jobs/{job_id}/stream:** Async generator polls get_job via asyncio.to_thread every 1s; sends SSE event "job" with JSON payload (dates serialized); stops when status in (completed, failed, partial). Headers: text/event-stream, Cache-Control, Connection keep-alive.
- **POST /api/admin/jobs/{job_id}/retry:** Calls retry_job; 404 if job missing, 400 if status not failed/partial; on success enqueues process_upload_job(job_id) and returns updated job.
- **Frontend:** getAdminJobStreamUrl(jobId), retryAdminJob(jobId). AdminJobsPage: useEffect opens EventSource when detail.id set and status non-terminal; on "job" event updates detail and closes if terminal; Retry button when status failed/partial calls retryAdminJob and updates detail/list.

## Task Commits

1. **Live status SSE + retry** - `493f130` (feat)

## Files Created/Modified

- `src/backend/apps/worker_jobs.py` - retry_job()
- `src/backend/apps/web_server.py` - GET stream, POST retry
- `src/frontend/web/src/lib/api.ts` - stream URL helper, retryAdminJob
- `src/frontend/web/src/pages/AdminJobsPage.tsx` - EventSource effect, Retry button

## Decisions Made

- Progress message "Processing article N of M" not implemented in this phase; stream sends full job row so UI can show status/updated_at; optional progress_message can be added later in worker + schema.
- EventSource does not support custom headers; same-origin requests send cookies for auth.

## Deviations from Plan

None - plan executed as specified.

## Issues Encountered

None.

## Self-Check: PASSED

- retry_job, stream and retry endpoints, frontend stream + retry present. Commit 493f130 verified.

---
*Phase: 09-live-status-and-retry*
*Completed: 2026-03-08*
