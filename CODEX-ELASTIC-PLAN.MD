# CODEX Elastic Migration Plan

Migration plan to replace PostgreSQL BM25 search with Elasticsearch while keeping PostgreSQL as source of truth.

## Scope

- Keep `dou.*` and `registry.*` in PostgreSQL as canonical data.
- Introduce Elasticsearch as primary full-text search engine.
- Preserve backward compatibility with current API response shapes.
- Maintain rollback path to PG BM25 during rollout.

## Goals

- Improve text search latency and relevance features.
- Add native highlight, fuzzy matching, faceting, and suggest.
- Avoid risky big-bang migration.

## Non-Goals

- Replacing PostgreSQL storage.
- Changing ingestion identity semantics (`registry.*` logic).
- Rewriting chat workflow end-to-end.

## Target Architecture

1. Data ingest writes to PostgreSQL (`dou.*`).
2. ES indexer backfills/syncs from PostgreSQL.
3. API/MCP search layer routes to backend adapter: `pg` or `es`.
4. Feature flag controls backend: `SEARCH_BACKEND`.

## Phased Plan

### Phase 1: Infra and Configuration

Deliverables:
- Add Elasticsearch service (single-node dev profile) to infra stack.
- Add env vars:
  - `SEARCH_BACKEND=pg|es`
  - `ES_URL`
  - `ES_INDEX`
  - `ES_USERNAME`
  - `ES_PASSWORD`
  - `ES_VERIFY_TLS`
- Add startup/health commands to docs.

Exit criteria:
- ES boots locally with constrained heap and healthy status.
- App starts with `SEARCH_BACKEND=pg` and `SEARCH_BACKEND=es` (ES path may still return not-ready during early phases).

### Phase 2: Index Design and Mappings

Deliverables:
- Create versioned index mapping file (for example `search/es_index_v1.json`).
- Portuguese analyzer chain with lowercase + ASCII folding.
- Define searchable and filterable fields from `dou.document` + `dou.edition`.
- Define highlighting and fuzzy defaults.

Exit criteria:
- Index template is reproducible from repository files.
- Mapping supports current filter set (`date`, `section`, `art_type`, `issuing_organ`).

### Phase 3: Indexer (Backfill + Incremental Sync)

Deliverables:
- Implement `ingest/es_indexer.py` with commands:
  - `backfill`
  - `sync`
  - `stats`
- Bulk indexing with retries and error reporting.
- Persist high-water mark/cursor for incremental sync.
- Count-parity checks between SQL source subset and ES index.

Exit criteria:
- Full backfill completes successfully.
- Incremental sync processes only new/changed documents.

### Phase 4: Search Adapter Integration

Deliverables:
- Add a search adapter interface used by web API and MCP.
- Keep existing PG BM25 adapter.
- Add ES adapter that returns normalized results matching existing response schema.
- Implement backend selection via `SEARCH_BACKEND`.

Exit criteria:
- API contract tests pass for both backends.
- Frontend and MCP work without response-shape changes.

### Phase 5: ES Feature Enablement

Deliverables:
- Highlight snippets in search responses.
- Fuzzy typo tolerance.
- Faceted aggregations for dynamic filters.
- Suggest/autocomplete endpoint backed by ES.
- Optional synonyms dictionary and reload process.

Exit criteria:
- Relevance and UX checks pass on curated query set.
- Aggregations and suggest endpoints are stable.

### Phase 6: Rollout and Decommission

Deliverables:
- Shadow mode comparisons (`pg` vs `es`) for top-k and latency.
- Controlled rollout by environment/config.
- One-step rollback by setting `SEARCH_BACKEND=pg`.
- Decommission BM25-only jobs after stable period.

Exit criteria:
- Sustained latency and correctness targets are met.
- Team signs off before removing BM25 dependencies.

## Testing Strategy

- Unit tests for query translation and result normalization.
- Integration tests for backfill/sync/search/highlight/facets/suggest.
- Benchmark tests with P50/P95 latency and throughput.
- Data quality checks:
  - doc count parity
  - random sample field parity
  - filter correctness.

## Operational Safeguards

- Keep PG BM25 code path until ES proves stable.
- Use index aliases for zero-downtime reindex.
- Keep structured logs for indexing failures and retry outcomes.
- Add health checks for ES cluster and index freshness.

## Risks and Mitigations

- Memory pressure from JVM:
  - Start with minimum viable heap in dev, tune by dataset growth.
- Mapping mistakes causing reindex churn:
  - Version mappings and use aliases.
- Search quality regression:
  - Run side-by-side query evaluation before cutover.
- Sync drift between PG and ES:
  - Track sync cursor and periodic full parity checks.

## Rollback Plan

1. Set `SEARCH_BACKEND=pg`.
2. Restart API/MCP services.
3. Continue ingestion normally (PostgreSQL remains source of truth).
4. Investigate ES indexing/search issues without user-facing downtime.

## Execution Checklist

- [x] Phase 1 complete
- [x] Phase 2 complete
- [x] Phase 3 complete
- [x] Phase 4 complete
- [x] Phase 5 complete
- [ ] Phase 6 complete
