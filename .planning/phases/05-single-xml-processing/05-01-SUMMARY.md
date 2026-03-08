---
phase: 05-single-xml-processing
plan: "01"
subsystem: processing
tags: dou_ingest, arq, worker, elasticsearch, dedup

requires:
  - phase: 03-upload-api
    provides: POST upload, job creation, Tigris storage_key
  - phase: 04-worker-infrastructure
    provides: ARQ worker, process groups
provides:
  - Upload creates job and enqueues process_upload_job(job_id)
  - Worker: claim, download from Tigris, ingest_single_xml / ingest_zip, ES sync, update job
  - Deduplication via ON CONFLICT (id_materia) DO NOTHING (PROC-04, PROC-07)
  - Job transitions queued -> processing -> completed/failed with article counts
affects: Phase 6 ZIP Processing, Phase 8 Job Dashboard

tech-stack:
  added: ingest_single_xml, process_upload_job, upload enqueue
  patterns: Same dou.* pipeline for single XML; worker claims then runs ingest then ES sync

key-files:
  created: (none)
  modified: src/backend/ingest/dou_ingest.py, src/backend/workers/arq_worker.py, src/backend/apps/web_server.py

key-decisions:
  - "Single XML path: DOUIngestor.ingest_single_xml reuses parse/merge/filter/DB path; synthetic source_zip row"
  - "ES sync: worker calls es_indexer._run_sync after ingest so new docs appear in search"

patterns-established:
  - "Upload -> create_job -> enqueue process_upload_job; worker claim -> download -> ingest -> ES sync -> update_job_status"

requirements-completed: [PROC-01, PROC-03, PROC-04, PROC-07]

duration: 18
completed: "2026-03-08"
---

# Phase 5 Plan 01: Single XML Processing Summary

**End-to-end: upload XML -> job queued -> worker ingests to dou.* and ES, job completed with article counts; dedup and idempotent.**

## Performance

- **Duration:** ~18 min
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- DOUIngestor.ingest_single_xml(xml_path): parse one XML, group_and_merge/merge_page_fragments/filter, same _insert_document path; ZIPIngestResult.articles_found for counts
- process_upload_job(ctx, job_id): claim_job_for_processing, download from Tigris to temp, ingest_single_xml (xml) or ingest_zip (zip), _run_sync to Elasticsearch, update_job_status completed/failed with articles_found/ingested/dup/failed
- POST /api/admin/upload: after create_job, enqueue ARQ process_upload_job(job_id) when REDIS_URL set
- Dedup: existing ON CONFLICT (id_materia) DO NOTHING; idempotent reprocess (PROC-04, PROC-07)

## Task Commits

1. **Task 1: ingest_single_xml** - `3681ded` (feat)
2. **Task 2: process_upload_job** - `68da25c` (feat)
3. **Task 3: Upload enqueue** - `4ba998b` (feat)

## Files Created/Modified

- `src/backend/ingest/dou_ingest.py` - ingest_single_xml, articles_found on ZIPIngestResult
- `src/backend/workers/arq_worker.py` - process_upload_job (claim, download, ingest, ES sync, update)
- `src/backend/apps/web_server.py` - asyncio.run(_enqueue()) after create_job

## Decisions Made

- Single XML uses same source_zip/dou.* path as ZIP with synthetic filename/sha/size; _infer_zip_meta from filename for month/section when possible.
- Worker runs ES sync after each job so new documents appear in search without separate cron.

## Deviations from Plan

None.

## Issues Encountered

None.

## Self-Check: PASSED

- dou_ingest.ingest_single_xml, arq_worker.process_upload_job, web_server enqueue present. Commits 3681ded, 68da25c, 4ba998b present.

---
*Phase: 05-single-xml-processing*
*Completed: 2026-03-08*
