# Technology Stack: Admin Upload + Background Processing

**Project:** GABI-KIMI (DOU Search Platform) -- Upload Milestone
**Researched:** 2026-03-08

## Context

This stack covers ONLY the new components needed for the admin upload milestone. The existing stack (FastAPI, React, PostgreSQL, Elasticsearch, Redis) is already deployed on Fly.io and is not re-evaluated here.

**What we are adding:**
1. File upload endpoint (XML/ZIP) to FastAPI
2. Blob storage on Fly.io (Tigris)
3. Background job processing (unzip, deduplicate, ingest)
4. Worker control table (job status tracking)

## Recommended Stack

### File Upload

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| python-multipart | >=0.0.22 | Multipart form parsing for FastAPI `UploadFile` | Required by FastAPI for file uploads. Already a transitive dependency of FastAPI but should be pinned explicitly. | HIGH |
| FastAPI `UploadFile` | (built-in) | Streaming file upload handler | Streams to disk via SpooledTemporaryFile, avoids loading full ZIP into memory. Already part of the framework. | HIGH |

**Key design decision:** Accept uploads via `UploadFile`, stream directly to Tigris using boto3's `upload_fileobj()`. Do NOT save to local disk first -- Fly.io ephemeral volumes disappear on redeploy.

### Blob Storage (Tigris on Fly.io)

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| boto3 | >=1.35 | S3-compatible client for Tigris | Tigris is Fly.io's native object storage, fully S3-compatible. boto3 is the standard Python S3 client. Tigris auto-injects `AWS_ENDPOINT_URL_S3`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` as Fly secrets. Zero config on deploy. | HIGH |

**Setup:**
```bash
# Create Tigris bucket (one-time, via Fly CLI)
fly storage create --name gabi-dou-uploads --region gru

# This auto-sets secrets on the app:
#   AWS_ENDPOINT_URL_S3
#   AWS_ACCESS_KEY_ID
#   AWS_SECRET_ACCESS_KEY
#   BUCKET_NAME
```

**Python client init:**
```python
import boto3, os

s3 = boto3.client("s3", endpoint_url=os.environ["AWS_ENDPOINT_URL_S3"])
bucket = os.environ["BUCKET_NAME"]

# Upload from UploadFile stream
s3.upload_fileobj(upload_file.file, bucket, object_key)

# Generate presigned URL for download (optional, for admin retrieval)
url = s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=3600)
```

**Why Tigris over alternatives:**
- Native Fly.io integration (auto-provisioned secrets, internal networking)
- S3-compatible (no proprietary API lock-in)
- Objects stored in `gru` region (same as app), cached globally
- No need for external AWS S3 account or cross-cloud networking
- Private buckets by default (admin-only access)

### Background Job Processing

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| arq | >=0.27 | Async Redis-based task queue | Async-native (matches FastAPI), uses Redis (already deployed at `gabi-dou-redis.internal`), minimal config, lightweight. Perfect for this workload: 1-10 upload jobs/day, not thousands/second. | HIGH |

**Why ARQ over alternatives:**

| Alternative | Why Not |
|-------------|---------|
| Celery | Synchronous-first design. Overkill for this workload. Requires separate broker config, heavy dependency tree. Async support is bolted on, not native. |
| Taskiq | More actively developed than ARQ, but adds unnecessary complexity (dependency injection framework, multiple broker adapters). Our job is simple: process a file. ARQ's simplicity wins. |
| FastAPI BackgroundTasks | Tied to the web process. If the machine stops (Fly auto_stop), the task dies. No retry, no status tracking, no persistence. Fundamentally unsuitable for file processing that takes 30+ seconds. |
| RQ (Redis Queue) | Synchronous-only. Not compatible with async FastAPI patterns. |

**ARQ maintenance-only status:** ARQ is in maintenance mode (no new features, but bug fixes continue). This is acceptable because: (a) the API is stable and complete for our needs, (b) the feature set (retry, abort, cron, result storage) covers our requirements, (c) Redis protocol is stable. If ARQ ever becomes unmaintained, migrating to Taskiq is straightforward since both use Redis.

**Worker architecture on Fly.io:**
```toml
# fly.toml -- add worker process group
[processes]
  web = "python -m uvicorn src.backend.apps.web_server:app --host 0.0.0.0 --port 8000"
  worker = "python -m src.backend.worker.main"
```

This runs web and worker as separate Fly Machines from the same Docker image. The worker can be scaled independently (e.g., 0 machines when idle if using Fly's auto-stop, or always-on with `min_machines_running = 1`).

### Job Status Tracking

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| PostgreSQL (existing) | -- | Worker control table | Already deployed. SQL is the right tool for durable job status that survives restarts. ARQ stores transient state in Redis; PostgreSQL stores the authoritative record. | HIGH |

**Schema addition (not a library, just SQL):**
```sql
CREATE TABLE upload_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by      UUID NOT NULL REFERENCES users(id),
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','processing','completed','failed','rejected')),
    filename        TEXT NOT NULL,
    storage_key     TEXT NOT NULL,       -- Tigris object key
    file_size_bytes BIGINT,
    file_type       TEXT NOT NULL CHECK (file_type IN ('xml','zip')),
    articles_found  INTEGER,
    articles_new    INTEGER,
    articles_dup    INTEGER,
    error_message   TEXT,
    completed_at    TIMESTAMPTZ
);
```

### Supporting Libraries

| Library | Version | Purpose | When Needed | Confidence |
|---------|---------|---------|-------------|------------|
| python-multipart | >=0.0.22 | Form/file upload parsing | Always (upload endpoint) | HIGH |
| boto3 | >=1.35 | Tigris/S3 client | Always (blob storage) | HIGH |
| arq | >=0.27 | Background task queue | Always (worker) | HIGH |
| lxml | >=5.0 | Fast XML parsing (already used by ingestion pipeline) | Upload processing | MEDIUM |

**Note on lxml:** The existing ingestion pipeline likely already uses BeautifulSoup (in requirements.txt). For the worker, stick with whatever the current `dou_ingest.py` uses rather than introducing a second XML parser.

## What NOT to Use

| Technology | Why Not |
|------------|---------|
| AWS S3 directly | Adds cross-cloud latency, requires separate AWS account, Tigris is drop-in replacement with better Fly.io integration |
| Celery | Overkill. Synchronous-first. Heavy. This project processes a handful of uploads per day, not millions of tasks. |
| Dramatiq | Less ecosystem support than Celery, no clear advantage over ARQ for async workloads |
| Fly Volumes (persistent disk) | Ephemeral by nature on shared-cpu machines, tied to specific machine. Tigris is the correct answer for file persistence. |
| Background thread in web process | Dies when Fly stops the machine. No persistence, no retry, no status tracking. |
| Kafka / RabbitMQ | Massively over-engineered for this workload. Redis is already running. |
| SQLAlchemy for job table | The project uses raw psycopg2. Adding an ORM for one table is unnecessary complexity. |

## Installation

```bash
# Add to ops/deploy/web/requirements.txt
python-multipart>=0.0.22
boto3>=1.35
arq>=0.27
```

No new infrastructure services needed -- Redis and PostgreSQL are already deployed.

## Environment Variables (new)

| Variable | Source | Purpose |
|----------|--------|---------|
| `AWS_ENDPOINT_URL_S3` | `fly storage create` (auto-set) | Tigris endpoint |
| `AWS_ACCESS_KEY_ID` | `fly storage create` (auto-set) | Tigris auth |
| `AWS_SECRET_ACCESS_KEY` | `fly storage create` (auto-set) | Tigris auth |
| `BUCKET_NAME` | `fly storage create` (auto-set) | Tigris bucket name |

## Sources

- [Fly.io Tigris docs](https://fly.io/docs/tigris/)
- [Fly.io Python + Object Storage guide](https://fly.io/docs/python/do-more/add-object-storage/)
- [Tigris boto3 SDK docs](https://www.tigrisdata.com/docs/sdks/s3/aws-python-sdk/)
- [Fly.io multiple processes guide](https://fly.io/docs/app-guides/multiple-processes/)
- [ARQ documentation](https://arq-docs.helpmanual.io/)
- [ARQ on PyPI](https://pypi.org/project/arq/)
- [FastAPI file upload docs](https://fastapi.tiangolo.com/tutorial/request-files/)
- [python-multipart on PyPI](https://pypi.org/project/python-multipart/)
- [boto3 documentation](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/quickstart.html)
