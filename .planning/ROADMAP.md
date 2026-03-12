# Roadmap: GABI Hybrid Search

## Overview

This milestone upgrades GABI's existing BM25-only search to hybrid BM25 + semantic vector search with Cohere Rerank, exposed through both FastAPI REST endpoints and upgraded MCP tools. The journey runs: harden ES infrastructure and migrate the index to v2 (Phase 1), generate and backfill embeddings for all 16.3M documents (Phase 2), build the hybrid query orchestrator with fusion, rerank, and resilience (Phase 3), wire the orchestrator into FastAPI endpoints (Phase 4), and upgrade the MCP tools for agent consumption (Phase 5). The embedding backfill (Phase 2) is designed to run in the background while Phases 3-5 are developed against partial embedding coverage.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Infrastructure Upgrade** - Raise ES heap, create gabi_documents_v2 with dense_vector, reindex v1 data, switch alias
- [ ] **Phase 2: Embedding Backfill Pipeline** - Resumable cursor-based pipeline to embed all 16.3M docs with Cohere, with MongoDB status tracking
- [ ] **Phase 3: Hybrid Search Core** - kNN + BM25 fusion, Cohere Rerank, semantic fallback, resilience, and search transparency
- [ ] **Phase 4: FastAPI Endpoints** - REST API exposing hybrid search with mode parameter, autocomplete, facets, health, and CORS
- [ ] **Phase 5: MCP Tool Upgrade** - Upgrade es_search with mode param, es_health with coverage, es_similar tool, backward compat

## Phase Details

### Phase 1: Infrastructure Upgrade
**Goal**: Elasticsearch is ready for vector workloads — heap at 4GB+, v2 index with dense_vector field exists, all v1 BM25 data is available in v2, and all consumers point to the alias
**Depends on**: Nothing (first phase)
**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-04
**Success Criteria** (what must be TRUE):
  1. `GET /_nodes/stats/jvm` reports heap_max >= 4GB for all ES nodes and no circuit breaker trips occur under kNN test queries
  2. `gabi_documents_v2` index exists with a `dense_vector` field of 1024 dims, int8_hnsw similarity, and all original BM25 fields intact
  3. `GET /gabi_documents` alias resolves to `gabi_documents_v2` (not v1); existing BM25 queries against the alias return correct results
  4. Document count in `gabi_documents_v2` matches `gabi_documents_v1` (zero-downtime reindex verified via count comparison)
**Plans**: 3 plans

Plans:
- [x] 01-01-PLAN.md — Raise ES heap to 4GB+ and create v2 index with dense_vector mapping
- [x] 01-02-PLAN.md — Backfill 16.3M docs from MongoDB to v2 (deviation: direct backfill, skipped v1)
- [x] 01-03-PLAN.md — Alias gabi_documents → v2 and update all consumer defaults

### Phase 2: Embedding Backfill Pipeline
**Goal**: All 16.3M DOU documents have embeddings stored in both MongoDB and the ES v2 index, generated via a resumable cursor pipeline that survives interruption and tracks per-document status
**Depends on**: Phase 1
**Requirements**: EMBED-01, EMBED-02, EMBED-03, EMBED-04, EMBED-05
**Success Criteria** (what must be TRUE):
  1. `embed_indexer.py` can be interrupted and restarted without re-embedding already-completed documents (cursor resumes from last checkpoint)
  2. MongoDB `countDocuments({embedding_status: "done"})` equals the ES v2 document count after a full backfill run on the 10K sample
  3. A 10K sample validation confirms the ementa + body_plain truncation strategy keeps all documents within Cohere's 512-token limit with acceptable quality
  4. New DOU documents ingested after the backfill are automatically queued and embedded by the incremental sync path
  5. `embed_indexer.py stats` reports per-status counts (pending/done/failed) and estimated completion time for the full 16.3M run
**Plans**: TBD

Plans:
- [ ] 02-01: Build embed_indexer.py with cursor pattern and MongoDB embedding_status tracking
- [ ] 02-02: Validate ementa + body_plain truncation strategy on 10K sample
- [ ] 02-03: Run full 16.3M document backfill and verify coverage

### Phase 3: Hybrid Search Core
**Goal**: A `HybridSearch` orchestrator correctly fuses BM25 and kNN results, applies Cohere Rerank, triggers semantic fallback on zero BM25 results, reports search mode in every response, and degrades gracefully when Cohere is unavailable or embedding coverage is partial
**Depends on**: Phase 1 (requires v2 index); Phase 2 can run in parallel
**Requirements**: SEARCH-01, SEARCH-02, SEARCH-03, SEARCH-04, SEARCH-05, SEARCH-06, RESIL-01, RESIL-02, RESIL-03
**Success Criteria** (what must be TRUE):
  1. A kNN query against a document's embedding returns semantically similar documents (validated on 10K embedded sample using 5 representative DOU queries)
  2. A hybrid query with both BM25 and kNN sub-queries returns results ranked better than BM25-alone on the same 5 test queries (RRF or convex combination fusion, no Enterprise license dependency)
  3. Cohere Rerank reorders the top-50 fused candidates and the final ranked list is noticeably different from pre-rerank order
  4. When a query returns zero BM25 results, the system transparently falls back to kNN-only and the response `mode` field reads `semantic-fallback`
  5. When Cohere Rerank API returns an error, the search returns BM25/RRF results without throwing an exception, and a structured log entry records the fallback event
  6. A document without an embedding is still returned by BM25 path in a hybrid query (no document silently dropped due to missing vector)
**Plans**: TBD

Plans:
- [ ] 03-01: Register Cohere Rerank inference endpoint in ES and build hybrid_search.py skeleton
- [ ] 03-02: Implement kNN query path and hybrid fusion (RRF or convex combination)
- [ ] 03-03: Implement Cohere Rerank, semantic fallback, search mode transparency, and resilience

### Phase 4: FastAPI Endpoints
**Goal**: REST API endpoints expose hybrid search to frontend and external consumers, with mode selection, autocomplete, facets, single document retrieval, health reporting with embedding coverage, and CORS configured
**Depends on**: Phase 3
**Requirements**: API-01, API-02, API-03, API-04, API-05, API-06
**Success Criteria** (what must be TRUE):
  1. `GET /api/v1/search?q=rescisao+contrato&mode=hybrid` returns reranked hybrid results with a `search_mode` field in the response body
  2. `GET /api/v1/suggest?q=licit` returns autocomplete completions from the existing ES suggest index
  3. `GET /api/v1/facets?q=rescisao` returns aggregation buckets (section, year, organ) for the query results
  4. `GET /api/v1/document/{id}` returns the full document by ID or 404 if not found
  5. `GET /api/v1/health` returns embedding coverage as `{embedded_count: N, total_count: M, coverage_pct: X}`
  6. A cross-origin request from the frontend origin receives a 200 response (CORS preflight passes)
**Plans**: TBD

Plans:
- [ ] 04-01: Implement /api/v1/search endpoint with mode param and pagination
- [ ] 04-02: Implement /api/v1/suggest, /api/v1/facets, and /api/v1/document/{id}
- [ ] 04-03: Implement /api/v1/health with embedding coverage stats and CORS middleware

### Phase 5: MCP Tool Upgrade
**Goal**: All existing MCP tools continue working unchanged when called without new parameters, es_search gains a mode param for hybrid search, es_health reports embedding coverage, and a new es_similar tool enables document-to-document semantic retrieval
**Depends on**: Phase 3
**Requirements**: MCP-01, MCP-02, MCP-03, MCP-04
**Success Criteria** (what must be TRUE):
  1. An existing Claude Code session calling `es_search(query="licitacao")` (no mode param) returns the same BM25 results as before the upgrade — backward compatibility verified
  2. `es_search(query="rescisao contrato", mode="hybrid")` returns reranked hybrid results with a `search_mode` field in the response
  3. `es_health()` response includes `embedding_coverage` object with `embedded_count`, `total_count`, and `coverage_pct` fields
  4. `es_similar(doc_id="...")` returns documents semantically similar to the referenced document using its stored embedding
**Plans**: TBD

Plans:
- [ ] 05-01: Upgrade es_search with mode param and es_health with embedding coverage
- [ ] 05-02: Implement es_similar tool and verify full backward compatibility

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5
Note: Phase 2 (backfill) can run in the background while Phase 3 is developed against partial coverage.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Infrastructure Upgrade | 3/3 | Complete | 2026-03-12 |
| 2. Embedding Backfill Pipeline | 0/3 | Not started | - |
| 3. Hybrid Search Core | 0/3 | Not started | - |
| 4. FastAPI Endpoints | 0/3 | Not started | - |
| 5. MCP Tool Upgrade | 0/2 | Not started | - |
