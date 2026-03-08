# Feature Landscape

**Domain:** Admin document upload and background ingestion for a legal document search platform (DOU)
**Researched:** 2026-03-08

## Table Stakes

Features admins expect from a document upload panel. Missing any of these and the admin experience feels broken or untrustworthy.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Single XML file upload | Admins need to ingest individual corrections or late-published acts | Low | Drag-and-drop zone + file picker. Accept `.xml` only. Validate DOU XML schema on client before upload. |
| ZIP bundle upload | Bulk ingestion matches the existing automated pipeline format | Low | Accept `.zip` only. Size limit enforced client-side (e.g., 200 MB). Show file size before confirm. |
| Upload progress indicator | Without feedback, admin does not know if upload is working | Low | Browser-native `XMLHttpRequest` or `fetch` progress events. Show percentage bar during transfer. |
| Immediate acknowledgment | Admin must know the file was received before background processing begins | Low | Return HTTP 202 with job ID immediately after blob storage write completes. Do NOT block on ingestion. |
| Job status tracking (list view) | Admin needs to see what is processing, what succeeded, what failed | Medium | Table showing: job ID, filename, status (queued/processing/completed/failed/partial), submitted timestamp, completed timestamp, article count. Poll or SSE for live updates. |
| Job detail view | When something fails, admin needs to know why | Medium | Show per-article breakdown: parsed count, ingested count, deduplicated (skipped) count, error count. For errors, show the specific article identifier and error message. |
| Error visibility with actionable messages | "Error" without explanation is useless | Medium | Map backend exceptions to human-readable messages: "Duplicate article (natural_key_hash already exists)", "Invalid XML structure at line N", "Missing required field: artType". |
| File type validation | Prevent accidental upload of PDFs, DOCXs, images | Low | Client-side MIME check + server-side magic bytes verification. Reject with clear message. |
| Authentication and authorization | Upload is a privileged operation | Low | Already exists via `require_admin_access` decorator. Reuse existing admin auth flow. |
| Upload history / audit log | Admins need to see who uploaded what and when | Medium | Store uploader identity (token_id/user_id), timestamp, filename, job outcome. Immutable append-only log consistent with CRSS-1 philosophy. |

## Differentiators

Features that make this admin panel notably better than a basic upload form. Not expected, but valuable.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Pre-upload validation preview | Parse XML client-side and show article count, date range, sections detected before confirming upload. Catches wrong-file mistakes early. | Medium | Use a lightweight XML parser (browser DOMParser) to extract `<article>` elements and show summary. Not full validation, just a sanity check. |
| Deduplication preview | Show how many articles in the upload already exist in the index before processing. Saves time on known-duplicate uploads. | Medium | Requires a lightweight server endpoint that checks natural_key_hashes against the registry without ingesting. |
| Retry failed jobs | One-click retry for failed ingestion jobs without re-uploading the file | Medium | Requires blob storage retention of uploaded files. Job references blob path, retry re-reads from blob. |
| Partial success handling | When a ZIP has 500 articles and 3 fail, ingest the 497 and surface the 3 failures clearly | Medium | The existing pipeline already handles per-article errors. Surface this in the UI with "497 ingested, 3 failed" and expandable error details. |
| Real-time job progress via SSE | Stream processing progress (e.g., "Processing article 124 of 500") instead of polling | Medium | Backend already uses SSE for chat streaming, so the pattern exists. Reuse the SSE infrastructure for job progress events. |
| Bulk job management | Select multiple jobs, retry all failed, or clear completed jobs from the list | Low | UI convenience. Checkboxes + bulk action dropdown. Backend is just multiple single-job calls. |
| Ingestion statistics dashboard | Show trends: articles ingested per day, error rate over time, average processing duration | High | Likely overkill for initial milestone. Defer unless analytics page can be extended cheaply. |
| Drag-and-drop with paste support | Allow pasting XML content directly (not just file upload) for quick single-article ingestion | Low | Textarea with "Paste XML" tab alongside file upload tab. Useful for corrections to individual articles. |

## Anti-Features

Features to explicitly NOT build for this milestone. Each has a reason.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| In-browser document editor | This is a read-only search platform, not a CMS. Editing government publications would violate data integrity (CRSS-1). | Upload pre-formatted XML only. If an article needs correction, upload a new version and let deduplication handle it. |
| Public upload endpoint | Upload is admin-only. Exposing upload to authenticated non-admin users creates data quality risk. | Keep behind `require_admin_access`. No self-service upload. |
| Scheduled/cron upload from UI | The automated pipeline already handles scheduled ingestion via `orchestrator.py`. Adding UI-based scheduling creates two competing scheduling systems. | Keep automated pipeline as-is. Admin upload is for manual/ad-hoc ingestion only. |
| Email notifications for job completion | Over-engineering for a small admin team. Adds email infrastructure dependency. | Job status is visible in the admin panel. Admin can check back or use SSE for real-time updates. |
| Upload from URL (fetch remote file) | Adds complexity (timeout handling, redirect following, content-type validation) for a rare use case. The automated pipeline already handles remote fetching from in.gov.br. | Admin downloads file locally first, then uploads. Keep upload path simple. |
| Multi-tenant upload isolation | Single-tenant system. Only one organization uses this. | No tenant scoping needed. All uploads go to the same registry. |
| Version history / rollback for individual articles | The registry is append-only (CRSS-1 sealed). "Rolling back" would break the commitment chain. | Ingest a corrected version. Deduplication via natural_key_hash handles replacement logic at the pipeline level. |
| OCR / PDF-to-XML conversion | DOU publishes in structured XML. OCR adds massive complexity for a format that is already machine-readable. | Accept only XML and ZIP-of-XML. If a user has a PDF, they need to convert it externally. |

## Feature Dependencies

```
File upload (XML/ZIP) --> Blob storage write --> Job creation
                                                    |
                                                    v
                                          Worker control table
                                                    |
                                                    v
                                    Background worker picks up job
                                          |                    |
                                          v                    v
                                  ZIP: unzip + parse    XML: parse directly
                                          |                    |
                                          v                    v
                                    Normalize + deduplicate
                                          |
                                          v
                                  Ingest to PostgreSQL + ES index
                                          |
                                          v
                                  Update job status (success/partial/failed)
                                          |
                                          v
                                  Admin sees result in job list
```

Key dependency chains:
- **Blob storage** must work before upload endpoint can accept files
- **Worker control table** (PostgreSQL) must exist before jobs can be tracked
- **Background worker** must be running before jobs get processed
- **Job status API** must exist before the frontend can show job progress
- **Existing ingestion pipeline** (xml_parser, normalizer, es_indexer) is reused -- no new parsing code needed

## MVP Recommendation

**Prioritize (must ship together for the feature to be useful):**

1. **Single XML and ZIP upload endpoint** -- the core action. HTTP 202 + job ID response.
2. **Blob storage integration** -- store uploaded file, reference from job record.
3. **Worker control table** -- PostgreSQL table tracking job lifecycle (queued -> processing -> completed/failed).
4. **Background worker** -- process jobs from the control table using existing pipeline code.
5. **Job list view** -- admin page showing all jobs with status, timestamps, counts.
6. **Job detail view** -- click into a job to see per-article results and errors.
7. **Upload form UI** -- drag-and-drop zone with file type validation and progress bar.

**Defer to polish iteration:**
- Pre-upload validation preview: Nice but not blocking. Admin can upload and see results quickly.
- Deduplication preview: Useful but adds a new API endpoint. Ship after core flow works.
- Retry failed jobs: Requires blob retention policy decision. Ship after confirming blob storage costs.
- SSE progress streaming: Polling is sufficient for MVP. SSE is a UX enhancement.
- Paste XML support: Edge case convenience.

**Explicitly skip:**
- Ingestion statistics dashboard: The existing analytics page covers search analytics. Ingestion stats can come later.
- Bulk job management: Premature optimization. Single-job operations are fine initially.

## Sources

- Project codebase analysis: existing admin auth (`web_server.py`), ingestion pipeline (`orchestrator.py`, `bulk_pipeline.py`), admin users page (`AdminUsersPage.tsx`)
- [10 Document Management System Best Practices for 2026 | Red Brick Labs](https://www.redbricklabs.io/blog/document-management-system-best-practices)
- [6 Essential Document Management System Features in 2025 | Terralogic](https://terralogic.com/essential-document-management-system-features-2025/)
- [UI patterns for async workflows, background jobs, and data pipelines - LogRocket Blog](https://blog.logrocket.com/ui-patterns-for-async-workflows-background-jobs-and-data-pipelines)
- [Admin Dashboard UI/UX: Best Practices for 2025 | Medium](https://medium.com/@CarlosSmith24/admin-dashboard-ui-ux-best-practices-for-2025-8bdc6090c57d)
