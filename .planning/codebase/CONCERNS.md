# Codebase Concerns

**Analysis Date:** 2026-03-08

## Tech Debt

**Monolithic web_server.py (2720 lines):**
- Issue: `src/backend/apps/web_server.py` is the single largest file in the project. It contains API endpoints, document loading, PDF generation, chat/RAG logic, media serving, static file serving, and SPA routing all in one file.
- Files: `src/backend/apps/web_server.py`
- Impact: Difficult to navigate, test in isolation, or modify without risk of side effects. PDF generation alone spans ~350 lines inline.
- Fix approach: Extract into focused modules: `src/backend/apps/routes/search.py`, `src/backend/apps/routes/chat.py`, `src/backend/apps/routes/document.py`, `src/backend/apps/pdf_export.py`, `src/backend/apps/routes/media.py`. Keep `web_server.py` as the app assembly point.

**Duplicated utility functions across modules:**
- Issue: `_build_dsn()`, `_env_bool()`, and `_parse_csv_env()` are copy-pasted across 5+ files with identical or near-identical implementations.
- Files: `src/backend/apps/web_server.py`, `src/backend/apps/auth.py`, `src/backend/search/adapters.py`, `src/backend/ingest/embedding_pipeline.py`, `src/backend/ingest/es_indexer.py`, `src/backend/ingest/bm25_indexer.py`
- Impact: Bug fixes or DSN format changes must be replicated in every copy. Risk of drift between implementations.
- Fix approach: Create `src/backend/core/config.py` with shared `build_dsn()`, `env_bool()`, `parse_csv_env()`. Import everywhere.

**Mixed psycopg2 and psycopg (v3) usage:**
- Issue: The codebase uses both `psycopg2-binary` (sync, legacy) and `psycopg[binary]` (v3, async-capable). Web server and search adapters use psycopg2; dbsync and registry_ingest use psycopg v3.
- Files: `src/backend/apps/web_server.py` (psycopg2), `src/backend/apps/mcp_server.py` (psycopg2), `src/backend/search/adapters.py` (psycopg2), `src/backend/dbsync/registry_ingest.py` (psycopg v3), `src/backend/dbsync/executor.py` (psycopg v3)
- Impact: Two PostgreSQL driver dependencies to maintain. Inconsistent connection patterns. psycopg2 blocks the event loop in async FastAPI handlers.
- Fix approach: Migrate all modules to psycopg v3. Use async connections in FastAPI endpoints. Remove psycopg2-binary from requirements.

**No database connection pooling in web server:**
- Issue: Every API request creates a new `psycopg2.connect()` call and closes the connection after use. No connection pool.
- Files: `src/backend/apps/web_server.py:171-177` (`_conn()` function)
- Impact: Under load, connection churn causes PostgreSQL overhead and potential connection exhaustion. Each request pays TCP + auth latency.
- Fix approach: Use `psycopg_pool.AsyncConnectionPool` (psycopg v3) or `psycopg2.pool.ThreadedConnectionPool` in the lifespan context manager.

**Hardcoded default credentials in DSN construction:**
- Issue: Multiple files contain `password=gabi` as a hardcoded default fallback when environment variables are not set.
- Files: `src/backend/apps/web_server.py:80`, `src/backend/apps/mcp_server.py:61`, `src/backend/search/adapters.py:37`, `src/backend/ingest/embedding_pipeline.py:53`, `src/backend/ingest/es_indexer.py:45`, `src/backend/ingest/orchestrator.py:51`, `src/backend/ingest/auto_discovery.py:56`, `src/backend/dbsync/schema_sync.py:16`
- Impact: Production risk if environment variables are missing -- silently connects with dev credentials. No fail-fast for misconfiguration.
- Fix approach: Remove default password values. Require explicit environment variable or fail with a clear error message at startup.

**Legacy standalone HTML frontend:**
- Issue: `web/index.html` is a 2643-line self-contained HTML file loading Tailwind from CDN. The new React frontend lives in `src/frontend/web/`. Both are served by the backend with a fallback mechanism.
- Files: `web/index.html`, `src/backend/apps/web_server.py:87-92`
- Impact: Two frontends to maintain. Confusion about which is canonical. CDN-loaded Tailwind in legacy version is not production-grade.
- Fix approach: Remove `web/index.html` once React frontend is feature-complete. Remove fallback logic from web_server.py.

## Known Bugs

**Synchronous DB calls blocking async event loop:**
- Symptoms: FastAPI chat endpoint is `async def` but calls synchronous `psycopg2.connect()` and cursor operations that block the event loop.
- Files: `src/backend/apps/web_server.py:2238-2572` (`api_chat`), `src/backend/apps/web_server.py:171-177` (`_conn()`)
- Trigger: Any chat or document request under concurrent load.
- Workaround: FastAPI runs sync endpoints in a thread pool, but `api_chat` is explicitly async, so DB calls block the main thread.

## Security Considerations

**In-memory WAF state not shared across workers:**
- Risk: `BLOCKED_IPS` and `SCAN_SCORES` dicts in `security_middleware.py` are process-local. With multiple Uvicorn workers, a scanner hitting different workers never accumulates enough score to be blocked.
- Files: `src/backend/apps/middleware/security_middleware.py:37-38`
- Current mitigation: Rate limiting via Redis is available separately.
- Recommendations: Move WAF block state to Redis or use a shared-memory mechanism. Consider removing in-memory WAF in favor of Redis-only rate limiting.

**Session secret auto-derived from token hashes:**
- Risk: When `GABI_AUTH_SECRET` is not set, the session signing secret is derived from a hash of configured API tokens. If tokens change, all sessions are invalidated. If tokens are leaked, the session secret is also compromised.
- Files: `src/backend/apps/auth.py:73-77`
- Current mitigation: Works for single-instance dev; production should set `GABI_AUTH_SECRET`.
- Recommendations: Log a warning at startup when `GABI_AUTH_SECRET` is not set. Require it when `FLY_APP_NAME` is present (production).

**Qwen API key passed through without validation:**
- Risk: The chat endpoint forwards user messages to DashScope Qwen API. If `QWEN_API_KEY` is empty, chat silently falls back to static responses rather than clearly indicating misconfiguration.
- Files: `src/backend/apps/web_server.py:84`, `src/backend/apps/web_server.py:2479-2489`
- Current mitigation: Fallback to RAG-only responses when API key is missing.
- Recommendations: Add startup validation. Log warning when QWEN_API_KEY is empty.

## Performance Bottlenecks

**Per-request database connections:**
- Problem: Every API request opens a new database connection, executes queries, and closes it.
- Files: `src/backend/apps/web_server.py:171-177`
- Cause: No connection pooling. `_conn()` creates a fresh `psycopg2.connect()` each time.
- Improvement path: Implement connection pooling in the FastAPI lifespan. Use `psycopg_pool.AsyncConnectionPool` for async endpoints.

**Document detail page fires 5 sequential queries:**
- Problem: Loading a single document requires 5 separate SQL queries executed sequentially (document, normative_refs, procedure_refs, signatures, media).
- Files: `src/backend/apps/web_server.py:228-298` (`_load_document_payload`)
- Cause: Separate queries for each related table rather than a single joined query or parallel execution.
- Improvement path: Use a single query with LEFT JOINs and `json_agg()` to fetch all related data in one round trip.

**Search adapter loads embedding model on import:**
- Problem: `src/backend/search/adapters.py` imports from `src/backend/ingest/embedding_pipeline.py` at module level, which can trigger model loading even when hybrid search is not configured.
- Files: `src/backend/search/adapters.py:16`
- Cause: Direct import of `_create_embedder` and `_load_embed_config` at top of file.
- Improvement path: Lazy-import embedding pipeline only when hybrid/vector search is actually used.

## Fragile Areas

**Chat RAG pipeline in web_server.py:**
- Files: `src/backend/apps/web_server.py:2050-2572`
- Why fragile: Complex control flow with nested helper functions (`_chat_search`, `_is_off_topic`, `_should_use_rag`), inline regex patterns for Portuguese NLP, multiple fallback paths (RAG only, Qwen only, static response). Hardcoded Portuguese stop words and off-topic patterns.
- Safe modification: Test with diverse Portuguese queries. Ensure fallback chain works when Qwen API is down.
- Test coverage: No automated tests cover chat endpoint behavior.

**PDF generation inline in web_server.py:**
- Files: `src/backend/apps/web_server.py:700-1080` (approximately)
- Why fragile: ~380 lines of ReportLab PDF generation code with hardcoded layout constants, font sizes, and page templates. Mixed with API endpoint logic.
- Safe modification: Extract to standalone module. Add visual regression tests for PDF output.
- Test coverage: No tests for PDF generation.

**XML parser blob splitting heuristic:**
- Files: `src/backend/ingest/xml_parser.py:373`
- Why fragile: Uses a hardcoded `_BLOB_MIN_LENGTH = 15000` threshold to decide when to split document bodies. Sensitive to document structure changes from INLabs.
- Safe modification: Validate against XML fixtures in `tests/fixtures/xml_samples/`.
- Test coverage: Partial -- fixture-based tests exist but may not cover edge cases.

## Scaling Limits

**Redis optional / graceful degradation:**
- Current capacity: Redis is optional. All Redis operations silently return empty results on failure (`src/backend/search/redis_signals.py`).
- Limit: Without Redis, features like top searches, search result caching, suggest caching, and rate limiting are silently disabled. No alerts.
- Scaling path: Make Redis required in production. Add health check endpoint that reports Redis connectivity status.

**Single-process ingestion pipeline:**
- Current capacity: Bulk pipeline processes dates sequentially within a single process.
- Limit: Backfilling large date ranges (years of data) is slow. No parallelism across dates.
- Scaling path: Add multiprocessing or task queue (Celery/RQ) for parallel date ingestion.

## Dependencies at Risk

**psycopg2-binary alongside psycopg:**
- Risk: Maintaining two PostgreSQL drivers increases dependency surface. psycopg2 is in maintenance mode; psycopg v3 is the future.
- Impact: psycopg2-binary may not receive timely updates for new PostgreSQL versions.
- Migration plan: Replace all psycopg2 usage with psycopg v3 (already used in dbsync modules). Remove psycopg2-binary from `requirements.txt`.

**Unpinned dependency versions:**
- Risk: `requirements.txt` uses `>=` minimum versions with no upper bounds. A `pip install` can pull breaking changes.
- Files: `requirements.txt`
- Impact: Builds are not reproducible. Dependency updates may silently break functionality.
- Migration plan: Add a `requirements.lock` or use `pip-compile` to pin exact versions. Keep `requirements.txt` for minimum bounds.

## Missing Critical Features

**No frontend test coverage:**
- Problem: The React frontend has only a placeholder test (`src/frontend/web/src/test/example.test.ts`) that asserts `true === true`.
- Blocks: Cannot refactor frontend components with confidence. No regression detection.

**No backend API integration tests:**
- Problem: Backend tests (`tests/`) test search adapters and ingest pipeline in isolation with mocked HTTP. No tests exercise FastAPI endpoints end-to-end.
- Blocks: Cannot verify that API contract matches frontend expectations. Auth, rate limiting, and middleware interactions are untested.

**No type checking enforced:**
- Problem: No `mypy.ini`, `pyproject.toml` mypy config, or CI type-checking step detected for the Python backend. No `tsconfig.json` strict mode verification for frontend.
- Blocks: Type errors caught only at runtime.

## Test Coverage Gaps

**Chat and RAG endpoints:**
- What's not tested: The entire `/api/chat` flow including off-topic detection, RAG search, Qwen API proxy, streaming SSE, and fallback chains.
- Files: `src/backend/apps/web_server.py:2050-2572`
- Risk: Regression in chat behavior goes unnoticed. Portuguese NLP heuristics may break with edge-case inputs.
- Priority: High

**PDF generation:**
- What's not tested: PDF export endpoint and ReportLab template rendering.
- Files: `src/backend/apps/web_server.py:700-1080`
- Risk: Layout breaks, encoding issues with Portuguese characters, or missing fonts produce corrupt PDFs.
- Priority: Medium

**Security middleware:**
- What's not tested: WAF rules, scanner detection, IP blocking, path traversal prevention.
- Files: `src/backend/apps/middleware/security_middleware.py`, `src/backend/apps/middleware/security.py`
- Risk: Security regressions when modifying middleware. False positives blocking legitimate requests.
- Priority: High

**Auth session lifecycle:**
- What's not tested: Session creation, cookie signing/verification, expiration, token rotation.
- Files: `src/backend/apps/auth.py`
- Risk: Auth bypass or session fixation issues.
- Priority: High

**Frontend components:**
- What's not tested: All React components, pages, hooks, and API client functions.
- Files: `src/frontend/web/src/pages/*.tsx`, `src/frontend/web/src/components/*.tsx`, `src/frontend/web/src/lib/api.ts`
- Risk: UI regressions undetected. API contract drift between frontend types and backend responses.
- Priority: Medium

---

*Concerns audit: 2026-03-08*
