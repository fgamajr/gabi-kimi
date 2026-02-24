Architectural Gap Audit — GABI System
  ═════════════════════════════════════

  Forensic Comparison: Implementation vs. Specification

  ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
  1. Target Architecture Model (Extracted from V6/V7 Plans)

  System: GABI (Ingestão e Busca Jurídica TCU)

  Target_Components:
    Pipeline_Stages:
      - Seed:         Load source definitions from YAML to PostgreSQL
      - Discovery:    Discover URLs via multiple strategies (static, pattern, crawl, API)
      - Fetch:        HTTP streaming download with memory-safe parsing
      - Ingest:       Parse → Chunk → Embed → Index (PostgreSQL + Elasticsearch)
      - Index:        Dual-write to PG + Elasticsearch with vector embeddings

    Services:
      - API:          REST v1 with JWT auth, rate limiting, OpenAPI
      - Worker:       Hangfire-based job processor with queue separation
      - Search:       Hybrid lexical + semantic search with reranker

    Infrastructure:
      - PostgreSQL:   Primary persistence, job queue, DLQ
      - Elasticsearch: Full-text search + vector storage (dense_vector)
      - Redis:        Caching / distributed locks
      - OpenTelemetry: Distributed tracing + metrics (OTLP export)

    Resilience:
      - Polly:        Circuit breakers for ES, YouTube API, OpenAI
      - ErrorTaxonomy: Classified retries (Transient/Throttled/Permanent/Bug)
      - DLQ:          Dead letter queue with replay capability

    Processing:
      - Chunking:     Text segmentation for embeddings
      - Embeddings:   Vector generation (OpenAI/local TEI)
      - Reranker:     Cross-encoder relevance scoring

    Observability:
      - SLOs:         P99 latency < 200ms, error budget < 0.1%
      - Tracing:      End-to-end pipeline waterfall
      - Metrics:      docs/min, memory/stage, error rate

  ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
  2. Current Architecture Model (Codebase Evidence)

  System: GABI (Current Implementation)

  Implemented_Components:
    Pipeline_Stages:
      - Seed:         ✅ IMPLEMENTED (CatalogSeedJobExecutor)
      - Discovery:    ✅ IMPLEMENTED (7 adapters, ChangeDetector, LinkComparator)
      - Fetch:        ✅ IMPLEMENTED (CSV streaming, JSON API, memory-safe)
      - Ingest:       ❌ STUBBED (IngestJobExecutor only updates DB status)
      - Index:        ❌ MISSING (IElasticIndexer interface only, no implementation)

    Services:
      - API:          ✅ PARTIAL (JWT auth, basic endpoints, no search)
      - Worker:       ✅ IMPLEMENTED (Hangfire with 6 job types)
      - Search:       ❌ MISSING (no search service implementation)

    Infrastructure:
      - PostgreSQL:   ✅ IMPLEMENTED (full EF Core + migrations)
      - Elasticsearch:❌ STUBBED (entity has ElasticsearchId field, never populated)
      - Redis:        ⚠️ CONFIGURED (Hangfire uses PG, Redis referenced but unused)
      - OpenTelemetry:✅ IMPLEMENTED (API + Worker with OTLP export)

    Resilience:
      - Polly:        ⚠️ PARTIAL (basic retry in Fetch, no circuit breakers)
      - ErrorTaxonomy:✅ IMPLEMENTED (ErrorClassifier with 4 categories)
      - DLQ:          ✅ IMPLEMENTED (entries, retry, replay via API)

    Processing:
      - Chunking:     ❌ MISSING (spans created, no actual implementation)
      - Embeddings:   ❌ MISSING (no embedding service)
      - Reranker:     ❌ MISSING (not implemented)

    Media:
      - Upload:       ✅ IMPLEMENTED (multipart, local file, URL)
      - Transcription:✅ IMPLEMENTED (OpenAI Whisper - NOT AWS)

  ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
  3. Component Diff Matrix

   Component             Status        Evidence                             Notes
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Seed Pipeline         IMPLEMENTED   CatalogSeedJobExecutor.cs            34 sources loadable
   Discovery Engine      IMPLEMENTED   DiscoveryEngine.cs, 7 adapters       URL pattern, static, crawl, API pagination
   Fetch Pipeline        IMPLEMENTED   FetchJobExecutor.cs                  Streaming CSV, JSON API, memory < 300MB
   Ingest Pipeline       STUBBED       IngestJobExecutor.cs:29-118          Only updates DB status, NO chunk/embed/index
   Elasticsearch Index   MISSING       IDocumentIndexer.cs interface only   No implementation found
   Chunking Service      MISSING       IChunker.cs interface only           No implementation
   Embedding Service     MISSING       IEmbedder.cs interface only          No implementation
   Search Service        MISSING       No search service class              Dashboard mocks ES data
   OpenTelemetry         IMPLEMENTED   Program.cs API + Worker              Tracing + metrics with OTLP
   Error Taxonomy        IMPLEMENTED   ErrorTaxonomy.cs                     4-category classifier
   Polly Retry           PARTIAL       FetchService.cs                      Basic retry only, no circuit breaker
   Circuit Breakers      MISSING       —                                    Required per V6 P2.2
   DLQ + Replay          IMPLEMENTED   DlqService.cs, DlqFilter.cs          Full DLQ lifecycle
   Media Upload          IMPLEMENTED   MediaEndpoints.cs                    Multipart, local file, URL
   Media Transcription   IMPLEMENTED   MediaTranscribeJobExecutor.cs        OpenAI Whisper (non-AWS)
   NetArchTest           IMPLEMENTED   LayeringTests.cs                     3/3 tests passing
   Result<T> Pattern     MISSING       —                                    4 error patterns coexist (V6 P0.0)
   Typed Config          MISSING       15+ Dictionary<string,object>        V6 P0.0b not implemented
   Embeddings Vector     MISSING       —                                    pgvector or ES dense_vector
   Reranker              MISSING       —                                    V6 P1.4 not started
   Normative Events      MISSING       —                                    V6 P1.1 not started
   Motor Temporal        MISSING       —                                    V6 P2.1 not started

  ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
  4. Pipeline Reality Report

  Document Flow Analysis

  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
  │   Source    │───▶│  Discovery  │───▶│    Fetch    │───▶│   Ingest    │───▶│    Index    │
  │   (YAML)    │    │   (Links)   │    │  (Content)  │    │ (Process)   │    │  (Search)   │
  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
        ✅                   ✅                  ✅                 ❌                 ❌
     WORKING             WORKING             WORKING            STUBBED          MISSING

  Execution Reality (Per V6 A.1 Evidence)

   Stage       Status    Evidence                             Memory
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Seed        ✅ PASS   34 sources registered                —
   Discovery   ✅ PASS   7 sources tested, 200 links/source   —
   Fetch       ✅ PASS   200 docs (Senado), streaming CSV     95 MiB
   Ingest      ⚠️ STUB    Updates DB status only               N/A
   ES Index    ❌ FAIL   NO IMPLEMENTATION                    N/A

  Critical Finding: The Ingest Gap

  The IngestJobExecutor creates OpenTelemetry activities for:

  • pipeline.parse ✅ (document already parsed in Fetch)
  • pipeline.chunk ❌ NO-OP (span created, no chunking)
  • pipeline.embed ❌ NO-OP (span created, no embedding)
  • pipeline.index ❌ NO-OP (span created, no ES indexing)

  Code Evidence (src/Gabi.Worker/Jobs/IngestJobExecutor.cs:60-70):

  // Only updates status - NO actual processing
  doc.Status = "completed";
  doc.ProcessingStage = "ingested";
  await _context.SaveChangesAsync(ct);

  Resume/Fail-Safe Capability

   Capability                Status      Evidence
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Idempotency (Discovery)   ✅ YES      Link hash-based deduplication
   Idempotency (Fetch)       ✅ YES      ETag/Last-Modified checking
   Idempotency (Ingest)      ⚠️ PARTIAL   Status-based, no ES rollback
   Resume (Fetch)            ✅ YES      ResetStuckProcessingItemsAsync
   Resume (Ingest)           ❌ NO       No ES document tracking
   DLQ Replay                ✅ YES      API endpoint + filter

  ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
  5. AWS Lock-In Report

  Constraint: Final system MUST NOT depend on AWS

   Finding                  Severity   Details                                    Mitigation
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   S3 Reference (Comment)   INFO       DocumentEntity.cs:69 mentions "S3/minio"   Comment only, no code dependency
   AWS SDK                  NONE       No AWSSDK packages in any .csproj          ✅ Clean
   OpenAI Transcription     N/A        Uses OpenAI Whisper API                    ✅ Non-AWS, third-party
   YouTube API              N/A        Google Data API v3                         ✅ Non-AWS, third-party

  Verdict: ✅ AWS INDEPENDENCE CONFIRMED

  The system has zero hard AWS dependencies. The architecture is portable to any cloud provider or on-premise deployment.

  ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
  6. Completion Metrics

   Dimension                 Implemented        Target              % Complete
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Architecture Components   12 / 22            22                  55%
   Pipeline Functional       3 / 5 stages       5                   60%
   Production Readiness      Partial            Full                40%
   Observability             OTel + DLQ         +SLOs +Alerts       70%
   Resilience                Retry + Taxonomy   +Circuit Breakers   50%

  Detailed Breakdown

   V6 Deliverable                    Status                             %
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   P0.0 Result<T>                    ❌ Not started                     0%
   P0.0b Typed Config                ❌ 15+ Dictionary<string,object>   0%
   P0.0c Contract Consolidation      ✅ Completed (Fase 1)              100%
   P0.0d OpenTelemetry               ✅ Implemented                     100%
   P0.0e Error Taxonomy              ✅ Implemented                     100%
   P0.1 API REST v1                  ⚠️ Partial (no search)              60%
   P0.2 Search Service               ❌ Missing                         0%
   P0.3 Observability Core           ⚠️ Partial (no SLOs)                50%
   P0.4 NetArchTest                  ✅ Implemented                     100%
   P0.5 Smoke Tests                  ❌ Missing                         0%
   P0.6 Memory Budget CI             ❌ Missing                         0%
   P0.7 Gabi.Ingest.Tests            ❌ Project empty                   0%
   P1.1 Normative Events             ❌ Missing                         0%
   P1.2 Multi-Source Consolidation   ❌ Missing                         0%
   P1.3 Embeddings                   ❌ Missing                         0%
   P1.4 Reranker                     ❌ Missing                         0%
   P2.2 Circuit Breakers             ❌ Missing                         0%

  ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
  7. Minimal Path to Final Architecture

  Priority 1: Pipeline Completion (BLOCKING)

  Goal: Documents must flow to Elasticsearch

  1. Implement Elasticsearch Indexer (~8h)
    • Create Gabi.Ingest/ElasticIndexer.cs
    • Implement IElasticIndexer.IndexAsync()
    • Add ES client configuration (NEST/Elastic.Clients.Elasticsearch)
  2. Implement Chunking Service (~6h)
    • Create Gabi.Ingest/Chunker.cs
    • Implement IChunker.ChunkAsync() with text segmentation
  3. Implement Embedding Service (~6h)
    • Create Gabi.Ingest/Embedder.cs
    • Integrate OpenAI embeddings API (or local TEI)
  4. Fix IngestJobExecutor (~4h)
    • Wire up Chunk → Embed → Index pipeline
    • Add transaction boundary (PG + ES)

  Priority 2: Search API (BLOCKING)

  Goal: Users can search indexed documents

  5. Implement Search Service (~8h)
    • Create Gabi.Api/Services/SearchService.cs
    • Query DSL for lexical + semantic search
    • Add POST /api/v1/search endpoint

  Priority 3: Resilience (REQUIRED)

  Goal: Production-grade fault tolerance

  6. Add Circuit Breakers (~6h)
    • Configure Polly CircuitBreakerPolicy for ES
    • Configure for YouTube API, OpenAI API
    • Add to Program.cs Worker

  Priority 4: Code Quality (TECH DEBT)

  Goal: V6 P0.0 deliverables

  7. Adopt Result<T> Pattern (~16h)
    • Add ErrorOr package
    • Refactor JobStateMachine, repositories
    • Update 4 error patterns to single pattern
  8. Typed Config (~12h)
    • Replace 15+ Dictionary<string,object> with records
    • Create JobPayload, DocumentMetadata types

  Priority 5: Testing (CONFIDENCE)

  Goal: Validate architecture

  9. Gabi.Ingest.Tests (~8h)
    • Unit tests for Chunker, Embedder, Indexer
    • 80% coverage target
  10. Smoke Tests (~4h)
    • tests/smoke-test.sh implementation
    • Health + auth + basic flow validation

  Priority 6: Advanced Features (DIFFERENTIATION)

  Goal: V6 P1/P2 differentiators

  11. Normative Events Engine (~24h)
  12. Multi-Source Consolidation (~16h)
  13. Reranker Integration (~12h)

  ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
  8. Architectural Risk Essay

  Systemic Risks

  1. The "Fake Ingest" Problem (CRITICAL)

  The most severe architectural risk is the disconnected ingest stage. The IngestJobExecutor creates telemetry spans suggesti
  ng work is happening (pipeline.chunk, pipeline.embed, pipeline.index) but performs zero actual processing. This is a false
  observability signal — the system appears healthy while failing to deliver its core value (searchable documents).

  Impact:

  • Users cannot search documents (primary use case broken)
  • SLOs cannot be met (documents never reach ES)
  • Memory/performance metrics are meaningless (no actual processing)

  Evidence:

  // IngestJobExecutor.cs lines 47-57
  using var chunkActivity = PipelineTelemetry.ActivitySource.StartActivity("pipeline.chunk");
  using var embedActivity = PipelineTelemetry.ActivitySource.StartActivity("pipeline.embed");
  using var indexActivity = PipelineTelemetry.ActivitySource.StartActivity("pipeline.index");
  // ... NO actual chunking, embedding, or indexing occurs

  2. Interface Without Implementation Pattern

  Multiple critical interfaces have zero implementations:

  • IDocumentIndexer / IElasticIndexer — no indexer exists
  • IChunker — no chunker exists
  • IEmbedder — no embedder exists

  This suggests the architecture was designed top-down but implementation stalled at the contract layer. The system appears a
  rchitecturally complete while being functionally hollow.

  3. Pipeline Determinism vs. Reality

  The pipeline claims idempotency but cannot guarantee it:

  • Discovery/Fetch: Properly idempotent (hash/ETag based)
  • Ingest: Falsely idempotent (status-based only)
  • Index: Non-existent (cannot verify)

  Without ES document tracking, the system cannot:

  • Detect duplicate documents across re-runs
  • Rollback partial failures
  • Resume interrupted indexing

  4. Memory Budget Fiction

  The 300MB memory budget is validated for Fetch (95 MiB measured), but Ingest has no memory control. When chunking + embeddi
  ng is implemented, memory usage will increase significantly. The current telemetry provides false confidence.

  5. AWS Independence (Confirmed Safe)

  The system successfully avoids AWS lock-in. The only AWS reference is a comment about S3/minio as a future option. Current
  transcription uses OpenAI (portable), not AWS Transcribe.

  Hidden Technical Debt

   Debt                             Location                                       Effort to Fix
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   4 coexisting error patterns      JobStateMachine, repositories, fetch results   16h (Result<T> refactor)
   15+ untyped Dictionary configs   IngestJob.Payload, metadata fields             12h (typed records)
   Enum proliferation               9 different status enums                       4h (StatusVocabulary usage)
   Mock ES data in dashboard        DashboardService.cs:295                        8h (real ES integration)
   Hard-coded parse configs         FetchJobExecutor.cs                            6h (config-driven)

  Survivability Assessment

   Scenario                    Current State             With Priority 1 Fixes
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Single document ingestion   ✅ Works to PG            ✅ Works end-to-end
   10k document batch          ✅ Memory-safe            ⚠️ Needs ES batch tuning
   ES cluster failure          ❌ No impact (not used)   ⚠️ Needs circuit breaker
   Network partition           ✅ Hangfire retries       ✅ Error taxonomy handles
   Duplicate job execution     ⚠️ PG idempotent           ⚠️ ES dedup needed

  Trajectory Verdict

  The architecture is CONVERGING but INCOMPLETE.

  Positive indicators:

  • Clean layered architecture (validated by NetArchTest)
  • Solid foundation (Discovery + Fetch are production-ready)
  • Observability infrastructure in place (OTel)
  • Error taxonomy implemented
  • AWS-independent design confirmed

  Negative indicators:

  • Critical path broken (Ingest → Index missing)
  • False telemetry (spans without work)
  • Multiple error patterns (technical debt)
  • No search capability (primary feature missing)

  Risk Level: 🔴 HIGH — The system cannot fulfill its primary purpose (search) in the current state. The gap between "appear…
  to work" (telemetry shows activity) and "actually works" (documents searchable) is dangerous.

  Recommendation: Halt all V7 work. Complete Priority 1 (Pipeline Completion) before any other features. The system is a "suc
  cessful failure" — well-architected but functionally incomplete.
