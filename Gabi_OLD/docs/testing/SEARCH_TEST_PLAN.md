# Search API Test Plan

> **Hybrid Search Validation (BM25 + Vector + Graph + RRF)**  
> **Focus:** MCP Integration Readiness

---

## 1. Executive Summary

The GABI Search API implements a 3-strategy hybrid search with RRF (Reciprocal Rank Fusion):
- **BM25**: Full-text search via Elasticsearch (Portuguese analyzer)
- **Vector**: Semantic similarity via pgvector (cosine distance)
- **Graph**: Legal reference matching via PostgreSQL adjacency table

This document defines comprehensive test scenarios to validate search functionality for MCP (Model Context Protocol) integration.

---

## 2. Test Environment Requirements

### 2.1 Infrastructure
```yaml
Required Services:
  - PostgreSQL: 5433 (with pgvector extension)
  - Elasticsearch: 9200 (single index: gabi-docs)
  - TEI/Embedder: 8080 (for vector search)
  - API: https://localhost:5100

Test Data:
  - Minimum 100+ documents across 3+ sources
  - Documents with embeddings (pgvector)
  - Documents with relationships (graph edges)
  - Mixed status: active, pending, failed
```

### 2.2 Test Data Setup
```sql
-- Seed command (run via API)
POST /api/v1/dashboard/seed

-- Verify data distribution
SELECT source_id, status, COUNT(*) 
FROM documents 
GROUP BY source_id, status;

-- Verify embeddings
SELECT COUNT(*) FROM document_embeddings;

-- Verify relationships
SELECT COUNT(*) FROM document_relationships;
```

---

## 3. Test Scenarios

### 3.1 BM25 Search Tests

| ID | Test Case | Input | Expected Result | Priority |
|----|-----------|-------|-----------------|----------|
| BM25-001 | Basic keyword search | `q=licitacao` | Returns documents containing "licitacao" in title/content | P0 |
| BM25-002 | Portuguese stemming | `q=licitações` | Matches "licitacao", "licitacoes" (Portuguese analyzer) | P0 |
| BM25-003 | Title boost verification | Title: "Acordao X", Content: "licitacao" | Title matches rank higher than content-only matches | P1 |
| BM25-004 | Multi-word query | `q=contrato administrativo` | Returns documents with all words (AND semantics) | P0 |
| BM25-005 | Empty query handling | `q=` | HTTP 400 BadRequest with error code `missing_query` | P0 |
| BM25-006 | Special characters | `q=Lei 14.133/2021` | Properly escapes and searches | P1 |
| BM25-007 | Case insensitivity | `q=ACORDAO` vs `q=acordao` | Returns same results | P1 |
| BM25-008 | Long query (>100 chars) | Query with 200 characters | Handles gracefully, truncates if needed | P2 |

**Implementation Notes:**
- Uses Elasticsearch Portuguese analyzer
- Fields: `title^3` (boosted), `contentPreview^2`
- Only documents with `status=active` are returned

---

### 3.2 Vector Similarity Search Tests

| ID | Test Case | Input | Expected Result | Priority |
|----|-----------|-------|-----------------|----------|
| VEC-001 | Semantic similarity | `q=normas sobre compras publicas` | Returns docs about "licitacao" even without keyword match | P0 |
| VEC-002 | Embedding generation | Any query text | Query is embedded via TEI/ONNX (384 dimensions) | P0 |
| VEC-003 | Embedding failure handling | TEI unavailable | Search continues with BM25+Graph only, `EmbeddingFailed=true` | P1 |
| VEC-004 | Distance metric | Vector search results | Uses cosine distance (`<=>` operator) | P1 |
| VEC-005 | Top-K limiting | Query with many matches | Returns max 200 results (RankWindowSize) | P2 |
| VEC-006 | Source-filtered vector search | `sourceId=tcu_acordaos` | Only searches embeddings from specified source | P1 |

**Implementation Notes:**
- Embeddings stored in `document_embeddings` table (pgvector)
- Query vector generated via `IEmbedder.EmbedAsync()`
- Distance: cosine similarity (384 dimensions)

---

### 3.3 Hybrid Search with RRF Fusion Tests

| ID | Test Case | Input | Expected Result | Priority |
|----|-----------|-------|-----------------|----------|
| RRF-001 | RRF formula verification | Known ranked lists | Score = Σ(1/(k+r)) for k=60 | P0 |
| RRF-002 | BM25-only results | Query with no vector matches | RRF score = BM25 contribution only | P1 |
| RRF-003 | Vector-only results | Semantic query with no BM25 matches | RRF score = Vector contribution only | P1 |
| RRF-004 | Graph boost | Query matching legal references | Documents with citations get boosted | P2 |
| RRF-005 | Deduplication | Same doc in BM25 and Vector | Appears once with combined score | P0 |
| RRF-006 | Rank preservation | Multi-strategy results | Higher-ranked docs in any strategy score better | P1 |
| RRF-007 | Tie-breaking | Equal RRF scores | Deterministic ordering (doc ID) | P2 |

**RRF Formula:**
```csharp
Score(d) = Σ(1 / (60 + rank_i(d)))
where rank_i(d) = position in strategy i (1-indexed)
```

---

### 3.4 Search Filters Tests

| ID | Test Case | Input | Expected Result | Priority |
|----|-----------|-------|-----------------|----------|
| FIL-001 | Source filter | `sourceId=tcu_acordaos` | Only docs from specified source | P0 |
| FIL-002 | Invalid source filter | `sourceId=nonexistent` | Empty results (HTTP 200, total=0) | P1 |
| FIL-003 | Status filter (implicit) | Any query | Only `status=active` documents returned | P0 |
| FIL-004 | Pagination - first page | `page=1&pageSize=10` | Returns first 10 results | P0 |
| FIL-005 | Pagination - middle page | `page=3&pageSize=20` | Skips 40 results, returns next 20 | P0 |
| FIL-006 | Pagination - boundary | `page=999&pageSize=10` | Empty results, valid response | P1 |
| FIL-007 | Page size clamping | `pageSize=500` | Clamped to 100 | P1 |
| FIL-008 | Page size minimum | `pageSize=0` | Defaults to 20 | P1 |
| FIL-009 | Combined filters | `q=licitacao&sourceId=X&page=2&pageSize=5` | All filters applied | P0 |

---

### 3.5 Search Performance Tests (100+ Documents)

| ID | Test Case | Setup | Expected Result | Priority |
|----|-----------|-------|-----------------|----------|
| PERF-001 | Latency baseline | 100 documents | < 200ms p95 | P0 |
| PERF-002 | Latency at scale | 1000 documents | < 500ms p95 | P1 |
| PERF-003 | Concurrent searches | 10 parallel queries | No errors, stable latency | P1 |
| PERF-004 | BM25 performance | Large result set | ES query < 100ms | P1 |
| PERF-005 | Vector performance | kNN search | pgvector query < 150ms | P1 |
| PERF-006 | Memory usage | 100+ results | No excessive memory growth | P2 |
| PERF-007 | Circuit breaker | ES unavailable | Graceful degradation | P1 |

**Performance Thresholds:**
```yaml
Acceptable:
  - p50: < 100ms
  - p95: < 300ms
  - p99: < 500ms
  
Warning:
  - p95: 300-500ms
  
Critical:
  - p95: > 500ms
  - Errors: > 0.1%
```

---

### 3.6 Response Format & MCP Integration Tests

| ID | Test Case | Input | Expected Result | Priority |
|----|-----------|-------|-----------------|----------|
| MCP-001 | Response schema validation | Any search | Returns `SearchResultDto` structure | P0 |
| MCP-002 | Hit schema validation | Any search | Each hit has required fields | P0 |
| MCP-003 | Required fields present | `q=acordao` | id, sourceId, title, snippet present | P0 |
| MCP-004 | Optional metadata | Document with metadata | sourceViewUrl, publicationDate, etc. | P1 |
| MCP-005 | Snippet truncation | Long content | Snippet max 240 chars | P1 |
| MCP-006 | Total count accuracy | Paginated query | `total` reflects unfiltered result count | P0 |
| MCP-007 | Latency reporting | Any query | `latencyMs` field populated | P1 |
| MCP-008 | Embedding failure flag | TEI down | `embeddingFailed=true` | P1 |

**Expected Response Schema:**
```json
{
  "query": "licitacao",
  "total": 42,
  "page": 1,
  "pageSize": 10,
  "latencyMs": 45.23,
  "embeddingFailed": false,
  "hits": [
    {
      "id": "doc-uuid",
      "sourceId": "tcu_acordaos",
      "externalId": "12345",
      "title": "Acordao 123/2024",
      "snippet": "Texto resumido do documento...",
      "sourceViewUrl": "https://...",
      "sourceDownloadUrl": "https://...",
      "sourcePdfUrl": "https://...",
      "sourceAccessibleUrl": "/api/v1/documents/{id}/source-file",
      "section": "Primeira Secao",
      "publicationDate": "2024-01-15",
      "pageStart": "1",
      "pageEnd": "10"
    }
  ]
}
```

---

### 3.7 Error Handling & Edge Cases

| ID | Test Case | Input | Expected Result | Priority |
|----|-----------|-------|-----------------|----------|
| ERR-001 | Elasticsearch unavailable | ES down | Fallback to PG (if allowed) or 503 | P0 |
| ERR-002 | PostgreSQL unavailable | PG down | HTTP 503 or timeout | P0 |
| ERR-003 | TEI timeout | Slow embedder | Search continues, embeddingFailed=true | P1 |
| ERR-004 | Invalid UTF-8 | `q=\xff\xfe` | Handled gracefully | P2 |
| ERR-005 | SQL injection attempt | `q='; DROP TABLE` | Safely escaped | P0 |
| ERR-006 | Very long sourceId | 500 char string | Handled gracefully | P2 |
| ERR-007 | Negative pagination | `page=-1` | Normalized to page=1 | P1 |
| ERR-008 | ES circuit breaker open | After 5 failures | Returns 503 or degraded response | P1 |

---

## 4. MCP Integration Specific Tests

### 4.1 Tool: `SearchDocuments`
```csharp
[McpServerTool]
public async Task<string> SearchDocuments(
    [Description("Search query text")] string query,
    [Description("Optional source ID")] string? sourceId = null,
    [Description("Maximum number of results (1-100)")] int limit = 10,
    CancellationToken cancellationToken = default)
```

| ID | Test Case | Input | Expected Result | Priority |
|----|-----------|-------|-----------------|----------|
| MCP-T1 | Basic MCP search | `query="licitacao"` | Returns formatted JSON | P0 |
| MCP-T2 | MCP with source filter | `query="acordao", sourceId="tcu"` | Filtered results | P0 |
| MCP-T3 | MCP limit parameter | `limit=5` | Max 5 results returned | P0 |
| MCP-T4 | MCP URL encoding | `query="Lei 14.133/2021"` | Properly URL-encoded | P0 |
| MCP-T5 | MCP auth flow | No token | Authenticates via env vars | P1 |

### 4.2 Tool: `SearchLegalReferences`
```csharp
[McpServerTool]
public async Task<string> SearchLegalReferences(
    [Description("Reference pattern")] string reference,
    [Description("Maximum number of results")] int topK = 10,
    CancellationToken cancellationToken = default)
```

| ID | Test Case | Input | Expected Result | Priority |
|----|-----------|-------|-----------------|----------|
| MCP-G1 | Graph search by ref | `reference="Acordao 1234/2024"` | Returns citing documents | P0 |
| MCP-G2 | Partial ref match | `reference="Lei 14.133"` | Matches "Lei 14.133/2021" | P1 |
| MCP-G3 | Case insensitive | `reference="ACORDAO"` | Matches "Acordao" | P1 |

---

## 5. Test Implementation Guide

### 5.1 Unit Tests (Gabi.Api.Tests)
```csharp
[Collection("Api")]
public class SearchServiceTests : IClassFixture<CustomWebApplicationFactory>
{
    // Test SearchService directly with mocked dependencies
    // Mock: IElasticsearchClient, IEmbedder, IDocumentEmbeddingRepository
}
```

### 5.2 Integration Tests
```csharp
[Collection("Integration")]
public class SearchIntegrationTests : IClassFixture<IntegrationTestFixture>
{
    // Full stack: API + PostgreSQL + Elasticsearch + TEI
    // Use WebApplicationFactory with real services
}
```

### 5.3 Load Tests
```bash
# Using k6 or similar
k6 run --vus 10 --duration 30s search-load-test.js
```

---

## 6. Test Data Generator

```csharp
public static class SearchTestDataGenerator
{
    public static async Task SeedDocumentsAsync(
        GabiDbContext db, 
        ElasticsearchClient es,
        int count = 100)
    {
        // 1. Create sources
        // 2. Create DiscoveredLinks (status=completed)
        // 3. Create Documents (status=active)
        // 4. Index to Elasticsearch
        // 5. Create embeddings (pgvector)
        // 6. Create relationships (graph)
    }
}
```

---

## 7. Validation Checklist

### Pre-Deployment
- [ ] All P0 tests passing
- [ ] BM25 returns relevant results
- [ ] Vector search returns semantic matches
- [ ] RRF fusion working correctly
- [ ] Pagination works for large result sets
- [ ] Response schema matches MCP requirements
- [ ] Performance < 300ms p95

### Post-Deployment
- [ ] MCP tools responding correctly
- [ ] No 503 errors under normal load
- [ ] Monitoring dashboards active
- [ ] Alert thresholds configured

---

## 8. Appendix

### A. Search Service Architecture
```
┌─────────────────────────────────────────────────────────────┐
│                        SearchService                         │
├─────────────────────────────────────────────────────────────┤
│  Strategy 1: BM25 (Elasticsearch)                           │
│    - Index: gabi-docs                                       │
│    - Analyzer: portuguese                                   │
│    - Fields: title^3, contentPreview^2                      │
├─────────────────────────────────────────────────────────────┤
│  Strategy 2: Vector (pgvector)                              │
│    - Table: document_embeddings                             │
│    - Distance: cosine (<=>)                                 │
│    - Dimensions: 384                                        │
├─────────────────────────────────────────────────────────────┤
│  Strategy 3: Graph (PostgreSQL)                             │
│    - Table: document_relationships                          │
│    - Search: ILIKE on TargetRef                             │
├─────────────────────────────────────────────────────────────┤
│  Fusion: RRF (Reciprocal Rank Fusion)                       │
│    - k = 60                                                 │
│    - Score = Σ(1/(k+rank))                                  │
└─────────────────────────────────────────────────────────────┘
```

### B. RRF Calculation Example
```
BM25 ranks:  [DocA(1), DocB(2), DocC(3)]
Vector ranks: [DocB(1), DocC(2), DocD(3)]

RRF scores:
  DocA: 1/(60+1) = 0.0164
  DocB: 1/(60+1) + 1/(60+1) = 0.0328
  DocC: 1/(60+3) + 1/(60+2) = 0.0317
  DocD: 1/(60+3) = 0.0159

Final order: DocB, DocC, DocA, DocD
```

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-27  
**Owner:** GABI Engineering Team
