# Stack Research

**Domain:** Hybrid BM25 + semantic search with reranking on Elasticsearch 8.x (Portuguese legal text)
**Researched:** 2026-03-12
**Confidence:** MEDIUM-HIGH (core ES/Cohere APIs verified against official docs; Portuguese embedding benchmark data MEDIUM from academic sources)

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Elasticsearch | 8.15.4 (existing) | BM25 + kNN HNSW vector index | Already deployed. ES 8.0+ supports `dense_vector` with `index: true` for approximate kNN via HNSW. Native co-location of BM25 and vector index means no second vector DB to operate. |
| Cohere `embed-multilingual-v3.0` | current (API) | Generate 1024-dim embeddings for DOU documents and queries | Supports 100+ languages including Portuguese (`pt`). 512-token context. 1024 dims. The v3 input_type distinction (`search_document` vs `search_query`) is essential for asymmetric retrieval quality. Verified against official Cohere docs. |
| Cohere Rerank (`rerank-multilingual-v3.0` or `rerank-v3.5`) | current (API) | Cross-encoder reranking of combined BM25+kNN candidate set | Supports Portuguese, 4096-token context per document (vs 512 for embeddings), production rate limit 1000 req/min. Rerank 3.5 is a single multilingual model and supersedes rerank-multilingual-v3.0 for new integrations. |
| `elasticsearch` Python client | `>=8.15, <9` | Typed Python interface to ES REST API | Replaces raw httpx calls with typed helpers, bulk helpers, and async support. Version-pinned to major version 8 to match running ES 8.15.4. The package at v9.x requires ES 9.x server. |
| `cohere` Python SDK | `>=5.0` | Embed and Rerank API calls | SDK v5+ is the v2 API surface (breaking change from v4). Provides `co.embed()`, `co.rerank()`, and async `co.embed_jobs.*` for batch pipeline. Max 96 texts per `co.embed()` call (rate limit: 2000 inputs/min production). |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `tenacity` | `>=8.2` | Retry with exponential backoff for Cohere and ES bulk calls | Always. Embedding pipeline will hit 429s at scale; tenacity handles retry logic without custom loops. |
| `tqdm` | `>=4.66` | Progress bars for embedding backfill pipeline | Embedding 7M docs will take hours; progress visibility is necessary for ops confidence. |
| `numpy` | `>=1.26` | Vector normalization and dot-product similarity pre-checks | Only needed if implementing local score normalization (convex combination). Skip if using ES boost weights directly. |
| `pydantic` | `>=2.5` (existing) | Typed request/response models for new search endpoints | Already in project via `pydantic-settings`. Extend for hybrid search request/response schemas. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `ruff` (existing) | Lint and format new embedding/search modules | Keep `E402, E501` ignored per project convention. 120-char line length. |
| `httpx` (existing) | Keep for MCP server direct ES calls | MCP server uses raw httpx for ES. Do not migrate MCP server to elasticsearch-py yet — scope creep. New FastAPI endpoints should use elasticsearch-py. |
| ES `_reindex` API | Zero-downtime index migration to add `dense_vector` field | Cannot add `dense_vector` to existing index via `_mapping` PUT. Must reindex to new index (`gabi_documents_v2`), then atomically swap alias. Pattern: create v2 index, reindex with `_reindex`, swap alias, update cursor. |

---

## Installation

```bash
# New runtime dependencies (add to requirements.txt)
pip install "elasticsearch>=8.15,<9"
pip install "cohere>=5.0"
pip install "tenacity>=8.2"
pip install "tqdm>=4.66"

# Optional: only if implementing local score normalization
pip install "numpy>=1.26"
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| `cohere embed-multilingual-v3.0` (1024 dims) | `cohere embed-multilingual-light-v3.0` (384 dims) | If 32GB RAM is a hard constraint. Light saves ~70% vector RAM (384 vs 1024 dims = ~19GB vs ~7GB after int8 quantization) but lower retrieval quality. Prefer full model given existing hardware. |
| `cohere embed-multilingual-v3.0` | `voyage-multilingual-2` | Voyage outperforms Cohere on Portuguese MTEB benchmarks (5.6% avg improvement per Voyage AI evaluation). Prefer Voyage if Cohere quality is insufficient post-evaluation. API interface is nearly identical. |
| `cohere embed-multilingual-v3.0` | `multilingual-e5-large` (open weights, self-hosted) | If API cost is a blocker for embedding 7M docs. Self-hosting requires GPU or significant CPU time. For this project's local infra, API is preferable to avoid GPU provisioning. |
| `cohere rerank-v3.5` | ES RRF retriever (`rrf` in retriever API) | RRF requires an Enterprise license on self-hosted ES. The free/basic license does not include RRF. Since this project runs ES locally with security disabled (basic license), RRF is unavailable. Use Cohere Rerank as the fusion/ranking step instead. |
| `elasticsearch` Python client v8.x | Raw `httpx` calls (existing pattern) | Keep httpx in the MCP server where it already works. For new FastAPI endpoints and the embedding pipeline, use the typed client — it handles bulk helpers, retries, and the `knn` query DSL more cleanly. |
| Cohere Embed Jobs API (async batch) | Synchronous `co.embed()` loop | Use Embed Jobs for the initial 7M doc backfill. The async jobs API handles 100K+ documents without managing rate limits manually. For incremental sync of new documents, synchronous batches of 96 are fine. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| ES ELSER (sparse vector model) | ELSER is an English-only sparse neural model. It does not support Portuguese. Despite being native to ES, it will produce low-quality results on DOU text. | `cohere embed-multilingual-v3.0` or `voyage-multilingual-2` via external API. |
| `elasticsearch-py` v9.x | Latest PyPI release is 9.3.0 but it requires ES 9.x server. Using v9 client against ES 8.15 will cause API shape mismatches and deprecation warnings. | Pin to `>=8.15,<9`. |
| `langchain` or `llamaindex` as orchestration layer | Both are high-abstraction wrappers that obscure the ES query DSL, add heavy dependencies, and make debugging harder. This project already uses direct httpx/ES patterns. Adding a RAG framework to glue two APIs together is overengineering. | Call `co.embed()`, `co.rerank()`, and `es.search()` directly. |
| BM25-only MCP tools for hybrid search | The existing 5 MCP tools issue BM25-only queries. Reusing them for hybrid search without modification would silently degrade results for semantic queries. | Upgrade the MCP search tools to call the new FastAPI hybrid endpoint instead of hitting ES directly. |
| `sentence-transformers` local cross-encoder for reranking | Would require downloading a multilingual cross-encoder model, GPU or slow CPU inference, and in-process memory. For 7M docs this is impractical. The PROJECT.md explicitly excludes local cross-encoder models. | Cohere Rerank API. |
| Float32 `dense_vector` without quantization | 7M docs × 1024 dims × 4 bytes ≈ 28.7 GB RAM just for HNSW vectors. This exceeds typical dev machine limits. | Use `int8_hnsw` element quantization via `index_options.type: "int8_hnsw"`. This reduces vector RAM to ~7.2 GB with negligible recall degradation. ES 8.15 defaults to `bbq_hnsw` for dims >= 384, which is even more aggressive — verify default behavior on 8.15 and set explicitly. |

---

## Stack Patterns by Variant

**For the initial 7M document backfill (one-time embedding pipeline):**
- Use Cohere Embed Jobs API (`co.embed_jobs.create()`), not the synchronous embed loop
- Upload MongoDB text exports as `.jsonl` to Cohere datasets API
- Retrieve result dataset, then bulk-index vectors into ES `gabi_documents_v2`
- Because it is async and managed, eliminates 2000 input/min rate limit management

**For incremental embedding of new documents (ongoing sync):**
- Process new documents in batches of 96 (Cohere embed max per call)
- Use `tenacity` retry with exponential backoff for 429 handling
- Integrate into existing `es_indexer.py` sync path: embed first, then bulk index to ES

**For hybrid search at query time:**
- Embed the query string with `input_type="search_query"` (different from document input_type)
- Issue combined ES query: `knn` section (top-100 candidates) + `query` section (BM25 match) with boost weights
- Collect merged result set (top 25-50 documents)
- Pass candidates to `co.rerank()` with original query → return top-10

**If RRF is needed in the future:**
- Upgrade ES to 8.x with Enterprise license or Elastic Cloud
- Use `rrf` retriever in the search request body
- This removes the need for Cohere Rerank as the fusion step (but Cohere Rerank still adds quality on top of RRF)

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|----------------|-------|
| `elasticsearch>=8.15,<9` | ES server 8.15.4 | Major version must match. v9 client is incompatible with v8 server. |
| `cohere>=5.0` | Cohere v2 API (`/v2/embed`, `/v2/rerank`) | SDK v4.x uses deprecated v1 API. The v2 API surface changed embed input_type handling. |
| `pydantic>=2.5` (existing) | FastAPI >=0.111 | Already in project. No new constraint introduced. |
| ES `dense_vector` with `int8_hnsw` | ES 8.6+ | int8 scalar quantization was introduced in 8.6. Safe on 8.15. |
| ES hybrid `knn` + `query` in same request | ES 8.0+ | The combined `knn`/`query` hybrid pattern (with `boost` weights, not RRF) has been available since 8.0. No license restriction. |

---

## Key Architectural Constraint: Index Migration Required

The existing `gabi_documents_v1` index has no `dense_vector` field. ES does not allow adding `dense_vector` fields to an existing index via PUT mapping. **A full reindex is required.**

Pattern:
1. Create `gabi_documents_v2` with updated mapping (adds `embedding` field: `dense_vector`, dims=1024, `index_options.type: "int8_hnsw"`)
2. Run embedding backfill pipeline → writes vectors directly to v2 index
3. Reindex non-vector fields from v1 to v2 via ES `_reindex` API (or replay from MongoDB)
4. Atomic alias swap: `gabi_documents` alias points to v2
5. Update all code to use alias name, not versioned index name

Replaying from MongoDB (rather than `_reindex`) is preferable because it gives clean control over the embedding pipeline and avoids copying stale v1 data shapes.

---

## Memory Sizing: 7M Documents with 1024-dim Vectors

| Quantization | Vector RAM | Recommendation |
|-------------|-----------|----------------|
| Float32 (no quantization) | ~28.7 GB | Do not use at this scale |
| int8_hnsw | ~7.2 GB | Recommended. 75% reduction, negligible recall loss |
| bbq_hnsw (binary) | ~0.9 GB | Experimental quality tradeoff. Test retrieval quality before adopting. |

At 7M docs with int8 quantization, a 32 GB RAM machine (with 50% allocated to ES JVM) is sufficient.

---

## Sources

- [Elastic kNN Search Docs](https://www.elastic.co/docs/solutions/search/vector/knn) — dense_vector field parameters, hybrid kNN+query pattern, ES version history (HIGH confidence)
- [Elastic Hybrid Search Overview](https://www.elastic.co/search-labs/blog/hybrid-search-elasticsearch) — RRF license requirement, retriever API (GA in 8.16), convex combination alternative (HIGH confidence)
- [ES 8.15 dense_vector Reference](https://www.elastic.co/guide/en/elasticsearch/reference/8.15/dense-vector.html) — max dims (4096), int8/int4 quantization, HNSW defaults (HIGH confidence)
- [Cohere Embed Models Docs](https://docs.cohere.com/docs/cohere-embed) — embed-multilingual-v3.0 dims (1024), input_type distinction, 512-token context (HIGH confidence)
- [Cohere Rerank Overview](https://docs.cohere.com/docs/rerank-overview) — rerank-v3.5 multilingual, Portuguese support, 4096 token context (HIGH confidence)
- [Cohere Rate Limits](https://docs.cohere.com/docs/rate-limits) — 2000 inputs/min embed, 1000 req/min rerank, 96 texts/call max (HIGH confidence)
- [Cohere Embed Jobs API](https://docs.cohere.com/v2/docs/embed-jobs-api) — async batch embedding for 100K+ documents, JSONL format (HIGH confidence)
- [elasticsearch PyPI](https://pypi.org/project/elasticsearch/) — latest v9.3.0, v8.x pin required for ES 8.15 compatibility (HIGH confidence)
- [Voyage Multilingual 2 Evaluation](https://towardsdatascience.com/voyage-multilingual-2-embedding-evaluation-a544ac8f7c4b/) — Portuguese benchmark comparison vs Cohere (MEDIUM confidence, third-party evaluation)
- [ES Dense Vector Memory Calculator](https://xeraa.net/dense-vector-calculator) — Memory sizing estimates (MEDIUM confidence)
- [Elasticsearch Hybrid Search Benchmarked](https://softwaredoug.com/blog/2025/03/13/elasticsearch-hybrid-search-strategies) — Real-world hybrid search strategy comparisons (MEDIUM confidence)

---

*Stack research for: GABI Hybrid Search — Elasticsearch BM25 + Cohere Embeddings + Cohere Rerank*
*Researched: 2026-03-12*
