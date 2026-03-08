# Research Summary: Admin Upload + Background Processing

**Domain:** File upload with async processing for legal document search platform
**Researched:** 2026-03-08
**Overall confidence:** HIGH

## Executive Summary

Adding admin document upload to GABI requires three new capabilities: file storage (Tigris), background processing (ARQ), and a job tracking table (PostgreSQL). The good news is that the existing infrastructure already covers most dependencies -- Redis is deployed for search caching and doubles as the ARQ broker, PostgreSQL hosts the job control table alongside existing registry tables, and Fly.io's native Tigris integration means zero additional cloud accounts.

The architecture is straightforward: the FastAPI web process accepts uploads, streams them to Tigris, creates a job record, and enqueues an ARQ task. A separate worker process (same Docker image, different entrypoint via Fly.io process groups) picks up the task, downloads from Tigris, and feeds the file through the existing ingestion pipeline (XML parsing, normalization, deduplication, PostgreSQL insert, Elasticsearch indexing). The admin sees job status via polling.

The most important architectural decision is running the worker as a separate Fly.io process group, not as a BackgroundTask in the web process. This prevents OOM on the 512MB web machine, survives machine restarts, and enables independent scaling. The worker should get 1GB RAM to handle ZIP extraction comfortably.

The three libraries to add are minimal: `boto3` (Tigris/S3 client), `arq` (async task queue), and `python-multipart` (FastAPI file upload support, likely already a transitive dependency). No new infrastructure services are needed.

## Key Findings

**Stack:** boto3 for Tigris blob storage, ARQ for async Redis-based task queue, python-multipart for file uploads. Three pip packages, zero new infrastructure.

**Architecture:** Upload-then-enqueue pattern with Fly.io process groups (web + worker). PostgreSQL as authoritative job state, Redis as transport only.

**Critical pitfall:** OOM risk if processing runs in the web process (512MB). Must use separate worker process group with 1GB+ RAM from day one.

## Implications for Roadmap

Based on research, suggested phase structure:

1. **Infrastructure Foundation** - Tigris bucket, job control table migration, boto3 client module
   - Addresses: blob storage requirement, job tracking schema
   - Avoids: ephemeral disk pitfall, building on unstable foundation
   - Rationale: Everything else depends on storage and the job table existing

2. **Upload API** - Upload endpoint with validation, job status endpoints
   - Addresses: file upload, job visibility, admin auth integration
   - Avoids: memory buffering pitfall (stream to Tigris), event loop blocking (sync endpoints)
   - Rationale: Can be tested independently before worker exists (upload stores file, creates pending job)

3. **Worker Process** - ARQ worker, pipeline integration, fly.toml process groups, Dockerfile update
   - Addresses: background processing, deduplication, ES indexing, retry logic
   - Avoids: non-idempotent processing, ZIP Slip, crash-loop without recovery
   - Rationale: Most complex piece; reuses existing pipeline code but needs careful error handling

4. **Admin UI** - Upload form, job list, job detail, error display
   - Addresses: admin experience, upload progress, status visibility
   - Avoids: building UI before API contract is stable
   - Rationale: Depends on all API endpoints; build last

**Phase ordering rationale:**
- Phase 1 before 2: Upload endpoint needs Tigris bucket and job table to exist
- Phase 2 before 3: Upload creates jobs that worker processes; testing uploads in isolation validates the storage + job flow
- Phase 3 before 4: Frontend polls job status; worker must be producing status updates
- Each phase is independently testable: bucket via CLI, upload via curl, worker via Redis enqueue, UI via browser

**Research flags for phases:**
- Phase 1: Standard patterns, unlikely to need deeper research. Fly CLI commands are well-documented.
- Phase 2: ZIP Slip prevention needs a unit test with crafted ZIP. File size limits need load testing on 512MB machine.
- Phase 3: Pipeline integration (calling `DOUIngestor` from worker) may need refactoring if existing code assumes CLI context. Needs investigation during implementation.
- Phase 4: Standard React patterns, no research needed.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack (boto3, arq, python-multipart) | HIGH | All verified via official docs and PyPI. Versions confirmed current. |
| Features (upload, job tracking, status) | HIGH | Directly from project requirements in PROJECT.md. Standard patterns. |
| Architecture (process groups, Tigris, ARQ) | HIGH | Fly.io docs explicitly document process groups. ARQ docs cover Redis worker pattern. |
| Pitfalls (OOM, ZIP Slip, event loop) | HIGH | Well-documented failure modes. Verified against Fly.io constraints (512MB RAM, ephemeral disk, auto_stop). |
| Pipeline reuse (DOUIngestor) | MEDIUM | Read source code, but did not test calling ingest functions from a worker context. May need minor refactoring. |

## Gaps to Address

- **DOUIngestor interface:** The existing `ingest_zip()` method's exact signature and return type need verification during Phase 3 implementation. It may assume CLI arguments or global state.
- **CRSS-1 sealing:** How upload-ingested articles get sealed into the commitment chain is not addressed in this research. The existing automated pipeline likely handles sealing separately. This needs clarification.
- **Tigris pricing:** Tigris storage costs on Fly.io for the expected volume (a few GB/month) should be negligible but were not verified against Fly.io's current pricing page.
- **ARQ worker auto-stop:** Whether Fly.io can auto-stop worker machines when the ARQ queue is empty needs testing. If not, the worker runs 24/7 even with no jobs.
- **Tigris virtual-hosted style:** One source mentioned Tigris may require virtual-hosted style S3 addressing (`s3={'addressing_style': 'virtual'}` in boto3 Config). This needs verification during Phase 1 smoke test.
