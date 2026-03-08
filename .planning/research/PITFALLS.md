# Pitfalls Research

**Domain:** File upload + background processing + blob storage for FastAPI on Fly.io
**Researched:** 2026-03-08
**Confidence:** HIGH

## Critical Pitfalls

### Pitfall 1: OOM on 512MB Fly.io Machine During ZIP Processing

**What goes wrong:**
The current web server runs on `shared-cpu-2x` with only 512MB RAM. DOU ZIP bundles can be tens of megabytes, and extracting + parsing XML in-memory while simultaneously serving search requests will trigger OOM kills. Fly.io's Linux OOM killer terminates the process silently, and the machine restarts — dropping all in-flight requests and any background tasks running in-process.

**Why it happens:**
Developers add `BackgroundTasks` to the web server process because it is the simplest path. The upload endpoint receives the file, then kicks off extraction in the same process. With 512MB total (shared with FastAPI, psycopg2 connection pools, and Elasticsearch client), a single 30MB ZIP extracting to 200MB of XML strings exhausts memory.

**How to avoid:**
Run background processing as a separate Fly.io process group. In `fly.toml`, define a `[processes]` section:
```toml
[processes]
  web = "python ops/bin/web_server.py"
  worker = "python ops/bin/worker.py"
```
Scale the worker machine with more RAM (1GB+). The web process stays lean — it only receives the upload, writes to Tigris, and inserts a job row into the `worker_control` table. The worker polls the table and processes jobs.

**Warning signs:**
- Machine restarts in Fly.io dashboard without deploy
- Health check failures on `/api/stats` during uploads
- `fly logs` showing `Out of memory: Killed process`

**Phase to address:**
Phase 1 (Infrastructure) — set up process groups before writing any upload code.

---

### Pitfall 2: Blocking the AsyncIO Event Loop with psycopg2

**What goes wrong:**
The codebase uses `psycopg2` (synchronous) everywhere. If the new upload endpoint is declared as `async def` and calls psycopg2 directly (e.g., to insert a job record or check deduplication hashes), it blocks the entire event loop. All concurrent requests freeze until the DB call returns. Under load, this cascades into health check timeouts and Fly.io restarting the machine.

**Why it happens:**
FastAPI makes it easy to write `async def` routes, and developers assume all code inside is non-blocking. But psycopg2 is a C-extension that blocks the calling thread. FastAPI only runs `def` (sync) endpoints in a threadpool automatically — `async def` routes run directly on the event loop.

**How to avoid:**
For the upload endpoint and any new endpoints that touch psycopg2, declare them as `def` (not `async def`). FastAPI will automatically run them in a threadpool, preventing event loop blocking. This matches the existing pattern in the codebase. Do NOT mix `await` calls and psycopg2 in the same function. If you need async and DB access in one endpoint, use `asyncio.to_thread()` to wrap the synchronous DB call.

**Warning signs:**
- Response times spike for ALL endpoints when uploads are happening
- Uvicorn worker timeout errors under concurrent requests
- `/api/stats` health check intermittently failing

**Phase to address:**
Phase 2 (Upload Endpoint) — enforce at code review that upload routes are `def`, not `async def`.

---

### Pitfall 3: ZIP Slip (Path Traversal) on Admin Uploads

**What goes wrong:**
An attacker (or a corrupted ZIP) contains entries with paths like `../../etc/passwd` or `../../../app/ops/bin/web_server.py`. If the extraction code uses `zipfile.extractall()` without validation, files get written outside the intended directory. On Fly.io this could overwrite application code in the running container.

**Why it happens:**
Python's `zipfile` module does NOT prevent path traversal by default. The existing `zip_downloader.py` downloads from a trusted government source, so it may not have this protection. But admin uploads come from user-controlled input — even trusted admins could upload corrupted files.

**How to avoid:**
Never use `zipfile.extractall()` for user-uploaded ZIPs. Instead, iterate entries and validate each path:
```python
import zipfile, os

def safe_extract(zip_path, target_dir):
    with zipfile.ZipFile(zip_path) as zf:
        for entry in zf.infolist():
            # Reject absolute paths and path traversal
            if entry.filename.startswith('/') or '..' in entry.filename:
                raise ValueError(f"Unsafe ZIP entry: {entry.filename}")
            # Only extract .xml files
            if not entry.filename.lower().endswith('.xml'):
                continue
            target = os.path.join(target_dir, os.path.basename(entry.filename))
            with zf.open(entry) as src, open(target, 'wb') as dst:
                dst.write(src.read())
```
Also enforce a maximum decompressed size (e.g., 500MB) to prevent ZIP bombs.

**Warning signs:**
- ZIP entries with `..` in filenames in logs
- Extracted files appearing outside the designated temp directory
- Unusually large decompression ratios (ZIP bomb indicator)

**Phase to address:**
Phase 2 (Upload Endpoint) — implement before any ZIP processing code ships.

---

### Pitfall 4: Upload Writes to Ephemeral Disk Instead of Tigris

**What goes wrong:**
The developer saves the uploaded file to the local filesystem (e.g., `/app/uploads/` or `/tmp/`) intending to process it later. On Fly.io, the root filesystem is ephemeral — it resets on every deploy and machine restart. If the machine restarts between upload and processing, the file is gone. The job row in `worker_control` references a file that no longer exists.

**Why it happens:**
Local filesystem writes are the simplest approach and work fine in local development. Fly.io Volumes exist but are pinned to a single machine and region, so they don't help when the web machine and worker machine are separate processes (they may run on different physical hosts).

**How to avoid:**
Upload directly to Tigris (S3-compatible) from the web endpoint. Store only the Tigris object key in the `worker_control` table. The worker retrieves the file from Tigris for processing. This decouples the web and worker processes completely.

```python
import boto3

s3 = boto3.client('s3',
    endpoint_url='https://fly.storage.tigris.dev',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
)

# In upload endpoint:
key = f"uploads/{job_id}/{filename}"
s3.upload_fileobj(file.file, BUCKET, key)
# Store `key` in worker_control row
```

**Warning signs:**
- Jobs stuck in "pending" after a deploy
- Worker logs showing "FileNotFoundError" for upload paths
- Local `/tmp` usage growing without cleanup

**Phase to address:**
Phase 1 (Infrastructure) — create Tigris bucket and configure credentials before building upload endpoint.

---

### Pitfall 5: No Idempotency on Upload Re-processing

**What goes wrong:**
An admin uploads a ZIP, the worker partially processes it (inserts some articles into PostgreSQL), then crashes. The admin retries the upload or the worker retries the job. Without idempotency, duplicate articles get inserted, or worse, the CRSS-1 commitment chain gets corrupted because the same content is sealed twice with different sequence numbers.

**Why it happens:**
The existing ingestion pipeline (`bulk_pipeline.py`) uses `natural_key_hash` for deduplication, but this check may not be wired into the new upload path. Also, partial failures leave the database in an inconsistent state if transactions are not properly scoped.

**How to avoid:**
1. Wrap each job's DB operations in a single transaction — commit only after all articles from one ZIP are processed.
2. Use the existing `natural_key_hash` deduplication at the DB level (UNIQUE constraint or ON CONFLICT DO NOTHING).
3. Track job state transitions in `worker_control`: `pending -> processing -> completed | failed`. Only allow `pending -> processing` transition if current state is `pending` (use `UPDATE ... WHERE status = 'pending' RETURNING id` as an atomic claim).
4. Never seal CRSS-1 commitments inside the upload flow — run sealing as a separate scheduled step after ingestion is verified.

**Warning signs:**
- Duplicate articles appearing in search results
- `worker_control` rows stuck in "processing" state forever
- CRSS-1 chain verification failures

**Phase to address:**
Phase 3 (Worker Implementation) — design the state machine before writing any processing code.

---

### Pitfall 6: FastAPI UploadFile Loading Entire File Into Memory

**What goes wrong:**
Using `file: UploadFile` in a FastAPI endpoint and then calling `await file.read()` loads the entire file into memory. For a 50MB DOU ZIP uploaded to a 512MB machine, this consumes 10% of total RAM per concurrent upload. Three concurrent uploads and you are approaching OOM.

**Why it happens:**
The FastAPI documentation shows `contents = await file.read()` as the standard pattern. It works for small files but is dangerous for files over a few MB.

**How to avoid:**
Stream the upload directly to Tigris without buffering the full file in memory. Use `file.file` (the underlying SpooledTemporaryFile) as a file-like object:

```python
@app.post("/api/admin/upload")
def upload_dou_zip(file: UploadFile, principal: AuthPrincipal = Depends(require_admin_access)):
    # Stream directly to Tigris — never call file.read()
    key = f"uploads/{uuid4()}/{file.filename}"
    s3.upload_fileobj(file.file, BUCKET, key)
    # Create job record
    ...
```

Note: using `def` (not `async def`) here is intentional — see Pitfall 2.

**Warning signs:**
- Memory usage spikes during uploads visible in `fly logs` or metrics
- Slow upload response times
- OOM kills correlated with upload activity

**Phase to address:**
Phase 2 (Upload Endpoint) — enforce streaming pattern from day one.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| `BackgroundTasks` instead of worker process | No infrastructure change, one process to manage | OOM on web machine, lost jobs on restart, no retry | Never for ZIP processing. OK for fire-and-forget notifications. |
| Local filesystem for temp files | Simple, works in dev | Files lost on deploy, can't share between web/worker | Only for truly temporary files deleted within the same request |
| Polling `worker_control` table instead of Redis queue | No new dependency (Redis exists but for search signals) | DB load, polling latency, no pub/sub | Acceptable for low-volume admin uploads (< 50/day) |
| Single transaction per article instead of per ZIP | Simpler error handling | Partial ingestion on crash, dedup complexity | Never — always batch per ZIP |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Tigris (S3) | Using `s3v2` signature (default in some boto3 configs) — Tigris requires `s3v4` | Explicitly set `config=Config(signature_version='s3v4')` when creating boto3 client |
| Tigris (S3) | Hardcoding `us-east-1` as region | Use `auto` or `gru` (matching Fly primary region) as the Tigris region |
| Tigris (S3) | Using path-style addressing (`bucket.endpoint/key`) | Tigris requires virtual-hosted style — set `s3={'addressing_style': 'virtual'}` in boto3 Config |
| Fly.io Processes | Defining worker in fly.toml but forgetting to scale it | Run `fly scale count worker=1` after deploy — process groups start at 0 machines by default |
| Fly.io Processes | Sharing a Fly Volume between web and worker | Volumes bind to one machine only — use Tigris for shared storage |
| PostgreSQL | Opening new psycopg2 connections per request in the worker | Use a connection pool (`psycopg2.pool.ThreadedConnectionPool`) or connection-per-worker with keepalive |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Extracting ZIP in memory then parsing XML in memory | RAM doubles: once for raw bytes, once for parsed DOM | Stream extraction: extract to temp file, parse with iterparse (SAX-style), discard | ZIPs > 20MB (common for full DOU daily editions) |
| Inserting articles one-by-one instead of batch | 500ms per article x 2000 articles = 16 minutes per ZIP | Use `psycopg2.extras.execute_values()` for batch insert | > 100 articles per ZIP (almost always) |
| Running Elasticsearch indexing synchronously in the worker | Worker blocks on ES bulk API for minutes | Use ES `_bulk` API with appropriate batch size (500 docs). Accept async indexing latency. | > 500 documents per job |
| Health check hitting `/api/stats` which queries PostgreSQL | Under DB load from worker, health check times out, Fly restarts web | Use a lightweight `/healthz` endpoint that returns 200 without DB access | When worker is hammering the DB during ingestion |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Not validating file type on upload | Attacker uploads executable or PHP file, potential code execution if served | Check magic bytes (not just extension). Only accept `.zip` and `.xml`. Reject everything else at the endpoint level. |
| Exposing Tigris bucket publicly | Uploaded ZIPs (potentially containing sensitive government pre-release data) accessible to anyone | Keep bucket private. Generate short-lived presigned URLs only when admin needs to download. |
| No upload size limit | Denial of service via 2GB upload exhausting disk/memory | Set `app.add_middleware(...)` or nginx-level `client_max_body_size`. Limit to 200MB (largest DOU monthly ZIP is ~150MB). |
| Admin upload endpoint without rate limiting | Accidental or malicious repeated uploads overwhelming worker queue | Apply rate limiting: max 10 uploads per minute per admin user |
| Storing raw upload filename in DB without sanitization | Path injection, XSS if filename is displayed in admin UI | Use `os.path.basename()` and strip non-alphanumeric characters. Store a generated UUID-based key, keep original name as metadata only. |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| No upload progress indicator | Admin thinks upload failed, retries, creates duplicate jobs | Show upload progress bar. Return job ID immediately after upload completes. |
| No job status visibility | Admin has no idea if their upload is processing, succeeded, or failed | Admin dashboard polling `/api/admin/jobs` showing status, article count, errors |
| Silent deduplication | Admin uploads same ZIP twice, sees "0 new articles" with no explanation | Show explicit message: "X articles already existed, Y new articles ingested" |
| Blocking the admin UI during processing | Admin uploads ZIP and UI freezes waiting for processing to complete | Return 202 Accepted immediately. Provide job status endpoint for polling. |
| No error details on failure | Admin sees "Failed" with no actionable information | Show specific error: "3 XML files had invalid encoding", "ZIP contained no .xml files", etc. |

## "Looks Done But Isn't" Checklist

- [ ] **Upload endpoint:** Often missing file size limit enforcement — verify `Content-Length` is checked before reading body
- [ ] **Worker process:** Often missing graceful shutdown (SIGTERM handling) — verify in-progress jobs are marked as `failed` or `interrupted` on shutdown, not left as `processing` forever
- [ ] **Job status API:** Often missing cleanup of old completed/failed jobs — verify a retention policy (delete after 30 days) exists
- [ ] **Tigris integration:** Often missing cleanup of processed uploads — verify ZIPs are deleted from Tigris after successful ingestion to avoid storage costs
- [ ] **Deduplication:** Often missing cross-ZIP deduplication — verify `natural_key_hash` constraint catches duplicates across separate uploads, not just within one ZIP
- [ ] **CRSS-1 chain:** Often missing — verify upload-ingested articles are eventually sealed into the commitment chain (separate cron/step, not inline)
- [ ] **Error recovery:** Often missing — verify a failed job can be manually retried from the admin UI without re-uploading the file (file still in Tigris)

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| OOM during processing | LOW | Machine auto-restarts. Job stays in `processing` state. Add timeout-based recovery: if `processing` for > 30 min, reset to `pending`. |
| Duplicate articles from non-idempotent retry | MEDIUM | Query by `natural_key_hash`, remove duplicates. Re-verify CRSS-1 chain integrity. |
| ZIP Slip exploitation | HIGH | Audit filesystem for unexpected files. Rebuild container image. Rotate all secrets. |
| Lost uploads (ephemeral disk) | MEDIUM | Ask admin to re-upload. If Tigris was used, recover from bucket. |
| Corrupted CRSS-1 chain from inline sealing | HIGH | Reconstruct chain from article records. Requires manual verification of all sealed batches since corruption. |
| Worker stuck in crash loop | LOW | Check logs, fix bug, redeploy. Stale `processing` jobs auto-recover via timeout. |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| OOM on 512MB machine | Phase 1 (Infrastructure) | Verify `fly.toml` has separate process groups with worker at 1GB+ RAM |
| Blocking event loop with psycopg2 | Phase 2 (Upload Endpoint) | All new endpoints use `def` not `async def` when touching psycopg2 |
| ZIP Slip path traversal | Phase 2 (Upload Endpoint) | Unit test with crafted ZIP containing `../` entries — must raise error |
| Ephemeral disk file loss | Phase 1 (Infrastructure) | Tigris bucket created, credentials in Fly secrets, no local file writes for uploads |
| Non-idempotent re-processing | Phase 3 (Worker) | Integration test: process same ZIP twice, verify no duplicate articles |
| UploadFile memory buffering | Phase 2 (Upload Endpoint) | Code review: no `file.read()` calls, only `file.file` streaming |
| No upload size limit | Phase 2 (Upload Endpoint) | Verify 413 response for files > 200MB |
| Tigris S3 misconfiguration | Phase 1 (Infrastructure) | Smoke test: upload and retrieve a test file via boto3 |
| Worker graceful shutdown | Phase 3 (Worker) | Send SIGTERM to worker, verify in-progress job is marked interrupted |
| Health check under load | Phase 3 (Worker) | Add `/healthz` endpoint, update fly.toml health check path |

## Sources

- [Fly.io Tigris Global Object Storage Docs](https://fly.io/docs/tigris/)
- [Fly.io Process Groups](https://fly.io/docs/launch/processes/)
- [Fly.io Machine Sizing](https://fly.io/docs/machines/guides-examples/machine-sizing/)
- [Fly.io Volumes Overview](https://fly.io/docs/volumes/overview/)
- [FastAPI Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [FastAPI Request Files](https://fastapi.tiangolo.com/tutorial/request-files/)
- [FastAPI Concurrency and async/await](https://fastapi.tiangolo.com/async/)
- [FastAPI BackgroundTasks vs ARQ vs Celery](https://medium.com/@komalbaparmar007/fastapi-background-tasks-vs-celery-vs-arq-picking-the-right-asynchronous-workhorse-b6e0478ecf4a)
- [Tigris AWS Python SDK](https://www.tigrisdata.com/docs/sdks/s3/aws-python-sdk/)
- [Snyk ZIP Slip Vulnerability](https://security.snyk.io/research/zip-slip-vulnerability)
- [Python Async Workers on Fly Machines](https://fly.io/blog/python-async-workers-on-fly-machines/)
- [Fly.io Multiple Processes](https://fly.io/docs/app-guides/multiple-processes/)

---
*Pitfalls research for: GABI-KIMI admin upload + background processing on Fly.io*
*Researched: 2026-03-08*
