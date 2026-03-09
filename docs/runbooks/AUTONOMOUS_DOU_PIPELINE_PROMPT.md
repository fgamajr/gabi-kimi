# Unified Pipeline Architectural Reference -- GABI DOU

> **Purpose:** This document is an architectural reference for implementation agents working on the GABI DOU pipeline. It is NOT a single execution blob. Each section describes a specific aspect of the system so that agents can integrate with existing infrastructure without accidentally rewriting it or making incorrect topology assumptions.
>
> **Companion document:** See [AUTONOMOUS_DOU_STATUS_AND_FLY_PREFLIGHT.md](AUTONOMOUS_DOU_STATUS_AND_FLY_PREFLIGHT.md) for current implementation state, open gaps, Fly.io migration blockers, and extensibility planning.

---

## FONTES DE DADOS -- DUAL-SOURCE STRATEGY

The GABI DOU pipeline uses two data sources with distinct responsibilities:

1. **Liferay (in.gov.br)** -- The authoritative source for historical DOU content (2002 through anything outside the recent window). Liferay provides monthly ZIP archives via public URLs. This is the only source for historical backfill.

2. **INLABS (Imprensa Nacional)** -- The operational source for recent DOU editions within the last 30 days. INLABS provides daily ZIP downloads via authenticated API. This is a short-window source only.

**Key principle:** The pipeline treats INLABS as recent-only infrastructure. Historical ingestion always uses Liferay. If INLABS fails for a recent edition, the system degrades gracefully: search remains operational with the existing corpus, and the item eventually transitions to Liferay monthly fallback when available.

### Official INLABS References

- Official repository: `https://github.com/Imprensa-Nacional/inlabs`
- Login endpoint: `POST https://inlabs.in.gov.br/logar.php`
- Session cookie: `inlabs_session_cookie`
- Download pattern: `GET https://inlabs.in.gov.br/index.php?p=YYYY-MM-DD&dl=YYYY-MM-DD-DOx.zip`
- INLABS provides XML/PDF since January 1, 2020, but the 30-day window is a project constraint, not a publicly documented INLABS limitation.

---

## PATCH 1 -- CRITICAL SOURCE WINDOW RULE

```
CRITICAL SOURCE WINDOW RULE:
- INLABS must only be used for the last 30 days of DOU editions.
- Do not attempt to use INLABS for historical backfill older than 30 days.
- This is a PROJECT constraint, not a publicly documented INLABS limitation.
- Historical ingestion (2002 through anything outside the 30-day window)
  must use the mapped public Liferay URLs from in.gov.br.
- If INLABS fails for a recent edition:
  1. Keep search operational with the already-indexed corpus.
  2. Retry INLABS within the 30-day window.
  3. If the item ages out of the 30-day window, mark it as FALLBACK_PENDING.
  4. When the monthly Liferay ZIP becomes available, enqueue that fallback automatically.
- BM25 remains the baseline retrieval layer; embeddings are additive, not blocking.
- Hybrid search must remain fully functional while historical backlog is incomplete.
```

---

## PATCH 2 -- ARQUITETURA DEFINITIVA (5-App Topology)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         Fly.io Infrastructure (região: GRU)                  │
│                                                                              │
│  ┌── App 1: gabi-dou-frontend ──┐                                           │
│  │  Static SPA (React/TS)       │  Public: HTTPS                            │
│  │  CDN-served, no backend      │  Origin: gabi-dou-frontend.fly.dev        │
│  └──────────────────────────────┘                                           │
│             │ calls API                                                      │
│             ▼                                                                │
│  ┌── App 2: gabi-dou-web ───────────────────────────────────────────┐       │
│  │  FastAPI (public, :8080)                                          │       │
│  │  ├─ /search, /api/v1/* (public search, IP rate-limited)          │       │
│  │  ├─ /api/document/* (protected, bearer-token auth)               │       │
│  │  ├─ /api/admin/* (admin-only, role-checked)                      │       │
│  │  ├─ /api/chat (protected, Qwen, rate-limited)                    │       │
│  │  ├─ /api/worker/* (proxy → worker.internal:8081)                 │       │
│  │  ├─ /healthz (public, Fly liveness)                              │       │
│  │  └─ /dist/* (static path containment, only if serving frontend)  │       │
│  │                                                                   │       │
│  │  ALREADY IMPLEMENTED:                                             │       │
│  │  ├─ Bearer-token auth + Postgres identity store                  │       │
│  │  ├─ httpOnly signed sessions for document reader                 │       │
│  │  ├─ Per-principal + per-IP rate limiting (Redis-backed)          │       │
│  │  ├─ Trusted Host validation, CSP, security headers              │       │
│  │  ├─ Request body size enforcement                                │       │
│  │  ├─ ARQ upload_worker process (manual upload queue, NOT the      │       │
│  │  │   autonomous pipeline — this is a DIFFERENT worker)           │       │
│  │  └─ Admin endpoints: /api/admin/roles, /api/admin/users          │       │
│  │                                                                   │       │
│  │  Depends on: Postgres (identity), Redis (rate limit + ARQ)       │       │
│  └───────────────────────────────────────────────────────────────────┘       │
│           │ proxy                    │ rate limiting                          │
│           ▼                          ▼                                        │
│  ┌── App 3: gabi-dou-worker ────┐  ┌── App 5: gabi-dou-redis ──────┐       │
│  │  Pipeline Autônomo (:8081)    │  │  Redis (rate limits + ARQ)     │       │
│  │  INTERNAL ONLY                │  │  INTERNAL ONLY                 │       │
│  │  ├─ Discovery (INLABS 30d)   │  │  redis://...internal:6379/0   │       │
│  │  ├─ Downloader (INLABS+LR)   │  └──────────────────────────────┘       │
│  │  ├─ Extractor (XML parser)   │                                           │
│  │  ├─ BM25 Indexer (ES bulk)   │  Postgres (managed or Fly)                │
│  │  ├─ Embedder (OpenAI)        │  └─ auth.user, auth.role,                 │
│  │  ├─ Verifier                  │     auth.api_token (identity store)       │
│  │  ├─ Watchdog + Telegram       │                                           │
│  │  ├─ Catalog Reconciler        │                                           │
│  │  └─ Scheduler (APScheduler)  │                                           │
│  │                                │                                           │
│  │  Volume /data:                 │                                           │
│  │  ├─ registry.db (SQLite)      │                                           │
│  │  ├─ tmp/ (ZIPs in transit)    │                                           │
│  │  └─ logs/                     │                                           │
│  └───────────────────────────────┘                                           │
│           │                                                                   │
│           ▼                                                                   │
│  ┌── App 4: gabi-dou-es ────────────────────────────────────────────┐       │
│  │  Elasticsearch 8.x (single-node, INTERNAL ONLY)                   │       │
│  │  Volume /data (50GB)                                              │       │
│  │  ├─ dou_documents index (BM25 + dense_vector)                    │       │
│  │  └─ snapshots → Tigris (S3-compatible, for backup)               │       │
│  │  Accessible: gabi-dou-es.internal:9200                            │       │
│  └───────────────────────────────────────────────────────────────────┘       │
│                                                                              │
│  External connections (WORKER only):                                         │
│  → inlabs.in.gov.br (auth + download, HTTPS)                               │
│  → www.in.gov.br (Liferay direct URLs for historical/fallback, HTTPS)       │
│  → api.openai.com (embeddings, HTTPS)                                       │
│  → api.telegram.org (alerts, HTTPS)                                         │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## PATCH 3 -- EXISTING INFRASTRUCTURE -- DO NOT REWRITE

```
## EXISTING INFRASTRUCTURE — DO NOT REWRITE

The following components are ALREADY IMPLEMENTED and TESTED in the codebase.
The agent must INTEGRATE with them, not replace them.

### Web App (gabi-dou-web)
ALREADY HAS:
- Bearer-token authentication (GABI_API_TOKENS env var, labeled per operator)
- Postgres identity store (auth.user, auth.role, auth.user_role, auth.api_token)
- httpOnly signed browser sessions (GABI_AUTH_SECRET)
- Per-principal + per-IP rate limiting via Redis
- Trusted Host validation (GABI_ALLOWED_HOSTS)
- CSP + security headers middleware (security.py)
- Request body size enforcement (GABI_MAX_BODY_SIZE_BYTES)
- /healthz public endpoint for Fly liveness
- /api/admin/* admin-only endpoints
- ARQ upload_worker process for manual ZIP upload queue (uses Redis)
- Worker proxy: /api/worker/* → http://gabi-dou-worker.internal:8081/*

DO NOT:
- Replace the auth system
- Add a new rate limiter
- Create a new health endpoint
- Change security middleware
- Confuse the ARQ upload_worker with the autonomous pipeline worker

### Pipeline Worker (gabi-dou-worker)
ALREADY HAS:
- Full lifecycle stages (DISCOVERED → ... → VERIFIED)
- Source routing (INLABS vs Liferay, with source field in dou_files)
- SQLite registry bootstrap from ops/data/dou_catalog_registry.json
- Worker binds to :: on Fly, 0.0.0.0 locally
- /health endpoint on :8081
- Dashboard timeline seeding with synthetic state-seed entries

STILL NEEDS (OPEN GAPS from preflight):
- pause/resume persisted (currently in-memory only)
- Delayed Liferay monthly fallback (INLABS failure → wait for month ZIP)
- Re-embed backfill policy for legacy verified corpus
- Watchdog holiday awareness (Brazilian holidays calendar)
- Live catalog extension model (month-level table beyond dou_files)

### Fly.io Configuration
ALREADY ALIGNED:
- web fly.toml checks /healthz
- Worker process group named upload_worker (not autonomous pipeline)
- Worker internal networking configured for .internal DNS
- ES health check at /_cluster/health
- Web → worker: http://gabi-dou-worker.internal:8081
- Worker → ES: http://gabi-dou-es.internal:9200

STILL PENDING:
- Real .internal connectivity validation on Fly
- Volume sizing (worker + ES)
- First-boot behavior with empty volumes
- Tigris snapshot operational validation
- Secrets finalization for both web and worker apps
```

---

## MODULE 1: State Machine

The pipeline worker tracks every DOU file through a registry-backed lifecycle. The current `FileStatus` enum defines these states:

- `DISCOVERED` -- File URL known, not yet queued
- `QUEUED` -- Scheduled for download
- `DOWNLOADING` -- Download in progress
- `DOWNLOAD_FAILED` -- Download failed (retryable)
- `DOWNLOADED` -- ZIP saved to disk
- `EXTRACTING` -- XML extraction in progress
- `EXTRACTED` -- Articles extracted from ZIP
- `EXTRACT_FAILED` -- Extraction failed (retryable)
- `BM25_INDEXING` -- Elasticsearch bulk indexing in progress
- `BM25_INDEXED` -- Articles indexed for BM25 search
- `BM25_INDEX_FAILED` -- Indexing failed (retryable)
- `EMBEDDING` -- OpenAI embedding in progress
- `EMBEDDED` -- Dense vectors stored
- `EMBEDDING_FAILED` -- Embedding failed (retryable)
- `VERIFYING` -- Cross-check in progress
- `VERIFIED` -- File fully processed and verified
- `VERIFY_FAILED` -- Verification failed (retryable)

All failed states can transition back to `QUEUED` for retry (up to `MAX_RETRIES = 3`). The `VERIFIED` state can transition to `EMBEDDING` for re-embed backfill of legacy corpus.

### PATCH 4 -- FALLBACK_PENDING

The following state and DDL represent the TARGET state machine expansion. `FALLBACK_PENDING` is NOT yet in code -- it is a specification for future implementation.

```
# New states for the INLABS 30-day window fallback
'DOWNLOAD_FAILED':    ['DOWNLOADING', 'FALLBACK_PENDING'],  # retry OR wait for monthly
'FALLBACK_PENDING':   ['DOWNLOADING'],  # monthly Liferay ZIP became available

# New table (or columns) for month-level catalog state
CREATE TABLE dou_catalog_months (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year_month TEXT NOT NULL UNIQUE,
    folder_id INTEGER,
    group_id TEXT DEFAULT '49035712',
    source_of_truth TEXT,
    catalog_status TEXT DEFAULT 'KNOWN',
    month_closed INTEGER DEFAULT 0,
    inlabs_window_expires_at TEXT,
    fallback_eligible_at TEXT,
    liferay_zip_available INTEGER DEFAULT 0,
    last_reconciled_at TEXT,
    UNIQUE(year_month)
);
```

---

## MODULE 2: Discovery / Download

Already implemented. The discovery module handles both INLABS (recent 30-day window) and Liferay (historical catalog) sources. Source routing is automatic based on publication date. Details will be expanded in Plan 02.

## MODULE 3: Extractor

Already implemented. Parses XML articles from downloaded ZIP files with ZIP Slip protection and encoding detection (chardet with latin-1 fallback).

## MODULE 4: BM25 Indexer

Already implemented. Bulk indexes extracted articles into Elasticsearch using batch size 300. BM25 search becomes available immediately after indexing, before embeddings complete.

## MODULE 5: Embedder

Already implemented. Generates dense vectors via OpenAI API and stores them in the Elasticsearch index alongside BM25 fields. Supports re-embed backfill for legacy verified corpus.

## MODULE 6: Verifier

Already implemented. Cross-checks indexed document counts against extracted article counts with 5% tolerance. Marks files as VERIFIED when counts match.

---

## PATCH 5 -- MODULE 6B: Catalog Reconciler

The Catalog Reconciler is NOT yet implemented. It is a specification for the automatic recovery path when INLABS items age out of the 30-day window.

```
## MODULE 6B — Catalog Reconciler (Liferay Monthly Fallback)

class CatalogReconciler:
    """
    Periodically checks if monthly Liferay ZIPs are now available
    for items that failed during the INLABS window.

    Runs: Once per week (monthly ZIPs appear on first Tuesday of next month)

    Logic:
    1. Get all dou_catalog_months where month_closed=0 and month is past
    2. For each, check if Liferay has the monthly ZIP:
       - If folder_id is known: HEAD request to the expected URL
       - If folder_id unknown: probe predictively (IDs grow monotonically)
    3. If ZIP found: mark liferay_zip_available=1, month_closed=1
    4. Get all dou_files in FALLBACK_PENDING for that month
    5. Update their download_url to the Liferay URL
    6. Transition from FALLBACK_PENDING → DOWNLOADING

    This is the automatic recovery path for:
    "INLABS was down for a week, those editions are now past 30 days,
     but the monthly ZIP on Liferay just appeared, so we grab it there."
    """
```

---

## MODULE 7: Orchestrator

The orchestrator coordinates all pipeline modules via APScheduler. It runs discovery, download, extraction, indexing, embedding, and verification in sequence. The scheduler supports pause/resume (currently in-memory only; persistent pause is an open gap).

---

## PATCHES 6-9 (To Be Applied in Plan 02)

The following patches are specified in the PRD but will be applied in Plan 02:

- **PATCH 6** -- Two-worker disambiguation (ARQ upload_worker vs autonomous pipeline worker)
- **PATCH 7** -- INLABS auth details expansion for MODULE 2
- **PATCH 8** -- Updated execution order adjusted for current codebase state
- **PATCH 9** -- Modular prompt usage guidance (meta section)

---

## Cross-References

- **Architecture target:** [AUTONOMOUS_DOU_PIPELINE.md](AUTONOMOUS_DOU_PIPELINE.md)
- **Implementation state + Fly preflight:** [AUTONOMOUS_DOU_STATUS_AND_FLY_PREFLIGHT.md](AUTONOMOUS_DOU_STATUS_AND_FLY_PREFLIGHT.md)
- **Fly web security:** [FLY_WEB_SECURITY.md](FLY_WEB_SECURITY.md)
- **Fly split deploy:** [FLY_SPLIT_DEPLOY.md](FLY_SPLIT_DEPLOY.md)
- **Official INLABS repository:** `https://github.com/Imprensa-Nacional/inlabs`
