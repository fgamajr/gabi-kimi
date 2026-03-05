# CODEX Plan: Redis-Backed Autofill, Autocomplete, and Top Searches

Implementation plan to add Google-like query assist UX on top of current Elasticsearch search, using Redis for low-latency ranking and caching.

## 1. Objective

Deliver end-to-end query assist features in web search:

- Autofill/autocomplete while typing.
- "Top searches" surfaced above the search bar.
- Example queries ("try searching for...") based on real usage + curated fallback.
- Fast response under load via Redis.

Keep PostgreSQL as source-of-truth for documents, Elasticsearch as search engine, and MCP/web response contracts stable.

## 2. Scope

In scope:

- Add Redis service to local infra.
- Add Redis client + config in backend.
- Record search telemetry from real queries.
- New endpoints:
  - `/api/top-searches`
  - `/api/search-examples`
- Upgrade `/api/suggest` ranking by combining ES + Redis popularity.
- Frontend updates for suggestion UX and top-search chips above search input.
- Basic anti-noise controls (min length, normalization, rate limits per key).

Out of scope:

- User accounts/personalized history.
- Semantic embeddings/vector search.
- Cross-session personalization by identity.

## 3. Current Baseline

- Search backend is adapter-driven (`pg` or `es`) and MCP-shared.
- ES index for 2002 currently populated and queryable.
- Existing UI already has suggestion dropdown from `/api/suggest`.
- No persistent query analytics/counters yet.

## 4. Target Architecture

Request flow:

1. User types query in web UI.
2. Web calls `/api/suggest?q=...`.
3. Backend fetches:
   - ES suggestions (relevance candidates),
   - Redis popularity signals (prefix + top terms).
4. Backend merges, deduplicates, ranks, returns top N.
5. On `/api/search` success, backend increments Redis counters for query analytics.

Top searches flow:

1. Frontend loads `/api/top-searches?period=day&n=10`.
2. Backend reads Redis sorted sets.
3. Frontend renders clickable chips above search box.

Example queries flow:

1. Frontend loads `/api/search-examples?n=6`.
2. Backend combines:
   - weekly top queries,
   - curated static examples (fallback),
   - optional randomization.

## 5. Redis Data Model

Key conventions (namespace: `gabi:search:*`):

- `gabi:search:top:day:{YYYY-MM-DD}` (ZSET)
  - member: normalized query
  - score: count
  - TTL: 14 days
- `gabi:search:top:week:{YYYY-WW}` (ZSET)
  - member: normalized query
  - score: count
  - TTL: 16 weeks
- `gabi:search:prefix:{pfx}` (ZSET or HASH)
  - optional prefix popularity acceleration
  - TTL: 7 days
- `gabi:search:last_seen:{query}` (STRING/TS)
  - optional recency signal for tie-break
  - TTL: 16 weeks
- `gabi:search:curated_examples` (SET/LIST static bootstrap)

Normalization rules:

- lowercase + trim + collapse spaces.
- remove leading/trailing punctuation.
- keep accents (display) but store folded canonical key for merge.
- reject noise: length < 2, pure punctuation, high-entropy garbage.

## 6. Backend Changes

### 6.1 Infra and Config

Files:

- `infra/docker-compose.yml`
- `infra/db_control.py`
- `.env.example`
- `README.md`

Add:

- Redis service (`redis:7-alpine`, port `6379`, healthcheck).
- Env vars:
  - `REDIS_URL` (default `redis://localhost:6379/0`)
  - `REDIS_PREFIX` (default `gabi`)
  - `SEARCH_ANALYTICS_ENABLED=true|false`
  - `TOP_SEARCH_MIN_QUERY_LEN` (default `3`)
  - `TOP_SEARCH_MAX_QUERY_LEN` (default `120`)

### 6.2 Redis Integration Module

Create `search/redis_signals.py`:

- `record_query(query: str) -> None`
- `get_top_searches(period: Literal["day","week"], n: int) -> list[dict]`
- `get_prefix_candidates(prefix: str, n: int) -> list[dict]`
- `get_example_queries(n: int) -> list[str]`
- safety wrappers: fail-open (if Redis down, search still works).

Implementation details:

- Use `redis-py` client.
- Pipeline increments for day+week counters.
- set expirations idempotently.

### 6.3 API Updates

Files:

- `web_server.py`
- `mcp_server.py` (shared function layer)

Changes:

1. `/api/search`
- After successful query execution, call `record_query(q)` when:
  - not `q="*"`,
  - query length >= threshold,
  - request is not clearly bot/noise.

2. `/api/suggest`
- Merge three sources:
  - ES-based suggestions (existing),
  - Redis top prefix matches,
  - optional curated examples matching prefix.
- Rank formula (simple and robust):
  - `score = es_rank_weight + log1p(redis_count)*w`.
- Return unchanged schema:
  - `{prefix, suggestions:[{term, doc_freq, cat}]}`

3. New endpoint `/api/top-searches`
- Params:
  - `period=day|week` (default `day`)
  - `n` (default `10`, max `30`)
- Response:
  - `{period, items:[{term, count}]}`

4. New endpoint `/api/search-examples`
- Params:
  - `n` (default `6`, max `20`)
- Response:
  - `{items:[{term, source}]}` where source in `["trending","curated"]`

5. MCP tools (optional but recommended)
- Add `dou_top_searches(period, n)` for assistant discoverability.

### 6.4 Reliability Behavior

- Redis unavailable:
  - `/api/search` remains functional.
  - `/api/suggest` falls back to ES-only.
  - `/api/top-searches` returns empty list with `available=false`.
- Log warnings with throttling to avoid log spam.

## 7. Frontend Changes (Google-like Query Assist)

File:

- `web/index.html`

Planned UI behavior:

1. Above search bar (when query empty):
- Render "Em alta" chips from `/api/top-searches`.
- Render "Experimente buscar" examples from `/api/search-examples`.
- Clicking chip/example fills input + executes search.

2. Autocomplete dropdown:
- Keep current dropdown shape.
- Add section headers:
  - `Em alta`
  - `Sugestões`
- Keyboard navigation:
  - Up/Down/Enter/Escape.

3. Autofill behavior:
- On hover/arrow selection, preview term in input ghost style.
- On Enter, commit selected suggestion.

4. Empty/Loading/Error states:
- skeleton rows during fetch.
- fallback curated examples if API empty.

5. Performance:
- Debounce input 150-200ms.
- cancel in-flight suggest requests on new keystroke.

## 8. Ranking and Abuse Controls

- Ignore query telemetry for:
  - very short tokens,
  - repeated identical submissions within a short window (per IP hash + minute bucket),
  - obvious bot patterns.
- Optional lightweight rate guard in Redis:
  - `INCR gabi:search:rate:{iphash}:{minute}` with TTL 120s.

## 9. Testing Strategy

### 9.1 Unit Tests

Add:

- `tests/test_redis_signals.py`
- Extend `tests/test_search_adapters.py` for merged suggest ranking.

Cover:

- query normalization.
- top-search increment and retrieval.
- TTL behavior.
- suggest merge/dedupe ordering.
- Redis-down fail-open behavior.

### 9.2 Integration Tests

Add script:

- `tests/test_web_search_assist.py`

Flow:

1. seed a few queries via `/api/search`.
2. assert `/api/top-searches` contains them ordered by count.
3. assert `/api/suggest` reflects popularity boost.
4. assert `/api/search-examples` non-empty with fallback.

### 9.3 Manual Validation

- Type `minist` and confirm dropdown shows mixed ES + trending terms.
- Verify top chips appear and are clickable.
- Stop Redis container and confirm search still works (graceful degradation).

## 10. Rollout Plan

Phase A:

- Ship backend Redis integration behind flag `SEARCH_ANALYTICS_ENABLED=false`.
- Validate no regressions.

Phase B:

- Enable analytics counters in dev.
- Observe key growth, endpoint latencies, logs.

Phase C:

- Enable top searches + examples UI.
- Tune ranking weights and thresholds.

Phase D:

- Enable by default.
- Document operational playbook.

## 11. Operational Considerations

- Redis memory:
  - set `maxmemory-policy allkeys-lru` in dev if needed.
- Key cardinality:
  - enforce max query length and minimum length.
  - optionally store only top K per day via periodic trim.
- Observability:
  - log `suggest_source_counts` (es vs redis).
  - expose `/api/stats` section for Redis health and key counts.

## 12. Security and Privacy

- Store only normalized query text and aggregate counters.
- If using IP-based anti-abuse, hash IP with one-way hash and short TTL.
- No PII persistence in Redis keys/values.

## 13. Definition of Done

- Redis service available via infra manager.
- `/api/top-searches` and `/api/search-examples` live and documented.
- `/api/suggest` merges ES + Redis signals with stable schema.
- Web UI shows top chips + examples and autocomplete enhancements.
- Fail-open behavior validated with Redis down.
- Tests added and passing for core logic.

## 14. Execution Checklist

- [ ] Add Redis service and env vars.
- [ ] Implement `search/redis_signals.py`.
- [ ] Wire query recording into `/api/search`.
- [ ] Implement `/api/top-searches`.
- [ ] Implement `/api/search-examples`.
- [ ] Merge Redis ranking into `/api/suggest`.
- [ ] Update frontend for top chips + examples + keyboard UX.
- [ ] Add/extend tests.
- [ ] Update docs and runbook.
- [ ] Validate graceful degradation and performance.

