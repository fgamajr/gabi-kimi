# Pitfalls Research

**Domain:** Hybrid BM25 + semantic vector search on large-scale Portuguese legal document platform (ES 8.15.4, single node, ARM/aarch64, 512MB heap, ~7M documents)
**Researched:** 2026-03-12
**Confidence:** HIGH (official Elastic docs + verified community post-mortems)

---

## Critical Pitfalls

### Pitfall 1: Adding `dense_vector` to an Existing Index Without Reindexing

**What goes wrong:**
You cannot add a `dense_vector` field to `gabi_documents_v1` with a PUT mapping call and expect it to work for kNN. Elasticsearch field type changes to an indexed field require a full reindex into a new index. Attempting to add vectors as document updates into the existing index creates a partially-populated field state where some documents have vectors and some do not, and the HNSW graph is not properly built from those partial updates. kNN queries return garbage or empty results against a mixed-state index.

**Why it happens:**
Developers assume ES mapping additions work like ALTER TABLE in SQL. For non-vector fields, adding a new field via PUT mapping is safe. For `dense_vector` with `index: true` (the default in ES 8.x), the HNSW graph must be built segment-by-segment during indexing. Retrofitting vectors into existing segments does not rebuild the graph.

**How to avoid:**
Create `gabi_documents_v2` (new index) with `dense_vector` in the mapping from the start. Use the alias `gabi_documents` pointing to whichever index is current. During the embedding backfill phase, write to v2. When v2 is complete and verified, flip the alias. Keep v1 alive and read-only until v2 is verified in production. Never modify the mapping of a production index that has live traffic.

**Warning signs:**
- kNN search returns 0 results or fewer results than expected
- `GET /gabi_documents_v2/_count` diverges from MongoDB document count
- `_cat/indices` shows v2 store size is much smaller than v1 (vectors not actually indexed)

**Phase to address:** Phase 1 (Index Migration) — must be the very first engineering decision before any embedding work begins.

---

### Pitfall 2: 512MB JVM Heap is Fatal for kNN Search on 7M Documents

**What goes wrong:**
The current ES Docker container runs with 512MB heap. For 7M documents with 768-dimension float vectors (unquantized), the HNSW graph alone requires approximately 21GB of OS file cache to keep hot. Even with bbq_hnsw quantization (the automatic default for dims >= 384), which reduces to ~1-5% of index size in off-heap RAM for DiskBBQ algorithm, the JVM heap at 512MB will hit circuit breakers on concurrent kNN queries. ES circuit breakers protect against OOM but will return 429/503 errors under any real search load, not graceful degradation.

**Why it happens:**
The current setup was sized for BM25 text search, where 512MB heap is sufficient for inverted index lookups. Vector HNSW graphs require much more off-heap memory for OS file cache. The single Docker container on Parallels shared storage compounds this — Parallels shared folder I/O is slower than native NVMe, meaning more data must be held in file cache to achieve acceptable latency.

**How to avoid:**
Increase ES heap to at minimum 2GB, recommended 4GB (`-Xms4g -Xmx4g`). Do not exceed 50% of available RAM and never exceed 32GB (G1GC compressed oops boundary). Enable bbq_hnsw quantization explicitly in the mapping to minimize off-heap footprint. Use `index.store.preload: ["vec", "vex"]` to eagerly load vector files into OS cache. Test with actual 7M-document load before declaring the embedding pipeline done — do not test on a 100K sample and assume scale.

**Warning signs:**
- ES returns `circuit_breaking_exception` on kNN queries
- `GET /_nodes/stats/jvm` shows heap usage consistently above 85%
- kNN queries time out while BM25 queries succeed
- Docker container OOM-killed (check `docker inspect gabi-es` for `OOMKilled: true`)

**Phase to address:** Phase 1 (Infrastructure) — heap must be increased before embedding backfill generates any kNN traffic. Do not start phase 2 (embedding pipeline) without verifying ES survives a sample kNN query under the new heap setting.

---

### Pitfall 3: kNN Filter Placement Causes Zero Results

**What goes wrong:**
The existing BM25 search applies filters (date range, `edition_section`, `art_type`) as part of the `bool` query. When adding kNN, placing the same filters in the outer `bool` query's `filter` clause while using a top-level `knn` section causes those filters to act as a **post-filter** on the kNN results. Because kNN fetches exactly `k` approximate neighbors before filtering, a restrictive filter (e.g., `edition_section: "DO1"`) can eliminate all `k` candidates, returning 0 results to the user — even though many relevant documents exist.

**Why it happens:**
The mental model "filters in `bool` filter the whole query" holds for BM25 but breaks for kNN. ES processes kNN and standard `bool` queries in separate phases. Filters applied outside the `knn` clause operate on the already-reduced candidate set, not during HNSW graph traversal.

**How to avoid:**
Pass filters **inside** the `knn.filter` argument. This enables pre-filtering during HNSW graph traversal via Lucene BitSets. The `knn` query object has its own `filter` field specifically for this purpose. Validate by running filtered kNN queries against a section (`"DO1"`) and confirming result count is non-zero. When building the hybrid query composer, make filter injection into both the BM25 `bool` and the `knn.filter` a single function call to avoid divergence.

```python
# WRONG: filter is post-filter on kNN results
{
  "knn": {"field": "embedding", "query_vector": [...], "k": 50},
  "query": {"bool": {"filter": [{"term": {"edition_section": "DO1"}}]}}
}

# CORRECT: filter runs during HNSW traversal
{
  "knn": {
    "field": "embedding",
    "query_vector": [...],
    "k": 50,
    "num_candidates": 200,
    "filter": [{"term": {"edition_section": "DO1"}}]
  }
}
```

**Warning signs:**
- Hybrid search with section filter returns 0 results while BM25-only returns results
- kNN result count is much lower than expected when any filter is active
- Filtered kNN is slower than unfiltered kNN (paradoxically, more restrictive HNSW traversal needed)

**Phase to address:** Phase 3 (Hybrid Query Composition) — the query builder must enforce correct filter placement from the first working implementation. Do not test only on unfiltered queries and add filters later.

---

### Pitfall 4: Embedding Backfill Pipeline Fails Silently at Scale

**What goes wrong:**
The current `es_indexer.py` uses cursor-based batch processing with a JSON file for state. An embedding backfill for 7M documents at the typical rate of 2,000 documents per batch requires ~3,500 API calls to the embedding provider. If the cursor file is corrupted, the process crashes mid-run, or the embedding API returns a partial success, documents get skipped without any visibility. You discover this weeks later when kNN recall is mysteriously low — some date ranges have no embeddings.

**Why it happens:**
Pipelines built for BM25 indexing (which is fast and cheap) are extended to handle embedding generation (which is slow and expensive) without adding the necessary audit layer. MongoDB `_id`-based cursor pagination is correct for BM25 but becomes insufficient for embeddings when you need to track per-document embedding status independently from BM25 index state.

**How to avoid:**
Add an `embedding_status` field to MongoDB documents: `pending`, `done`, or `failed`. The embedding pipeline queries `{embedding_status: "pending"}`, processes in batches, and marks each document `done` after successful ES upsert with the vector. Failed documents get `failed` status with an error message, not silent skips. This allows exact resume, retry of failed docs, and a completion query `db.documents.countDocuments({embedding_status: "done"})` to verify parity with ES. The cursor file is replaced by MongoDB query state — more durable and auditable.

**Warning signs:**
- Cursor file is the only source of truth for pipeline progress
- No way to count how many documents have embeddings vs. do not
- ES doc count < MongoDB doc count after pipeline completes
- kNN recall is lower for specific date ranges (spotty coverage)

**Phase to address:** Phase 2 (Embedding Pipeline) — design the status tracking before writing a single embedding API call. This is non-negotiable for a 7M-document pipeline.

---

### Pitfall 5: Score Normalization Makes Hybrid Fusion Unstable

**What goes wrong:**
BM25 scores for DOU documents are unbounded and query-dependent (a short `ementa` query scores 2.1, a multi-term body query scores 47.3). Cosine similarity from kNN is bounded [0, 1]. Combining them with a weighted linear sum (`0.6 * bm25 + 0.4 * cosine`) produces rankings that are dominated by whichever score is numerically larger — almost always BM25 on long-document queries. The weights need constant retuning as query patterns change, and the fusion is unstable across different query types.

**Why it happens:**
Score normalization seems like a simple math problem but the normalization is per-result-set (min-max uses the min/max of the current results), making normalized scores relative, not absolute. What looks like "50th percentile BM25" on one query is "95th percentile BM25" on another — the normalized weight is meaningless across queries.

**How to avoid:**
Use Reciprocal Rank Fusion (RRF) as the default fusion strategy. ES 8.x has native RRF support via the `rrf` retriever. RRF operates on ranks, not scores, making it immune to scale mismatches. For the Cohere Rerank step, pass the top 50-100 candidates from both BM25 and kNN to Cohere and let it score them on a single scale — this replaces normalization with a trained cross-encoder. Do not implement custom linear score normalization for the initial milestone. If linear combination is required later (e.g., for boosting recency), normalize BM25 scores with a sigmoid or log transform before combining.

**Warning signs:**
- Changing a single search term dramatically shifts which documents appear first (unstable ranking)
- Short queries return only semantic results; long queries return only BM25 results
- Manual evaluation shows good candidates present in sub-results but not in final merged list

**Phase to address:** Phase 3 (Hybrid Query Composition) — choose RRF or Cohere Rerank from the start. Do not prototype with linear fusion and "fix it later."

---

### Pitfall 6: DOU Document Body Exceeds Embedding Model Token Limit

**What goes wrong:**
DOU documents vary wildly in length. `texto` (body) fields can be hundreds of paragraphs for complex legal acts or a single sentence for errata. Most embedding models have a 512- or 8192-token hard limit. Models silently truncate text beyond the limit rather than erroring — the embedding represents only the first portion of the document. A 50-page contract embedded as its title and first paragraph behaves as if the rest doesn't exist in semantic search.

**Why it happens:**
Developers test the embedding pipeline on short documents where truncation doesn't trigger, then run backfill on all documents and never detect that 40% of docs are being truncated. There is no warning in the API response — the embedding simply returns.

**How to avoid:**
Decide a field embedding strategy before starting backfill: either embed `ementa` (summary field, usually short, HIGH confidence, LOW truncation risk) or embed `ementa + body_plain[:N_chars]` with explicit character pre-truncation before calling the API. Embedding `ementa` alone is the safer default for DOU because the `ementa` is always a structured summary of the act — this is how legal document retrieval systems typically work. Log token counts per batch during backfill and alert if p95 token count approaches model limit. Never embed `body_plain` directly without pre-truncation logic.

**Warning signs:**
- Average tokens per document is very close to the model's context limit
- kNN recall is poor for long documents
- Semantic queries that should match deep within a document always fail

**Phase to address:** Phase 2 (Embedding Pipeline) — the field selection and truncation strategy must be decided and enforced in the embedding pipeline design, not discovered during quality evaluation.

---

### Pitfall 7: Cohere Rerank API Dependency Creates Single Point of Failure

**What goes wrong:**
The hybrid search path becomes: ES kNN + BM25 → merge candidates → Cohere Rerank API → return results. If Cohere's API is unavailable, rate-limited (trial tier: 10 req/min), or returns a 5xx, the entire search request fails — not just degrades. BM25-only fallback is not implemented because "we'll add that later." Users see search broken during Cohere outages.

**Why it happens:**
External API dependencies are treated as always-available during development. Rate limits are only hit when load testing (which often doesn't happen before launch). Trial API keys are used in early development and forgotten in staging — where they then hit rate limits under even light test load.

**How to avoid:**
Implement Cohere Rerank as an optional enhancement, not a required step. The search endpoint should have a `rerank: bool` parameter (default `true`) and a `_fallback_to_rrf()` code path that activates when Cohere returns any error. Log all Cohere failures to detect degradation. Use production API keys from day one (not trial) — trial keys have 10 req/min, production keys have 1,000 req/min. Add a 2-second timeout on the Cohere call; do not use the SDK default which may be much longer.

**Warning signs:**
- Cohere latency causes search requests to exceed 3 seconds
- Trial key rate limit errors in logs (`429 Too Many Requests`)
- No fallback path exists in the search handler

**Phase to address:** Phase 4 (API Endpoints) — implement the fallback path as part of the initial endpoint implementation, not as a follow-up ticket.

---

### Pitfall 8: Embedding Model Changes Require Full Re-Embedding

**What goes wrong:**
You embed 7M documents with model A (e.g., OpenAI `text-embedding-3-small`, 1536 dimensions). Later you discover model B (e.g., a Portuguese legal fine-tune, 768 dimensions) gives significantly better recall for DOU queries. Switching models requires: deleting the vector field from ES, creating a new index with the new vector dimensions, and re-embedding all 7M documents from scratch. This is a multi-day operation on a single-node setup and means zero semantic search during the migration window.

**Why it happens:**
Model selection happens early when "good enough" is acceptable, and the migration cost is underestimated because it was fast to embed a sample. The actual backfill time for 7M documents at 2,000 docs/batch with network API calls is hours to days depending on rate limits.

**How to avoid:**
Spend time validating the embedding model on real DOU documents before starting the 7M backfill. Test on a 10K sample covering multiple document types, sections, and years. Run precision/recall evaluation with 20-30 representative queries from actual legal search use cases. Document why the chosen model was selected. Treat model selection as a decision with high migration cost — it is not easily reversible. If uncertain, prefer the model with the highest Portuguese language benchmark score on MTEB, currently models like `intfloat/multilingual-e5-large` (768d) or `Cohere embed-multilingual-v3` (1024d).

**Warning signs:**
- Model was chosen based on English benchmarks only (BEIR, MTEB English subset)
- No Portuguese legal text evaluation was done before committing to backfill
- Switching models is treated as a "quick config change"

**Phase to address:** Phase 2 (Embedding Pipeline) — model validation is a gate before the full backfill begins. Do not start the 7M run until model evaluation on Portuguese DOU text is complete.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Use `gabi_documents_v1` in-place for vectors via update API | Skip reindex effort | HNSW graph not built, kNN returns garbage | Never |
| Embed `body_plain` without truncation logic | Simpler pipeline code | Silent truncation for 40%+ of documents | Never |
| Use trial Cohere API key in staging | Free during dev | 10 req/min breaks any load test | Never |
| Keep 512MB ES heap for vector workload | No infra change needed | OOM circuit breaker fires under any load | Never |
| Skip embedding status tracking in MongoDB | Faster to build | No resume capability, silent gaps in coverage | Never |
| Use linear score fusion (0.6*bm25 + 0.4*cos) | Intuitive weights | Unstable rankings across query types | MVP only if RRF unavailable |
| Embed only `ementa` field (not body) | Lower cost, lower truncation risk | Semantic search misses body-only matches | Acceptable starting point |
| Use `num_candidates: 100` fixed value | Simpler configuration | Over-retrieves on cheap queries, under-retrieves on filtered queries | Acceptable until tuning phase |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| ES kNN + date filter | Put date filter in outer `bool.filter`, not in `knn.filter` | Always pass filters as `knn.filter` for pre-filtering during HNSW traversal |
| Cohere Rerank | Pass all 7M doc IDs to Cohere | Pass only top 50-100 candidates from pre-retrieval; Cohere has a `max_chunks_per_doc` limit |
| OpenAI Embeddings Batch API | Call `/embeddings` synchronously for 7M docs | Use Batch API (`/v1/batches`) for 50% cost reduction and async processing |
| ES bulk indexing vectors | Use same 2000-doc batch size as text indexing | Reduce batch size to 100-500 for vector bulk operations (each doc is ~3-24KB of float data) |
| MongoDB embedding status | Store embedding as field in the same document | Use separate `embedding_status` field, never store the raw vector in MongoDB (storage waste) |
| ES `dense_vector` dims | Choose dims based on cheapest model | Dims are immutable after index creation — picking wrong dims forces full reindex |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| HNSW graph not preloaded into OS cache | First kNN query after ES restart takes 30+ seconds | Add `index.store.preload: ["vec", "vex"]` to index settings | Every ES restart with 7M vector index |
| `num_candidates` too high on filtered queries | kNN queries with section filter take 5-10x longer than unfiltered | Start with `num_candidates = min(200, k * 10)`, tune down for common filter combinations | When any filter reduces candidate set below k |
| Concurrent embedding + search on single node | Search latency spikes during backfill (bulk indexing holds write lock causing merge) | Run backfill during off-peak hours; use throttled bulk with `?wait_for_active_shards=0` | Any concurrent write+read load on single-node ES |
| Cohere Rerank on 100+ candidates per query | Rerank latency exceeds 2 seconds | Limit pre-retrieval candidates to 50 per retriever; test Cohere latency at p95 | Under any non-trivial load |
| ES heap at 512MB with vector queries | Circuit breaker 429s on first concurrent kNN queries | Increase heap to 4GB before enabling kNN | First concurrent user beyond 1 |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Committing `COHERE_API_KEY` in env file to git | Key exposure, billing fraud | Add `.env` to `.gitignore` (already done); use `COHERE_API_KEY` env var only, never hardcode |
| Using same Cohere key for dev and production | Dev load burns production quota | Separate Cohere API keys per environment |
| ES security disabled (current state) in production | Any process on the host can read/delete all legal documents | Acceptable for local-only internal tool; must enable security if exposed beyond localhost |

---

## "Looks Done But Isn't" Checklist

- [ ] **Embedding backfill complete:** Check `db.documents.countDocuments({embedding_status: "done"})` equals `GET /gabi_documents_v2/_count` — not just "pipeline ran to completion"
- [ ] **kNN with filters works:** Run a date-filtered kNN query and verify non-zero results — do not test only on unfiltered kNN
- [ ] **Cohere fallback works:** Kill network access to Cohere mid-request and verify BM25-only results are returned, not a 500 error
- [ ] **ES heap increased:** `GET /_nodes/stats/jvm` shows `heap_max_in_bytes` >= 2GB, not 512MB
- [ ] **Backward compatibility preserved:** Existing MCP tools (`es_search`, `es_facets`, `es_document`) return same results as before — run a regression check using saved test queries
- [ ] **Alias switching done:** Application points to `gabi_documents` alias, not `gabi_documents_v1` hardcoded — verify in `ops/bin/mcp_es_server.py` and `es_indexer.py`
- [ ] **Incremental sync covers embeddings:** New documents ingested after backfill also get embedded — test by ingesting 10 fresh documents and verifying they appear in kNN results within the sync window

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Deployed wrong dims, need model change | HIGH (full reindex) | Create v3 index with correct dims; re-run full embedding backfill; alias flip |
| Embedding backfill has gaps (no status tracking) | HIGH (unknown coverage) | Cross-query MongoDB vs ES: `db.documents.find({embedding_status: {$exists: false}})`, re-embed all |
| ES OOM during kNN load | MEDIUM (config change + restart) | Increase Docker heap limit, restart ES, wait for HNSW graph to be read into OS cache |
| Cohere outage causing search downtime | LOW (fallback code path) | If fallback implemented: zero action. If not: deploy RRF fallback under production pressure |
| kNN filter returning 0 results | LOW (query fix) | Fix filter placement in `knn.filter`; redeploy query builder; no data migration needed |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Index immutability / reindex required | Phase 1 (Index Migration) | `GET /gabi_documents_v2/_mapping` shows `dense_vector` field; alias points to v2 |
| 512MB heap fatal for kNN | Phase 1 (Infrastructure) | `GET /_nodes/stats/jvm` shows heap >= 2GB; run 10 concurrent kNN queries without circuit breaker errors |
| kNN filter placement (zero results) | Phase 3 (Hybrid Query) | Integration test: kNN with `edition_section: "DO1"` filter returns > 0 results |
| Embedding backfill silent gaps | Phase 2 (Embedding Pipeline) | `countDocuments({embedding_status: "done"})` == ES doc count |
| Score normalization instability | Phase 3 (Hybrid Query) | Use RRF by default; evaluate on 20 test queries across query types |
| Document truncation | Phase 2 (Embedding Pipeline) | Log p95 token count per batch; assert < 90% of model limit |
| Cohere single point of failure | Phase 4 (API Endpoints) | Integration test: Cohere disabled → search returns BM25 results, no 500 |
| Embedding model lock-in | Phase 2 (pre-backfill gate) | Evaluated model on 10K Portuguese DOU sample before starting 7M backfill |

---

## Sources

- Elastic Official Docs: [Tune approximate kNN search](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/approximate-knn-search)
- Elastic Official Docs: [Dense vector field type](https://www.elastic.co/guide/en/elasticsearch/reference/8.15/dense-vector.html)
- Elastic Official Docs: [kNN search in Elasticsearch](https://www.elastic.co/docs/solutions/search/vector/knn)
- Elastic Blog: [Vector search filtering: how it works](https://www.elastic.co/search-labs/blog/vector-search-filtering)
- Elastic Blog: [Elasticsearch kNN: exact vs approximate](https://www.elastic.co/search-labs/blog/knn-exact-vs-approximate-search)
- Elastic Blog: [Elasticsearch kNN and num_candidates strategies](https://www.elastic.co/search-labs/blog/elasticsearch-knn-and-num-candidates-strategies)
- Elastic Blog: [Elasticsearch on ARM](https://www.elastic.co/blog/elasticsearch-on-arm)
- Elastic Blog: [Linear retriever for hybrid search](https://www.elastic.co/search-labs/blog/linear-retriever-hybrid-search)
- Real-world post-mortem: [Elasticsearch hybrid search in practice (Doug Turnbull, 2025)](https://softwaredoug.com/blog/2025/02/08/elasticsearch-hybrid-search)
- Real-world benchmarks: [Elasticsearch hybrid search recipes benchmarked (March 2025)](https://softwaredoug.com/blog/2025/03/13/elasticsearch-hybrid-search-strategies)
- Cohere Official Docs: [Rerank API rate limits](https://docs.cohere.com/docs/rate-limits)
- Cohere Official Docs: [Rerank model overview](https://docs.cohere.com/docs/rerank)
- OpenSearch Blog: [Building effective hybrid search](https://opensearch.org/blog/building-effective-hybrid-search-in-opensearch-techniques-and-best-practices/)
- Academic: [LegalBERT-pt: Pretrained model for Brazilian Portuguese legal domain](https://dl.acm.org/doi/10.1007/978-3-031-45392-2_18)
- Academic: [JurisBERT for Brazilian legal STS](https://huggingface.co/alfaneo/jurisbert-base-portuguese-sts)
- Opster Guide: [Elasticsearch circuit breakers](https://opster.com/guides/elasticsearch/operations/elasticsearch-circuit-breakers/)
- Pinecone: [Chunking strategies for LLM applications](https://www.pinecone.io/learn/chunking-strategies/)
- Elastic Discuss: [Dense vector field extremely large](https://discuss.elastic.co/t/dense-vector-field-extremely-large/382380)

---
*Pitfalls research for: Hybrid BM25 + semantic search on GABI DOU (ES 8.15.4, single-node ARM, 7M Portuguese legal documents)*
*Researched: 2026-03-12*
