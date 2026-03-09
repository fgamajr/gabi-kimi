# Requirements: GABI Admin Upload

**Defined:** 2026-03-08
**Core Value:** Admins can upload DOU documents (XML/ZIP) and see them ingested into the search index via background processing

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Infrastructure

- [x] **INFRA-01**: Tigris blob storage bucket created and accessible from FastAPI via boto3
- [x] **INFRA-02**: Worker control table in PostgreSQL tracks job lifecycle (queued → processing → completed/failed/partial)
- [x] **INFRA-03**: ARQ worker runs as separate Fly.io process group with 1GB+ RAM
- [x] **INFRA-04**: fly.toml updated with web + worker process groups and correct entrypoints

### Upload

- [x] **UPLD-01**: Admin can upload a single XML file via drag-and-drop or file picker
- [x] **UPLD-02**: Admin can upload a ZIP bundle of XML files (up to 200MB)
- [x] **UPLD-03**: Upload streams directly to Tigris blob storage (no local disk buffering)
- [x] **UPLD-04**: Server validates file type (XML/ZIP only) via magic bytes, rejects others with clear message
- [x] **UPLD-05**: Upload returns HTTP 202 with job ID immediately after blob write completes
- [x] **UPLD-06**: Admin sees upload progress indicator during file transfer
- [x] **UPLD-07**: Admin can preview XML before upload — client-side parse shows article count, date range, sections detected
- [x] **UPLD-08**: Admin can paste XML content directly via textarea tab for single-article ingestion

### Processing

- [x] **PROC-01**: Worker picks up queued jobs and processes them using existing ingestion pipeline (xml_parser → normalizer → registry_ingest → ES indexer)
- [x] **PROC-02**: Worker handles ZIP files: unzip → parse each XML → normalize → deduplicate → ingest
- [x] **PROC-03**: Worker handles single XML files: parse → normalize → deduplicate → ingest
- [x] **PROC-04**: Deduplication uses existing natural_key_hash — duplicate articles are skipped, not errored
- [x] **PROC-05**: Partial success supported — if ZIP has 500 articles and 3 fail, 497 are ingested and 3 failures surfaced
- [x] **PROC-06**: ZIP Slip protection — validate all extracted paths are within target directory
- [x] **PROC-07**: Processing is idempotent — re-processing same file produces same result without duplicates

### Job Tracking

- [x] **JOBS-01**: Admin sees job list with columns: filename, status, submitted time, completed time, article count
- [x] **JOBS-02**: Admin can click into job detail showing per-article breakdown (ingested, skipped/duplicate, failed with error message)
- [x] **JOBS-03**: Error messages are human-readable: "Duplicate article", "Invalid XML at line N", "Missing field: artType"
- [x] **JOBS-04**: Admin can retry a failed job with one click (re-reads file from blob storage)
- [x] **JOBS-05**: Job progress streams in real-time via SSE ("Processing article 124 of 500")
- [x] **JOBS-06**: Upload history serves as audit log — who uploaded what, when, outcome (immutable)

### Cleanup

- [x] **CLEN-01**: Legacy Alpine.js frontend (`web/index.html`) removed from codebase

## Phase 11 Requirements

### Fly.io Multi-App Infrastructure

- [x] **FLY-01**: Elasticsearch runs on a dedicated Fly.io machine (performance-2x, 4GB RAM, 50GB volume) with single-node config
- [x] **FLY-02**: Worker runs on a dedicated Fly.io machine (shared-cpu-1x, 512MB, volume at /data) with APScheduler + internal FastAPI
- [x] **FLY-03**: Web FastAPI proxies `/api/worker/*` requests to `worker.internal:8081` via httpx
- [x] **FLY-04**: All 3 machines in `gru` region, communicating via `.internal` DNS (6PN private network)

### Autonomous Pipeline

- [x] **PIPE-01**: SQLite registry in WAL mode tracks all DOU files with state machine (DISCOVERED → ... → VERIFIED)
- [x] **PIPE-02**: Discovery crawls Liferay JSONWS API to find new DOU publications, rate-limited to 5 req/s
- [x] **PIPE-03**: Downloader fetches ZIPs from in.gov.br with rate limiting and retry (up to 3 retries)
- [x] **PIPE-04**: Extractor handles multi-era ZIP formats (2002-2018 vs 2019+), detects encoding (chardet)
- [x] **PIPE-05**: Ingestor parses XML, normalizes, and bulk-indexes to ES (bypasses PostgreSQL)
- [x] **PIPE-06**: Verifier confirms doc counts in ES match expected counts per file
- [x] **PIPE-07**: APScheduler runs 5 cron jobs (discovery 23:00, download 23:30, ingest 00:00, verify 01:00, retry 06:00)
- [x] **PIPE-08**: Migration script converts `dou_catalog_registry.json` to SQLite, cross-references ES for already-ingested files

### Admin Dashboard

- [x] **DASH-01**: Pipeline page with tab navigation (Overview, Timeline, Pipeline, Logs, Settings)
- [x] **DASH-02**: Overview tab shows health badge, metric cards, recent activity, coverage by year, quick actions
- [x] **DASH-03**: Timeline tab shows month-by-month detail with per-file status, retry/log actions
- [x] **DASH-04**: Pipeline tab shows scheduler status, next run times, execution history
- [x] **DASH-05**: Logs tab shows filterable event log stream (by level, file, run)
- [x] **DASH-06**: Settings tab shows schedule config, disk usage, danger zone
- [x] **DASH-07**: Dashboard auto-refreshes every 30s via React Query

## Phase 12 Requirements

### Documentation Patches

- [x] **DOC-01**: CRITICAL SOURCE WINDOW RULE block inserted verbatim (INLABS 30-day window, fallback strategy)
- [x] **DOC-02**: 5-app topology diagram replaces incorrect 3-app diagram (frontend, web, worker, ES, Redis)
- [x] **DOC-03**: EXISTING INFRASTRUCTURE section documents implemented features with DO NOT rewrite directives
- [x] **DOC-04**: FALLBACK_PENDING lifecycle state documented with dou_catalog_months DDL
- [x] **DOC-05**: Catalog Reconciler MODULE 6B documented with class docstring specification
- [x] **DOC-06**: Dual-worker clarification distinguishes ARQ upload_worker from autonomous pipeline worker
- [x] **DOC-07**: INLABS auth details documented (login flow, cookie, rate limits, audit logging)
- [x] **DOC-08**: Execution order updated to reflect current codebase state (5-step gap-focused plan)
- [x] **DOC-09**: Modular usage note explains how to consume the document as focused slices

### ULTRA MEGA PROMPT Extensions

- [x] **DOC-10**: Enrichment pipeline modules (DocumentEnricher, HighlightsGenerator, FeedGenerator) spec'd with input/output contracts and cost model
- [x] **DOC-11**: Extended ES mapping and SQLite registry columns for enrichment fields and state tracking documented
- [ ] **DOC-12**: Search API architecture documents citizen vs professional modes with hybrid RRF scoring, plus Postgres tables (auditor_profiles, workspaces)
- [ ] **DOC-13**: Cost tracking/budget controls and holiday-aware watchdog spec with Brazilian holiday calendar

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Polish

- **PLSH-01**: Deduplication preview — show how many articles already exist before processing
- **PLSH-02**: Bulk job management — select multiple jobs, retry all failed, clear completed
- **PLSH-03**: Ingestion statistics dashboard — articles per day, error rates, processing duration
- **PLSH-04**: Vite dev proxy configuration for local development

## Out of Scope

| Feature | Reason |
|---------|--------|
| In-browser document editor | Read-only platform; editing violates CRSS-1 data integrity |
| Scheduled upload from UI | Automated pipeline already handles scheduling via orchestrator.py |
| Email notifications | Over-engineering for small admin team; job status visible in panel |
| Upload from URL | Adds complexity; admin can download locally first |
| OCR / PDF-to-XML conversion | DOU publishes structured XML; OCR is unnecessary complexity |
| Public upload endpoint | Upload is admin-only; data quality risk if opened to non-admins |
| Version rollback | Registry is append-only (CRSS-1 sealed); ingest corrected versions instead |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 1 | Complete |
| INFRA-02 | Phase 2 | Complete |
| INFRA-03 | Phase 4 | Complete |
| INFRA-04 | Phase 4 | Complete |
| UPLD-01 | Phase 7 | Complete |
| UPLD-02 | Phase 7 | Complete |
| UPLD-03 | Phase 3 | Complete |
| UPLD-04 | Phase 3 | Complete |
| UPLD-05 | Phase 3 | Complete |
| UPLD-06 | Phase 7 | Complete |
| UPLD-07 | Phase 7 | Complete |
| UPLD-08 | Phase 7 | Complete |
| PROC-01 | Phase 5 | Complete |
| PROC-02 | Phase 6 | Complete |
| PROC-03 | Phase 5 | Complete |
| PROC-04 | Phase 5 | Complete |
| PROC-05 | Phase 6 | Complete |
| PROC-06 | Phase 6 | Complete |
| PROC-07 | Phase 5 | Complete |
| JOBS-01 | Phase 8 | Complete |
| JOBS-02 | Phase 8 | Complete |
| JOBS-03 | Phase 8 | Complete |
| JOBS-04 | Phase 9 | Complete |
| JOBS-05 | Phase 9 | Complete |
| JOBS-06 | Phase 8 | Complete |
| CLEN-01 | Phase 10 | Complete |
| FLY-01 | Phase 11 | Not started |
| FLY-02 | Phase 11 | Not started |
| FLY-03 | Phase 11 | Not started |
| FLY-04 | Phase 11 | Not started |
| PIPE-01 | Phase 11 | Not started |
| PIPE-02 | Phase 11 | Complete |
| PIPE-03 | Phase 11 | Complete |
| PIPE-04 | Phase 11 | Complete |
| PIPE-05 | Phase 11 | Complete |
| PIPE-06 | Phase 11 | Complete |
| PIPE-07 | Phase 11 | Not started |
| PIPE-08 | Phase 11 | Not started |
| DASH-01 | Phase 11 | Not started |
| DASH-02 | Phase 11 | Not started |
| DASH-03 | Phase 11 | Not started |
| DASH-04 | Phase 11 | Not started |
| DASH-05 | Phase 11 | Not started |
| DASH-06 | Phase 11 | Not started |
| DASH-07 | Phase 11 | Not started |
| DOC-01 | Phase 12 | Not started |
| DOC-02 | Phase 12 | Not started |
| DOC-03 | Phase 12 | Not started |
| DOC-04 | Phase 12 | Not started |
| DOC-05 | Phase 12 | Not started |
| DOC-06 | Phase 12 | Not started |
| DOC-07 | Phase 12 | Not started |
| DOC-08 | Phase 12 | Not started |
| DOC-09 | Phase 12 | Not started |
| DOC-10 | Phase 12 | Not started |
| DOC-11 | Phase 12 | Not started |
| DOC-12 | Phase 12 | Not started |
| DOC-13 | Phase 12 | Not started |

**Coverage:**
- v1 requirements: 26 total (all complete)
- Phase 11 requirements: 19 total
- Phase 12 requirements: 13 total
- Mapped to phases: 58
- Unmapped: 0

---
*Requirements defined: 2026-03-08*
*Last updated: 2026-03-09 after Phase 12 ULTRA MEGA PROMPT extension requirements added*
