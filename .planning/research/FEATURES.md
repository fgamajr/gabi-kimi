# Feature Research

**Domain:** Hybrid search platform — legal document corpus (government gazette)
**Researched:** 2026-03-12
**Confidence:** HIGH (core pipeline features), MEDIUM (differentiators), LOW (embedding model selection for Portuguese legal)

## Context: What Already Exists

The baseline MCP server (`ops/bin/mcp_es_server.py`) already ships:

| Tool | What it does |
|------|-------------|
| `es_search` | BM25 full-text with field weighting, filters, pagination, highlights, filter inference |
| `es_suggest` | Prefix autocomplete over title/organ/type |
| `es_facets` | Aggregations: section, art_type, organ, date histogram |
| `es_document` | Single document fetch by doc_id |
| `es_health` | Cluster + index health |

The ES index mapping (`es_index_v1.json`) has no `dense_vector` field. No embedding pipeline exists yet.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features that must exist for hybrid search to be considered functional. Missing any of these means the upgrade is incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Dense vector field in ES index | Foundation of kNN — without it nothing else works | LOW | Add `dense_vector` to mapping; requires index recreation or reindex |
| Embedding generation pipeline (batch) | Must embed all ~7M existing docs before hybrid search is useful | HIGH | Needs batching, resumability via cursor, error recovery; dominant time cost of milestone |
| Incremental embedding sync | New DOU docs need vectors or hybrid degrades over time | MEDIUM | Piggyback on existing `es_sync_cursor.json` pattern |
| kNN search query path | The `knn` retriever clause in ES 8.x; returns vector-similar docs | LOW | ES 8.x native, no external vector DB needed |
| Hybrid fusion (BM25 + kNN) | Combining both recall sets into one ranked list | MEDIUM | RRF via ES retriever API or convex combination; RRF needs Enterprise license |
| Cohere Rerank as final pass | Re-orders fused candidates by cross-encoder relevance | MEDIUM | Call Rerank API after BM25+kNN retrieval; max ~1000 docs/request |
| `es_search` upgrade (backward-compatible) | Existing callers must not break; hybrid must be additive | LOW | Add `mode` param defaulting to `bm25`; `hybrid` opts in |
| `es_health` upgraded | Report on embedding coverage % and search backend mode | LOW | Agent needs to know if hybrid is operational |
| Environment variable for embedding model | Which model/API to call for query-time embeddings | LOW | `EMBED_MODEL`, `EMBED_API_KEY` already referenced in codebase |
| Query embedding at search time | User query must also be embedded to query the kNN index | LOW | Single embedding call per search query; adds ~50-200ms latency |

### Differentiators (Competitive Advantage)

Features that go beyond functional hybrid search and make GABI meaningfully better than a plain BM25 DOU search.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Semantic fallback for zero-result BM25 | When exact terms fail, semantic search catches conceptual matches — critical for legal synonyms (e.g., "rescisão" vs "extinção de contrato") | MEDIUM | Detect BM25 hit count == 0, retry with kNN-only; already feasible with ES retriever pattern |
| Tiered candidate strategy | BM25-matched docs get full vector rerank; no-BM25-match docs get vector-only path. Better precision than naive RRF | MEDIUM | Documented in benchmarks as best performer; requires dis_max with tiered boosting |
| Portuguese-tuned embedding model | Legal PT-BR text has specific vocabulary; domain-appropriate model lifts recall significantly | MEDIUM | Voyage law-2 benchmarks 6-10% above OpenAI on legal retrieval; needs eval on DOU corpus |
| Reranker-aware snippet selection | After Cohere Rerank, show the passage Cohere scored highest, not arbitrary highlight | MEDIUM | Cohere returns relevance scores per doc; use to select best highlight fragment |
| Search mode transparency in MCP response | Tell the agent which path was taken (bm25, hybrid, semantic-fallback) and rerank score | LOW | Extend `search_context` payload; agents can reason about result quality |
| Embedding coverage stats in `es_health` | Report `embedded_count / total_count`; agent knows when pipeline is partially complete | LOW | Count query with `exists` filter on `embedding` field |
| Configurable rerank depth | How many candidates to pass to Cohere (default: 50, max: 100) is tunable without code changes | LOW | `RERANK_TOP_K` env var; over-fetching improves recall at API cost |
| Date-biased hybrid for news-like queries | Legal docs often want recency even when semantically broad; allow `sort=hybrid_date` | MEDIUM | Combine hybrid score with exponential time decay; common in news search |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| ELSER (Elastic sparse vectors) for Portuguese | Seems native/integrated, avoids external API | ELSER is English-only; applying it to Portuguese DOU text produces poor expansion; confirmed by Elastic docs (E5 recommended for non-English) | Use dense vectors + external multilingual embedding model |
| Real-time embedding on ingest | "Always fresh" semantics for new docs | Ingest is bulk ZIP processing; synchronous embedding at ingest adds per-doc API calls, rate-limit pressure, and ingest latency. Breaks the existing pipeline model | Async incremental sync via cursor — same pattern as ES indexer |
| Per-document re-embedding on field update | "Always accurate" vectors if metadata changes | DOU documents are immutable (official gazette); fields don't change post-ingest. Adds complexity with zero benefit | Skip; embed once, mark as embedded |
| Custom fine-tuned embedding model | Maximum domain accuracy | Requires labeled training data (relevance judgments for DOU queries) that doesn't exist; months of MLOps work for uncertain gain | Use Voyage law-2 or OpenAI text-embedding-3-large as pre-trained multilingual legal model |
| Separate vector database (Pinecone, Weaviate) | Seems "purpose-built" for vectors | Adds a third data store alongside MongoDB and ES; operational complexity, no meaningful gain since ES 8.x HNSW is production-grade | ES native kNN — co-located with BM25 index, fewer moving parts |
| RRF-only fusion without reranker | Simpler, no external API dependency | RRF provides modest gains (~1.5% NDCG over pure BM25 on benchmarks); reranker is the meaningful improvement; RRF also requires ES Enterprise license | Convex combination (no license needed) as fallback, Cohere Rerank as primary fusion |
| Streaming search results | Modern UX feel | Adds SSE/WebSocket complexity to MCP tools; MCP protocol is request-response; agents don't benefit from streaming — they need complete result sets | Standard paged response with `has_more` |

---

## Feature Dependencies

```
[Embedding batch pipeline]
    └──produces──> [Dense vectors in ES]
                       ├──enables──> [kNN search query]
                       └──enables──> [Query embedding at search time]
                                         └──requires──> [Embedding API (EMBED_API_KEY)]

[kNN search query] ──combines with──> [BM25 search] ──fuses via──> [Hybrid fusion]
                                                                         └──feeds──> [Cohere Rerank]
                                                                                         └──produces──> [Ranked results]

[Incremental embedding sync]
    └──requires──> [Embedding batch pipeline] (same API + model)
    └──requires──> [Dense vectors in ES] (index must exist)

[Semantic fallback]
    └──requires──> [kNN search query]
    └──enhances──> [es_search MCP tool]

[Embedding coverage stats]
    └──requires──> [Dense vectors in ES]
    └──enhances──> [es_health MCP tool]
```

### Dependency Notes

- **Embedding batch pipeline is the critical path**: No other hybrid feature is usable until vectors exist in ES. The batch pipeline must run to completion (or meaningful partial coverage) before any hybrid search is testable.
- **Index recreation is required**: The current `es_index_v1.json` has no `dense_vector` field. Adding it requires creating a new index and reindexing all ~7M docs. This is a one-time migration, but it means the pipeline must also re-embed (or the embedding can be done directly into the new index from MongoDB).
- **Cohere Rerank requires candidates first**: Rerank is a post-retrieval step — it cannot be the primary retrieval mechanism. BM25 and/or kNN must produce candidates before reranking.
- **Query embedding depends on same model as index**: The embedding model used at ingest must match the model used at query time. Changing models later requires full re-embedding.
- **RRF fusion conflicts with non-Enterprise ES**: If using the open-source ES distribution, RRF requires workaround (score normalization + convex combination). Confirm license before committing to RRF retriever API.

---

## MVP Definition

### Launch With (v1 — Functional Hybrid)

Minimum feature set that makes hybrid search usable end-to-end.

- [ ] Dense vector field added to ES index mapping (new index `gabi_documents_v2`)
- [ ] Batch embedding pipeline: MongoDB → embedding API → ES bulk, resumable, cursor-based
- [ ] `es_search` upgraded with `mode: hybrid` parameter (defaults to `bm25` for backward compat)
- [ ] Hybrid query: BM25 candidates + kNN candidates, fused by convex combination (no Enterprise license dependency)
- [ ] Cohere Rerank as final pass on top-N candidates
- [ ] Incremental embedding sync (same cursor pattern as ES indexer)
- [ ] `es_health` reports embedding coverage

### Add After Validation (v1.x)

Once hybrid search is running and result quality is confirmed:

- [ ] Semantic fallback — when BM25 returns zero results
- [ ] Search mode transparency in MCP response payload
- [ ] Configurable `RERANK_TOP_K` env var
- [ ] Tiered candidate strategy (dis_max boosting) — if quality benchmarking shows gap over convex combination

### Future Consideration (v2+)

- [ ] Date-biased hybrid for time-sensitive queries — requires user feedback to validate need
- [ ] Reranker-aware snippet selection — low priority since MCP agents read full body anyway
- [ ] Embedding model switch to Voyage law-2 — worth evaluating after baseline works; requires full re-embedding

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Dense vector field + index migration | HIGH | MEDIUM | P1 |
| Batch embedding pipeline (7M docs) | HIGH | HIGH | P1 |
| kNN query path in ES | HIGH | LOW | P1 |
| Hybrid fusion (convex combination) | HIGH | MEDIUM | P1 |
| Cohere Rerank integration | HIGH | LOW | P1 |
| Incremental embedding sync | HIGH | MEDIUM | P1 |
| `es_search` mode param (backward compat) | HIGH | LOW | P1 |
| `es_health` embedding coverage | MEDIUM | LOW | P2 |
| Semantic fallback on zero BM25 results | HIGH | LOW | P2 |
| Search mode transparency in response | MEDIUM | LOW | P2 |
| Configurable rerank depth | LOW | LOW | P2 |
| Tiered candidate strategy | MEDIUM | MEDIUM | P3 |
| Date-biased hybrid | LOW | HIGH | P3 |
| Voyage law-2 model eval | MEDIUM | HIGH | P3 |

**Priority key:**
- P1: Must have for launch — hybrid search is non-functional without these
- P2: Should have — improves reliability and observability significantly
- P3: Nice to have — future quality improvements after baseline validated

---

## Competitor Feature Analysis

Context: No direct competitor exists for DOU specifically. Reference points are legal research platforms (Jusbrasil, LexML) and enterprise search benchmarks.

| Feature | Jusbrasil (BR legal) | Elastic ESRE | GABI Hybrid (planned) |
|---------|---------------------|--------------|----------------------|
| BM25 keyword search | Yes | Yes | Yes (existing) |
| Vector/semantic search | Yes (proprietary) | Yes (ELSER/dense) | Yes (dense + external model) |
| Reranking | Unknown | Yes (Cohere integration documented) | Yes (Cohere Rerank 4) |
| MCP / agent integration | No | No (ES Labs demo only) | Yes (primary interface) |
| DOU-specific filter inference | No | No | Yes (existing, unique) |
| Portuguese legal domain tuning | Yes (proprietary) | No | Partial (model selection) |
| 7M doc coverage (2002-2026) | Partial | N/A | Yes (full corpus) |

---

## Sources

- [Elasticsearch hybrid search overview](https://www.elastic.co/what-is/hybrid-search)
- [Elasticsearch hybrid search tutorial](https://www.elastic.co/search-labs/tutorials/search-tutorial/vector-search/hybrid-search)
- [Elasticsearch hybrid search strategies (benchmarked)](https://softwaredoug.com/blog/2025/03/13/elasticsearch-hybrid-search-strategies)
- [ELSER language support — English only](https://discuss.elastic.co/t/can-elser-be-used-with-languages-other-than-english/351186)
- [E5 multilingual model docs](https://www.elastic.co/docs/explore-analyze/machine-learning/nlp/ml-nlp-e5)
- [Cohere Rerank overview](https://docs.cohere.com/docs/rerank-overview)
- [Cohere Rerank 4 announcement](https://www.hpcwire.com/bigdatawire/this-just-in/cohere-introduces-rerank-4/)
- [Voyage law-2 legal retrieval benchmarks](https://blog.voyageai.com/2024/04/15/domain-specific-embeddings-and-retrieval-legal-edition-voyage-law-2/)
- [Voyage 3-large multilingual](https://blog.voyageai.com/2025/01/07/voyage-3-large/)
- [Hybrid search for regulatory texts (arXiv)](https://arxiv.org/html/2502.16767v1)
- [Hybrid search vs pure vector search](https://dasroot.net/posts/2026/02/hybrid-search-bm25-vectors-vs-pure-vector-search/)
- [MCP + hybrid search for agentic AI](https://www.elastic.co/search-labs/blog/context-engineering-hybrid-search-agentic-ai-accuracy)

---

*Feature research for: GABI hybrid search milestone*
*Researched: 2026-03-12*
