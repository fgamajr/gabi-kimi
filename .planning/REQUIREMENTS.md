# Requirements: GABI Hybrid Search

**Defined:** 2026-03-12
**Core Value:** Legal professionals and AI agents find the most relevant DOU documents by combining keyword precision with meaning-based retrieval, reranked for quality

## v1 Requirements

Requirements for hybrid search milestone. Each maps to roadmap phases.

### Infrastructure

- [ ] **INFRA-01**: ES JVM heap increased from 512MB to 4GB+ before any kNN workload
- [ ] **INFRA-02**: New ES index `gabi_documents_v2` created with `dense_vector` field (HNSW, int8 quantization)
- [ ] **INFRA-03**: Alias `gabi_documents` points to v2 index; all consumers use alias
- [ ] **INFRA-04**: All existing BM25 data reindexed from v1 to v2 with zero downtime

### Embedding Pipeline

- [ ] **EMBED-01**: Batch embedding pipeline generates vectors for all ~7M documents using Cohere embed-multilingual-v3.0
- [ ] **EMBED-02**: Pipeline is resumable via cursor (same pattern as es_indexer.py)
- [ ] **EMBED-03**: Per-document embedding status tracked in MongoDB (pending/done/failed)
- [ ] **EMBED-04**: Incremental embedding sync auto-embeds new DOU documents after ingestion
- [ ] **EMBED-05**: Embedding field is `ementa` + first N chars of `body_plain` (truncation strategy validated on 10K sample)

### Hybrid Search

- [ ] **SEARCH-01**: kNN search query path returns semantically similar documents
- [ ] **SEARCH-02**: Hybrid query composes BM25 + kNN results via convex combination (no Enterprise license dependency)
- [ ] **SEARCH-03**: Cohere Rerank (rerank-multilingual-v3.0) re-orders top-N fused candidates
- [ ] **SEARCH-04**: Semantic fallback triggers kNN-only search when BM25 returns zero results
- [ ] **SEARCH-05**: Search response includes mode transparency (which path: bm25/hybrid/semantic-fallback, rerank applied)
- [ ] **SEARCH-06**: Query-time embedding generated for user query (~50-200ms added latency acceptable)

### FastAPI Endpoints

- [ ] **API-01**: `GET /api/v1/search` with `mode` param (bm25/semantic/hybrid), filters, pagination
- [ ] **API-02**: `GET /api/v1/suggest` autocomplete endpoint
- [ ] **API-03**: `GET /api/v1/facets` aggregation endpoint
- [ ] **API-04**: `GET /api/v1/document/{id}` single document retrieval
- [ ] **API-05**: `GET /api/v1/health` with embedding coverage stats
- [ ] **API-06**: CORS middleware configured for frontend consumption

### MCP Tools

- [ ] **MCP-01**: `es_search` upgraded with `mode` param (default: `bm25` for backward compatibility)
- [ ] **MCP-02**: `es_health` reports embedding coverage (embedded_count / total_count)
- [ ] **MCP-03**: All existing MCP tool behavior unchanged when mode=bm25 (backward compatible)
- [ ] **MCP-04**: New `es_similar(doc_id)` tool for kNN "more like this" on a document's embedding

### Resilience

- [ ] **RESIL-01**: Cohere API unavailable triggers fallback to BM25-only results (no silent failure)
- [ ] **RESIL-02**: Structured logging for all search paths and fallback events
- [ ] **RESIL-03**: Hybrid search degrades gracefully with partial embedding coverage (docs without vectors still returned via BM25)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Search Quality

- **QUAL-01**: Tiered candidate strategy (dis_max boosting) for precision improvement
- **QUAL-02**: Date-biased hybrid scoring for time-sensitive queries
- **QUAL-03**: Reranker-aware snippet selection (show passage Cohere scored highest)

### Model Optimization

- **MODEL-01**: Evaluate Voyage law-2 against Cohere embed-multilingual-v3.0 on DOU corpus
- **MODEL-02**: Configurable `RERANK_TOP_K` env var for tuning rerank depth

## Out of Scope

| Feature | Reason |
|---------|--------|
| ELSER (Elastic sparse vectors) | English-only; confirmed unusable for Portuguese |
| Separate vector database (Pinecone, Weaviate) | ES 8.x kNN is production-grade; third data store adds complexity with no gain |
| Custom fine-tuned embedding model | Requires labeled training data that doesn't exist; months of MLOps work |
| Real-time embedding on ingest | DOU ingest is bulk ZIP processing; sync embedding breaks pipeline model |
| Streaming search results | MCP protocol is request-response; agents need complete result sets |
| Frontend search UI changes | Separate milestone; this phase is backend/API only |
| RRF via ES retriever API | Requires above-Basic license; convex combination is license-free alternative |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 1 | Pending |
| INFRA-02 | Phase 1 | Pending |
| INFRA-03 | Phase 1 | Pending |
| INFRA-04 | Phase 1 | Pending |
| EMBED-01 | Phase 2 | Pending |
| EMBED-02 | Phase 2 | Pending |
| EMBED-03 | Phase 2 | Pending |
| EMBED-04 | Phase 2 | Pending |
| EMBED-05 | Phase 2 | Pending |
| SEARCH-01 | Phase 3 | Pending |
| SEARCH-02 | Phase 3 | Pending |
| SEARCH-03 | Phase 3 | Pending |
| SEARCH-04 | Phase 3 | Pending |
| SEARCH-05 | Phase 3 | Pending |
| SEARCH-06 | Phase 3 | Pending |
| API-01 | Phase 4 | Pending |
| API-02 | Phase 4 | Pending |
| API-03 | Phase 4 | Pending |
| API-04 | Phase 4 | Pending |
| API-05 | Phase 4 | Pending |
| API-06 | Phase 4 | Pending |
| MCP-01 | Phase 5 | Pending |
| MCP-02 | Phase 5 | Pending |
| MCP-03 | Phase 5 | Pending |
| MCP-04 | Phase 5 | Pending |
| RESIL-01 | Phase 3 | Pending |
| RESIL-02 | Phase 3 | Pending |
| RESIL-03 | Phase 3 | Pending |

**Coverage:**
- v1 requirements: 28 total
- Mapped to phases: 28
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-12*
*Last updated: 2026-03-12 after initial definition*
