---
phase: 06-zip-processing
plan: "01"
subsystem: processing
tags: dou_ingest, arq, worker, zip, zip-slip, partial-success

requires:
  - phase: 05-single-xml-processing
    provides: process_upload_job, ingest_zip/ingest_single_xml, update_job_status
provides:
  - ZIP Slip protection in ingest_zip (reject path traversal / absolute paths before extract)
  - Partial success: documents_dup and documents_failed in ZIPIngestResult; job status "partial" when some fail
  - Job record: total (articles_found), ingested, dup, failed and error_message (first 5 errors)
affects: Phase 8 Job Dashboard (displays partial/failed counts)

tech-stack:
  added: (none)
  patterns: Per-article try/except in ingest loop; commit after loop so successful inserts persist

key-files:
  created: (none)
  modified: src/backend/ingest/dou_ingest.py, src/backend/workers/arq_worker.py

key-decisions:
  - "ZIP Slip: reject any entry with name.startswith('/') or '..' in name; abort ZIP and cleanup (no partial extract)"
  - "Partial success: ingest_zip continues on per-article exception; documents_failed and errors[]; worker sets status 'partial' when documents_failed > 0 and documents_inserted > 0"

patterns-established:
  - "Job status partial with articles_found, articles_ingested, articles_dup, articles_failed, error_message"

requirements-completed: [PROC-02, PROC-05, PROC-06]

duration: 15
completed: "2026-03-08"
---

# Phase 6 Plan 01: ZIP Processing Summary

**ZIP Slip protection on extraction; partial success with accurate per-article counts (ingested, dup, failed) and job status "partial" when some articles fail.**

## Performance

- **Duration:** ~15 min
- **Tasks:** 1 (ZIP Slip + partial/counts + worker status)
- **Files modified:** 2

## Accomplishments

- **ZIP Slip (PROC-06):** In `ingest_zip`, before extracting each ZIP entry, reject if `name.startswith("/")` or `".." in name`; append error, set `success=False`, cleanup extract dir, return (no extraction).
- **Contagens:** `ZIPIngestResult` already had `documents_dup` and `documents_failed`. In `ingest_zip` and `ingest_single_xml`: on `_insert_document` return, if `inserted` then `documents_inserted += 1`, else `documents_dup += 1`; on exception `documents_failed += 1` and append to `errors`; loop continues so partial success is persisted on `conn.commit()`.
- **Worker:** Use `result.documents_dup` and `result.documents_failed` (no formula). If `result.success` and `documents_failed > 0` and `documents_inserted > 0` → status **"partial"**, else **"completed"**. Pass `articles_found`, `articles_ingested`, `articles_dup`, `articles_failed`, and `error_message` (first 5 errors) for partial/failed.

## Task Commits

1. **ZIP Slip + partial success + worker status** - `9819e99` (feat)

## Files Created/Modified

- `src/backend/ingest/dou_ingest.py` - ZIP Slip check in extract loop; documents_dup/documents_failed in both ingest_zip and ingest_single_xml insert loops
- `src/backend/workers/arq_worker.py` - status "partial", result.documents_dup/result.documents_failed, error_message for partial/failed

## Decisions Made

- ZIP Slip aborts entire ZIP (no partial extract) to avoid any path escape.
- Partial success: per-article exceptions do not rollback; commit at end so all successful inserts are kept.

## Deviations from Plan

None - plan executed as specified.

## Issues Encountered

None.

## Self-Check: PASSED

- ZIP Slip check present in ingest_zip (path validation). documents_dup/documents_failed updated in both ingest paths. Worker sets partial and passes counts. Commits 9819e99, bb8bd85 present.

---
*Phase: 06-zip-processing*
*Completed: 2026-03-08*
