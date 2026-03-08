---
phase: 02-job-control-schema
plan: "01"
subsystem: database
tags: postgresql, admin.worker_jobs, job lifecycle, fastapi

requires:
  - phase: 01-storage-foundation
    provides: Tigris storage for uploads (Phase 3 will write blobs)
provides:
  - admin.worker_jobs table with status, filename, timestamps, article counts, error details
  - Status transitions enforced (queued -> processing -> completed|failed|partial)
  - FastAPI queryable via GET /api/admin/jobs and GET /api/admin/jobs/{id}
  - ensure_worker_jobs_schema at app startup
affects: Phase 3 Upload API, Phase 4 Worker, Phase 8 Job Dashboard

tech-stack:
  added: admin.worker_jobs schema, worker_jobs.py (raw psycopg2)
  patterns: Bootstrap schema from SQL file (split by ";"), transition validation in Python

key-files:
  created: src/backend/dbsync/worker_jobs_schema.sql, src/backend/apps/worker_jobs.py
  modified: src/backend/apps/web_server.py

key-decisions:
  - "Table name worker_jobs in schema admin (ROADMAP); status values match success criteria"
  - "Transitions enforced in update_job_status and claim_job_for_processing (no DB trigger)"

patterns-established:
  - "Job CRUD in dedicated module; schema applied at startup like auth_schema"

requirements-completed: [INFRA-02]

duration: 12
completed: "2026-03-08"
---

# Phase 2 Plan 01: Job Control Schema Summary

**PostgreSQL admin.worker_jobs table with full job lifecycle, transition enforcement, and FastAPI list/detail endpoints.**

## Performance

- **Duration:** ~12 min
- **Tasks:** 3
- **Files created:** 2; **Files modified:** 1

## Accomplishments

- Migration `worker_jobs_schema.sql`: admin.worker_jobs with id, filename, storage_key, file_type, status, article counts, error_message, error_detail, timestamps
- Status CHECK: queued, processing, completed, failed, partial; transitions enforced in worker_jobs.update_job_status and claim_job_for_processing
- worker_jobs.py: ensure_worker_jobs_schema(), create_job(), get_job(), list_jobs(), update_job_status(), claim_job_for_processing()
- FastAPI: ensure_worker_jobs_schema() in lifespan; GET /api/admin/jobs (list), GET /api/admin/jobs/{job_id} (detail)

## Task Commits

1. **Task 1: admin.worker_jobs schema** - `c58e439` (feat)
2. **Task 2: worker_jobs module (CRUD + transitions)** - `702ef47` (feat)
3. **Task 3: startup ensure + GET jobs API** - `80b4c15` (feat)

## Files Created/Modified

- `src/backend/dbsync/worker_jobs_schema.sql` - CREATE SCHEMA admin, CREATE TABLE worker_jobs, indexes
- `src/backend/apps/worker_jobs.py` - schema ensure, create/get/list/update/claim with transition checks
- `src/backend/apps/web_server.py` - lifespan ensure, GET /api/admin/jobs, GET /api/admin/jobs/{job_id}

## Decisions Made

- Raw psycopg2 (no SQLAlchemy) to match existing identity_store and dbsync patterns.
- Constraint names chk_worker_jobs_file_type and chk_worker_jobs_status to allow single-statement split by ";" for bootstrap.

## Deviations from Plan

None.

## Issues Encountered

None.

## Next Phase Readiness

- Phase 3 (Upload API) can create jobs via create_job() and write blobs to Tigris; worker (Phase 4/5) will use claim_job_for_processing and update_job_status.

## Self-Check: PASSED

- 02-01-SUMMARY.md, worker_jobs_schema.sql, worker_jobs.py exist. Commits c58e439, 702ef47, 80b4c15 present.

---
*Phase: 02-job-control-schema*
*Completed: 2026-03-08*
