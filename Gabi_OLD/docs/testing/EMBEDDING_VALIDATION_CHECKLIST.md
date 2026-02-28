# Embedding Validation Checklist

> **Purpose:** Validate that embeddings work correctly with or without ONNX models, ensuring vector search functionality across all deployment scenarios.

---

## Summary

The GABI system supports three embedding providers:
1. **ONNX** (`OnnxEmbedder`) - Local inference using `paraphrase-multilingual-MiniLM-L12-v2` (384-dim)
2. **TEI** (`TeiEmbedder`) - External Text Embeddings Inference service (384-dim)
3. **Hash** (`HashEmbedder`) - Deterministic fallback for development/tests (384-dim)

**Critical Constraint:** All providers MUST produce 384-dimensional vectors to match `pgvector(384)` column.

---

## 1. ONNX Model Loading Tests

### 1.1 Model Files Validation
| # | Test | Expected Result | Priority |
|---|------|-----------------|----------|
| 1.1.1 | Verify `models/paraphrase-multilingual-MiniLM-L12-v2/model.onnx` exists | File exists (~470MB) | P0 |
| 1.1.2 | Verify `models/paraphrase-multilingual-MiniLM-L12-v2/vocab.txt` exists | File exists | P0 |
| 1.1.3 | Verify `config.json` exists and is valid JSON | Config parseable | P1 |

### 1.2 ONNX Runtime Initialization
| # | Test | Expected Result | Priority |
|---|------|-----------------|----------|
| 1.2.1 | `OnnxEmbedder` constructor loads model successfully | No exception thrown | P0 |
| 1.2.2 | `OnnxEmbedder` loads vocabulary correctly | Vocab size > 0 (expected ~30K) | P0 |
| 1.2.3 | `OnnxEmbedder` health check passes after initialization | Returns `true` | P0 |
| 1.2.4 | Invalid model path throws descriptive exception | `FileNotFoundException` with path info | P1 |
| 1.2.5 | Invalid vocab path throws descriptive exception | `FileNotFoundException` with path info | P1 |

### 1.3 ONNX Inference
| # | Test | Expected Result | Priority |
|---|------|-----------------|----------|
| 1.3.1 | `EmbedAsync("test text")` returns 384-dim vector | `result.Count == 384` | P0 |
| 1.3.2 | `EmbedBatchAsync(["a", "b", "c"])` returns 3 vectors of 384 dims | All vectors 384-dim | P0 |
| 1.3.3 | Empty string produces valid embedding | Returns 384-dim zero or near-zero vector | P1 |
| 1.3.4 | Long text (>128 tokens) truncates correctly | Still returns 384-dim vector | P1 |
| 1.3.5 | Special characters (Unicode, accents) handled | Returns valid 384-dim vector | P1 |
| 1.3.6 | Portuguese text embedding works | Returns valid 384-dim vector | P1 |
| 1.3.7 | Batch size respects configured limit (default 32) | Processes in batches of 32 | P2 |

---

## 2. Hash-Based Fallback Embedding Tests

### 2.1 HashEmbedder Correctness
| # | Test | Expected Result | Priority |
|---|------|-----------------|----------|
| 2.1.1 | `EmbedAsync("test")` returns 384-dim vector | `result.Count == 384` | P0 |
| 2.1.2 | Same input produces same output (deterministic) | `hash("abc") == hash("abc")` | P0 |
| 2.1.3 | Different inputs produce different outputs | `hash("abc") != hash("xyz")` | P0 |
| 2.1.4 | Vector values are in valid float range | All values between -1 and 1 | P1 |
| 2.1.5 | Empty string produces valid embedding | Returns 384-dim zero vector | P1 |
| 2.1.6 | Null/whitespace text handled gracefully | Returns 384-dim zero vector | P1 |
| 2.1.7 | Batch processing returns correct count | Input count == output count | P0 |

### 2.2 HashEmbedder Chunk Embedding
| # | Test | Expected Result | Priority |
|---|------|-----------------|----------|
| 2.2.1 | `EmbedChunksAsync` returns `EmbeddingResult` with correct model name | `result.Model == "hash-embedder-v1"` | P0 |
| 2.2.2 | Each chunk gets correct index | Chunk indices match input order | P0 |
| 2.2.3 | Token count preserved in embedded chunks | `embeddedChunk.TokenCount == original.TokenCount` | P1 |
| 2.2.4 | Metadata preserved through embedding | `embeddedChunk.Metadata == original.Metadata` | P1 |
| 2.2.5 | Health check always returns `true` | Returns `true` | P0 |

---

## 3. pgvector Storage Tests

### 3.1 Database Schema Validation
| # | Test | Expected Result | Priority |
|---|------|-----------------|----------|
| 3.1.1 | `document_embeddings` table exists | Table accessible | P0 |
| 3.1.2 | `Embedding` column is `vector(384)` | Column type confirmed | P0 |
| 3.1.3 | pgvector extension is enabled | `CREATE EXTENSION IF NOT EXISTS "vector"` succeeds | P0 |
| 3.1.4 | Unique constraint on `(DocumentId, ChunkIndex)` exists | Constraint enforced | P0 |
| 3.1.5 | Foreign key to `documents` table exists | Referential integrity enforced | P0 |

### 3.2 Repository CRUD Operations
| # | Test | Expected Result | Priority |
|---|------|-----------------|----------|
| 3.2.1 | `UpsertChunkEmbeddingsAsync` inserts new embeddings | Row count increases | P0 |
| 3.2.2 | `UpsertChunkEmbeddingsAsync` updates existing embeddings (upsert) | Data updated without error | P0 |
| 3.2.3 | Embedding vector stored matches input exactly | Retrieved values == input values | P0 |
| 3.2.4 | `HasEmbeddingsAsync` returns `true` for document with embeddings | Returns `true` | P0 |
| 3.2.5 | `HasEmbeddingsAsync` returns `false` for document without embeddings | Returns `false` | P0 |
| 3.2.6 | Multiple chunks for same document stored correctly | All chunks retrievable | P0 |

### 3.3 Vector Search Operations
| # | Test | Expected Result | Priority |
|---|------|-----------------|----------|
| 3.3.1 | `SearchSimilarAsync` returns results ordered by distance | Results sorted by ascending distance | P0 |
| 3.3.2 | Vector search with `topK=5` returns exactly 5 results | `results.Count == 5` | P0 |
| 3.3.3 | Vector search filtered by `sourceId` works | Only matching source returned | P0 |
| 3.3.4 | Vector distance is calculated correctly | Distance values between 0 and positive float | P1 |
| 3.3.5 | Search with non-matching source returns empty | `results.Count == 0` | P1 |
| 3.3.6 | Search works with 384-dim query vector | No exception thrown | P0 |

---

## 4. Embedding Dimension Compatibility Tests

### 4.1 Cross-Provider Dimension Consistency
| # | Test | Expected Result | Priority |
|---|------|-----------------|----------|
| 4.1.1 | `OnnxEmbedder` produces 384-dim vectors | `vector.Length == 384` | P0 |
| 4.1.2 | `TeiEmbedder` produces 384-dim vectors | `vector.Length == 384` | P0 |
| 4.1.3 | `HashEmbedder` produces 384-dim vectors | `vector.Length == 384` | P0 |
| 4.1.4 | All providers produce same dimension count | All return 384 | P0 |

### 4.2 pgvector Column Compatibility
| # | Test | Expected Result | Priority |
|---|------|-----------------|----------|
| 4.2.1 | 384-dim vector inserts successfully into `vector(384)` | No exception | P0 |
| 4.2.2 | Mismatched dimension (e.g., 768) fails with clear error | Exception with dimension info | P1 |
| 4.2.3 | Zero vector (all zeros) stores correctly | Retrieves as zero vector | P1 |
| 4.2.4 | Vector with extreme values (-1, 1) stores correctly | Values preserved | P1 |

### 4.3 IEmbedder Interface Compliance
| # | Test | Expected Result | Priority |
|---|------|-----------------|----------|
| 4.3.1 | All implementations implement `IEmbedder` | Compile-time verification | P0 |
| 4.3.2 | `EmbedAsync`, `EmbedBatchAsync`, `EmbedChunksAsync`, `HealthCheckAsync` present | Interface compliance | P0 |
| 4.3.3 | CancellationToken propagates correctly | `OperationCanceledException` on cancellation | P1 |

---

## 5. Embedding Generation Performance Tests

### 5.1 Throughput Benchmarks
| # | Test | Expected Result | Priority |
|---|------|-----------------|----------|
| 5.1.1 | `HashEmbedder`: Embed 1000 chunks in < 100ms | Duration < 100ms | P1 |
| 5.1.2 | `OnnxEmbedder`: Embed 100 chunks in < 5s | Duration < 5s | P1 |
| 5.1.3 | `TeiEmbedder`: Embed batch of 32 in < 2s (mock) | Duration < 2s | P1 |
| 5.1.4 | Batch processing is faster than sequential | Batch time < N × single time | P2 |

### 5.2 Resource Usage
| # | Test | Expected Result | Priority |
|---|------|-----------------|----------|
| 5.2.1 | `OnnxEmbedder` memory usage < 300MB peak | Memory monitored | P1 |
| 5.2.2 | Large batch (1000 chunks) doesn't cause OOM | Process completes | P0 |
| 5.2.3 | Concurrent embedding requests handled safely | No race conditions | P0 |

### 5.3 Latency Tests
| # | Test | Expected Result | Priority |
|---|------|-----------------|----------|
| 5.3.1 | Single text embedding < 100ms (Hash) | Duration < 100ms | P2 |
| 5.3.2 | Single text embedding < 500ms (ONNX) | Duration < 500ms | P2 |
| 5.3.3 | Empty batch returns immediately | Duration < 1ms | P2 |

---

## 6. Integration Tests

### 6.1 Worker Job Integration
| # | Test | Expected Result | Priority |
|---|------|-----------------|----------|
| 6.1.1 | `ChunkAndExtractJobExecutor` with `HashEmbedder` completes successfully | Job status = Success | P0 |
| 6.1.2 | Embeddings stored after successful job execution | `HasEmbeddingsAsync` returns true | P0 |
| 6.1.3 | Job with empty content marked as metadata-only | Status = completed, stage = metadata_only | P0 |
| 6.1.4 | Failed embedding doesn't fail entire job (fault isolation) | Job succeeds, error logged | P0 |

### 6.2 End-to-End Pipeline
| # | Test | Expected Result | Priority |
|---|------|-----------------|----------|
| 6.2.1 | Document flow: Fetch → Chunk → Embed → Store → Search | Full pipeline works | P0 |
| 6.2.2 | Search returns semantically similar documents | Relevant results returned | P0 |
| 6.2.3 | Re-embedding same document updates existing rows (upsert) | No duplicate chunks | P0 |

### 6.3 Configuration-Based Provider Selection
| # | Test | Expected Result | Priority |
|---|------|-----------------|----------|
| 6.3.1 | `Embeddings:Provider=hash` uses `HashEmbedder` | DI resolves to `HashEmbedder` | P0 |
| 6.3.2 | `Embeddings:Provider=onnx` with valid model uses `OnnxEmbedder` | DI resolves to `OnnxEmbedder` | P0 |
| 6.3.3 | `Embeddings:Provider=auto` with no TEI URL, no ONNX model uses `HashEmbedder` | Falls back to Hash | P0 |
| 6.3.4 | `Embeddings:Provider=auto` with TEI URL uses `TeiEmbedder` | Uses TEI | P0 |

---

## 7. Error Handling & Edge Cases

### 7.1 Graceful Degradation
| # | Test | Expected Result | Priority |
|---|------|-----------------|----------|
| 7.1.1 | ONNX model missing → falls back to HashEmbedder | Service starts, uses Hash | P0 |
| 7.1.2 | TEI unavailable → circuit breaker opens after 5 failures | Circuit breaker triggers | P0 |
| 7.1.3 | TEI 429 (rate limit) → `EmbeddingRateLimitException` | Specific exception type | P0 |

### 7.2 Edge Cases
| # | Test | Expected Result | Priority |
|---|------|-----------------|----------|
| 7.2.1 | Very long text (512KB) handled per GAP-13 | Document marked failed with size error | P0 |
| 7.2.2 | Single character text produces valid embedding | Returns 384-dim vector | P1 |
| 7.2.3 | Text with only whitespace produces valid embedding | Returns 384-dim zero vector | P1 |
| 7.2.4 | Concurrent modification of chunk list handled | No exception | P2 |

---

## Test Implementation Templates

### Unit Test: HashEmbedder Dimensions
```csharp
[Fact]
public async Task EmbedAsync_Returns384Dimensions()
{
    var embedder = new HashEmbedder();
    var result = await embedder.EmbedAsync("test text");
    Assert.Equal(384, result.Count);
}
```

### Unit Test: ONNX Model Loading
```csharp
[Fact]
public void Constructor_WithValidModel_LoadsSuccessfully()
{
    var logger = new Mock<ILogger<OnnxEmbedder>>().Object;
    var embedder = new OnnxEmbedder(
        "models/paraphrase-multilingual-MiniLM-L12-v2/model.onnx",
        "models/paraphrase-multilingual-MiniLM-L12-v2/vocab.txt",
        logger);
    Assert.True(await embedder.HealthCheckAsync());
}
```

### Integration Test: pgvector Storage
```csharp
[Fact]
public async Task UpsertChunkEmbeddings_Stores384DimVector()
{
    var docId = Guid.NewGuid();
    var chunks = new[] { new ChunkEmbedding(0, "test", new float[384], "test-model") };
    var count = await _repo.UpsertChunkEmbeddingsAsync(docId, "source1", chunks);
    Assert.Equal(1, count);
    Assert.True(await _repo.HasEmbeddingsAsync(docId));
}
```

### Performance Test: Embedding Throughput
```csharp
[Fact]
public async Task EmbedBatchAsync_100Chunks_CompletesWithinTime()
{
    var embedder = new HashEmbedder();
    var texts = Enumerable.Range(0, 100).Select(i => $"text {i}").ToList();
    var sw = Stopwatch.StartNew();
    var result = await embedder.EmbedBatchAsync(texts);
    sw.Stop();
    Assert.True(sw.ElapsedMilliseconds < 100, $"Took {sw.ElapsedMilliseconds}ms");
}
```

---

## CI/CD Integration

### Required Test Jobs
1. **`dotnet test --filter "FullyQualifiedName~HashEmbedderTests"`** - Hash fallback
2. **`dotnet test --filter "FullyQualifiedName~OnnxEmbedderTests"`** - ONNX (if model present)
3. **`dotnet test --filter "FullyQualifiedName~DocumentEmbeddingRepositoryTests"`** - pgvector storage
4. **`dotnet test --filter "FullyQualifiedName~TeiEmbedderTests"`** - TEI mock tests

### Pre-deployment Checks
- [ ] All P0 tests pass
- [ ] Model files present in deployment artifact
- [ ] pgvector extension available in target PostgreSQL
- [ ] `vector(384)` column type verified

---

## Related Documentation

- `src/Gabi.Ingest/OnnxEmbedder.cs` - ONNX runtime embedder
- `src/Gabi.Ingest/HashEmbedder.cs` - Hash fallback embedder  
- `src/Gabi.Ingest/TeiEmbedder.cs` - TEI service embedder
- `src/Gabi.Postgres/Repositories/DocumentEmbeddingRepository.cs` - Storage
- `src/Gabi.Postgres/Migrations/20260227120000_AddDocumentEmbeddingsAndRelationships.cs` - Schema
- `src/Gabi.Worker/Program.cs` (lines 160-217) - Provider selection logic

---

**Last Updated:** 2026-02-27  
**Owner:** Architecture Team  
**Review Cycle:** Per sprint
