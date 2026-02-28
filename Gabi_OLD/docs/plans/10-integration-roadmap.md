# GABI Integration Roadmap

> **MASTER PLAN**: Comprehensive integration strategy tying all GABI components together.
> **Version**: 1.0.0  
> **Last Updated**: 2026-02-12  
> **Status**: Draft - Pending Review

---

## Executive Summary

This document provides the master integration plan for the GABI (Geração de Análise de Bases Informatizadas) system - a legal document ingestion and search platform for TCU (Tribunal de Contas da União) data.

### Current State Assessment

| Component | Status | Completeness | Risk Level |
|-----------|--------|--------------|------------|
| Gabi.Contracts | ✅ Stable | 100% | Low |
| Gabi.Discover | 🟡 Partial | 60% (StaticUrl, UrlPattern working) | Medium |
| Gabi.Api | 🟡 MVP | 40% (discovery only) | Medium |
| Gabi.Postgres | 🟡 Schema Only | 30% (EF Core, empty) | Medium |
| Gabi.Sync | 🟡 Contracts Only | 20% | High |
| Gabi.Ingest | 🔴 Empty | 0% | Critical |
| Frontend | 🟡 MVP | 50% (list + details) | Medium |
| Infrastructure | ✅ Ready | 100% | Low |

### Missing Critical Components

- WebCrawl strategy implementation
- ApiPagination strategy implementation  
- Persistent storage integration
- Job queue (Redis-based)
- Pipeline execution engine
- Resilience patterns (retry, circuit breaker, DLQ)

---

## 1. Phased Implementation Roadmap

### Phase 0: Foundation (Current - COMPLETE)

**Duration**: 3 weeks (COMPLETED)  
**Goal**: Establish project structure, contracts, and infrastructure

**Deliverables**:
- ✅ .NET 8 solution with 6 projects
- ✅ Docker Compose (Postgres 15, Elasticsearch 8, Redis 7)
- ✅ Contract definitions (21 files)
- ✅ Layered architecture documentation
- ✅ Frontend Vite scaffold

**Verification**:
```bash
dotnet build  # Build succeeds
docker compose up -d  # Infra starts
./scripts/dev-up.sh  # Health checks pass
```

---

### Phase 1: MVP - "Discovery to API" (Weeks 4-6)

**Duration**: 3 weeks  
**Goal**: End-to-end data flow from discovery to API response

#### 1.1 Postgres Persistence Layer

**Priority**: P0 - Critical Path

| Task | Effort | Dependencies | Owner |
|------|--------|--------------|-------|
| DocumentEntity finalization | 2d | Contracts | Data Layer |
| ChangeDetectionCache entity | 1d | Contracts | Data Layer |
| ExecutionManifest entity | 1d | Contracts | Data Layer |
| EF Migrations | 1d | Entities | Data Layer |
| Repository implementations | 3d | Entities | Data Layer |

**Key Decisions**:
- Use UUID PKs for all entities
- Soft delete with `IsDeleted` flag
- JSONB for flexible metadata storage
- TimescaleDB consideration for time-series metrics

**Verification**:
```bash
dotnet ef migrations add Initial
dotnet ef database update
```

#### 1.2 Gabi.Ingest - Fetcher

**Priority**: P0 - Critical Path

| Task | Effort | Dependencies | Owner |
|------|--------|--------------|-------|
| HttpClient wrapper with resilience | 3d | - | Ingest |
| Streaming download (64KB chunks) | 2d | MemoryManager | Ingest |
| Change detection integration | 2d | Cache entity | Ingest |
| SSRF protection | 1d | - | Ingest |
| Retry with exponential backoff | 2d | - | Ingest |

**Critical Requirements**:
- **NO** `ReadAsStringAsync()` - streaming only
- ETag/Last-Modified caching
- Rate limiting (respect politeness)
- Timeout handling

**Verification**:
```csharp
// Integration test
var fetcher = new ContentFetcher(httpClient, cache);
var content = await fetcher.FetchAsync(url, config);
Assert.NotNull(content.Stream);
```

#### 1.3 Gabi.Ingest - Parser (CSV)

**Priority**: P0 - Critical Path

| Task | Effort | Dependencies | Owner |
|------|--------|--------------|-------|
| CSV streaming parser (| delimited) | 3d | - | Ingest |
| Field mapping from YAML config | 2d | Contracts | Ingest |
| Transform pipeline (strip_quotes, etc.) | 2d | Transforms | Ingest |
| UTF-8 encoding handling | 1d | - | Ingest |

**Critical Requirements**:
- Line-by-line streaming (no full file load)
- Configurable delimiter
- Quote handling

#### 1.4 API Integration

**Priority**: P0 - Critical Path

| Task | Effort | Dependencies | Owner |
|------|--------|--------------|-------|
| Connect SourceCatalog to Postgres | 2d | Repositories | API |
| Add document endpoints | 2d | Repositories | API |
| Health check with DB verification | 1d | DbContext | API |

**Verification**:
```bash
GET /api/v1/sources → 200 with persisted data
GET /health/ready → checks DB connectivity
```

#### 1.5 MVP Integration Test

**Scenario**: Full flow for single source (tcu_sumulas)

```
1. API receives refresh request
2. Discovery finds 1 URL (static)
3. Fetcher downloads with caching
4. Parser streams CSV rows
5. Documents stored in Postgres
6. API returns document count
```

**Success Criteria**:
- [ ] End-to-end in < 30 seconds
- [ ] Memory stays < 300MB
- [ ] Zero data loss
- [ ] Idempotent (re-run = no new data)

---

### Phase 2: v1 - "Production-Ready Ingestion" (Weeks 7-10)

**Duration**: 4 weeks  
**Goal**: Complete ingestion pipeline with resilience

#### 2.1 Gabi.Sync - SyncEngine

**Priority**: P0 - Critical Path

| Task | Effort | Dependencies | Owner |
|------|--------|--------------|-------|
| ExecutionManifest tracking | 2d | Entity | Sync |
| Phase orchestration | 3d | Pipeline | Sync |
| Retry with DLQ | 3d | - | Sync |
| Dead Letter Queue implementation | 2d | Postgres | Sync |
| Progress reporting | 2d | - | Sync |

**State Machine**:
```
Pending → Running → [Completed|Failed|Cancelled]
                    ↓
                  Retrying (max 3)
                    ↓
                  DLQ (after exhaustion)
```

#### 2.2 Job Queue (Redis)

**Priority**: P1 - Important

| Task | Effort | Dependencies | Owner |
|------|--------|--------------|-------|
| Redis queue integration | 2d | Redis | Sync |
| Job serialization | 1d | Contracts | Sync |
| Worker pool | 3d | - | Worker |
| Scheduled jobs (cron) | 2d | sources.yaml | Worker |

**Queue Design**:
```
queues:
  - gabi:queue:high     # Manual triggers
  - gabi:queue:normal   # Scheduled jobs
  - gabi:queue:dlq      # Failed jobs
```

#### 2.3 Missing Discovery Strategies

**Priority**: P1 - Important

| Task | Effort | Dependencies | Owner |
|------|--------|--------------|-------|
| WebCrawl implementation | 4d | - | Discover |
| ApiPagination implementation | 3d | - | Discover |
| Rate limiting (politeness) | 2d | - | Discover |
| robots.txt respect | 1d | - | Discover |

**WebCrawl Requirements**:
- Depth limiting
- URL deduplication
- Domain restriction
- Respect robots.txt

#### 2.4 Resilience Patterns

**Priority**: P0 - Critical Path

| Pattern | Implementation | Scope |
|---------|----------------|-------|
| Retry | Polly | HTTP calls, DB writes |
| Circuit Breaker | Polly | External APIs |
| Timeout | CancellationToken | All async ops |
| Bulkhead | SemaphoreSlim | Concurrent sources |
| Fallback | Default values | Non-critical features |

**Configuration**:
```yaml
resilience:
  retry:
    max_attempts: 3
    backoff: exponential
    initial_delay: 1s
    max_delay: 60s
  circuit_breaker:
    failure_threshold: 5
    duration: 30s
  timeout: 5m
```

#### 2.5 Observability

**Priority**: P1 - Important

| Task | Effort | Dependencies | Owner |
|------|--------|--------------|-------|
| Structured logging (Serilog) | 1d | - | All |
| Metrics (Prometheus) | 2d | - | All |
| Distributed tracing | 2d | - | All |
| Health checks expansion | 1d | - | API, Worker |

**Metrics to Track**:
- `gabi_documents_processed_total`
- `gabi_documents_failed_total`
- `gabi_pipeline_duration_seconds`
- `gabi_memory_usage_bytes`
- `gabi_discovery_urls_found`

---

### Phase 3: v2 - "Advanced Features" (Weeks 11-14)

**Duration**: 4 weeks  
**Goal**: Full-text search, embeddings, and hybrid RAG

#### 3.1 Elasticsearch Integration

**Priority**: P1 - Important

| Task | Effort | Dependencies | Owner |
|------|--------|--------------|-------|
| Index mapping design | 2d | - | Index |
| Bulk indexing | 3d | ES client | Index |
| BM25 search | 2d | - | Search |
| Index synchronization | 2d | Change detection | Index |

#### 3.2 pgvector & Embeddings

**Priority**: P1 - Important

| Task | Effort | Dependencies | Owner |
|------|--------|--------------|-------|
| Chunking strategies | 3d | - | Chunk |
| pgvector extension setup | 1d | Postgres | Data |
| Vector storage | 2d | EF Core | Data |
| TEI integration (HTTP) | 3d | TEI container | Embed |

**Chunking Strategies**:
- `whole_document` - for small docs
- `semantic_section` - by legal structure
- `fixed_size` - token-based with overlap

#### 3.3 Hybrid Search API

**Priority**: P1 - Important

| Task | Effort | Dependencies | Owner |
|------|--------|--------------|-------|
| BM25 + Vector fusion | 3d | ES + PG | Search |
| Reranking (Cross-Encoder) | 3d | TEI | Search |
| Search endpoints | 2d | - | API |
| Query pre-processing | 2d | - | Search |

**Search Endpoint**:
```
POST /api/v1/search
{
  "query": "licitação direta",
  "type": "hybrid",  // exact | semantic | hybrid
  "limit": 10,
  "filters": {
    "source": "tcu_acordaos",
    "year": [2020, 2021, 2022]
  }
}
```

#### 3.4 MCP Server Enhancement

**Priority**: P2 - Nice to Have

| Task | Effort | Dependencies | Owner |
|------|--------|--------------|-------|
| Hybrid search tools | 2d | Search API | MCP |
| Document retrieval | 1d | - | MCP |
| Source statistics | 1d | - | MCP |

---

### Phase 4: Production Hardening (Weeks 15-16)

**Duration**: 2 weeks  
**Goal**: Production deployment readiness

#### 4.1 Performance Optimization

| Task | Effort | Target |
|------|--------|--------|
| Connection pooling | 2d | < 100ms p99 DB latency |
| Query optimization | 2d | < 50ms p99 search |
| Caching layer | 2d | 80% cache hit rate |
| Compression | 1d | 50% bandwidth reduction |

#### 4.2 Security Hardening

| Task | Effort | Priority |
|------|--------|----------|
| API authentication | 2d | P0 |
| Rate limiting | 1d | P0 |
| Input validation | 2d | P0 |
| Secrets management | 1d | P1 |

#### 4.3 Documentation

| Task | Effort |
|------|--------|
| API documentation (OpenAPI) | 2d |
| Runbooks | 2d |
| Deployment guide | 1d |
| Architecture decision records | 1d |

---

## 2. Integration Sequence

### Dependency Graph

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           GABI COMPONENT DEPENDENCIES                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        Gabi.Contracts (Layer 0)                      │   │
│  │     Records, Enums, Interfaces - ZERO DEPENDENCIES                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    ▲                                        │
│        ┌───────────────────────────┼───────────────────────────┐           │
│        ▼                           ▼                           ▼           │
│  ┌─────────────┐            ┌─────────────┐            ┌─────────────┐     │
│  │Gabi.Postgres│            │Gabi.Discover│            │ Gabi.Ingest │     │
│  │   (Data)    │            │  (Control)  │            │   (Data)    │     │
│  └──────┬──────┘            └──────┬──────┘            └──────┬──────┘     │
│         │                          │                          │            │
│         └──────────────────────────┼──────────────────────────┘            │
│                                    ▼                                       │
│                           ┌─────────────┐                                  │
│                           │  Gabi.Sync  │                                  │
│                           │ (Orchestrate)│                                 │
│                           └──────┬──────┘                                  │
│                                  │                                         │
│         ┌────────────────────────┼────────────────────────┐               │
│         ▼                        ▼                        ▼               │
│  ┌─────────────┐          ┌─────────────┐          ┌─────────────┐       │
│  │Gabi.Worker  │          │  Gabi.Api   │          │  Gabi.MCP   │       │
│  │ (Background)│          │   (REST)    │          │  (Claude)   │       │
│  └─────────────┘          └─────────────┘          └─────────────┘       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Integration Order

#### Wave 1: Foundation Layer
**Week**: 4-5  
**Components**: Postgres + Ingest(Fetcher + Parser)

```
Gabi.Contracts
    ↓
Gabi.Postgres ──┐
    ↓            ├──→ Integration Tests
Gabi.Ingest ────┘
```

**Integration Points**:
1. `IDocumentRepository` → `DocumentEntity` CRUD
2. `IContentFetcher` → `FetchedContent` with streaming
3. `IDocumentParser` → `ParsedDocument` transformation

#### Wave 2: Orchestration Layer
**Week**: 6-7  
**Components**: Sync + Discover completion

```
Gabi.Discover ──┐
    ↓            ├──→ Gabi.Sync
Gabi.Ingest ────┘
    ↓
Gabi.Postgres
```

**Integration Points**:
1. `ISyncEngine` coordinates discovery → fetch → parse → store
2. `ExecutionManifest` tracks job state
3. `ChangeDetectionCache` prevents redundant work

#### Wave 3: API Layer
**Week**: 8  
**Components**: API + Frontend

```
Gabi.Api
    ↓
Gabi.Postgres (read-only views)
    ↓
Frontend (Vite)
```

**Integration Points**:
1. `ISourceCatalog` serves source metadata
2. Document endpoints for retrieval
3. WebSocket/SSE for real-time progress

#### Wave 4: Advanced Features
**Week**: 11-14  
**Components**: Search + Embeddings + MCP

```
Gabi.Ingest ──→ Chunk + Embed ──→ pgvector
    ↓
Elasticsearch ←── Index ←────────┘
    ↓
Search API ←── Hybrid Search
    ↓
MCP Server
```

### Critical Path

The critical path (longest sequence of dependent tasks):

```
Contracts (done)
    ↓ 0d
Postgres Entities (3d)
    ↓ 0d
Repositories (3d)
    ↓ 0d
Fetcher (5d) ──→ Parser (5d)
    ↓               ↓
    └──→ SyncEngine (7d)
            ↓
        API Integration (3d)
            ↓
        MVP Complete

Total Critical Path: 26 days (~5 weeks)
```

---

## 3. Risk Mitigation

### Risk Register

| ID | Risk | Likelihood | Impact | Mitigation Strategy |
|----|------|------------|--------|---------------------|
| R1 | Memory exhaustion in 1GB Fly.io | Medium | Critical | Streaming-only, backpressure, memory budgets |
| R2 | TCU API changes/breakage | Low | High | Abstraction layer, change detection, alerts |
| R3 | Postgres performance at scale | Medium | High | Connection pooling, indexing, read replicas |
| R4 | CSV parsing edge cases | Medium | Medium | Fuzz testing, fallback parsers, DLQ |
| R5 | Network timeouts during fetch | High | Medium | Retry with backoff, partial download resume |
| R6 | Data inconsistency (PG vs ES) | Medium | High | Source of truth pattern, reconciliation job |
| R7 | Worker crashes mid-pipeline | Low | High | Idempotency, state persistence, resume capability |
| R8 | Concurrent source modifications | Low | Medium | Optimistic locking, versioning |

### Detailed Mitigations

#### R1: Memory Exhaustion

**Detection**:
- Memory pressure events from `IMemoryManager`
- Prometheus alert: `gabi_memory_pressure_ratio > 0.8`

**Prevention**:
- Hard limit: `MaxFileSize = 100MB`
- Streaming only (no `ToList()`, no `ReadAsStringAsync()`)
- Sequential processing (parallelism = 1 in 1GB)
- GC trigger at 75% memory usage

**Recovery**:
- Automatic backpressure (pause → GC → resume)
- Document drop only as last resort (configurable)
- Pipeline restart with smaller batch size

**Testing**:
```csharp
[Fact]
public async Task LargeFile_StreamsWithoutOOM()
{
    var largeFile = GenerateFile(size: 500MB);
    var memoryBefore = GC.GetTotalMemory(true);
    
    await _fetcher.FetchAsync(largeFile);
    
    var memoryAfter = GC.GetTotalMemory(true);
    Assert.True(memoryAfter - memoryBefore < 100MB);
}
```

#### R2: External API Changes

**Strategy**: Defensive programming with abstractions

```csharp
public interface ISourceAdapter
{
    Task<bool> ValidateSchemaAsync();  // Proactive check
    Task<AdaptedResult> AdaptAsync(RawData data);
}
```

**Monitoring**:
- Schema validation on startup
- Alert on unexpected field absence
- Graceful degradation (skip unknown fields)

#### R3: Database Performance

**Prevention**:
- Query plan analysis (EXPLAIN)
- Proper indexing strategy
- Connection pooling (max 100)
- Async everywhere

**Scaling Path**:
1. Single instance (current)
2. Read replica for API queries
3. Connection pooling optimization
4. Sharding (by source_id)

#### R6: Data Inconsistency

**Source of Truth Hierarchy**:
1. PostgreSQL (canonical)
2. Elasticsearch (derived, rebuildable)
3. pgvector (derived, rebuildable)

**Reconciliation Job**:
```csharp
public async Task ReconcileAsync()
{
    var pgDocs = await _pg.GetAllIdsAsync();
    var esDocs = await _es.GetAllIdsAsync();
    
    var missingInEs = pgDocs.Except(esDocs);
    var orphanedInEs = esDocs.Except(pgDocs);
    
    await _es.IndexAsync(missingInEs);
    await _es.DeleteAsync(orphanedInEs);
}
```

### Testing Strategy by Risk

| Risk | Unit Test | Integration Test | Load Test | Chaos Test |
|------|-----------|------------------|-----------|------------|
| R1 | Memory budget | 500MB file ingest | 10 concurrent sources | Kill pod mid-processing |
| R2 | Adapter mock | Real TCU fetch | - | Simulate 404/500 |
| R3 | - | 1M document query | 1000 req/s | Drop DB connections |
| R4 | Parser edge cases | Malformed CSV | Large CSV files | Corrupt data |
| R5 | Retry logic | Timeout simulation | - | Network partition |

---

## 4. Testing Strategy

### Test Pyramid

```
                    ┌─────────┐
                    │   E2E   │  5% - Full system scenarios
                    │  (slow) │
                   ┌┴─────────┴┐
                   │Integration│  20% - Component interactions
                   │  (medium) │
                  ┌┴───────────┴┐
                  │  Contract   │  25% - API/Interface contracts
                  │   (fast)    │
                 ┌┴─────────────┴┐
                 │     Unit      │  50% - Isolated logic
                 │    (fast)     │
                 └───────────────┘
```

### Unit Tests (50%)

**Scope**: Individual classes, isolated with mocks

**Naming Convention**: `MethodName_StateUnderTest_ExpectedBehavior`

```csharp
[Fact]
public void Acquire_UnderPressure_WaitsForMemory()
{
    // Arrange
    var manager = new MemoryManager(logger, totalMemory: 100);
    manager.Acquire(80); // 80% allocated
    
    // Act & Assert
    Assert.Throws<TimeoutException>(() =>
        manager.Acquire(30, timeout: TimeSpan.FromMilliseconds(100)));
}

[Theory]
[InlineData("|", "a|b|c", new[] { "a", "b", "c" })]
[InlineData(";", "x;y;z", new[] { "x", "y", "z" })]
public void ParseLine_VariousDelimiters_ParsesCorrectly(
    string delimiter, string input, string[] expected)
{
    var parser = new CsvParser(delimiter);
    var result = parser.ParseLine(input);
    Assert.Equal(expected, result);
}
```

**Coverage Targets**:
- Business logic: 90%+
- Infrastructure: 70%+
- DTOs/Records: 0% (no logic)

### Contract Tests (25%)

**Scope**: Interface implementations against contracts

```csharp
public interface IContentFetcherContractTests
{
    protected IContentFetcher CreateFetcher();
    
    [Fact]
    public async Task FetchAsync_ValidUrl_ReturnsContent()
    {
        var fetcher = CreateFetcher();
        var result = await fetcher.FetchAsync("https://example.com/doc.csv");
        
        Assert.NotNull(result);
        Assert.NotNull(result.Stream);
        Assert.True(result.ContentLength > 0);
    }
    
    [Fact]
    public async Task FetchAsync_UnchangedContent_ReturnsNull()
    {
        // Cache hit scenario
    }
}
```

### Integration Tests (20%)

**Scope**: Component interactions with real dependencies (TestContainers)

```csharp
[Collection("Postgres")]
public class DocumentRepositoryTests
{
    private readonly PostgreSqlContainer _postgres;
    
    [Fact]
    public async Task CreateAsync_Document_SavesToDatabase()
    {
        // Arrange
        var context = CreateContext();
        var repo = new DocumentRepository(context);
        var doc = new DocumentEntity { /* ... */ };
        
        // Act
        await repo.CreateAsync(doc);
        
        // Assert
        var saved = await context.Documents.FindAsync(doc.Id);
        Assert.NotNull(saved);
        Assert.Equal(doc.DocumentId, saved.DocumentId);
    }
}
```

**Test Containers**:
- PostgreSQL with pgvector
- Elasticsearch
- Redis

### E2E Tests (5%)

**Scope**: Full system scenarios

```csharp
[Fact]
public async Task FullPipeline_SingleSource_ProcessesDocuments()
{
    // Arrange
    var factory = new WebApplicationFactory<Program>();
    var client = factory.CreateClient();
    
    // Act
    var response = await client.PostAsync(
        "/api/v1/sources/tcu_sumulas/refresh", null);
    
    // Wait for processing
    await WaitForProcessingComplete("tcu_sumulas", timeout: TimeSpan.FromMinutes(2));
    
    // Assert
    var docs = await client.GetAsync("/api/v1/documents?source=tcu_sumulas");
    var count = await docs.Content.ReadFromJsonAsync<DocumentCount>();
    Assert.True(count?.Total > 0);
}
```

### Test Environments

| Environment | Purpose | Data | Refresh |
|-------------|---------|------|---------|
| Local | Dev iteration | In-memory/Local containers | On demand |
| CI | PR validation | TestContainers | Every run |
| Staging | Integration | Production snapshot (anonymized) | Weekly |
| Production | Live | Real data | - |

### Performance Testing

**Load Tests**:
```csharp
[Fact]
public async Task Search_UnderLoad_MeetsSLA()
{
    var client = CreateClient();
    
    var result = await Benchmark.Run(async () =>
    {
        await client.GetAsync("/api/v1/search?q=licitação");
    }, iterations: 1000, parallelism: 10);
    
    Assert.True(result.P99 < 100); // 99th percentile < 100ms
    Assert.True(result.ErrorRate < 0.01); // < 1% errors
}
```

**Memory Tests**:
```csharp
[Fact]
public async Task Ingest_LargeSource_StaysWithinBudget()
{
    var meter = new MemoryMeter();
    
    await _syncEngine.ExecuteAsync("tcu_normas"); // 587MB file
    
    Assert.True(meter.PeakMB < 400);
    Assert.True(meter.CurrentMB < 200); // After GC
}
```

---

## 5. Migration Plan

### From In-Memory to Persistent Storage

#### Current State (In-Memory)
```csharp
// SourceCatalogService.cs - CURRENT
private readonly Dictionary<string, SourceDefinition> _sources = new();
private readonly Dictionary<string, List<DiscoveredLinkDto>> _discoveredLinks = new();
```

#### Target State (Persistent)
```csharp
// Future - with PostgreSQL
private readonly ISourceRepository _sourceRepository;
private readonly IDiscoveryCacheRepository _cacheRepository;
```

### Migration Strategy: Strangler Fig Pattern

```
Phase 1: Dual Write (Week 5)
┌─────────────────────────────────────────┐
│  Write to Memory + Postgres             │
│  Read from Memory (fast)                │
└─────────────────────────────────────────┘

Phase 2: Shadow Read (Week 6)
┌─────────────────────────────────────────┐
│  Write to both                          │
│  Read from Memory, verify with Postgres │
│  Log discrepancies                      │
└─────────────────────────────────────────┘

Phase 3: Cutover (Week 7)
┌─────────────────────────────────────────┐
│  Write to Postgres                      │
│  Read from Postgres                     │
│  Memory cache as L2 only                │
└─────────────────────────────────────────┘

Phase 4: Cleanup (Week 8)
┌─────────────────────────────────────────┐
│  Remove in-memory stores                │
│  Keep only caching layer                │
└─────────────────────────────────────────┘
```

### Step-by-Step Migration

#### Step 1: Add Postgres Repository (Week 5, Day 1-2)

```csharp
// New: ISourceRepository
public interface ISourceRepository
{
    Task<SourceEntity?> GetAsync(string id);
    Task SaveAsync(SourceEntity source);
    Task<IReadOnlyList<SourceSummary>> ListAsync();
}

// Modified: SourceCatalogService
public class SourceCatalogService : ISourceCatalog
{
    private readonly Dictionary<string, SourceDefinition> _memoryCache; // Keep for now
    private readonly ISourceRepository _repository; // New
    
    public async Task SaveAsync(SourceEntity source)
    {
        // Dual write
        _memoryCache[source.Id] = source;
        await _repository.SaveAsync(source);
    }
}
```

#### Step 2: Migration Script (Week 5, Day 3)

```csharp
public class MigrationService
{
    public async Task MigrateFromMemoryToPostgres()
    {
        foreach (var (id, source) in _memorySources)
        {
            var entity = MapToEntity(source);
            await _repository.SaveAsync(entity);
        }
    }
}
```

#### Step 3: Verification (Week 5, Day 4-5)

```csharp
[Fact]
public async Task Migration_DataIntegrity_MatchesSource()
{
    // Pre-migration
    var memoryData = _catalog.ListSourcesAsync();
    
    // Run migration
    await _migrationService.MigrateAsync();
    
    // Post-migration
    var pgData = await _repository.ListAsync();
    
    // Verify
    Assert.Equal(memoryData.Count, pgData.Count);
    Assert.Equal(
        memoryData.Select(s => s.Id).OrderBy(x => x),
        pgData.Select(s => s.Id).OrderBy(x => x));
}
```

#### Step 4: Feature Flag Cutover (Week 6)

```csharp
public class SourceCatalogService
{
    private readonly bool _usePostgres;
    
    public async Task<IReadOnlyList<SourceSummary>> ListSourcesAsync()
    {
        if (_usePostgres)
            return await _repository.ListAsync();
        
        return _memoryCache.Values.Select(...).ToList();
    }
}

// appsettings.json
{
  "FeatureFlags": {
    "UsePostgresForSources": true
  }
}
```

### Rollback Plan

If issues detected:

```csharp
// Instant rollback - flip feature flag
{
  "FeatureFlags": {
    "UsePostgresForSources": false  // Revert to memory
  }
}

// Data reconciliation if needed
public async Task ReconcileAsync()
{
    var memory = _memoryCache.Values.ToList();
    var postgres = await _repository.ListAsync();
    
    var discrepancies = memory
        .Where(m => !postgres.Any(p => p.Id == m.Id && p.Version == m.Version));
    
    foreach (var d in discrepancies)
    {
        await _repository.SaveAsync(d);
    }
}
```

### Database Migration Strategy

**Tool**: Entity Framework Core Migrations

```bash
# Initial migration
dotnet ef migrations add InitialSchema --project src/Gabi.Postgres

# Apply
dotnet ef database update --project src/Gabi.Postgres

# Rollback (if needed)
dotnet ef database update PreviousMigration
```

**Zero-Downtime Migrations**:
1. Add new column/table (nullable)
2. Deploy code that writes to both
3. Backfill data
4. Make column non-nullable
5. Deploy code that reads from new
6. Remove old column

---

## 6. Appendix

### A. Component Status Dashboard

```
┌─────────────────┬────────────┬──────────┬──────────┬──────────┐
│ Component       │ Contracts  │  Impl    │  Tests   │   Docs   │
├─────────────────┼────────────┼──────────┼──────────┼──────────┤
│ Gabi.Contracts  │ ✅ 100%    │ ✅ 100%  │ ✅ 100%  │ ✅ 100%  │
│ Gabi.Postgres   │ ✅ 100%    │ 🟡 30%   │ 🔴 0%    │ 🟡 50%   │
│ Gabi.Discover   │ ✅ 100%    │ 🟡 60%   │ 🟡 70%   │ 🟡 60%   │
│ Gabi.Ingest     │ ✅ 100%    │ 🔴 0%    │ 🔴 0%    │ 🔴 0%    │
│ Gabi.Sync       │ ✅ 100%    │ 🟡 20%   │ 🔴 0%    │ 🟡 30%   │
│ Gabi.Api        │ ✅ 100%    │ 🟡 40%   │ 🔴 0%    │ 🟡 50%   │
│ Gabi.Worker     │ ✅ 100%    │ 🟡 30%   │ 🔴 0%    │ 🟡 40%   │
│ Frontend        │ N/A        │ 🟡 50%   │ 🔴 0%    │ 🟡 50%   │
└─────────────────┴────────────┴──────────┴──────────┴──────────┘

Legend: ✅ Complete | 🟡 Partial | 🔴 Missing
```

### B. Technology Stack

| Layer | Technology | Version | Purpose |
|-------|------------|---------|---------|
| Runtime | .NET | 8.0 LTS | Application runtime |
| Database | PostgreSQL | 15 | Primary storage |
| Extension | pgvector | 0.5+ | Vector storage |
| Search | Elasticsearch | 8.11 | Full-text search |
| Cache/Queue | Redis | 7 | Caching, job queue |
| Embeddings | TEI | latest | Embedding generation |
| Frontend | Vite + Vanilla JS | 5.x | Web UI |
| Observability | Prometheus/Grafana | - | Metrics |
| Logging | Serilog | 3.x | Structured logging |

### C. Glossary

| Term | Definition |
|------|------------|
| **Change Detection** | Mechanism to detect if remote content has changed (ETag, Last-Modified, hash) |
| **Chunk** | Segment of a document for embedding generation |
| **DLQ** | Dead Letter Queue - for failed processing |
| **Fingerprint** | SHA-256 hash of normalized content for deduplication |
| **Pipeline** | Sequence of processing stages: Discovery → Fetch → Parse → Transform → Index |
| **Source** | External data source defined in sources.yaml |
| **TCU** | Tribunal de Contas da União (Brazilian Court of Accounts) |
| **TEI** | Text Embeddings Inference (Hugging Face) |

### D. Decision Log

| Date | Decision | Rationale | Alternatives Rejected |
|------|----------|-----------|----------------------|
| 2026-01-15 | PostgreSQL + pgvector over Pinecone | Cost, single datastore | Pinecone (10x cost), Weaviate (complexity) |
| 2026-01-20 | Streaming-only processing | 1GB RAM constraint | Disk spill (not available in Fly.io) |
| 2026-01-25 | Sequential processing | Memory safety | Parallel processing (OOM risk) |
| 2026-02-01 | Minimal API over Controllers | Simplicity, performance | MVC (boilerplate), FastEndpoints (learning curve) |
| 2026-02-05 | In-memory → Postgres migration | Progressive enhancement | Big bang (risky) |

---

## Review & Approval

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Technical Lead | | | |
| Architect | | | |
| Product Owner | | | |

---

*This document is a living document. Update as the project evolves.*
