# Phase 11: Fly.io Migration and Dashboard and Extensibility - Context

**Gathered:** 2026-03-09
**Status:** Ready for planning
**Source:** Inline PRD (conversation decisions + mega prompts)

<domain>
## Phase Boundary

This phase delivers three interconnected capabilities:

1. **Fly.io Migration** — Deploy the full GABI Search stack (web + worker + ES) to Fly.io with 3 separate machines
2. **Autonomous Ingestion Pipeline** — Replace manual JSON-based catalog with auto-discovery, download, extraction, indexing, and verification pipeline using SQLite state machine
3. **Admin Dashboard** — React-based pipeline control center for monitoring and managing the ingestion pipeline

</domain>

<decisions>
## Implementation Decisions

### Infrastructure Architecture
- 3 Fly.io Machines: WEB (FastAPI + React SPA), WORKER (pipeline + SQLite + internal API), ES (Elasticsearch 8.x single-node)
- Primary region: `gru` (Sao Paulo)
- WEB queries ES directly for search; proxies `/api/worker/*` to `worker.internal:8081` for dashboard
- WORKER never exposed to internet; only accessible via Fly internal network (`.internal` DNS)
- ES accessible at `es.internal:9200`

### Elasticsearch on Fly.io
- Single-node ES on dedicated machine with persistent volume (50GB)
- Machine: performance-2x (2 vCPU, 4GB RAM), JVM heap 2GB
- No HA, no replicas — acceptable for TCU internal tool
- Backup: Daily ES snapshots to Tigris (S3-compatible)
- Index mapping: Portuguese analyzer with `brazilian_stemmer`, `asciifolding`, `brazilian_stop`

### Pipeline Registry — SQLite
- SQLite in WAL mode on worker volume at `/data/registry.db`
- 3 tables: `dou_files` (state per ZIP), `pipeline_runs` (audit log), `pipeline_log` (event log)
- State machine: DISCOVERED → QUEUED → DOWNLOADING → DOWNLOADED → EXTRACTING → EXTRACTED → INGESTING → INGESTED → VERIFIED
- Failure states: DOWNLOAD_FAILED, EXTRACT_FAILED, INGEST_FAILED, VERIFY_FAILED
- Retry: up to 3 retries per file
- All timestamps UTC ISO 8601
- Worker owns SQLite; web queries via internal API proxy

### Discovery — Dual Source Strategy
- INLABS is the primary discovery channel for new publications, but only within its rolling availability window of the last 30 days
- Historical coverage and older backfill remain on public Liferay monthly ZIPs using `ops/data/dou_catalog_registry.json`
- Operational rule:
  - Historical (`<= 2019`) -> Liferay only
  - Recent already mapped in the JSON catalog (`2020+`) -> Liferay allowed for backfill and month-close fallback
  - Future / day-to-day auto-discovery (`now - 30 days` to today) -> INLABS first
  - If INLABS fails for recent content, fallback is not “probe ancient INLABS”; fallback is to wait for the month archive to land in `in.gov.br` Liferay and then ingest from there
- Liferay JSONWS / HEAD probing stays as a backfill and emergency source, not the primary live-discovery path
- Rate limit: max 5 req/s per host
- Schedule: discovery loop every 12 hours, with retry checks every 2 hours

### Pipeline Orchestrator
- APScheduler with 5 cron jobs: discovery (23:00), download (23:30), ingest (00:00), verify (01:00), retry (06:00)
- Each phase creates a `pipeline_runs` record with UUID
- Graceful shutdown on SIGTERM
- Heartbeat every 60s for dashboard health check
- Idempotent: re-running any phase produces same result
- Fail small: one file failing does not stop the batch
- Hybrid search must remain usable before the historical corpus is complete; BM25 is the base availability layer, embeddings are additive

### Worker Internal API
- FastAPI on port 8081 (internal only)
- Endpoints: `/registry/status`, `/registry/months`, `/registry/files/{id}`, `/pipeline/runs`, `/pipeline/logs`, `/pipeline/trigger/{phase}`, `/pipeline/retry/{file_id}`, `/pipeline/pause`, `/pipeline/resume`, `/health`

### Initial Migration
- One-time script: reads `dou_catalog_registry.json` → populates SQLite
- Cross-references with ES to mark already-ingested files as INGESTED
- ~867 files (289 months x 3 sections)

### Worker Fly.io Config
- `shared-cpu-1x`, 512MB RAM
- Volume mounted at `/data` for registry.db + tmp/
- Dockerfile: python:3.12-slim, non-root user, healthcheck
- `auto_stop_machines = false` (worker must stay running for scheduler)

### Admin Dashboard
- Tab-based navigation: Overview, Timeline, Pipeline, Logs, Settings
- Auto-refresh every 30s via React Query
- Keyboard shortcuts: 1-5 for tabs, R refresh, P pause
- Overview: health badge, 4 metric cards, recent activity, coverage by year, quick actions
- Timeline: month-by-month detail with per-file status, retry/log actions on failures
- Pipeline: scheduler status, next runs, execution history
- Logs: filterable event log stream (level, file, run)
- Settings: schedule config, disk usage, danger zone
- Proxy: web FastAPI proxies `/api/worker/*` to `worker.internal:8081/*`
- Stack: React 18 + TypeScript + Tailwind CSS + Lucide React + React Query + Zustand

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
- How to encode the INLABS 30-day boundary in code so the worker cannot accidentally request older content from INLABS
- Month-close fallback policy for recent files that missed INLABS but become available as monthly Liferay ZIPs

</decisions>

<specifics>
## Specific Ideas

- ZIP naming pattern: `S{section:02d}{month:02d}{year:04d}.zip` (e.g., S01022026.zip)
- Sections: S01, S02, S03, SE (extra)
- DOUDocument model: id, year_month, publication_date, section, title, body, act_type, act_number, orgao, signatario, dou_page, source_zip, extracted_at, indexed_at
- Coverage visualization: per-year progress bars in dashboard overview
- Month card in timeline: header with status badge, per-file rows with section/filename/status/doc_count/size/duration
- Worker Dockerfile uses `python -m src.worker.main` as entrypoint
- Migration script before full pipeline: verify registry looks correct first

</specifics>

<deferred>
## Deferred Ideas

- PostgreSQL migration (when multi-machine or more stateful tables needed)
- Dark theme for dashboard (light theme default)
- Phone-responsive dashboard (desktop + tablet only)
- ES cluster mode (horizontal scaling)
- HA/failover for ES
- CI/CD pipeline (GitHub Actions) — manual `fly deploy` for now

</deferred>

---

*Phase: 11-fly-io-migration-and-dashboard-and-extensibility*
*Context gathered: 2026-03-09 via Inline PRD*
