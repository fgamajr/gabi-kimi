---
phase: 03-upload-api
plan: "01"
subsystem: api
tags: fastapi, upload, tigris, magic-bytes, worker_jobs

requires:
  - phase: 01-storage-foundation
    provides: Tigris upload_fileobj, is_configured
  - phase: 02-job-control-schema
    provides: create_job, admin.worker_jobs
provides:
  - POST /api/admin/upload returns 202 with job_id
  - File type validation by magic bytes (XML/ZIP only), clear rejection for others
  - Stream to Tigris via upload_fileobj (no full file in memory)
  - Job record in admin.worker_jobs with status queued
affects: Phase 4 Worker, Phase 7 Upload UI

tech-stack:
  added: upload_validation.py (magic-byte detection)
  patterns: Validate then seek(0) then stream; def not async def for psycopg2

key-files:
  created: src/backend/apps/upload_validation.py
  modified: src/backend/apps/web_server.py

key-decisions:
  - "Magic bytes: XML = <?xml or < (after BOM/whitespace); ZIP = PK\\x03\\x04 or PK\\x05\\x06"
  - "Filename sanitized to basename only; storage_key = uploads/{uuid}/{filename}"

patterns-established:
  - "Upload flow: validate_upload_file -> upload_fileobj -> create_job -> 202 {job_id, status}"

requirements-completed: [UPLD-03, UPLD-04, UPLD-05]

duration: 10
completed: "2026-03-08"
---

# Phase 3 Plan 01: Upload API Summary

**POST /api/admin/upload: magic-byte validation (XML/ZIP), stream to Tigris, create queued job, return 202 with job_id.**

## Performance

- **Duration:** ~10 min
- **Tasks:** 2
- **Files created:** 1; **Files modified:** 1

## Accomplishments

- upload_validation.py: detect_upload_type (ZIP/XML magic bytes), validate_upload_file (peek, validate, seek(0))
- POST /api/admin/upload: admin-only; validates file type; streams to Tigris via upload_fileobj; creates job with create_job(); returns 202 {job_id, status: "queued"}
- Non-XML/non-ZIP returns 400 with clear message (UPLD-04)
- No full-file buffering: only peek for validation, then stream (UPLD-03, UPLD-05)

## Task Commits

1. **Task 1: Magic-byte validation** - `80b5ac8` (feat)
2. **Task 2: POST /api/admin/upload** - `40d4842` (feat)

## Files Created/Modified

- `src/backend/apps/upload_validation.py` - PEEK_SIZE, detect_upload_type, validate_upload_file
- `src/backend/apps/web_server.py` - POST /api/admin/upload, _sanitize_upload_filename, MAX_UPLOAD_BYTES constant

## Decisions Made

- Sync endpoint (def) to avoid blocking event loop with psycopg2 create_job (PITFALLS).
- uploaded_by from AuthPrincipal.user_id or token_id for audit.

## Deviations from Plan

None.

## Issues Encountered

None.

## Self-Check: PASSED

- upload_validation.py, web_server.py POST /api/admin/upload present. Commits 80b5ac8, 40d4842 present.

---
*Phase: 03-upload-api*
*Completed: 2026-03-08*
