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

## PATCH 6 -- Two Different Workers -- Do Not Confuse

The GABI DOU system has TWO completely separate worker processes. Confusing them is a common and dangerous mistake.

1. **ARQ `upload_worker`** -- Runs on the **WEB app** (`gabi-dou-web`) as a Fly.io process group. Handles MANUAL admin ZIP/XML uploads via the `/api/admin/upload` endpoint. Processes jobs from the ARQ task queue (Redis-backed). Codepath: `src/backend/workers/arq_worker.py`. Entrypoint: `arq src.backend.workers.arq_worker.WorkerSettings`.

2. **Autonomous pipeline worker** -- Runs on **its own Fly.io app** (`gabi-dou-worker`) as a separate machine. Handles SCHEDULED discovery, download, extraction, BM25 indexing, embedding, and verification of DOU publications. Codepath: `src/backend/worker/main.py`. Binds to `:8081` (internal only).

**What they share:** Redis (ARQ task queue for upload_worker, rate limiting for both apps).

**What they do NOT share:** Codebase paths, lifecycle management, scheduling logic, data flow, or Fly.io process groups.

**RULE: An agent must NEVER attempt to merge these two systems, run autonomous pipeline tasks through ARQ, or confuse their codepaths.**

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

Already implemented. The discovery module handles both INLABS (recent 30-day window) and Liferay (historical catalog) sources. Source routing is automatic based on publication date.

### PATCH 7 -- INLABS Authentication Details

The `INLabsClient` class (`src/backend/worker/inlabs_client.py`) implements the official INLABS login and download flow.

**IMPLEMENTED (in codebase):**

| Detail | Value |
|--------|-------|
| Login endpoint | `POST https://inlabs.in.gov.br/logar.php` |
| Login payload | `email` + `password` (form-encoded, `application/x-www-form-urlencoded`) |
| Origin header | `origem: 736372697074` (hex-encoded string, decodes to `script`) |
| Session cookie | `inlabs_session_cookie` (set by server after successful login) |
| Download URL pattern | `GET https://inlabs.in.gov.br/index.php?p=YYYY-MM-DD&dl=YYYY-MM-DD-DOx.zip` |
| Valid sections | `DO1`, `DO2`, `DO3`, `DO1E`, `DO2E`, `DO3E` |
| Window enforcement | `MAX_LOOKBACK_DAYS = 30` -- raises `InlabsWindowError` if date is older |
| Auto re-login | Transparent -- `download()` checks for cookie presence before each request; calls `login()` automatically if cookie is missing or expired |
| Session management | Handled by `httpx.AsyncClient` cookie jar; `INLabsClient` owns the client lifecycle |
| HTTP client | `httpx.AsyncClient` with 60s timeout, follow_redirects=True |
| Streaming download | ZIP files downloaded via `client.stream("GET", ...)` for memory efficiency |

**DOCUMENTED REQUIREMENTS (not yet in code):**

- **Rate limiting:** Max 5 requests/second to INLABS endpoints. This is a planned safeguard to avoid being blocked by Imprensa Nacional. NOT YET IMPLEMENTED.
- **Audit logging:** Log every INLABS interaction (login attempts, downloads, failures) for operational auditability. NOT YET IMPLEMENTED.

## MODULE 3: Extractor

Already implemented. Parses XML articles from downloaded ZIP files with ZIP Slip protection and encoding detection (chardet with latin-1 fallback).

## MODULE 3B: Enrichment Pipeline (SPECIFICATION FOR FUTURE IMPLEMENTATION)

> **STATUS:** This entire section is a SPECIFICATION FOR FUTURE IMPLEMENTATION. None of the modules, fields, or schema changes described below exist in code yet. They document the planned enrichment layer so future implementation agents have a clear contract.

The enrichment pipeline sits between extraction (MODULE 3) and BM25 indexing (MODULE 4). It uses GPT-4o-mini to transform raw DOU articles into citizen-readable content. Enrichment is **additive and non-blocking** -- if it fails, articles proceed to indexing without enrichment fields.

### 3B.1 -- DocumentEnricher (GPT-4o-mini)

**Input:** Raw extracted article fields:
- `title` (string)
- `body` (string)
- `artType` (string)
- `pubDate` (string)

**Output fields generated:**

| Field | Type | Description |
|-------|------|-------------|
| `summary_plain` | string | 2-3 sentence plain-language summary for citizens |
| `summary_technical` | string | Technical summary preserving legal terminology for professionals |
| `key_facts` | array of strings | 3-5 bullet points of key facts |
| `category` | string | One of: `legislation`, `procurement`, `personnel`, `judicial`, `regulatory`, `other` |
| `relevance_score` | float (0-1) | How relevant to general public (0 = niche regulatory, 1 = affects everyone) |
| `affected_entities` | array of strings | Organizations, agencies, people mentioned |
| `legal_impact` | string | Brief description of legal consequence or change |
| `references` | array of strings | Law numbers, decree numbers, prior acts referenced |

**Cost model:** GPT-4o-mini at ~$0.15/1M input tokens, ~$0.60/1M output tokens. Estimate ~500 tokens input + ~300 tokens output per article. At 1000 articles/day: **~$0.50/day**.

**Processing:** Batch of up to 20 articles per API call. Idempotent -- skip if enrichment fields already populated.

**Error handling:** If enrichment fails, article proceeds to indexing WITHOUT enrichment fields. Enrichment is additive, never blocking.

### 3B.2 -- HighlightsGenerator (GPT-4o-mini)

**Input:** Enriched article with `summary_plain` field populated.

**Output field:** `shareable_text` (string) -- A 280-character social-media-ready highlight.

Runs as part of the enrichment batch, not as a separate pipeline stage. Purpose: Enables "share this" feature in citizen-facing UI.

### 3B.3 -- FeedGenerator (Deterministic)

**NOT an LLM module** -- this is a deterministic aggregator.

**Input:** All articles enriched in the current run.

**Output:** Ordered feed entries grouped by category and `relevance_score`.

**Purpose:** Powers the "Today's DOU" citizen landing page.

**Logic:** Sort by `relevance_score` DESC, group by `category`, limit to top 20 per category.

---

### Extended ES Mapping -- Enrichment Fields (SPECIFICATION FOR FUTURE IMPLEMENTATION)

The following field mappings are ADDITIVE to the existing `dou_documents` index. They do not replace any existing fields. Articles indexed before enrichment is implemented will have these fields absent (null), which Elasticsearch handles gracefully.

```json
{
  "summary_plain": { "type": "text", "analyzer": "portuguese" },
  "summary_technical": { "type": "text", "analyzer": "portuguese" },
  "key_facts": { "type": "text", "analyzer": "portuguese" },
  "category": { "type": "keyword" },
  "relevance_score": { "type": "float" },
  "shareable_text": { "type": "text" },
  "affected_entities": { "type": "keyword" },
  "legal_impact": { "type": "text", "analyzer": "portuguese" },
  "references": { "type": "keyword" }
}
```

**Analyzer choice rationale:**

- **Existing fields** (title, body, etc.) use `pt_folded` -- a custom analyzer with standard tokenizer + lowercase + asciifolding, with NO stemming. This is correct for raw DOU text where exact token matching and diacritic folding are priorities.
- **Enrichment fields** (summary_plain, summary_technical, key_facts, legal_impact) use the built-in `portuguese` analyzer -- which includes stemming via the Portuguese snowball stemmer. This is intentional because LLM-generated summaries benefit from morphological analysis: stemming improves recall when users search with different word forms (e.g., "regulamentacao" matching "regulamentar").
- **Keyword fields** (category, affected_entities, references) use `keyword` type for exact-match filtering and aggregations.

---

### Extended SQLite Registry -- Enrichment State (SPECIFICATION FOR FUTURE IMPLEMENTATION)

The following columns extend the `dou_files` table for enrichment state tracking. Enrichment is DECOUPLED from the main pipeline state machine -- a file can be `VERIFIED` (BM25 indexed and count-checked) without being enriched. Enrichment runs as a post-verification pass.

```sql
-- Additional columns for dou_files table (enrichment tracking)
ALTER TABLE dou_files ADD COLUMN enrichment_status TEXT DEFAULT NULL;
-- Values: NULL (not enriched), 'ENRICHING', 'ENRICHED', 'ENRICHMENT_FAILED'
ALTER TABLE dou_files ADD COLUMN enriched_at TEXT DEFAULT NULL;
ALTER TABLE dou_files ADD COLUMN enrichment_error TEXT DEFAULT NULL;
ALTER TABLE dou_files ADD COLUMN articles_enriched INTEGER DEFAULT 0;
```

The `enrichment_status` column is independent of the main `FileStatus` state machine. A file progresses through the main pipeline (DISCOVERED -> ... -> VERIFIED) regardless of enrichment state. After verification, the enrichment pass processes articles and updates `enrichment_status` separately.

---

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

### Holiday-Aware Watchdog (SPECIFICATION FOR FUTURE IMPLEMENTATION)

> **STATUS:** Holiday awareness is listed as an open gap in PATCH 3's "STILL NEEDS" list. The watchdog exists but lacks holiday calendar integration. This subsection documents the planned behavior.

#### 1. Holiday Calendar

Brazilian national holidays when DOU is NOT published:

**Fixed holidays:**
- January 1 -- Confraternização Universal (New Year's Day)
- April 21 -- Tiradentes
- May 1 -- Dia do Trabalho (Labor Day)
- September 7 -- Independência do Brasil
- October 12 -- Nossa Senhora Aparecida
- November 2 -- Finados (All Souls' Day)
- November 15 -- Proclamação da República
- December 25 -- Natal (Christmas)

**Variable holidays (calculated from Easter):**
- Carnival Monday and Tuesday -- 48 and 47 days before Easter Sunday
- Good Friday -- 2 days before Easter Sunday
- Corpus Christi -- 60 days after Easter Sunday

**Holiday calculation:** Use Python `easter()` from the `dateutil` library to compute Easter Sunday, then derive Carnival and Good Friday dates programmatically.

#### 2. Watchdog Behavior

| Scenario | Behavior |
|----------|----------|
| **Normal day** | If no DOU publication discovered by 10:00 BRT, send Telegram alert |
| **Holiday** | Skip alert entirely -- DOU is not published on holidays |
| **Pre-holiday** | If tomorrow is a holiday, note in daily summary ("Tomorrow is [holiday], no DOU expected") |
| **Post-holiday** | Normal behavior resumes; expect publication |

#### 3. Telegram Notifications

**Daily summary message:**
- Count of articles discovered, downloaded, ingested, verified
- Any anomalies (missing sections, partial publications)
- Pre-holiday notice if applicable

**Alert triggers:**
- Missing publication on a non-holiday business day (after 10:00 BRT)
- Download failure after 3 retries
- Enrichment budget exceeded (daily or monthly cap)

**Format:** Plain text, no markdown (Telegram bot API `parse_mode` not set). Messages should be concise and actionable.

---

## SEARCH API ARCHITECTURE (SPECIFICATION FOR FUTURE IMPLEMENTATION)

> **STATUS:** The search API is ALREADY PARTIALLY IMPLEMENTED (BM25 search works). The citizen/professional mode split and RRF hybrid scoring described below are SPECIFICATIONS FOR FUTURE IMPLEMENTATION.

### Two Search Modes

#### Citizen Mode (default, ~90% of users)

- **Endpoint:** `GET /api/v1/search?mode=citizen`
- **Query fields:** `summary_plain`, `key_facts`, `category` (enrichment fields)
- **Result display:** Plain-language summaries with key facts
- **Progressive disclosure:** Initially shows `summary_plain`; full `body` text loads on explicit user action (click/expand)
- **Prerequisite:** Enrichment pipeline (MODULE 3B) must be implemented for the full citizen experience. Without enrichment, citizen mode degrades to standard BM25 on raw fields.

#### Professional Mode (~10% of users)

- **Endpoint:** `GET /api/v1/search?mode=professional`
- **Query fields:** Full `body` text, `summary_technical`, `references`
- **Result display:** Technical summaries with legal citations, affected entities, and referenced laws
- **Opt-in required:** Professional mode is never the default

### Hybrid Search with Reciprocal Rank Fusion (RRF)

The search combines two ranking signals:

1. **BM25 (Portuguese analyzer):** Provides keyword relevance. Uses the existing `pt_folded` analyzer for raw fields and `portuguese` analyzer for enrichment fields. **ALWAYS available** as the baseline retrieval layer.

2. **Dense vector (OpenAI embeddings):** Provides semantic relevance. Uses `ada-002` embeddings stored in the `dou_documents` index. **Additive** -- if embeddings are missing for some documents, those documents still appear via BM25.

**RRF scoring formula:**
```
score = sum(1 / (k + rank_i)) for each ranking signal i
```
Where `k = 60` (standard RRF constant that prevents high-ranked documents from dominating).

**Fallback behavior:** If vector search fails (e.g., OpenAI outage), degrade to BM25-only transparently. The user experience remains functional; only semantic relevance is lost.

### Conversational Chat

- **Endpoint:** `/api/chat`
- **Model:** Qwen (already implemented)
- **Rate limiting:** Per-user rate limiting (already implemented via Redis)
- **Search-augmented:** Retrieves top-5 documents via hybrid search, passes as context to the chat model (RAG pattern)

---

## PROGRESSIVE DISCLOSURE UX PRINCIPLES (DESIGN CONSTRAINTS)

> **STATUS:** These principles are DESIGN CONSTRAINTS that affect how enrichment modules generate content and how the search API structures responses. They are documented here so implementation agents understand the "why" behind API and data decisions.

### 1. Mobile-First Payload Optimization

All API responses must be optimized for mobile payload sizes. The `summary_plain` field is returned by default; full `body` text is only included on explicit request via `?expand=body` query parameter. This means the search API MUST NOT return the full article body in list results.

### 2. Citizen Default

The default search mode is `citizen`. Professional mode requires explicit opt-in (query parameter or user profile setting). This means enrichment (Plan 03 enrichment modules) is a prerequisite for the full citizen experience -- without enrichment fields, citizen mode falls back to raw BM25.

### 3. Two Audiences

| Audience | Percentage | Wants | API Fields |
|----------|-----------|-------|------------|
| Citizens | ~90% | Plain language, key facts, relevance | `summary_plain`, `key_facts`, `category`, `relevance_score` |
| Professionals | ~10% | Exact legal text, references, affected entities | `body`, `summary_technical`, `references`, `affected_entities` |

The pipeline must produce BOTH summary types during enrichment (MODULE 3B). This is not optional -- both audiences are first-class.

### 4. Shareable Content

Every article must have a `shareable_text` field (280 characters max) for social sharing. This is generated by the HighlightsGenerator enrichment module (MODULE 3B.2). The field enables a "share this" button in the citizen-facing UI.

---

## ADDITIONAL POSTGRES TABLES (SPECIFICATION FOR FUTURE IMPLEMENTATION)

> **STATUS:** These tables extend the existing `auth.*` schema on the WEB app (`gabi-dou-web`). The pipeline worker does NOT interact with these tables -- they are web-app-only for user features.
>
> **CRITICAL:** The existing auth schema uses UUID primary keys (see `src/backend/dbsync/auth_schema.sql`). All `id` columns MUST use `UUID PRIMARY KEY DEFAULT gen_random_uuid()` and all `user_id` foreign keys MUST use `UUID NOT NULL REFERENCES auth."user"(id)` (note: `user` is a reserved word in Postgres and must be double-quoted).

```sql
-- Auditor profiles: tracks professional users who need advanced features
CREATE TABLE auditor_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth."user"(id),
    organization TEXT,
    cpf_cnpj TEXT,
    professional_role TEXT,
    search_mode TEXT DEFAULT 'citizen',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Workspaces: collections of documents for professional users
CREATE TABLE workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth."user"(id),
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Workspace documents: many-to-many between workspaces and DOU articles
CREATE TABLE workspace_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    document_id TEXT NOT NULL,  -- ES document ID (not a Postgres FK)
    added_at TIMESTAMPTZ DEFAULT NOW(),
    notes TEXT
);
```

**Table purposes:**

| Table | Purpose | Used By |
|-------|---------|---------|
| `auditor_profiles` | Stores professional user metadata (organization, CPF/CNPJ, role) and default search mode | Web app user settings |
| `workspaces` | Named collections of DOU documents for professional analysis | Web app workspace feature |
| `workspace_documents` | Links workspaces to ES document IDs with optional notes | Web app workspace feature |

**Schema notes:**
- These tables are in **Postgres** (NOT SQLite). They belong to the web app's identity/feature database.
- The `document_id` in `workspace_documents` references an Elasticsearch document ID, not a Postgres row. This is intentional -- DOU articles live in ES, not Postgres.
- `search_mode` in `auditor_profiles` defaults to `'citizen'` and can be set to `'professional'` by the user.

---

## COST TRACKING AND BUDGET CONTROLS (SPECIFICATION FOR FUTURE IMPLEMENTATION)

> **STATUS:** This entire section is a SPECIFICATION FOR FUTURE IMPLEMENTATION. No cost tracking infrastructure exists in code yet.

### 1. Per-Module Cost Estimates

| Module | Service | Estimated Daily Cost | Basis |
|--------|---------|---------------------|-------|
| Enrichment (MODULE 3B) | GPT-4o-mini | ~$0.50/day | ~1000 articles/day, ~500 tokens in + ~300 tokens out per article |
| Embeddings (MODULE 5) | OpenAI ada-002 | ~$0.13/1000 articles | Standard ada-002 pricing |
| Telegram alerts (MODULE 7) | Telegram Bot API | Free | < 30 messages/day (well within free tier) |
| **Total** | | **< $1.00/day** | Normal operation |

### 2. Budget Controls

**Daily enrichment budget:**
- Environment variable: `ENRICHMENT_DAILY_BUDGET_USD` (default: `2.00`)
- Behavior: If daily spend exceeds budget, enrichment PAUSES until the next calendar day (BRT timezone)
- Degradation: Articles still get indexed for BM25 search but WITHOUT enrichment fields (summaries, categories, etc.)
- The daily budget is a soft cap -- the current batch completes, then no new batches start

**Monthly cost cap:**
- Environment variable: `MONTHLY_COST_CAP_USD` (default: `30.00`)
- Behavior: If monthly cumulative spend exceeds cap, ALL paid API calls (enrichment + embeddings) pause until next month
- This is a hard safety net to prevent runaway costs

**Cost tracking storage (SQLite, on worker volume):**
```sql
CREATE TABLE cost_log (
    id INTEGER PRIMARY KEY,
    date TEXT,           -- YYYY-MM-DD (BRT)
    module TEXT,         -- 'enrichment', 'embeddings', 'chat'
    tokens_in INTEGER,   -- Input tokens consumed
    tokens_out INTEGER,  -- Output tokens consumed
    cost_usd REAL,       -- Computed cost in USD
    created_at TEXT       -- ISO 8601 timestamp
);
```

### 3. Cost-Aware Operational Rules

1. **NEVER** run enrichment on historical backfill without explicit operator approval. A full historical corpus could be thousands of articles and cost hundreds of dollars.
2. **Embeddings for historical corpus** should be batched and rate-limited (e.g., 100 articles per batch, 1 batch per minute) to control costs and avoid API rate limits.
3. **All OpenAI API calls** must log token usage (input + output tokens) to the `cost_log` table for cost auditing. No silent API calls.
4. **Budget check before each batch:** Before starting an enrichment or embedding batch, query `cost_log` for today's total. If at or over budget, skip the batch and log a warning.

---

## PATCH 8 -- EXECUTION ORDER (adjusted for current codebase state)

Many modules are ALREADY IMPLEMENTED. Focus on gaps.

```
STEP 1: Resolve Fly PENDING items
  1a. Validate .internal connectivity (web → worker → ES) on Fly
  1b. Size volumes (worker: 10GB, ES: 50GB)
  1c. Set all secrets on both web and worker apps
  1d. Test first-boot with empty worker volume
  1e. Test worker restart recovery from volume-only state

STEP 2: Implement open gaps
  2a. Persist pause/resume state in SQLite (not in-memory)
  2b. Implement dou_catalog_months table + CatalogReconciler
  2c. Implement FALLBACK_PENDING state + delayed Liferay recovery
  2d. Add watchdog holiday awareness (at minimum: Carnival, major national holidays)
  2e. Implement re-embed backfill policy for legacy corpus

STEP 3: Validate external integrations on Fly
  3a. INLABS login + download from GRU region
  3b. OpenAI embeddings with cost-limited sample (10 docs)
  3c. Telegram alert delivery
  3d. ES snapshot to Tigris + test restore

STEP 4: Dashboard E2E against real worker
  4a. Dashboard renders real pipeline state (not synthetic seed)
  4b. Catalog coverage view (which months known vs ingested)
  4c. Trigger and retry actions work through the proxy

STEP 5: Initial bulk load + go live
  5a. Bootstrap registry from JSON catalog
  5b. Process historical backlog (Liferay URLs)
  5c. Enable INLABS daily discovery
  5d. Verify hybrid search works with partial corpus
  5e. Fernando stops touching it
```

---

## Official References

- **Official INLABS repository:** `https://github.com/Imprensa-Nacional/inlabs`
- **INLABS README notes:** XML/PDF available since January 1, 2020. The 30-day download window is a PROJECT constraint enforced in code (`MAX_LOOKBACK_DAYS = 30`), not a publicly documented INLABS limitation.
- **Login endpoint:** `POST https://inlabs.in.gov.br/logar.php`
- **Session cookie:** `inlabs_session_cookie`
- **Download pattern:** `GET https://inlabs.in.gov.br/index.php?p=YYYY-MM-DD&dl=YYYY-MM-DD-DOx.zip`

---

## PATCH 9 -- COMO USAR

### Recommended Execution Strategy

This unified prompt is an ARCHITECTURAL REFERENCE, not a single execution blob.

Use it as context, but execute in FOCUSED SLICES:

1. One prompt per Fly PENDING item
2. One prompt for the catalog extension model
3. One prompt for the delayed Liferay fallback
4. One prompt for watchdog hardening
5. One prompt for dashboard E2E

Each slice should reference this document as context plus the runbook:
  docs/runbooks/AUTONOMOUS_DOU_STATUS_AND_FLY_PREFLIGHT.md

---

## Cross-References

- **Architecture target:** [AUTONOMOUS_DOU_PIPELINE.md](AUTONOMOUS_DOU_PIPELINE.md)
- **Implementation state + Fly preflight:** [AUTONOMOUS_DOU_STATUS_AND_FLY_PREFLIGHT.md](AUTONOMOUS_DOU_STATUS_AND_FLY_PREFLIGHT.md)
- **Fly web security:** [FLY_WEB_SECURITY.md](FLY_WEB_SECURITY.md)
- **Fly split deploy:** [FLY_SPLIT_DEPLOY.md](FLY_SPLIT_DEPLOY.md)
- **Official INLABS repository:** `https://github.com/Imprensa-Nacional/inlabs`

---

*Document generated: 2026-03-09. Source: PRD-unified-prompt-patches.md*
