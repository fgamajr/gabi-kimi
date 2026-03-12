# Project Research Summary

**Project:** GABI Hybrid Search — BM25 + Semantic Search on 7M Portuguese Legal Documents
**Domain:** Hybrid vector + BM25 search on large-scale multilingual legal corpus (Elasticsearch 8.15.4)
**Researched:** 2026-03-12
**Confidence:** HIGH (core ES and Cohere APIs verified against official docs)

## Executive Summary

GABI is upgrading an existing BM25-only DOU search platform to hybrid BM25 + semantic vector search with Cohere Rerank. The project already has Elasticsearch 8.15.4, MongoDB with ~7M documents, a cursor-based ES indexer, and 5 working MCP search tools — meaning the baseline infrastructure is solid. The upgrade adds a `dense_vector` field to Elasticsearch (requiring a full index migration to `gabi_documents_v2`), an offline embedding pipeline using Cohere `embed-multilingual-v3.0` to generate 1024-dim vectors for all ~7M documents, and a query-time hybrid orchestrator that fuses BM25 + kNN candidates before passing them to Cohere Rerank. The recommended fusion strategy is RRF via the ES retriever API (available on ES 8.14+); if the cluster license is Basic, fall back to convex combination with log-normalized BM25 scores. The Cohere Rerank step should be registered as an ES inference endpoint so the application never calls Cohere directly.

The dominant constraint is time and operational risk: embedding 7M documents is a multi-hour (likely multi-day) background job that must be designed for resumability, auditability, and partial-coverage tolerance. The existing `es_indexer.py` cursor pattern is the right foundation, but must be extended with per-document `embedding_status` tracking in MongoDB — a JSON cursor file alone is insufficient for a pipeline this large. Model selection (Cohere vs Voyage vs open-weight multilingual-e5) must be validated on a 10K Portuguese DOU sample before the full backfill starts, because changing models afterward requires a complete re-embedding and index rebuild.

The critical risks are infrastructure-level: the current ES Docker container runs on 512MB JVM heap, which will trigger circuit breaker OOM errors under any kNN load. The heap must be raised to at minimum 2-4GB before vector indexing begins. Additionally, the index migration is irreversible — `dense_vector` cannot be added to an existing index mapping — so the new index schema must be correct from the start, including quantization settings (`int8_hnsw`) to keep HNSW vector RAM under ~7.2GB for 1024-dim vectors at 7M documents.

## Key Findings

### Recommended Stack

The existing Elasticsearch 8.15.4 deployment fully supports the hybrid search pattern without any additional infrastructure. The `elasticsearch` Python client should be pinned to `>=8.15,<9` to match the running server version (v9 client is incompatible with v8 server). Cohere `embed-multilingual-v3.0` is the recommended embedding model (1024 dims, Portuguese support, `input_type` distinction between `search_document` and `search_query` is required for asymmetric retrieval quality). Cohere `rerank-v3.5` (or `rerank-multilingual-v3.0`) handles the final rerank step, registered as an ES inference endpoint rather than called directly from application code. The `cohere` SDK must be `>=5.0` (v2 API surface — v4 SDK uses deprecated v1 API). Use `tenacity` for retry/backoff across all Cohere and ES bulk calls.

**Core technologies:**
- `elasticsearch>=8.15,<9`: Typed ES client with bulk helpers and kNN DSL support — version pinned to match server
- `cohere>=5.0` (`embed-multilingual-v3.0`): 1024-dim multilingual embeddings; `input_type` distinction is critical for retrieval quality
- `cohere>=5.0` (`rerank-v3.5`): Cross-encoder rerank via ES inference endpoint; 4096-token context, Portuguese support
- `tenacity>=8.2`: Exponential backoff for 429s at scale — non-negotiable for a 7M-doc pipeline
- `tqdm>=4.66`: Progress visibility for multi-hour backfill operations

**Critical version constraints:**
- ES client must stay at major version 8 (`<9`); v9 client cannot communicate with ES 8.15 server
- `cohere` SDK v4.x uses a deprecated API surface; `>=5.0` is required for v2 embed/rerank endpoints
- `int8_hnsw` quantization requires ES 8.6+ (safe on 8.15); must be set explicitly in mapping

### Expected Features

The embedding pipeline is the critical path — no hybrid search feature is testable until vectors exist in ES. All P1 features (index migration, batch embedding pipeline, kNN query path, hybrid fusion, Cohere Rerank, incremental embedding sync, `es_search` mode parameter) must be delivered together as a functional unit. The `mode: hybrid` parameter on `es_search` should default to `bm25` for backward compatibility, opting into hybrid explicitly.

**Must have (table stakes):**
- `gabi_documents_v2` index with `dense_vector` field (1024-dim, `int8_hnsw`) — foundation of all hybrid features
- Resumable batch embedding pipeline (MongoDB → Cohere API → ES), cursor-based with per-doc `embedding_status` in MongoDB
- kNN query path in ES via `knn` retriever clause — ES 8.x native, no separate vector DB
- Hybrid fusion: RRF via ES retriever (or convex combination fallback if Basic license) — eliminates score normalization instability
- Cohere Rerank as final pass on top-50 candidates — registered as ES inference endpoint
- Incremental embedding sync — piggyback on existing `es_sync_cursor.json` pattern so new DOU documents get vectors
- `es_search` upgraded with `mode` parameter — backward-compatible; existing callers unaffected

**Should have (competitive):**
- Semantic fallback when BM25 returns zero results — critical for legal synonym cases (e.g., "rescisão" vs "extinção de contrato")
- `es_health` embedding coverage reporting — agent visibility into pipeline completion status
- Search mode transparency in MCP response — agents can reason about which search path was taken
- Cohere Rerank fallback to BM25/RRF on API failure — prevents single-point-of-failure search outages
- Configurable `RERANK_TOP_K` env var — tunable without code changes

**Defer (v2+):**
- Date-biased hybrid scoring for time-sensitive queries
- Reranker-aware snippet selection
- Voyage law-2 model evaluation — worth validating after baseline works, requires full re-embedding if adopted

### Architecture Approach

The architecture keeps ES as the single query surface: both MCP tools and FastAPI endpoints call a shared `hybrid_search.py` orchestrator (never duplicating query logic). The Cohere Rerank integration is registered once as an ES inference endpoint (`PUT /_inference/rerank/cohere_rerank_multilingual`) so the entire BM25 + kNN + rerank pipeline executes in one round-trip from the application's perspective. The embedding pipeline (`embed_indexer.py`) mirrors the existing `es_indexer.py` cursor pattern exactly — same batch size, same checkpoint mechanics, same bulk indexing pattern — minimizing new operational concepts. Embeddings are stored in both MongoDB (source of truth) and ES (`dense_vector` field); if the ES index must be rebuilt, vectors can be replayed from MongoDB without re-calling the Cohere API.

**Major components:**
1. `embed_indexer.py` (new) — cursor-based batch pipeline: MongoDB read → Cohere embed → MongoDB `embedding_status` update → ES bulk upsert of `dense_vector` field
2. `hybrid_search.py` (new) — `SearchOrchestrator` class: query embed → build retriever DSL (text_similarity_reranker wrapping rrf { standard + knn }) → execute against ES → return ranked hits
3. `es_index_v2.json` (new) — updated mapping adding `dense_vector` (1024-dim, `int8_hnsw`, cosine) to all existing BM25 fields
4. `embed_sync_cursor.json` (new) — high-water mark for embedding pipeline (analogous to `es_sync_cursor.json`)
5. Upgraded MCP tools — thin wrappers calling `hybrid_search.py`; `mode` param preserves backward compatibility
6. Cohere inference endpoint — registered once in ES; application never calls Cohere Rerank directly

### Critical Pitfalls

1. **512MB ES JVM heap is fatal for kNN** — Circuit breaker fires under any concurrent kNN load. Raise Docker heap to 4GB (`-Xms4g -Xmx4g`) before starting the embedding pipeline. Verify with `GET /_nodes/stats/jvm`. This must happen in Phase 1 before any vector indexing.

2. **`dense_vector` cannot be added to existing index** — ES requires a full reindex to add an indexed vector field; retrofitting vectors into `gabi_documents_v1` via PUT mapping does not build the HNSW graph. Create `gabi_documents_v2` from scratch. Use an alias (`gabi_documents`) to enable atomic cutover.

3. **Embedding backfill fails silently without status tracking** — A JSON cursor file cannot detect gaps or skipped documents across 7M records. Add `embedding_status: pending|done|failed` to MongoDB documents. Completion check: `countDocuments({embedding_status: "done"})` must equal ES doc count.

4. **kNN filter placement causes zero results** — Filters placed in the outer `bool.filter` act as post-filters on already-retrieved kNN candidates, eliminating all results. Filters must be inside `knn.filter` for pre-filtering during HNSW traversal.

5. **Score normalization instability** — Linear fusion (`0.6 * bm25 + 0.4 * cosine`) produces unstable rankings because BM25 scores are unbounded and query-dependent. Use RRF (rank-based, scale-invariant) or Cohere Rerank as the sole fusion step. Never prototype with linear combination and "fix it later."

6. **Embedding model lock-in** — Changing embedding models after the 7M backfill requires a complete re-embedding and index rebuild. Validate the chosen model on a 10K Portuguese DOU sample before starting the full pipeline. This is a gate, not an optimization.

7. **Cohere as single point of failure** — If Cohere Rerank is unavailable and no fallback exists, all hybrid search requests fail. Implement `_fallback_to_rrf()` path from the start. Use production API keys (1000 req/min), not trial keys (10 req/min).

## Implications for Roadmap

Based on the dependency graph across all research files, 5 phases are appropriate:

### Phase 1: Infrastructure and Index Migration

**Rationale:** Everything else is blocked until the ES index has a `dense_vector` field and the JVM heap is sufficient to handle vector workloads. This phase has zero code dependencies on external APIs — it can be completed and verified before any Cohere credits are spent.
**Delivers:** `gabi_documents_v2` index with `dense_vector` mapping, `gabi_documents` alias pointing to v2, ES heap raised to 4GB, migration script, `es_index_v2.json` in source control
**Addresses:** Dense vector field (table stakes), index recreation requirement
**Avoids:** Pitfall 1 (OOM heap), Pitfall 2 (HNSW not built on existing index)
**Research flag:** Standard — ES `_reindex` API and alias switching are well-documented patterns

### Phase 2: Embedding Backfill Pipeline

**Rationale:** The embedding pipeline is the critical path and the longest-running step. It can be kicked off and run in the background while Phase 3 and 4 are developed in parallel. However, the pipeline design decisions (field selection, truncation strategy, model validation, status tracking) must be locked before the full run starts — they are irreversible.
**Delivers:** `embed_indexer.py` with `embedding_status` tracking in MongoDB, 10K sample validation confirming model quality, full 7M document backfill started (and running), `embed_sync_cursor.json` checkpoint state
**Uses:** `cohere>=5.0` (Embed Jobs API for batch), `tenacity` for retry, `tqdm` for progress
**Implements:** Cursor-based resumable pipeline (mirrors `es_indexer.py` pattern)
**Avoids:** Pitfall 3 (silent gaps — MongoDB status tracking), Pitfall 5 (document truncation — embed `ementa` or pre-truncated `ementa + body_plain[:N_chars]`), Pitfall 7 (model lock-in — validate before full backfill)
**Research flag:** Needs phase research — token limit handling for DOU document variety and optimal field selection (`ementa` only vs composite) would benefit from a quick experiment before committing to 7M run

### Phase 3: Hybrid Query Orchestrator

**Rationale:** `hybrid_search.py` can be built and unit-tested while the backfill runs (using partial embedding coverage or a small test index). The query DSL, filter placement, and fallback logic must be correct from first implementation — filter placement bugs are silent and hard to detect in production.
**Delivers:** `HybridSearch` class with `text_similarity_reranker { rrf { standard + knn } }` retriever DSL, filters correctly injected into both BM25 `bool` and `knn.filter`, BM25-only fallback mode, Cohere inference endpoint registered in ES
**Uses:** `elasticsearch>=8.15,<9` Python client, ES retriever chain (ES 8.14+ native), Cohere Rerank via ES inference endpoint
**Implements:** `hybrid_search.py`, `es_index_v2.json` (query schema), inference endpoint registration script
**Avoids:** Pitfall 4 (kNN filter zero results), Pitfall 6 (score normalization instability — use RRF)
**Research flag:** Confirm ES license tier before coding RRF path; if Basic license, implement convex combination fallback

### Phase 4: API Integration and Fallback

**Rationale:** With `hybrid_search.py` complete, upgrading the MCP tools and FastAPI endpoints is a thin wiring layer. The Cohere Rerank fallback must be implemented here — not deferred — because Cohere is an external dependency that will fail.
**Delivers:** Upgraded `es_search` MCP tool with `mode: hybrid|bm25` parameter (backward compatible), `es_health` with embedding coverage reporting, Cohere fallback to RRF/BM25, `RERANK_TOP_K` env var, updated FastAPI `/search` endpoint
**Implements:** Anti-pattern 2 avoidance (single hybrid path, not two separate search paths)
**Avoids:** Pitfall 8 (Cohere single point of failure — fallback is implemented in this phase)
**Research flag:** Standard — MCP tool upgrade and FastAPI endpoint patterns are established in the codebase

### Phase 5: Quality Enhancements

**Rationale:** After Phase 4, hybrid search is functional and measurably better than BM25. Phase 5 adds differentiators that require the baseline to exist first: semantic fallback, search mode transparency, and tiered candidate strategy if quality benchmarking shows a gap over convex combination.
**Delivers:** Semantic fallback on zero-BM25 results, search mode transparency in MCP response payload, configurable rerank depth, incremental embedding sync integrated into existing ES indexer sync path
**Addresses:** Differentiators from FEATURES.md (semantic fallback, tiered candidate strategy, transparency)
**Research flag:** Tiered candidate strategy (dis_max boosting) benefits from benchmarking on real DOU queries — mark for research-phase if included in scope

### Phase Ordering Rationale

- Phase 1 must precede all others: ES index structure and heap configuration gate every other deliverable
- Phase 2 (backfill) runs in parallel with Phases 3-4 by design: the pipeline takes days; hybrid query code can be built against partial embedding coverage
- Phase 3 before Phase 4: the query orchestrator must exist before the API layer can import it
- Phase 4 before Phase 5: quality enhancements require a working, deployed hybrid search baseline for meaningful evaluation
- Backward compatibility is enforced throughout: existing `es_search` callers default to `mode: bm25` until explicitly opted into hybrid

### Research Flags

Phases likely needing `/gsd:research-phase` during planning:
- **Phase 2:** Field selection and truncation strategy for DOU document variety — `ementa`-only vs composite embedding; token count distribution across 7M docs is unknown until sampled
- **Phase 3:** ES cluster license tier confirmation — RRF retriever requires above-Basic license; if Basic, alternative fusion DSL needed

Phases with standard patterns (skip research-phase):
- **Phase 1:** ES `_reindex` API and alias switching are fully documented; index mapping schema is deterministic from STACK.md
- **Phase 4:** MCP tool wiring and FastAPI endpoint upgrade follow established codebase patterns
- **Phase 5:** Semantic fallback logic and `es_health` extensions are straightforward — no novel patterns

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Core ES 8.x and Cohere APIs verified against official docs; version constraints confirmed; memory sizing from empirical data |
| Features | HIGH (core pipeline), MEDIUM (differentiators) | P1 features well-defined by dependency graph; differentiators need production data to prioritize |
| Architecture | HIGH | ES retriever chain, inference endpoint pattern, and cursor pipeline all verified against official Elastic docs and Cohere integration guide |
| Pitfalls | HIGH | 8 pitfalls sourced from official ES docs, verified community post-mortems, and Cohere rate limit docs; all have concrete prevention steps |

**Overall confidence:** HIGH

### Gaps to Address

- **ES cluster license tier:** The RRF retriever requires an ES license above Basic. The current setup has security disabled (Basic tier assumed). Confirm before Phase 3 — if Basic, the hybrid DSL must use convex combination, not the `rrf` retriever block. This changes the Phase 3 query builder significantly.
- **DOU document token distribution:** Pitfall 5 (document truncation) risk level depends on how many of the 7M DOU documents exceed the 512-token Cohere embed limit. This is unknown until sampled. A 10K sample token count during Phase 2 model validation will resolve this.
- **Cohere Embed Jobs API vs synchronous batching:** For the 7M backfill, the Embed Jobs async API is recommended to avoid managing 2000 input/min rate limits, but the API surface (uploading JSONL to Cohere datasets) is more complex than synchronous batching. Phase 2 should evaluate whether the async API is worth the setup cost given the project's single-node, non-production context.
- **Portuguese DOU embedding model quality:** Research flags `voyage-multilingual-2` as potentially 5.6% better on Portuguese MTEB benchmarks vs Cohere. This is medium-confidence academic data. The Phase 2 model validation gate is the right place to settle this empirically on actual DOU text before committing to the 7M backfill.

## Sources

### Primary (HIGH confidence)
- [Elastic kNN Search Docs](https://www.elastic.co/docs/solutions/search/vector/knn) — dense_vector field parameters, hybrid kNN+query pattern, filter placement
- [ES 8.15 dense_vector Reference](https://www.elastic.co/guide/en/elasticsearch/reference/8.15/dense-vector.html) — int8/int4 quantization, HNSW defaults, max dims
- [Semantic Reranking — Elastic Docs](https://www.elastic.co/docs/solutions/search/ranking/semantic-reranking) — text_similarity_reranker, inference endpoint registration
- [Using Cohere with Elasticsearch — Elastic Docs](https://www.elastic.co/docs/solutions/search/semantic-search/cohere-es) — inference endpoint setup, rerank integration
- [Cohere Embed Models Docs](https://docs.cohere.com/docs/cohere-embed) — embed-multilingual-v3.0 dims, input_type, 512-token context
- [Cohere Rerank Overview](https://docs.cohere.com/docs/rerank-overview) — rerank-v3.5 multilingual, Portuguese support, 4096-token context
- [Cohere Rate Limits](https://docs.cohere.com/docs/rate-limits) — 2000 inputs/min embed, 1000 req/min rerank, 96 texts/call max
- [Elastic: Tune approximate kNN search](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/approximate-knn-search) — num_candidates, preload settings, circuit breakers
- [Elastic Blog: Vector search filtering](https://www.elastic.co/search-labs/blog/vector-search-filtering) — pre-filter vs post-filter behavior

### Secondary (MEDIUM confidence)
- [Elasticsearch Hybrid Search Strategies (softwaredoug.com, March 2025)](https://softwaredoug.com/blog/2025/03/13/elasticsearch-hybrid-search-strategies) — real-world hybrid search benchmarks
- [Voyage Multilingual 2 Evaluation](https://towardsdatascience.com/voyage-multilingual-2-embedding-evaluation-a544ac8f7c4b/) — Portuguese benchmark comparison vs Cohere
- [ES Dense Vector Memory Calculator](https://xeraa.net/dense-vector-calculator) — memory sizing estimates
- [GDELT Project: ES ANN Vector Search RAM Costs](https://blog.gdeltproject.org/our-journey-towards-user-facing-vector-search-evaluating-elasticsearchs-ann-vector-search-ram-costs/) — empirical RAM data at scale

### Tertiary (LOW confidence)
- [Voyage law-2 legal retrieval benchmarks](https://blog.voyageai.com/2024/04/15/domain-specific-embeddings-and-retrieval-legal-edition-voyage-law-2/) — legal domain embedding quality; Portuguese legal domain not specifically evaluated
- [LegalBERT-pt](https://dl.acm.org/doi/10.1007/978-3-031-45392-2_18) — Portuguese legal domain pretrained model; not evaluated against DOU corpus specifically

---
*Research completed: 2026-03-12*
*Ready for roadmap: yes*
