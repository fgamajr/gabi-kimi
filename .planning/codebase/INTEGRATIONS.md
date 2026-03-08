# External Integrations

**Analysis Date:** 2026-03-08

## APIs & External Services

**Alibaba DashScope (Qwen LLM):**
- Purpose: Chat/RAG endpoint for answering legal questions about DOU documents
- SDK/Client: `httpx` direct HTTP calls to `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`
- Auth: `QWEN_API_KEY` env var (Bearer token)
- Model: `QWEN_MODEL` env var (default: `qwen-plus`)
- Implementation: `src/backend/apps/web_server.py` (streaming SSE proxy at `POST /api/chat`)

**OpenAI-Compatible Embeddings API:**
- Purpose: Generate vector embeddings for RAG hybrid search
- SDK/Client: `httpx` direct HTTP to configurable base URL
- Auth: `EMBED_API_KEY` or `OPENAI_API_KEY` env var
- Default base URL: `https://api.openai.com/v1` (configurable via `EMBED_BASE_URL`)
- Default model: `text-embedding-3-small` (configurable via `EMBED_MODEL`)
- Providers: `openai` (real API), `hash` (deterministic dev fallback)
- Implementation: `src/backend/ingest/embedding_pipeline.py`

**Diario Oficial da Uniao (DOU / INLABS):**
- Purpose: Source data - Brazilian federal government gazette publications
- Access: ZIP downloads containing XML + images
- Implementation: `src/backend/ingest/zip_downloader.py`, `src/backend/ingest/auto_discovery.py`, `src/backend/ingest/catalog_scraper.py`
- Data flow: Discovery -> Download ZIPs -> Extract XML -> Parse -> Normalize -> Ingest to PostgreSQL -> Index to Elasticsearch

## Data Storage

**PostgreSQL 16:**
- Purpose: Primary data store for 3.8M+ DOU documents, BM25 search
- Connection: `PG_DSN` env var or individual `PGHOST`/`PGPORT`/`PGDATABASE`/`PGUSER`/`PGPASSWORD`
- Default: `host=localhost port=5433 dbname=gabi user=gabi password=gabi`
- Client: `psycopg2` (sync driver, used throughout)
- Schema files: `src/backend/dbsync/dou_schema.sql`, `src/backend/dbsync/bm25_schema.sql`, `src/backend/dbsync/registry_schema.sql`, `src/backend/dbsync/download_registry_schema.sql`
- Schema sync tool: `src/backend/dbsync/schema_sync.py`, `src/backend/apps/schema_sync.py`
- Production: Fly.io managed (`gabi-dou-db.internal:5432`)

**Elasticsearch:**
- Purpose: Full-text search and hybrid retrieval (BM25 + vector + RRF)
- Connection: `ES_URL` (default: `http://localhost:9200`), `ES_INDEX` (default: `gabi_documents_v1`), `ES_CHUNKS_INDEX` (default: `gabi_chunks_v1`)
- Auth: `ES_USERNAME` / `ES_PASSWORD` (optional basic auth)
- Client: `httpx` direct HTTP (no official ES Python client)
- Index mappings: `src/backend/search/es_index_v1.json`, `src/backend/search/es_chunks_v1.json`
- Indexers: `src/backend/ingest/es_indexer.py` (documents), `src/backend/ingest/embedding_pipeline.py` (chunks with vectors)
- MCP server: `src/backend/apps/mcp_es_server.py`

**Redis:**
- Purpose: Query analytics (top searches), search result caching, suggest caching, rate limiting
- Connection: `REDIS_URL` (default: `redis://localhost:6379/0`)
- Key prefix: `REDIS_PREFIX` (default: `gabi`)
- Client: `redis` Python package (both sync and async: `redis.asyncio`)
- Graceful degradation: All Redis features are optional; code checks availability before use
- Implementation: `src/backend/search/redis_signals.py` (analytics/caching), `src/backend/apps/middleware/security.py` (rate limiting), `src/backend/apps/chat_security.py` (chat abuse detection)
- Production: `gabi-dou-redis.internal:6379`

**File Storage:**
- Local filesystem only
- Data directory: `ops/data/inlabs/` (ZIP downloads and extracted content)
- Cursor files: `src/backend/data/es_sync_cursor.json`, `src/backend/data/es_chunks_sync_cursor.json`

**Caching:**
- Redis-based: search results (`SEARCH_RESULT_CACHE_TTL_SEC`, default 180s), suggest results (`SUGGEST_CACHE_TTL_SEC`, default 120s)
- Implementation: `src/backend/search/redis_signals.py`

## Authentication & Identity

**Custom Token-Based Auth:**
- Implementation: `src/backend/apps/auth.py`
- Approach: Pre-shared API tokens via `GABI_API_TOKENS` env var (comma-separated, optional `label:token` format)
- Bearer token authentication (`Authorization: Bearer <token>`)
- Session cookies: HMAC-SHA256 signed, configurable TTL (`GABI_SESSION_TTL_SEC`, default 12h)
- Cookie name: `GABI_SESSION_COOKIE` (default: `gabi_session`)
- Local dev bypass: Auth skipped for localhost requests when `FLY_APP_NAME` is not set
- Frontend auth: `src/frontend/web/src/lib/auth.ts` (cookie-based `credentials: "include"`)
- Access key prompt: `src/frontend/web/src/components/AccessKeyPrompt.tsx`

**Rate Limiting:**
- Per-principal and per-IP rate limiting
- Buckets: chat (20/min), document PDF (10/min), media (90/min), document graph (30/min), document read (60/min)
- Backend: Redis (async) when available, in-memory fallback
- Implementation: `src/backend/apps/auth.py` (`_rate_rule_for_path`), `src/backend/apps/middleware/security.py` (`RateLimiter`)

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry/Datadog/etc. detected)

**Logging:**
- `loguru` (root `requirements.txt`) for pipeline operations
- `logging` stdlib (`gabi.security` logger) for security events in `src/backend/apps/middleware/security.py`
- Structured JSON security event logs via `log_security_event()`
- Pipeline reports: JSON output to `logs/pipeline_report.json`

**Health Checks:**
- `GET /api/stats` used as Fly.io health check endpoint (30s interval)

## CI/CD & Deployment

**Hosting:**
- Fly.io (3 apps, `gru` region - Sao Paulo, Brazil)
- Deploy configs: `ops/deploy/web/`, `ops/deploy/frontend-static/`, `ops/deploy/postgres/`
- Deploy script: `ops/scripts/deploy.sh`

**CI Pipeline:**
- Not detected (no `.github/workflows/`, `.gitlab-ci.yml`, or similar)

**Deployment Architecture:**
- `gabi-dou-frontend` (Nginx) -> serves static React build, proxies API calls
- `gabi-dou-web` (FastAPI/Uvicorn) -> API backend
- `gabi-dou-db` (PostgreSQL 16) -> persistent data with Fly volume mount
- `gabi-dou-redis` -> caching and analytics
- Internal networking via Fly.io 6PN (`.internal` DNS)

**Automated Ingestion:**
- Systemd timer: `config/systemd/gabi-ingest.timer` + `gabi-ingest.service`
- Scripts: `ops/scripts/daily_sync.sh`, `ops/scripts/run_overnight_chain.sh`
- Orchestrator: `src/backend/ingest/orchestrator.py`

## MCP (Model Context Protocol) Servers

**gabi-es (Elasticsearch MCP):**
- Entry: `src/backend/apps/mcp_es_server.py`, `ops/bin/mcp_es_server.py`
- Transport: stdio (default) or SSE (port 8766)
- Tools: Elasticsearch search, filtered search, hybrid retrieval

**gabi (PostgreSQL MCP):**
- Entry: `src/backend/apps/mcp_server.py`, `ops/bin/mcp_server.py`
- Transport: stdio (default) or SSE (port 8765)
- Tools: `dou_search`, `dou_search_filtered`, `dou_stats`, `dou_document`

## Environment Configuration

**Required env vars (production):**
- `PG_DSN` or `PGPASSWORD` - PostgreSQL connection
- `GABI_API_TOKENS` - At least one API token for authentication
- `GABI_ALLOWED_HOSTS` - Trusted hostnames
- `GABI_CORS_ORIGINS` - Allowed CORS origins

**Optional env vars:**
- `QWEN_API_KEY` - Enables chat functionality
- `ES_URL`, `ES_USERNAME`, `ES_PASSWORD` - Enables Elasticsearch search
- `REDIS_URL` - Enables caching and analytics
- `EMBED_API_KEY` - Enables vector embedding pipeline
- `SEARCH_BACKEND` - Selects search backend (`pg`, `es`, `hybrid`; default: `pg`)
- `VITE_API_BASE_URL` - Frontend API base URL (build-time)

**Secrets location:**
- Development: `.env` file at project root
- Production: Fly.io secrets (`fly secrets set`)

## Webhooks & Callbacks

**Incoming:**
- None detected

**Outgoing:**
- None detected

## Cryptographic Commitment (CRSS-1)

**Purpose:** Integrity verification for ingested DOU documents
- Custom specification: CRSS-1 (Canonical Registry Serialization Specification v1)
- Implementation: `src/backend/commitment/crss1.py` (canonical serialization + SHA256)
- Chain: `src/backend/commitment/chain.py` (hash chain linking batches)
- Tree: `src/backend/commitment/tree.py` (Merkle tree for batch records)
- Anchor: `src/backend/commitment/anchor.py` (anchoring commitments)
- Verify: `src/backend/commitment/verify.py` (verification utilities)
- CLI: `src/backend/apps/commitment_cli.py`, `ops/bin/commitment_cli.py`

---

*Integration audit: 2026-03-08*
