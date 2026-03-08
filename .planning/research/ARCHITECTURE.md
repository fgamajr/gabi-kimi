# Architecture Patterns

**Domain:** Background workers, file upload, and blob storage for legal document search platform
**Researched:** 2026-03-08

## Recommended Architecture

### High-Level View

```
                         +-------------------+
                         |   React SPA       |
                         |  (Admin Upload)   |
                         +--------+----------+
                                  |
                                  | POST /api/admin/upload
                                  | GET  /api/admin/jobs/{id}
                                  v
                    +-------------+--------------+
                    |      FastAPI Web Server     |
                    |   (gabi-dou-web process)    |
                    +---+--------+----------+----+
                        |        |          |
            upload file |  enqueue|   query  |
                        v   job  v  status  v
              +---------+  +-----+--+  +----+------+
              | Tigris   |  | Redis  |  | PostgreSQL|
              | (S3)     |  | Queue  |  | (jobs tbl)|
              +-----+----+  +---+----+  +-----+----+
                    |            |              |
                    |   dequeue  |    write     |
                    |     +------+    results   |
                    |     v                     |
                    | +---+-------------------+ |
                    | |   arq Worker Process  | |
                    | |  (gabi-dou-web worker)| |
                    | +-----------+-----------+ |
                    |             |              |
                    +--read ZIP---+--ingest------+
                                  |
                                  v
                          +-------+-------+
                          | Elasticsearch |
                          |  (indexing)   |
                          +---------------+
```

### Component Boundaries

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| **FastAPI Web (http)** | Accept uploads, enqueue jobs, serve job status API, serve SPA | Tigris (write), Redis (enqueue), PostgreSQL (read/write job status) |
| **arq Worker (process group)** | Execute ingestion pipeline: unzip, parse XML, normalize, deduplicate, ingest to PG, index to ES | Tigris (read), PostgreSQL (write), Elasticsearch (write), Redis (dequeue/results) |
| **Tigris Object Storage** | Store uploaded ZIP/XML files durably before processing | Accessed by Web (write) and Worker (read) |
| **Redis** | Job queue broker for arq, existing search signal caching | Accessed by Web (enqueue) and Worker (dequeue) |
| **PostgreSQL** | Job control table, document registry, CRSS-1 commitments | Accessed by Web (job status reads) and Worker (ingestion writes) |
| **Elasticsearch** | Full-text and vector search index | Written by Worker after successful PG ingestion |

### Data Flow

**Upload flow (synchronous, fast):**

1. Admin authenticates via existing bearer token / session
2. Admin POSTs file (ZIP or XML) to `/api/admin/upload`
3. Web server validates: file type, size limit (50MB), admin role check
4. Web server streams file to Tigris bucket (`gabi-uploads/{uuid}/{filename}`)
5. Web server inserts row into `admin.upload_jobs` table (status=`pending`)
6. Web server enqueues arq job with `(job_id, tigris_key)` payload
7. Web server returns `{job_id, status: "pending"}` immediately (HTTP 202)

**Processing flow (asynchronous, worker):**

1. arq worker picks up job from Redis queue
2. Worker updates `admin.upload_jobs` status to `processing`
3. Worker downloads file from Tigris to temp directory
4. Worker runs existing pipeline: unzip -> parse XML -> normalize -> deduplicate
5. Worker inserts new records into PG via `registry_ingest` (existing code)
6. Worker indexes new documents in Elasticsearch via `es_indexer` (existing code)
7. Worker updates `admin.upload_jobs`: status=`completed`, counts, errors
8. On failure: status=`failed`, error message stored, automatic retry via arq

**Status polling flow:**

1. Admin frontend polls `GET /api/admin/jobs/{job_id}` every 5 seconds
2. Web server reads from `admin.upload_jobs` table
3. Returns: status, progress counts, error details, timestamps

## Component Details

### 1. Upload Endpoint

```python
# src/backend/apps/upload.py

from fastapi import APIRouter, UploadFile, Depends
from src.backend.apps.auth import require_admin_access, AuthPrincipal

router = APIRouter(prefix="/api/admin", tags=["admin-upload"])

MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB
ALLOWED_EXTENSIONS = {".zip", ".xml"}

@router.post("/upload", status_code=202)
async def upload_document(
    file: UploadFile,
    principal: AuthPrincipal = Depends(require_admin_access),
):
    # 1. Validate file type and size
    # 2. Stream to Tigris via boto3 S3Client
    # 3. Insert job row into admin.upload_jobs
    # 4. Enqueue arq task
    # 5. Return job_id
    ...

@router.get("/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    principal: AuthPrincipal = Depends(require_admin_access),
):
    # Read from admin.upload_jobs
    ...

@router.get("/jobs")
async def list_jobs(
    principal: AuthPrincipal = Depends(require_admin_access),
):
    # List recent jobs with pagination
    ...
```

### 2. Job Control Table

```sql
CREATE SCHEMA IF NOT EXISTS admin;

CREATE TABLE admin.upload_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Who and what
    uploaded_by     TEXT NOT NULL,          -- token_id or user_id
    filename        TEXT NOT NULL,
    file_size       BIGINT NOT NULL,
    tigris_key      TEXT NOT NULL,          -- S3 object key

    -- Status tracking
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'retrying')),
    attempt         INT NOT NULL DEFAULT 0,
    max_attempts    INT NOT NULL DEFAULT 3,

    -- Results
    articles_parsed INT,
    articles_ingested INT,
    articles_duplicated INT,
    articles_failed INT,
    error_message   TEXT,
    error_detail    JSONB,

    -- Timing
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_upload_jobs_status ON admin.upload_jobs(status);
CREATE INDEX idx_upload_jobs_created ON admin.upload_jobs(created_at DESC);
```

### 3. arq Worker

```python
# src/backend/workers/ingest_worker.py

from arq import cron
from arq.connections import RedisSettings

async def process_upload(ctx, job_id: str, tigris_key: str):
    """Main worker task: download from Tigris, run ingestion pipeline."""
    # 1. Update job status to 'processing'
    # 2. Download file from Tigris to /tmp/{job_id}/
    # 3. If ZIP: extract XMLs (reuse zip_downloader.extract_xml_from_zip)
    # 4. Parse XMLs (reuse xml_parser.INLabsXMLParser)
    # 5. Normalize (reuse normalizer.article_to_ingest_record)
    # 6. Ingest to PG (reuse registry_ingest.ingest_batch_sealed)
    # 7. Index to ES (reuse es_indexer incremental sync)
    # 8. Update job status to 'completed' with counts
    # 9. Clean up temp files

class WorkerSettings:
    functions = [process_upload]
    redis_settings = RedisSettings.from_dsn(os.environ["REDIS_URL"])
    max_jobs = 2          # limit concurrent jobs (memory constrained)
    job_timeout = 600     # 10 min max per job
    max_tries = 3         # automatic retry
    retry_defer = 30      # 30s between retries
```

### 4. Tigris Integration

```python
# src/backend/storage/tigris.py

import boto3
from botocore.config import Config

def get_s3_client():
    """S3 client configured for Fly.io Tigris."""
    return boto3.client(
        "s3",
        endpoint_url=os.environ["AWS_ENDPOINT_URL_S3"],
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )

async def upload_to_tigris(file: UploadFile, key: str) -> int:
    """Stream upload file to Tigris, return bytes written."""
    client = get_s3_client()
    client.upload_fileobj(file.file, os.environ["BUCKET_NAME"], key)
    return file.size

async def download_from_tigris(key: str, dest: Path) -> Path:
    """Download object from Tigris to local path."""
    client = get_s3_client()
    client.download_file(os.environ["BUCKET_NAME"], key, str(dest))
    return dest
```

### 5. Fly.io Deployment (fly.toml changes)

```toml
# Updated fly.toml with worker process group

[processes]
web = "python -m uvicorn src.backend.apps.web_server:app --host 0.0.0.0 --port 8000"
worker = "python -m src.backend.workers.ingest_worker"

[http_service]
  processes = ["web"]       # Only web gets HTTP traffic
  internal_port = 8000
  force_https = true
  auto_stop_machines = 'stop'
  auto_start_machines = true
  min_machines_running = 1

[[vm]]
  processes = ["web"]
  size = 'shared-cpu-2x'
  memory = '512mb'

[[vm]]
  processes = ["worker"]
  size = 'shared-cpu-2x'
  memory = '1024mb'          # Workers need more RAM for XML parsing
```

## Patterns to Follow

### Pattern 1: Reuse Existing Pipeline as Library

**What:** The existing ingestion pipeline (`xml_parser`, `normalizer`, `registry_ingest`, `es_indexer`) was built as CLI tools. Refactor the core logic into importable functions that the worker calls directly.

**Why:** The `dou_ingest.DOUIngestor.ingest_zip()` method already does exactly what the worker needs. The worker wraps it with job status tracking and Tigris download.

**Example:**
```python
# Worker calls existing code directly
from src.backend.ingest.dou_ingest import DOUIngestor

ingestor = DOUIngestor(dsn=os.environ["PG_DSN"])
result = ingestor.ingest_zip(local_zip_path)
# result has: articles_parsed, articles_ingested, duplicates, errors
```

### Pattern 2: Idempotent Ingestion

**What:** The existing pipeline already handles deduplication via `natural_key_hash`. Re-uploading the same ZIP produces zero new records, not duplicates.

**Why:** arq guarantees at-least-once delivery. If a worker crashes mid-job and retries, the deduplication in `registry_ingest` (SERIALIZABLE CTE state machine) prevents double-insertion.

**Detection:** The `IngestResult` dataclass already tracks `inserted` vs `duplicated` counts.

### Pattern 3: Job Status as Source of Truth in PostgreSQL

**What:** Store job status in PostgreSQL, not Redis. Redis is only the queue broker.

**Why:** PostgreSQL survives restarts, is already backed up, and is queryable. Redis on Fly.io may lose data on restart. The admin UI needs reliable job history.

### Pattern 4: Streaming Upload (No Memory Buffering)

**What:** Stream uploaded files directly to Tigris using `upload_fileobj()`. Never load the entire file into memory on the web server.

**Why:** The web server runs on 512MB RAM. A 50MB ZIP in memory plus the framework overhead could cause OOM. Stream through to Tigris and let the worker (1GB RAM) handle extraction.

## Anti-Patterns to Avoid

### Anti-Pattern 1: Processing in the Request Handler

**What:** Running XML parsing, DB ingestion, or ES indexing inside the upload HTTP handler.

**Why bad:** A large ZIP with thousands of articles takes minutes to process. The HTTP request would time out (Fly.io has a 60s proxy timeout). The user gets no feedback.

**Instead:** Upload to Tigris, enqueue job, return 202 immediately.

### Anti-Pattern 2: Using FastAPI BackgroundTasks for Ingestion

**What:** Using `BackgroundTasks.add_task()` to run ingestion after the response.

**Why bad:** BackgroundTasks runs in the same process and event loop. If the web server scales down (Fly.io auto_stop), the background task dies. No retry mechanism. No status tracking. CPU-intensive XML parsing blocks the event loop.

**Instead:** Use arq with a dedicated worker process group.

### Anti-Pattern 3: Local Filesystem as Upload Buffer

**What:** Writing uploaded files to `/tmp` on the web server and having the worker read from there.

**Why bad:** Web and worker are separate Fly Machines. They do not share a filesystem. Even if co-located, machine restarts lose `/tmp`.

**Instead:** Use Tigris as the durable intermediary. Web writes, worker reads.

### Anti-Pattern 4: Celery for This Scale

**What:** Using Celery with its full broker/result-backend/beat infrastructure.

**Why bad:** Celery is synchronous by design, requires bridging for async FastAPI, adds significant complexity and memory overhead. This project processes at most a few uploads per day. Celery is built for millions of tasks.

**Instead:** arq is purpose-built for async Python, uses Redis (already deployed), has ~700 lines of code, and handles retries natively.

## Scalability Considerations

| Concern | Current (low volume) | Growth (100+ uploads/day) | At Scale |
|---------|---------------------|--------------------------|----------|
| Upload handling | Single web machine, stream to Tigris | Same pattern scales fine | Add presigned URL for direct-to-Tigris upload |
| Job processing | 1 worker, max_jobs=2 | `fly scale count worker=2` | Scale workers independently, increase max_jobs |
| Job queue | Redis single instance | Same Redis, separate queue name | Consider dedicated Redis for jobs |
| Storage | Tigris pay-per-use | Same, add lifecycle policy to delete processed files | Same |
| Job history | PostgreSQL query | Add pagination, archive old jobs | Partition table by month |

## Suggested Build Order

The following order respects dependencies and enables incremental testing:

### Phase 1: Infrastructure Foundation
1. **Tigris bucket** -- `fly storage create` on the gabi-dou-web app
2. **Job control table** -- SQL migration for `admin.upload_jobs`
3. **Tigris client module** -- `src/backend/storage/tigris.py` with upload/download

*Rationale:* These are prerequisites. Nothing else works without storage and the job table.

### Phase 2: Upload Endpoint
4. **Upload API route** -- `/api/admin/upload` with auth, validation, Tigris write, job row insert
5. **Job status API** -- `/api/admin/jobs/{id}` and `/api/admin/jobs`

*Rationale:* The upload endpoint can be tested independently by writing to Tigris and creating job rows, even before the worker exists. Status API enables frontend work in parallel.

### Phase 3: Worker Process
6. **arq worker module** -- `src/backend/workers/ingest_worker.py`
7. **Pipeline integration** -- Wire worker to existing `DOUIngestor.ingest_zip()` and `es_indexer`
8. **fly.toml process groups** -- Add worker process, configure VM sizes
9. **Dockerfile update** -- Ensure entrypoint handles both web and worker commands

*Rationale:* The worker is the most complex piece. It reuses existing pipeline code but needs careful error handling and status updates. Deploying with process groups requires Dockerfile changes.

### Phase 4: Frontend Integration
10. **Admin upload UI** -- File picker, upload progress, job status display
11. **Job list view** -- Table of recent jobs with status, counts, errors

*Rationale:* Frontend depends on all API endpoints being stable. Build last so the API contract is settled.

## Sources

- [Fly.io -- Multiple Processes](https://fly.io/docs/app-guides/multiple-processes/) (process groups in fly.toml)
- [Fly.io -- Work Queues Blueprint](https://fly.io/docs/blueprints/work-queues/) (Celery/worker patterns on Fly)
- [Fly.io -- Python Async Workers](https://fly.io/blog/python-async-workers-on-fly-machines/) (Python-specific worker guidance)
- [Fly.io -- Tigris Object Storage](https://fly.io/docs/tigris/) (S3-compatible storage setup)
- [arq Documentation v0.27](https://arq-docs.helpmanual.io/) (async task queue)
- [FastAPI Background Tasks vs ARQ + Redis](https://davidmuraya.com/blog/fastapi-background-tasks-arq-vs-built-in/) (comparison and integration patterns)
- [Building Resilient Task Queues with ARQ Retries](https://davidmuraya.com/blog/fastapi-arq-retries/) (retry and idempotency patterns)

**Confidence levels:**
- Fly.io process groups and Tigris: **HIGH** (official documentation, verified)
- arq as worker library: **MEDIUM** (well-documented, community-proven, but not verified via Context7)
- Existing pipeline reuse (`DOUIngestor.ingest_zip`): **HIGH** (read from source code directly)
- Job control table design: **HIGH** (standard pattern, no external dependencies)
