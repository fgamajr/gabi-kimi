# Roadmap: GABI Admin Upload

## Overview

Deliver an admin document upload pipeline for GABI: from Tigris blob storage and job tracking schema, through upload API and ARQ background workers, to a React admin UI with real-time job monitoring. The journey moves from infrastructure foundation to backend processing to frontend experience, ending with legacy cleanup. Each phase delivers a testable capability that builds on the previous.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Storage Foundation** - Tigris blob storage bucket configured and accessible from FastAPI
- [ ] **Phase 2: Job Control Schema** - PostgreSQL worker control table with full job lifecycle tracking
- [ ] **Phase 3: Upload API** - FastAPI endpoints that accept files, stream to Tigris, and return job IDs
- [ ] **Phase 4: Worker Infrastructure** - ARQ worker running as separate Fly.io process group
- [ ] **Phase 5: Single XML Processing** - Worker ingests individual XML files through the existing pipeline
- [ ] **Phase 6: ZIP Processing** - Worker handles ZIP bundles with partial success and security protections
- [ ] **Phase 7: Upload UI** - React admin page with drag-drop upload, preview, and paste input
- [ ] **Phase 8: Job Dashboard** - React job list and detail views showing ingestion results
- [ ] **Phase 9: Live Status and Retry** - Real-time SSE progress streaming and one-click job retry
- [ ] **Phase 10: Legacy Cleanup** - Remove Alpine.js frontend from codebase

## Phase Details

### Phase 1: Storage Foundation
**Goal**: A working Tigris blob storage bucket that FastAPI can read from and write to
**Depends on**: Nothing (first phase)
**Requirements**: INFRA-01
**Success Criteria** (what must be TRUE):
  1. A Tigris bucket exists and is bound to the Fly.io app
  2. FastAPI can upload a test file to Tigris and read it back via boto3
  3. Tigris credentials are available as environment variables in the Fly.io app
**Plans**: 01-01 done

Plans:
- [x] 01-01: Tigris module, runbook, storage-check endpoint

### Phase 2: Job Control Schema
**Goal**: A PostgreSQL table that tracks the full lifecycle of upload jobs
**Depends on**: Phase 1
**Requirements**: INFRA-02
**Success Criteria** (what must be TRUE):
  1. A migration creates the worker_jobs table with columns for status, filename, timestamps, article counts, and error details
  2. Job status transitions are enforced (queued -> processing -> completed/failed/partial)
  3. The job table is queryable from FastAPI via SQLAlchemy or raw SQL
**Plans**: 02-01 done

Plans:
- [x] 02-01: worker_jobs schema, module, GET /api/admin/jobs

### Phase 3: Upload API
**Goal**: Admins can upload files via API and receive an immediate job ID while the file lands in Tigris
**Depends on**: Phase 1, Phase 2
**Requirements**: UPLD-03, UPLD-04, UPLD-05
**Success Criteria** (what must be TRUE):
  1. POST to the upload endpoint with an XML or ZIP file returns HTTP 202 with a job ID
  2. The uploaded file exists in Tigris blob storage after the request completes
  3. A job record exists in the worker_jobs table with status "queued"
  4. Uploading a non-XML/non-ZIP file (e.g., PNG) returns an error with a clear rejection message
  5. The upload streams to Tigris without buffering the full file in server memory
**Plans**: TBD

Plans:
- [ ] 03-01: TBD

### Phase 4: Worker Infrastructure
**Goal**: An ARQ worker process runs alongside the web process on Fly.io, ready to consume jobs from Redis
**Depends on**: Phase 2
**Requirements**: INFRA-03, INFRA-04
**Success Criteria** (what must be TRUE):
  1. fly.toml defines both web and worker process groups with correct entrypoints
  2. The worker process starts successfully and connects to Redis as an ARQ worker
  3. The worker process has 1GB+ RAM allocated
  4. Enqueuing a test task via Redis results in the worker picking it up and executing it
**Plans**: TBD

Plans:
- [ ] 04-01: TBD

### Phase 5: Single XML Processing
**Goal**: The worker can take a queued job for a single XML file and ingest it into the search index
**Depends on**: Phase 3, Phase 4
**Requirements**: PROC-01, PROC-03, PROC-04, PROC-07
**Success Criteria** (what must be TRUE):
  1. Uploading a valid XML file via the API results in its articles appearing in Elasticsearch search results
  2. Uploading the same XML file twice does not create duplicate articles (deduplication via natural_key_hash)
  3. The job record transitions from "queued" to "processing" to "completed" with correct article counts
  4. Processing the same file again produces the same outcome without side effects (idempotent)
**Plans**: TBD

Plans:
- [ ] 05-01: TBD

### Phase 6: ZIP Processing
**Goal**: The worker handles ZIP bundles containing multiple XML files with robust error handling
**Depends on**: Phase 5
**Requirements**: PROC-02, PROC-05, PROC-06
**Success Criteria** (what must be TRUE):
  1. Uploading a ZIP with multiple XML files results in all valid articles being ingested
  2. If some articles in a ZIP fail, the rest are still ingested and the job status shows "partial" with failure details
  3. A crafted ZIP with path traversal entries (ZIP Slip) is rejected without extracting malicious paths
  4. The job record accurately reports total articles, ingested count, skipped/duplicate count, and failed count
**Plans**: TBD

Plans:
- [ ] 06-01: TBD

### Phase 7: Upload UI
**Goal**: Admins have a complete upload experience in the React frontend
**Depends on**: Phase 3
**Requirements**: UPLD-01, UPLD-02, UPLD-06, UPLD-07, UPLD-08
**Success Criteria** (what must be TRUE):
  1. Admin can drag-and-drop an XML file onto the upload area or use a file picker to select it
  2. Admin can upload a ZIP bundle (up to 200MB) using the same interface
  3. Admin sees a progress indicator during file upload
  4. Before uploading an XML file, admin can preview detected article count, date range, and DOU sections
  5. Admin can switch to a "paste" tab and submit raw XML content for single-article ingestion
**Plans**: TBD

Plans:
- [ ] 07-01: TBD

### Phase 8: Job Dashboard
**Goal**: Admins can monitor and audit all upload jobs with detailed per-article breakdowns
**Depends on**: Phase 5
**Requirements**: JOBS-01, JOBS-02, JOBS-03, JOBS-06
**Success Criteria** (what must be TRUE):
  1. Admin sees a job list table with columns: filename, status, submitted time, completed time, article count
  2. Clicking a job opens a detail view showing per-article breakdown (ingested, skipped/duplicate, failed)
  3. Error messages are human-readable (e.g., "Duplicate article", "Invalid XML at line 42", "Missing field: artType")
  4. Upload history is immutable and serves as an audit log of who uploaded what, when, and the outcome
**Plans**: TBD

Plans:
- [ ] 08-01: TBD

### Phase 9: Live Status and Retry
**Goal**: Admins see processing progress in real time and can retry failed jobs
**Depends on**: Phase 6, Phase 8
**Requirements**: JOBS-04, JOBS-05
**Success Criteria** (what must be TRUE):
  1. While a job is processing, the admin sees real-time progress updates (e.g., "Processing article 124 of 500")
  2. Progress streams via SSE without requiring page refresh or manual polling
  3. Admin can retry a failed job with one click, which re-reads the file from Tigris and reprocesses it
**Plans**: TBD

Plans:
- [ ] 09-01: TBD

### Phase 10: Legacy Cleanup
**Goal**: The old Alpine.js frontend is removed, leaving only the React SPA
**Depends on**: Phase 7, Phase 8
**Requirements**: CLEN-01
**Success Criteria** (what must be TRUE):
  1. The file web/index.html (Alpine.js frontend) no longer exists in the codebase
  2. The React SPA at /dist/ is the only frontend served by the backend
**Plans**: TBD

Plans:
- [ ] 10-01: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9 -> 10

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Storage Foundation | 1/1 | Complete | 2026-03-08 |
| 2. Job Control Schema | 1/1 | Complete | 2026-03-08 |
| 3. Upload API | 0/? | Not started | - |
| 4. Worker Infrastructure | 0/? | Not started | - |
| 5. Single XML Processing | 0/? | Not started | - |
| 6. ZIP Processing | 0/? | Not started | - |
| 7. Upload UI | 0/? | Not started | - |
| 8. Job Dashboard | 0/? | Not started | - |
| 9. Live Status and Retry | 0/? | Not started | - |
| 10. Legacy Cleanup | 0/? | Not started | - |
