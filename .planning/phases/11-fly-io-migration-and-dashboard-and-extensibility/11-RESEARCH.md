# Phase 11: Fly.io Migration and Dashboard and Extensibility - Research

**Researched:** 2026-03-09
**Domain:** Infrastructure deployment (Fly.io), autonomous data pipeline (Python), admin dashboard (React)
**Confidence:** HIGH

## Summary

Phase 11 transitions GABI from a monolithic web+worker app to a 3-machine Fly.io architecture (WEB, WORKER, ES), replaces the manual JSON catalog with an autonomous SQLite-backed ingestion pipeline, and adds a React admin dashboard for pipeline monitoring. The existing codebase already has substantial pipeline infrastructure (`auto_discovery.py`, `discovery_registry.py`, `zip_downloader.py`, `orchestrator.py`, `es_indexer.py`) that currently targets PostgreSQL as the registry backend. This phase migrates that state to SQLite on the worker volume and adds APScheduler for cron-based orchestration.

The current Fly.io deployment uses a single app (`gabi-dou-web`) with two process groups (web + worker). Phase 11 splits this into 3 separate Fly apps communicating via `.internal` DNS on Fly's 6PN private network. The dashboard is served as part of the existing React SPA, with the web backend proxying `/api/worker/*` requests to the worker's internal FastAPI.

**Primary recommendation:** Deploy as 3 separate Fly apps (gabi-dou-web, gabi-dou-worker, gabi-dou-es) with independent fly.toml files. Use APScheduler 3.11.x (not 4.x which is alpha). Use `aiosqlite` for async SQLite access in the worker's FastAPI. Reuse existing pipeline modules, adapting them from PostgreSQL-backed registry to SQLite.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- 3 Fly.io Machines: WEB (FastAPI + React SPA), WORKER (pipeline + SQLite + internal API), ES (Elasticsearch 8.x single-node)
- Primary region: `gru` (Sao Paulo)
- WEB queries ES directly for search; proxies `/api/worker/*` to `worker.internal:8081` for dashboard
- WORKER never exposed to internet; only accessible via Fly internal network (`.internal` DNS)
- ES accessible at `es.internal:9200`
- SQLite in WAL mode on worker volume at `/data/registry.db`
- 3 tables: `dou_files` (state per ZIP), `pipeline_runs` (audit log), `pipeline_log` (event log)
- State machine: DISCOVERED -> QUEUED -> DOWNLOADING -> DOWNLOADED -> EXTRACTING -> EXTRACTED -> INGESTING -> INGESTED -> VERIFIED
- Failure states: DOWNLOAD_FAILED, EXTRACT_FAILED, INGEST_FAILED, VERIFY_FAILED
- Retry: up to 3 retries per file
- Discovery via Liferay JSONWS API with predictive HEAD probe fallback
- Rate limit: max 5 req/s to in.gov.br
- APScheduler with 5 cron jobs: discovery (23:00), download (23:30), ingest (00:00), verify (01:00), retry (06:00)
- Worker FastAPI on port 8081 (internal only)
- Worker: shared-cpu-1x, 512MB RAM, volume at /data
- ES: performance-2x (2 vCPU, 4GB RAM), JVM heap 2GB, 50GB volume
- Dashboard: Tab-based (Overview, Timeline, Pipeline, Logs, Settings), auto-refresh 30s via React Query
- Dashboard stack: React 18 + TypeScript + Tailwind CSS + Lucide React + React Query + Zustand
- No HA, no replicas for ES
- Daily ES snapshots to Tigris (S3-compatible)

### Claude's Discretion
- Exact ZIP extraction logic for multi-era DOUs (2002-2018 vs 2019+ formats)
- Encoding detection strategy for old files (Latin-1 vs UTF-8)
- DOUDocument field extraction from XML/HTML/TXT
- Deterministic document ID generation scheme
- ES bulk batch size tuning
- Dashboard component file structure and shared component extraction
- Error toast implementation details
- Virtual scrolling decision for timeline (867 files)
- Disk space monitoring thresholds

### Deferred Ideas (OUT OF SCOPE)
- PostgreSQL migration (when multi-machine or more stateful tables needed)
- Dark theme for dashboard (light theme default)
- Phone-responsive dashboard (desktop + tablet only)
- ES cluster mode (horizontal scaling)
- HA/failover for ES
- CI/CD pipeline (GitHub Actions) -- manual `fly deploy` for now
</user_constraints>

## Standard Stack

### Core — Worker (Python)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| APScheduler | 3.11.x | Cron-based job scheduling | Mature, async-compatible, well-tested with FastAPI |
| aiosqlite | 0.20.x | Async SQLite access | Standard for async Python + SQLite; wraps sqlite3 |
| FastAPI | >=0.115 | Worker internal API (port 8081) | Already used in web server |
| uvicorn | >=0.34 | ASGI server for worker API | Already used |
| httpx | >=0.28 | HTTP client for Liferay discovery + ES queries | Already used |
| requests | >=2.31 | Sync HTTP for download pipeline | Already used in zip_downloader |

### Core — ES Machine
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Elasticsearch | 8.15.x | Search engine | Already used in docker-compose (8.15.2) |
| repository-s3 plugin | (bundled) | S3 snapshot repository for Tigris backups | Official ES plugin for S3-compatible backup |

### Core — Dashboard (React)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| @tanstack/react-query | ^5.83 | Server state + auto-refresh | Already installed |
| zustand | ^5.x | Client state (tab selection, filters) | Locked decision; lightweight store |
| lucide-react | ^0.462 | Icons | Already installed |
| recharts | ^2.15 | Coverage charts | Already installed |
| sonner | ^1.7 | Toast notifications | Already installed |
| @radix-ui/react-tabs | ^1.1 | Tab navigation | Already installed |
| @radix-ui/react-progress | ^1.1 | Progress bars for coverage | Already installed |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| chardet | 5.x | Encoding detection for old DOU files | Latin-1/UTF-8 detection on pre-2019 ZIPs |
| @tanstack/react-virtual | ^3.x | Virtual scrolling for timeline | Only if 867-file list causes perf issues (likely yes) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| APScheduler 3.11 | APScheduler 4.x | 4.x is alpha/unstable; 3.11 is proven |
| aiosqlite | sqlite3 (sync) | aiosqlite needed because FastAPI worker is async |
| Zustand | React Context | Zustand is simpler for cross-component state, no provider nesting |

**Installation (Worker):**
```bash
pip install APScheduler>=3.11 aiosqlite>=0.20 chardet>=5.0
```

**Installation (Dashboard):**
```bash
cd src/frontend/web && npm install zustand @tanstack/react-virtual
```

## Architecture Patterns

### Recommended Project Structure
```
ops/deploy/
  web/fly.toml              # WEB machine config (existing, modified)
  web/Dockerfile             # WEB Dockerfile (existing, modified)
  worker/fly.toml            # NEW: Worker machine config
  worker/Dockerfile          # NEW: Worker Dockerfile
  es/fly.toml                # NEW: ES machine config
  es/Dockerfile              # NEW: ES Dockerfile
  es/elasticsearch.yml       # NEW: ES config (single-node, no security)

src/backend/
  worker/                    # NEW: Worker application
    main.py                  # Entrypoint: FastAPI + APScheduler startup
    scheduler.py             # APScheduler cron job definitions
    registry.py              # SQLite registry (dou_files, pipeline_runs, pipeline_log)
    api.py                   # Internal API routes (/registry/*, /pipeline/*)
    pipeline/
      discovery.py           # Liferay crawler + HEAD probe fallback
      downloader.py          # ZIP download with rate limiting
      extractor.py           # ZIP extraction (multi-era format handling)
      ingestor.py            # XML parse + ES bulk index (bypasses PostgreSQL)
      verifier.py            # Post-ingest verification (doc count check)
    migration.py             # One-time: catalog JSON -> SQLite + ES cross-ref

src/frontend/web/src/
  pages/
    PipelinePage.tsx          # NEW: Dashboard page (tab container)
  components/pipeline/       # NEW: Dashboard components
    PipelineOverview.tsx      # Health, metrics, coverage, quick actions
    PipelineTimeline.tsx      # Month-by-month detail
    PipelineScheduler.tsx     # Scheduler status + execution history
    PipelineLogs.tsx          # Filterable event log
    PipelineSettings.tsx      # Schedule config, disk usage, danger zone
    MonthCard.tsx             # Expandable month with file rows
    FileStatusBadge.tsx       # Status badge component
    CoverageChart.tsx         # Year-by-year progress bars
  hooks/
    usePipeline.ts            # NEW: React Query hooks for worker API
  lib/
    workerApi.ts              # NEW: API client for /api/worker/* proxy
```

### Pattern 1: Fly.io Multi-App with Internal Networking
**What:** 3 separate Fly apps in the same organization, communicating via `.internal` DNS over 6PN private network.
**When to use:** When machines have different resource profiles and lifecycle requirements.

Key configuration:
```toml
# ops/deploy/worker/fly.toml
app = 'gabi-dou-worker'
primary_region = 'gru'

[env]
  ES_URL = 'http://gabi-dou-es.internal:9200'
  REGISTRY_DB = '/data/registry.db'

[mounts]
  source = 'gabi_worker_data'
  destination = '/data'

# No [http_service] — worker is internal only
# No [[services]] — not exposed to internet

[[vm]]
  size = 'shared-cpu-1x'
  memory = '512mb'
  auto_stop_machines = false   # Must stay running for scheduler
```

```toml
# ops/deploy/es/fly.toml
app = 'gabi-dou-es'
primary_region = 'gru'

[mounts]
  source = 'gabi_es_data'
  destination = '/usr/share/elasticsearch/data'

[[vm]]
  size = 'performance-2x'
  memory = '4096mb'
```

### Pattern 2: Web Proxy to Worker Internal API
**What:** The web FastAPI proxies `/api/worker/*` to `worker.internal:8081/*` using httpx.
**When to use:** To expose internal worker data to the dashboard without exposing the worker to the internet.

```python
# In web_server.py
import httpx

WORKER_BASE = "http://gabi-dou-worker.internal:8081"

@app.api_route("/api/worker/{path:path}", methods=["GET", "POST"])
async def proxy_worker(path: str, request: Request):
    async with httpx.AsyncClient() as client:
        resp = await client.request(
            method=request.method,
            url=f"{WORKER_BASE}/{path}",
            headers={"content-type": request.headers.get("content-type", "")},
            content=await request.body() if request.method == "POST" else None,
            timeout=10.0,
        )
        return Response(content=resp.content, status_code=resp.status_code,
                        media_type=resp.headers.get("content-type"))
```

### Pattern 3: SQLite Registry with WAL Mode
**What:** SQLite database in WAL mode for concurrent read/write from scheduler (writer) and API (reader).
**When to use:** Single-machine state management where PostgreSQL is overkill.

```python
import aiosqlite
import sqlite3

DB_PATH = "/data/registry.db"

async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    db.row_factory = aiosqlite.Row
    return db

# Schema
SCHEMA = """
CREATE TABLE IF NOT EXISTS dou_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL UNIQUE,
    section TEXT NOT NULL,          -- do1, do2, do3, se
    year_month TEXT NOT NULL,       -- 2026-01
    folder_id INTEGER,
    file_url TEXT,
    status TEXT NOT NULL DEFAULT 'DISCOVERED',
    retry_count INTEGER DEFAULT 0,
    doc_count INTEGER,
    file_size_bytes INTEGER,
    sha256 TEXT,
    error_message TEXT,
    discovered_at TEXT NOT NULL,
    queued_at TEXT,
    downloaded_at TEXT,
    extracted_at TEXT,
    ingested_at TEXT,
    verified_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id TEXT PRIMARY KEY,            -- UUID
    phase TEXT NOT NULL,            -- discovery, download, ingest, verify, retry
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL,
    completed_at TEXT,
    files_processed INTEGER DEFAULT 0,
    files_succeeded INTEGER DEFAULT 0,
    files_failed INTEGER DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS pipeline_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT REFERENCES pipeline_runs(id),
    file_id INTEGER REFERENCES dou_files(id),
    level TEXT NOT NULL DEFAULT 'INFO',
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dou_files_status ON dou_files(status);
CREATE INDEX IF NOT EXISTS idx_dou_files_year_month ON dou_files(year_month);
CREATE INDEX IF NOT EXISTS idx_pipeline_log_run_id ON pipeline_log(run_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_log_created ON pipeline_log(created_at);
"""
```

### Pattern 4: APScheduler with FastAPI Lifespan
**What:** AsyncIOScheduler started/stopped with FastAPI lifespan context manager.
**When to use:** When scheduler and API share the same process.

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from contextlib import asynccontextmanager

scheduler = AsyncIOScheduler(timezone="UTC")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Add cron jobs
    scheduler.add_job(run_discovery, CronTrigger(hour=23, minute=0), id="discovery")
    scheduler.add_job(run_download, CronTrigger(hour=23, minute=30), id="download")
    scheduler.add_job(run_ingest, CronTrigger(hour=0, minute=0), id="ingest")
    scheduler.add_job(run_verify, CronTrigger(hour=1, minute=0), id="verify")
    scheduler.add_job(run_retry, CronTrigger(hour=6, minute=0), id="retry")
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)

app = FastAPI(lifespan=lifespan)
```

### Pattern 5: ES Dockerfile with Volume Permissions
**What:** Elasticsearch Dockerfile that correctly handles volume permissions on Fly.io.
**When to use:** Deploying ES on Fly.io with persistent volumes.

```dockerfile
FROM docker.elastic.co/elasticsearch/elasticsearch:8.15.2

# Fly.io volumes mount as root; ES runs as elasticsearch user
# Use init script to fix permissions before starting ES
COPY --chmod=755 entrypoint.sh /usr/local/bin/entrypoint.sh

ENV discovery.type=single-node
ENV xpack.security.enabled=false
ENV ES_JAVA_OPTS="-Xms2g -Xmx2g"
ENV path.data=/usr/share/elasticsearch/data

USER root
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
```

```bash
#!/bin/bash
# entrypoint.sh — fix volume ownership then drop to elasticsearch user
chown -R elasticsearch:elasticsearch /usr/share/elasticsearch/data
exec su-exec elasticsearch /usr/share/elasticsearch/bin/elasticsearch
```

### Anti-Patterns to Avoid
- **Exposing worker to internet:** Worker MUST have no `[http_service]` or `[[services]]` in fly.toml. Dashboard access is via web proxy only.
- **Using APScheduler 4.x:** It is alpha/unstable. Stick with 3.11.x.
- **Sharing SQLite across machines:** SQLite is local to the worker volume. Never try to mount it from another machine.
- **Running ES as root:** Elasticsearch refuses to run as root. Use a chown + su-exec pattern in the entrypoint.
- **Forgetting `auto_stop_machines = false` on worker:** If the worker auto-stops, scheduled jobs stop. It MUST stay running.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cron scheduling | Custom sleep loops | APScheduler CronTrigger | Handles timezone, missed fires, graceful shutdown |
| Encoding detection | Heuristic byte scanning | chardet library | Handles Latin-1, CP1252, UTF-8 edge cases in old DOUs |
| Virtual scrolling | Manual windowing | @tanstack/react-virtual | 867 items benefits from virtualization; complex to hand-roll |
| S3 snapshot management | Custom backup scripts | ES repository-s3 plugin | Handles incremental snapshots, restore, lifecycle |
| HTTP reverse proxy | Custom socket forwarding | httpx.AsyncClient | Handles connection pooling, timeouts, streaming |
| Toast notifications | Custom notification system | sonner (already installed) | Consistent with existing app UX |

**Key insight:** The existing codebase already has 80% of the pipeline logic (`auto_discovery.py`, `zip_downloader.py`, `orchestrator.py`, `es_indexer.py`, `dou_ingest.py`). The main work is adapting these to use SQLite instead of PostgreSQL for registry state, and wiring them into APScheduler cron jobs on the worker machine.

## Common Pitfalls

### Pitfall 1: Fly.io Volume Permissions for Elasticsearch
**What goes wrong:** Fly.io volumes mount as root-owned. ES refuses to start because it cannot write to the data directory.
**Why it happens:** ES runs as `elasticsearch` user but the volume is owned by root.
**How to avoid:** Use a custom entrypoint that runs `chown -R elasticsearch:elasticsearch /data` before dropping to the elasticsearch user via `su-exec`.
**Warning signs:** `failed to obtain node locks` error in ES logs.

### Pitfall 2: .internal DNS Only Resolves Running Machines
**What goes wrong:** Web proxy to `gabi-dou-worker.internal` fails with DNS resolution error.
**Why it happens:** Fly.io `.internal` DNS only returns AAAA records for started/running machines. If worker is stopped, DNS returns nothing.
**How to avoid:** Set `auto_stop_machines = false` on the worker. Add health check timeout handling in the web proxy. Return 503 to dashboard if worker is unreachable.
**Warning signs:** Intermittent "connection refused" errors in web proxy logs.

### Pitfall 3: SQLite WAL Checkpoint Starvation
**What goes wrong:** WAL file grows unbounded because readers always hold a read lock.
**Why it happens:** React Query auto-refresh at 30s means the API is always reading. Checkpointing requires a gap with no readers.
**How to avoid:** Set `PRAGMA wal_autocheckpoint=1000` (default). The single-writer model with aiosqlite naturally creates gaps. Monitor WAL file size in the Settings tab.
**Warning signs:** WAL file exceeding 100MB.

### Pitfall 4: Rate Limiting Against in.gov.br
**What goes wrong:** IP gets blocked by in.gov.br firewall, breaking discovery and downloads.
**Why it happens:** Too many concurrent requests to Liferay API or download endpoints.
**How to avoid:** Enforce max 5 req/s with asyncio.Semaphore or time.sleep. Use random User-Agent rotation (already in zip_downloader). Add exponential backoff on 429/503.
**Warning signs:** HTTP 403 or connection timeout from in.gov.br.

### Pitfall 5: ES Memory OOM on 4GB Machine
**What goes wrong:** ES crashes with OOM on startup or during bulk indexing.
**Why it happens:** JVM heap set too high, or OS needs memory for file cache and page cache.
**How to avoid:** Set JVM heap to 2GB (50% of 4GB RAM). Leave 2GB for OS and file system cache. Use bulk batch sizes of 200-500 documents.
**Warning signs:** ES process killed by OOM killer, machine restarts.

### Pitfall 6: Existing Pipeline Assumes PostgreSQL
**What goes wrong:** Trying to reuse `dou_ingest.py` directly fails because it uses psycopg2 to insert into PostgreSQL.
**Why it happens:** The existing ingestor inserts into `dou.*` PostgreSQL schema. Phase 11 pipeline must index directly to ES.
**How to avoid:** The Phase 11 ingestor should: (1) extract XML from ZIP, (2) parse with existing `INLabsXMLParser`, (3) normalize with existing normalizer, (4) bulk-index to ES using `ESClient` from `es_indexer.py`. Do NOT route through PostgreSQL for the autonomous pipeline.
**Warning signs:** Import errors for psycopg2 on the worker machine.

### Pitfall 7: Fly.io App Creation Order
**What goes wrong:** Worker cannot reach ES because ES app doesn't exist yet.
**Why it happens:** Apps must be created in dependency order: ES first, then worker, then web.
**How to avoid:** Deploy in order: (1) ES app + volume, (2) Worker app + volume, (3) Web app updated config. Verify each with health checks before proceeding.

## Code Examples

### Worker Internal API Routes
```python
# src/backend/worker/api.py
from fastapi import FastAPI, HTTPException
from datetime import datetime, timezone

app = FastAPI(title="GABI Worker Internal API")

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "uptime_seconds": ...,
        "scheduler_running": scheduler.running,
        "last_heartbeat": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/registry/status")
async def registry_status():
    async with get_db() as db:
        cursor = await db.execute("""
            SELECT status, COUNT(*) as count
            FROM dou_files
            GROUP BY status
        """)
        rows = await cursor.fetchall()
        return {row["status"]: row["count"] for row in rows}

@app.get("/registry/months")
async def registry_months(year: int | None = None):
    async with get_db() as db:
        query = "SELECT year_month, section, status, doc_count FROM dou_files"
        params = []
        if year:
            query += " WHERE year_month LIKE ?"
            params.append(f"{year}-%")
        query += " ORDER BY year_month DESC, section"
        cursor = await db.execute(query, params)
        return await cursor.fetchall()

@app.post("/pipeline/trigger/{phase}")
async def trigger_phase(phase: str):
    valid = {"discovery", "download", "ingest", "verify", "retry"}
    if phase not in valid:
        raise HTTPException(400, f"Invalid phase: {phase}")
    # Run immediately in background
    scheduler.add_job(PHASE_MAP[phase], id=f"manual_{phase}_{int(time.time())}")
    return {"triggered": phase}
```

### Dashboard React Query Hooks
```typescript
// src/frontend/web/src/hooks/usePipeline.ts
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

const WORKER_BASE = "/api/worker";

export function usePipelineStatus() {
  return useQuery({
    queryKey: ["pipeline", "status"],
    queryFn: () => fetch(`${WORKER_BASE}/registry/status`).then(r => r.json()),
    refetchInterval: 30_000,
  });
}

export function usePipelineMonths(year?: number) {
  return useQuery({
    queryKey: ["pipeline", "months", year],
    queryFn: () => fetch(`${WORKER_BASE}/registry/months${year ? `?year=${year}` : ""}`).then(r => r.json()),
    refetchInterval: 30_000,
  });
}

export function useTriggerPipeline() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (phase: string) =>
      fetch(`${WORKER_BASE}/pipeline/trigger/${phase}`, { method: "POST" }).then(r => r.json()),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pipeline"] }),
  });
}
```

### ES Snapshot to Tigris
```python
# Worker: register S3 snapshot repository pointing to Tigris
import httpx

ES_URL = "http://gabi-dou-es.internal:9200"

async def register_snapshot_repo():
    """Register Tigris as ES snapshot repository (one-time setup)."""
    await httpx.put(f"{ES_URL}/_snapshot/tigris_backup", json={
        "type": "s3",
        "settings": {
            "bucket": "gabi-dou-es-snapshots",
            "endpoint": "fly.storage.tigris.dev",
            "protocol": "https",
            "path_style_access": True,
        }
    })

async def create_snapshot():
    """Create a named snapshot (called daily by scheduler)."""
    name = f"daily-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}"
    await httpx.put(f"{ES_URL}/_snapshot/tigris_backup/{name}", json={
        "indices": "gabi_documents_v1",
        "include_global_state": False,
    })
```

### Migration Script (Catalog JSON to SQLite)
```python
# src/backend/worker/migration.py
import json
import sqlite3
from datetime import datetime, timezone

def migrate_catalog_to_sqlite(catalog_path: str, db_path: str, es_url: str):
    """One-time migration: reads dou_catalog_registry.json, populates SQLite,
    cross-references with ES to mark already-ingested files."""
    with open(catalog_path) as f:
        catalog = json.load(f)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    # Get ingested months from ES
    ingested = _get_es_ingested_months(es_url)

    for entry in catalog["files"]:
        filename = entry["filename"]
        year_month = entry["year_month"]
        section = entry["section"]
        status = "INGESTED" if (year_month, section) in ingested else "DISCOVERED"
        now = datetime.now(timezone.utc).isoformat()

        conn.execute("""
            INSERT OR IGNORE INTO dou_files (filename, section, year_month, folder_id, status, discovered_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (filename, section, year_month, entry.get("folder_id"), status, now, now))

    conn.commit()
    conn.close()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single Fly app with process groups | Separate Fly apps per service | Fly.io 2024+ | Better resource isolation, independent scaling |
| APScheduler 4.x (alpha) | APScheduler 3.11.x (stable) | 2025 | 4.x complete rewrite, not production-ready |
| PostgreSQL for everything | SQLite for local state | Architecture decision | Simpler deployment, no network dependency for state |
| ARQ + Redis for pipeline jobs | APScheduler in-process | Architecture decision | No Redis dependency on worker; simpler for scheduled tasks |

**Deprecated/outdated:**
- APScheduler 4.x: Complete rewrite, still alpha. Do not use in production.
- `discovery_registry.py` PostgreSQL backend: Phase 11 replaces with SQLite on worker volume.

## Open Questions

1. **Tigris S3 API Compatibility with ES repository-s3**
   - What we know: ES requires full S3 API compatibility for snapshots. Tigris is S3-compatible but ES has strict requirements.
   - What's unclear: Whether Tigris supports all the S3 API endpoints ES needs (multipart upload, ETag validation, etc.).
   - Recommendation: Test snapshot creation early. If Tigris fails, fall back to daily `elasticdump` to a JSON file on the volume, synced to Tigris via boto3.

2. **Worker Memory Budget (512MB)**
   - What we know: Worker runs APScheduler + FastAPI + SQLite. ZIP extraction and XML parsing happen in-process.
   - What's unclear: Whether 512MB is sufficient for large ZIP extraction (some ZIPs may be 100MB+).
   - Recommendation: Extract ZIPs to `/data/tmp/` on the volume (not tmpfs). Process files one at a time. Monitor RSS. Upgrade to 1GB if needed.

3. **Encoding Detection for Pre-2019 DOUs**
   - What we know: Old DOUs may use Latin-1 or CP1252 encoding. Current parser assumes UTF-8.
   - What's unclear: Exact distribution of encoding issues across the 2002-2018 archive.
   - Recommendation: Use chardet on first 10KB of each XML. If confidence < 0.8, try Latin-1 fallback. Log encoding detections for monitoring.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework (Frontend) | Vitest 3.2.x + React Testing Library |
| Framework (Backend) | pytest (ad-hoc, no formal config) |
| Config file (Frontend) | `src/frontend/web/vitest.config.ts` |
| Quick run command (Frontend) | `cd src/frontend/web && npm test` |
| Full suite command | `cd src/frontend/web && npm test` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FLY-01 | ES fly.toml valid config | manual | `fly deploy --config ops/deploy/es/fly.toml --dryrun` | N/A Wave 0 |
| FLY-02 | Worker fly.toml valid config | manual | `fly deploy --config ops/deploy/worker/fly.toml --dryrun` | N/A Wave 0 |
| FLY-03 | Web proxy routes to worker | integration | Manual: `curl /api/worker/health` | N/A Wave 0 |
| PIPE-01 | SQLite schema creation | unit | `pytest tests/test_worker_registry.py -x` | -- Wave 0 |
| PIPE-02 | State machine transitions | unit | `pytest tests/test_worker_registry.py -x` | -- Wave 0 |
| PIPE-03 | Discovery finds new files | unit | `pytest tests/test_pipeline_discovery.py -x` | -- Wave 0 |
| PIPE-04 | Migration script populates SQLite | unit | `pytest tests/test_pipeline_migration.py -x` | -- Wave 0 |
| DASH-01 | Pipeline page renders tabs | unit | `cd src/frontend/web && npx vitest run src/components/pipeline` | -- Wave 0 |
| DASH-02 | usePipeline hooks fetch data | unit | `cd src/frontend/web && npx vitest run src/hooks/usePipeline` | -- Wave 0 |

### Sampling Rate
- **Per task commit:** `cd src/frontend/web && npm test` (frontend) / `pytest tests/test_worker_*.py -x` (backend)
- **Per wave merge:** Full test suites
- **Phase gate:** All tests green + successful `fly deploy --dryrun` for all 3 apps

### Wave 0 Gaps
- [ ] `tests/test_worker_registry.py` -- SQLite schema + state machine tests
- [ ] `tests/test_pipeline_discovery.py` -- Discovery logic tests
- [ ] `tests/test_pipeline_migration.py` -- Migration script tests
- [ ] `src/frontend/web/src/components/pipeline/*.test.tsx` -- Dashboard component tests
- [ ] pytest config: add `pyproject.toml` with `[tool.pytest.ini_options]` if not present

## Sources

### Primary (HIGH confidence)
- Existing codebase: `ops/deploy/web/fly.toml`, `src/backend/ingest/*.py`, `src/frontend/web/package.json`
- [Fly.io Private Networking Docs](https://fly.io/docs/networking/private-networking/) - .internal DNS, 6PN
- [Fly.io Volumes Docs](https://fly.io/docs/volumes/overview/) - Persistent storage
- [Fly.io Monorepo Docs](https://fly.io/docs/launch/monorepo/) - Multi-app deployment
- [APScheduler PyPI](https://pypi.org/project/APScheduler/) - Version 3.11.x
- [SQLite WAL Documentation](https://sqlite.org/wal.html) - WAL mode behavior
- [ES S3 Repository Docs](https://www.elastic.co/docs/deploy-manage/tools/snapshot-and-restore/s3-repository) - Snapshot config

### Secondary (MEDIUM confidence)
- [Fly.io ES Volume Permissions](https://community.fly.io/t/volume-permission-denied-with-elasticsearch-app/20861) - Permission fix pattern
- [Fly.io SQLite WAL Blog](https://fly.io/blog/sqlite-internals-wal/) - SQLite on Fly.io best practices
- [APScheduler User Guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html) - AsyncIOScheduler usage

### Tertiary (LOW confidence)
- Tigris S3 API full compatibility with ES repository-s3: needs validation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Libraries are either already in use or well-established
- Architecture (Fly.io multi-app): HIGH - Well-documented Fly.io pattern
- Architecture (SQLite pipeline): HIGH - SQLite WAL is proven, existing pipeline modules provide foundation
- Architecture (Dashboard): HIGH - All libraries already installed, React Query auto-refresh is standard
- Pitfalls: HIGH - Based on official docs and community reports
- ES snapshots to Tigris: LOW - S3 compatibility not verified

**Research date:** 2026-03-09
**Valid until:** 2026-04-09 (stable technologies, 30-day validity)
