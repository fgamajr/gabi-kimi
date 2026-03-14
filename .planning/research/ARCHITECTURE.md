# Architecture Research

**Domain:** Hybrid BM25+kNN search with Cohere Rerank on Elasticsearch 8.15.4 + MongoDB
**Researched:** 2026-03-12
**Confidence:** HIGH (Elasticsearch official docs + Cohere official docs verified)

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CONSUMERS (Query Path)                       │
├───────────────────┬─────────────────────────────────────────────────┤
│   MCP Server      │           FastAPI REST                           │
│  (stdio/SSE)      │       /search, /suggest, /document               │
│  5 upgraded tools │                                                  │
└────────┬──────────┴─────────────────┬───────────────────────────────┘
         │                            │
         ▼                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       SEARCH ORCHESTRATOR                            │
│  src/backend/search/hybrid_search.py                                 │
│                                                                      │
│  1. Embed query text → query_vector (Embedding API)                  │
│  2. Build retriever DSL: rrf { standard(BM25) + knn(vector) }        │
│  3. Wrap with text_similarity_reranker (Cohere inference endpoint)   │
│  4. Execute against Elasticsearch                                    │
│  5. Return ranked hits                                               │
└──────────┬─────────────────────────────┬───────────────────────────┘
           │                             │
           ▼                             ▼
┌──────────────────────┐   ┌─────────────────────────────────────────┐
│  Embedding Service   │   │         Elasticsearch 8.15.4            │
│  (external API)      │   │                                         │
│  Cohere embed-       │   │  Index: gabi_documents_v1               │
│  multilingual-v3 OR  │   │  Fields:                                │
│  OpenAI-compat API   │   │    body_plain (text, pt_folded)         │
│                      │   │    embedding  (dense_vector, 1024-dim)  │
│  Input: query text   │   │    ...existing BM25 fields...           │
│  Output: float[]     │   │                                         │
└──────────────────────┘   │  Rerank inference endpoint:             │
                           │    cohere_rerank_multilingual           │
                           │    → delegates to Cohere Rerank API     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                   INGESTION PATH (Offline / Async)                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   MongoDB (7M docs)                                                  │
│        │                                                             │
│        ▼                                                             │
│   embed_indexer.py (new, mirrors es_indexer.py pattern)             │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │  cursor pagination (_id-based, same as es_indexer)          │   │
│   │  batch N docs → call Embedding API (batch endpoint)         │   │
│   │  write embedding back to MongoDB doc.embedding field        │   │
│   │  bulk upsert to ES dense_vector field                       │   │
│   │  save cursor to embed_sync_cursor.json                      │   │
│   └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| `embed_indexer.py` | Batch-generate embeddings; upsert to MongoDB + ES dense_vector | MongoDB (read/write), Embedding API (HTTP), ES (HTTP bulk) |
| `embed_sync_cursor.json` | Resumable high-water mark for embedding pipeline | `embed_indexer.py` reads/writes |
| ES inference endpoint (cohere_rerank) | Cohere Rerank API proxy registered in ES | Elasticsearch calls out to Cohere API |
| `hybrid_search.py` | Build and execute hybrid retriever DSL | Embedding API (query embed), ES (search) |
| `es_index_v2.json` | Updated index mapping adding `dense_vector` field | `embed_indexer.py` uses on index creation |
| Upgraded MCP tools | Replace BM25-only search with hybrid search | `hybrid_search.py` |
| FastAPI endpoints | REST API exposing hybrid search | `hybrid_search.py` |

## Recommended Project Structure

```
src/backend/
├── core/
│   └── config.py           # Add: EMBED_API_URL, EMBED_MODEL, COHERE_API_KEY, EMBED_DIMS
├── search/
│   ├── es_index_v1.json    # Existing BM25-only mapping (keep for rollback)
│   ├── es_index_v2.json    # New: adds dense_vector field (1024-dim, cosine)
│   └── hybrid_search.py    # New: SearchOrchestrator class
├── ingest/
│   ├── es_indexer.py       # Existing (unchanged)
│   └── embed_indexer.py    # New: embedding generation + ES vector sync
└── main.py                 # Add /search, /document endpoints

ops/bin/
└── mcp_es_server.py        # Upgrade es_search tool to use hybrid_search.py

src/backend/data/
├── es_sync_cursor.json     # Existing BM25 cursor
└── embed_sync_cursor.json  # New: embedding pipeline cursor
```

### Structure Rationale

- `embed_indexer.py` follows the exact same cursor + bulk pattern as `es_indexer.py` — minimal new concepts, easy to operate.
- `hybrid_search.py` is the single source of truth for query composition — both MCP tools and FastAPI endpoints import it, no duplication.
- `es_index_v2.json` is a new mapping file so `es_index_v1.json` remains available if a rollback/reindex is needed.
- The Cohere rerank inference endpoint lives inside Elasticsearch (registered once via PUT `/_inference/rerank/cohere_rerank_multilingual`) so `hybrid_search.py` never calls Cohere directly — ES handles that network call.

## Architectural Patterns

### Pattern 1: Retriever Chain (ES 8.14+ native)

**What:** ES 8.14 introduced a `retriever` abstraction that composes BM25, kNN, and reranking in one query. The chain is: `text_similarity_reranker` wraps `rrf` which wraps `standard` (BM25) + `knn`.

**When to use:** All hybrid search queries. Replaces ad-hoc BM25 DSL in both MCP tools and REST API.

**Trade-offs:** Requires ES 8.14+ (we have 8.15.4). `rrf` retriever requires an Elasticsearch license above Basic — verify trial/enterprise tier is active. If license is Basic, fall back to manual RRF in Python or use linear retriever.

**Example:**
```json
POST /gabi_documents_v1/_search
{
  "retriever": {
    "text_similarity_reranker": {
      "retriever": {
        "rrf": {
          "retrievers": [
            {
              "standard": {
                "query": {
                  "bool": {
                    "must": {
                      "simple_query_string": {
                        "query": "licitação obras públicas",
                        "fields": ["identifica^5","ementa^4","body_plain"],
                        "default_operator": "and"
                      }
                    },
                    "filter": [{"term": {"edition_section": "do1"}}]
                  }
                }
              }
            },
            {
              "knn": {
                "field": "embedding",
                "query_vector": [0.021, -0.043, "...1024 dims..."],
                "k": 100,
                "num_candidates": 200
              }
            }
          ],
          "rank_constant": 60,
          "rank_window_size": 100
        }
      },
      "field": "body_plain",
      "inference_id": "cohere_rerank_multilingual",
      "inference_text": "licitação obras públicas",
      "rank_window_size": 50
    }
  },
  "size": 20
}
```

### Pattern 2: External Embedding, Pre-Stored Vectors

**What:** Embeddings are generated outside ES (via Cohere or OpenAI-compatible API), stored in MongoDB and indexed into ES `dense_vector` field. ES never calls the embedding model at search time — the caller embeds the query before sending the kNN retriever.

**When to use:** Always. This is the right approach when you already have MongoDB as source of truth and want to avoid ES ingest pipeline complexity.

**Trade-offs:** Requires a separate pipeline process (`embed_indexer.py`). Query path needs one extra HTTP call to embed the query (~50-100ms). No ES ingest pipeline needed.

**Example:**
```python
# In hybrid_search.py — query-time embed
async def embed_query(text: str) -> list[float]:
    resp = httpx.post(
        settings.embed_api_url + "/embeddings",
        json={"model": settings.embed_model, "input": [text]},
        headers={"Authorization": f"Bearer {settings.embed_api_key}"},
    )
    return resp.json()["data"][0]["embedding"]
```

### Pattern 3: Cursor-Based Resumable Embedding Pipeline

**What:** Mirror the `es_indexer.py` pattern — iterate MongoDB by `_id` order, batch N docs, call embedding API, upsert back to MongoDB, bulk index to ES. Checkpoint after each batch.

**When to use:** Full backfill of 7M documents and incremental sync of new docs.

**Trade-offs:** Slower than async parallel batching but safe, observable, and restartable. Cohere Embed API supports batches of 96 texts per call — use `batch_size=96` for embedding calls, grouped into larger ES bulk operations.

## Data Flow

### Query Path (Hybrid Search Request)

```
Caller (MCP tool / REST client)
    │  query="decreto saúde 2024"
    │  filters={section="do1", date_from="2024-01-01"}
    ▼
hybrid_search.py: HybridSearch.search()
    │
    ├─► embed_query(text) → POST {embed_api_url}/embeddings
    │       ← [float × 1024]  (~50-100ms)
    │
    ├─► build_retriever_dsl(query, query_vector, filters)
    │       → JSON: text_similarity_reranker {
    │                 rrf { standard(BM25+filters) + knn(embedding) }
    │               }
    │
    ├─► POST /gabi_documents_v1/_search  → Elasticsearch
    │       ES internally:
    │         1. BM25 retrieves top-100 scored by simple_query_string
    │         2. kNN retrieves top-100 by cosine similarity on embedding
    │         3. RRF fuses both lists → top-50 candidates
    │         4. text_similarity_reranker calls cohere_rerank_multilingual
    │              → ES calls Cohere Rerank API
    │              ← Cohere returns reranked scores
    │         5. ES returns top-20 reranked hits
    │       ← hits: [{doc_id, score, identifica, ementa, snippet, ...}]
    │
    └─► return SearchResponse
            total, hits, query_context, applied_filters
```

### Ingestion Path (Embedding Pipeline)

```
embed_indexer.py backfill / sync
    │
    ├─► load cursor from embed_sync_cursor.json
    │
    └─► LOOP:
          1. MongoDB: find({_id: {$gt: cursor}}).limit(batch_size=500)
          2. Split into embed_batches of 96 docs each
          3. For each embed_batch:
               POST {embed_api_url}/embeddings  (96 texts)
               ← [96 × float[1024]]
          4. MongoDB: bulk_write UpdateOne({_id}, {$set: {embedding, embedding_model, embedded_at}})
          5. ES: _bulk index with dense_vector field populated
          6. Save cursor
          7. Log progress
```

### Inference Endpoint Registration (One-Time Setup)

```
ops/setup_cohere_rerank.py (or manual curl)
    │
    └─► PUT /_inference/rerank/cohere_rerank_multilingual
          {
            "service": "cohere",
            "service_settings": {
              "api_key": "${COHERE_API_KEY}",
              "model_id": "rerank-multilingual-v3.0"
            },
            "task_settings": { "top_n": 50 }
          }
```

## Scaling Considerations

| Concern | Current Scale (~7M docs) | If Corpus Doubles |
|---------|--------------------------|-------------------|
| ES HNSW RAM (768-dim, bbq_hnsw) | ~6-7 GB (auto-quantized 4x from ~22 GB) | ~13 GB |
| ES HNSW RAM (1024-dim) | ~9 GB quantized | ~18 GB |
| Embedding backfill time (Cohere, 96 docs/call) | ~20 hrs at 1 call/sec, ~2 hrs at 10 calls/sec | Linear scale |
| Query latency (embed + kNN + BM25 + rerank) | 200-600ms total | Stable if shards scale |
| Cohere Rerank latency per request | 100-300ms | Stable (per-query) |
| ES bulk indexing throughput | 2000 docs/batch, same as es_indexer | Linear scale |

### Scaling Priorities

1. **First bottleneck: embedding backfill throughput.** 7M documents at ~96 docs/batch = ~73,000 API calls. Cohere's production tier handles concurrent requests. Use 3-5 concurrent httpx async requests with semaphore limiting to stay within rate limits.
2. **Second bottleneck: ES heap and HNSW RAM.** With default `bbq_hnsw` quantization (enabled automatically for dims >= 384), 7M × 1024-dim fits in ~9 GB. The existing Docker setup needs sufficient memory allocated.

## Anti-Patterns

### Anti-Pattern 1: Re-embedding at Query Time from ES Ingest Pipeline

**What people do:** Configure an ES ingest pipeline with an inference processor to call an embedding model when documents are indexed.

**Why it's wrong:** Tightly couples the indexing pipeline to a specific embedding model endpoint. Slow for bulk backfill (ES calls the model synchronously per batch). No control over batching or rate limiting. Difficult to change models.

**Do this instead:** Generate embeddings offline in `embed_indexer.py`, store in MongoDB and ES. Query-time: only embed the single query text.

### Anti-Pattern 2: Two Separate Search Paths (BM25 and Hybrid)

**What people do:** Keep the existing BM25 path untouched and add a separate "hybrid" endpoint. Tools call one or the other.

**Why it's wrong:** BM25-only path becomes stale, callers must decide which mode to use, MCP tools diverge.

**Do this instead:** Upgrade `es_search` tool and the REST endpoint to use hybrid_search.py. Add a `mode` parameter (`hybrid` default, `bm25` for backward compat) so existing callers keep working.

### Anti-Pattern 3: Calling Cohere Rerank API Directly from Application Code

**What people do:** Fetch ES results, then make a separate HTTP call to `api.cohere.com/rerank` in Python, manually re-sort hits.

**Why it's wrong:** Bypasses ES retriever chain, adds latency from two separate round-trips (ES + Cohere), loses ability to use ES `rank_window_size` optimization, harder to cache/debug.

**Do this instead:** Register Cohere as an ES inference endpoint (`PUT /_inference/rerank/...`). Use `text_similarity_reranker` in the ES query DSL. ES handles the Cohere API call internally, fused with retrieval in one round-trip from the application's perspective.

### Anti-Pattern 4: Storing Only Embeddings in ES, Not MongoDB

**What people do:** Write embeddings directly to ES only (not back to MongoDB).

**Why it's wrong:** MongoDB is the source of truth. If ES index is rebuilt from MongoDB (e.g., after mapping change), embeddings are lost and must be regenerated.

**Do this instead:** Always write `embedding`, `embedding_model`, `embedded_at` back to the MongoDB document. ES `dense_vector` field is populated from MongoDB data.

## Integration Points

### External Services

| Service | Integration Pattern | Key Config | Notes |
|---------|---------------------|-----------|-------|
| Cohere Rerank API | ES inference endpoint proxy — application never calls Cohere directly | `COHERE_API_KEY` env var; endpoint registered once via PUT `/_inference/rerank/cohere_rerank_multilingual` | Model: `rerank-multilingual-v3.0` supports Portuguese. Register once, reuse forever. |
| Embedding API (Cohere embed-multilingual-v3 or OpenAI-compat) | Direct HTTP call from `embed_indexer.py` (batch) and `hybrid_search.py` (single query) | `EMBED_API_URL`, `EMBED_API_KEY`, `EMBED_MODEL` env vars | 1024 dims for Cohere embed-v3. Can swap model by rerunning backfill. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `embed_indexer.py` ↔ MongoDB | pymongo cursor pagination + bulk_write | Same pattern as `es_indexer.py`. Adds `embedding`, `embedding_model`, `embedded_at` fields. |
| `embed_indexer.py` ↔ Elasticsearch | httpx bulk API, same `ESClient` class | Adds `embedding` (dense_vector) field to existing ES docs via update or full upsert |
| `hybrid_search.py` ↔ Elasticsearch | httpx POST `/_search` with retriever DSL | Single call per search request. ES handles Cohere rerank internally. |
| `hybrid_search.py` ↔ Embedding API | httpx POST to embed the query text | ~50-100ms per query. Consider in-process LRU cache for repeated queries. |
| MCP tools ↔ `hybrid_search.py` | Direct Python function call | MCP tools are thin wrappers; all search logic lives in hybrid_search.py |
| FastAPI ↔ `hybrid_search.py` | Async function call via `await` | Requires hybrid_search.py to expose async interface |

## Build Order (Phase Dependencies)

The dependency graph dictates this sequence:

```
Phase 1: ES Index v2 + dense_vector mapping
    → Required by: embed_indexer, hybrid search query
    → Deliverable: es_index_v2.json, index migration script

Phase 2: embed_indexer.py (batch embedding pipeline)
    → Requires: Phase 1 (dense_vector field exists)
    → Deliverable: ~7M docs get embeddings in MongoDB + ES
    → Note: longest-running step, can run in background

Phase 3: Cohere inference endpoint registration
    → Requires: Phase 1 (ES index exists with dense_vector)
    → Deliverable: rerank endpoint live in ES, verified with test query

Phase 4: hybrid_search.py (query orchestrator)
    → Requires: Phase 1 (mapping), Phase 3 (rerank endpoint)
    → Can be developed in parallel with Phase 2 (embedding backfill)
    → Deliverable: HybridSearch class with fallback to BM25 if no embedding

Phase 5: Upgrade MCP tools + FastAPI endpoints
    → Requires: Phase 4
    → Deliverable: es_search tool uses hybrid_search.py, REST /search endpoint
```

## Sources

- [Elasticsearch Hybrid Search Overview — Elastic Labs](https://www.elastic.co/search-labs/blog/hybrid-search-elasticsearch) — HIGH confidence
- [kNN Search in Elasticsearch — Elastic Docs](https://www.elastic.co/docs/solutions/search/vector/knn) — HIGH confidence
- [Semantic Reranking — Elastic Docs](https://www.elastic.co/docs/solutions/search/ranking/semantic-reranking) — HIGH confidence
- [Using Cohere with Elasticsearch — Elastic Docs](https://www.elastic.co/docs/solutions/search/semantic-search/cohere-es) — HIGH confidence
- [Cohere + Elasticsearch Integration Guide — Cohere Docs](https://docs.cohere.com/docs/elasticsearch-and-cohere) — HIGH confidence
- [Bring Your Own Dense Vectors to ES — Elastic Docs](https://www.elastic.co/docs/solutions/search/vector/bring-own-vectors) — HIGH confidence
- [Dense Vector Field Type — Elasticsearch Reference](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/dense-vector) — HIGH confidence
- [Elasticsearch Hybrid Search Recipes Benchmarked — softwaredoug.com](https://softwaredoug.com/blog/2025/03/13/elasticsearch-hybrid-search-strategies) — MEDIUM confidence (independent practitioner)
- [GDELT Project: ES ANN Vector Search RAM Costs](https://blog.gdeltproject.org/our-journey-towards-user-facing-vector-search-evaluating-elasticsearchs-ann-vector-search-ram-costs/) — MEDIUM confidence (empirical data)

---
*Architecture research for: GABI hybrid search integration (ES 8.15.4 + MongoDB + Cohere)*
*Researched: 2026-03-12*
