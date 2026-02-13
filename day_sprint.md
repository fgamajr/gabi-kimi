# Dashboard Integration & Security Hardening Sprint

## 🎨 FASE 0: Design da Sincronização (Snapshot + Diff + Reconcile)

### Objetivo
Definir arquitetura de sincronização profissional antes de implementar.

### Entregáveis
- [ ] Documento `docs/plans/sync-reconciliation-design.md`
- [ ] Definição de Natural Key por fonte: (source_id, external_id)
- [ ] Estratégia de snapshot para cada tipo:
  - CSV: lista de IDs do arquivo
  - API: paginação de IDs
  - Crawler: URLs canônicas
- [ ] Fase de Reconcile:
  - INSERT: na fonte, não na base
  - UPDATE: hash diferente
  - SOFT DELETE: na base, não na fonte (removed_from_source_at)
- [ ] Métricas: added/updated/removed/unchanged

**Gate**: Documento revisado e aprovado

---

## 📜 Regras Transversais (aplicáveis a todas as fases)

### TDD (Test-Driven Development)
- Nenhum código de produção sem teste que falhou antes
- Ciclo: Red → Green → Refactor

### Zero Kelvin
- Gate obrigatório após cada fase
- Script: `tests/zero-kelvin-test.sh`

### Data Governance
- Soft delete: `removed_from_source_at` (nunca apagar fisicamente)
- Audit trail: `created_at`, `updated_at`
- LGPD: classificação para dados sensíveis

---

## 🎯 Objective
Integrate the `user-first-view` React dashboard with the Gabi API, implementing a granular "Source -> Link" data model and a robust security layer.

---

## ✅ PHASE 1: Architecture & Contracts (Granularity) - COMPLETED

Align the API with the dashboard's needs, focusing on the new "Per-Link" granularity and honest pipeline status.

### 1.1 New DTOs & Models - ✅ DONE
- [x] Create `SourceDetailsResponse` (in DashboardModels.cs)
- [x] Enhance `DiscoveredLinkDto` with:
  - [x] `Status` (pending, processed, error)
  - [x] `DocumentCount` (from metadata)
  - [x] `PipelineStatus` (object with status per stage)
- [x] Create `LinkIngestStatsDto` (covered by LinkPipelineStatusDto)

### 1.2 Granular Endpoints - ✅ DONE
Implement paginated, filterable endpoints to support the "Source Details" view.
- [x] `GET /api/v1/sources/{id}/links`
  - [x] Query Params: `page`, `pageSize`, `status`, `sort`
- [x] `GET /api/v1/sources/{id}/links/{linkId}`
- [x] `GET /api/v1/sources/{id}` (Enhanced details)

### 1.3 Pipeline Reality Check - ✅ DONE
- [x] Update `SourceCatalogService` to return `planned` status for `ingest`, `indexing`, `embedding` stages.
- [x] Ensure `harvest` (discovery) reflects real-time status.

---

## ✅ PHASE 2: Security Hardening (Zero Trust) - COMPLETED

Implement a production-grade security layer before exposing the API to the refined dashboard.

### 2.1 Authentication & Authorization - ✅ DONE
- [x] **JWT Bearer Auth**:
  - [x] Add `Microsoft.AspNetCore.Authentication.JwtBearer`
  - [x] Configure Token Validation (Issuer, Audience, Lifetime)
  - [x] Add `Login` endpoint (/api/v1/auth/login)
- [x] **RBAC Policies**:
  - [x] Define Roles: `Admin`, `Operator`, `Viewer`
  - [x] Apply `[Authorize(Policy = "...")]` to endpoints.

### 2.2 Middleware Hardening - ✅ DONE
- [x] **Global Exception Handler**: Standardize error responses, hide stack traces.
- [x] **Rate Limiting**:
  - [x] 100 req/min for Read
  - [x] 10 req/min for Write
- [x] **CORS**: Restrict to dashboard origin only.
- [x] **Security Headers**: HSTS, X-Content-Type-Options, etc.
- [x] **Request Limits**: Set body size limits (10MB).

---

## ✅ PHASE 3: Dashboard Integration (Frontend) - COMPLETED

Adapt the `user-first-view` codebase to consume the Gabi API.

### 3.1 API Client Adaptation - ✅ DONE
- [x] Update `api.ts` to use the new endpoints.
- [x] Implement JWT token handling (interceptor for Bearer token).

### 3.2 Component Updates - ✅ DONE
- [x] **Source Cards**: Link to new "Source Details" page.
- [x] **Source Details Page**:
  - [x] Implement `LinksTable` (Server-side pagination).
  - [x] Show per-link status.
- [x] **Pipeline Visualization**: Handle "planned" stages gracefully (greyed out or labeled).

---

## 🧪 PHASE 4: Verification - PARTIAL

- [x] **Security Tests**: Verify 401/403 for unauthorized access (manual).
- [x] **Integration Tests**: Verify pagination and filtering on new endpoints (manual).
- [x] **E2E**: Manual verify dashboard flows against local Gabi instance.
- [ ] **Automated Tests**: Unit tests for security middleware (pending).
- [ ] Integration tests automatizados para /sources/{id}/links (pagination, filters)

---

# 🚀 NEXT SPRINT: Pipeline Completo (Zero Kelvin → Hash → Crawler)

## 🎯 Objective
Implement the complete ingestion pipeline from Zero Kelvin through document hashing and crawler support.

## 🏗️ CAMINHO C: Arquitetura Primeiro (Foundation)

### C1: Gabi.Jobs Module Extraction
- [ ] Create new project `src/Gabi.Jobs/Gabi.Jobs.csproj`
- [ ] Extract job-related code from `Gabi.Sync`
- [ ] Define clear interfaces: `IJobFactory`, `IJobCreator`, `IJobStateMachine`
- [ ] Move `IngestJob` contracts to appropriate location

### C2: Job Hierarchy Implementation
- [ ] Implement `JobFactory` (central job creation)
- [ ] Implement `SourceJobCreator` (creates parent job for source)
- [ ] Implement `DocumentJobCreator` (creates child jobs per document)
- [ ] Support job parent-child relationships in database
- [ ] Add `ParentJobId` field to `IngestJobEntity`

### C3: Job State Machine
- [ ] Define all job states: `pending`, `running`, `completed`, `failed`, `skipped`, `retrying`
- [ ] Implement state transitions with validation
- [ ] Add events: `OnJobStarted`, `OnJobCompleted`, `OnJobFailed`
- [ ] Ensure idempotency (same job can't run twice simultaneously)

### C4: Specialized Workers
- [ ] Create `DiscoveryWorker` (handles discover jobs)
- [ ] Create `FetchWorker` (handles fetch jobs)
- [ ] Create `HashWorker` (handles hash/deduplication jobs)
- [ ] Create `ParseWorker` (handles parse jobs)
- [ ] Worker routing based on `JobType`

### C5: Gabi.Pipeline Orchestrator
- [ ] Create new project `src/Gabi.Pipeline/Gabi.Pipeline.csproj`
- [ ] Extract `PipelineOrchestrator` from `Gabi.Sync/Pipeline/PipelineOrchestrator.cs`
- [ ] Support phase configuration from sources.yaml
- [ ] Implement phase ordering: discover → fetch → hash → parse → chunk → embed → index

### C6: Resilience Patterns
- [ ] Implement Circuit Breaker (prevent cascade failures)
- [ ] Add exponential backoff for retries
- [ ] Implement Dead Letter Queue (DLQ) for permanent failures
- [ ] Add health checks for each phase

### C7: PhaseCoordinator + Resilience + Schema
- [ ] Implement PhaseCoordinator
- [ ] Circuit Breaker e Retry Policy
- [ ] Migration AddJobHierarchy (ParentJobId, DocumentId, ContentHash, IsDuplicate)
- [ ] **NOVO**: Migration AddSoftDelete (ExternalId, RemovedFromSourceAt, RemovedReason)
- [ ] Índice único: `(SourceId, ExternalId)`
- [ ] Índice: `idx_documents_removed`

---

## 📦 CAMINHO A: Fontes Estruturadas (CSV)

### A1: Gabi.Fetch Module
- [ ] Create new project `src/Gabi.Fetch/Gabi.Fetch.csproj`
- [ ] Implement `IContentFetcher` interface
- [ ] Add HTTP client with streaming support
- [ ] Implement retry policy for network failures

### A2: Document Counter
- [ ] Implement `IDocumentCounter` interface
- [ ] CSV row counting without loading entire file
- [ ] Support for large files (500MB+)
- [ ] Progress reporting during counting

### A3: Metadata Extractor
- [ ] Implement `IMetadataExtractor`
- [ ] Extract: title, date, url, external identifier
- [ ] Support different metadata sources (HTTP headers, CSV columns, filename)
- [ ] Normalize dates to ISO format

### A4: Gabi.Hash Module
- [ ] Create new project `src/Gabi.Hash/Gabi.Hash.csproj`
- [ ] Implement `IContentHasher` with SHA-256
- [ ] Content normalization (whitespace, encoding)
- [ ] Fallback hash for empty/short content (URL + date + title)

### A5: Deduplication Service
- [ ] Implement `IDeduplicationService`
- [ ] Check hash existence in database
- [ ] Handle duplicate detection across sources
- [ ] Store duplicate references

### A6: CSV Streaming Strategy
- [ ] Implement `CsvFetchStrategy` with streaming
- [ ] Support configurable delimiter, encoding, quotes
- [ ] Handle malformed CSV gracefully
- [ ] Progress reporting per row

### A7: Parser Expansion
- [ ] Expand `Gabi.Ingest.Parser`
- [ ] Implement streaming CSV parser
- [ ] Add field transformers (strip_quotes, parse_int, parse_date)
- [ ] Support field validation rules

### A8: Pipeline Integration
- [ ] Wire fetch → hash → parse in orchestrator
- [ ] Configure for CSV sources (tcu_acordaos, tcu_normas, etc.)
- [ ] Test with tcu_sumulas (smallest file)

### A9: Reconcile Service (Snapshot + Diff + Reconcile)
- [ ] Implementar `IReconcileService`
- [ ] Snapshot: obter lista atual da fonte
- [ ] Diff: comparar com estado na base
- [ ] Reconcile:
  - [ ] INSERT: documentos novos
  - [ ] UPDATE: documentos alterados (hash mudou)
  - [ ] SOFT DELETE: documentos removidos da fonte
- [ ] Métricas: added/updated/removed/unchanged

---

## 🕷️ CAMINHO B: Fontes Não-Estruturadas (Crawler)

### B1: Gabi.Crawler Module
- [ ] Create new project `src/Gabi.Crawler/Gabi.Crawler.csproj`
- [ ] Implement base `WebCrawler` class
- [ ] Add HTTP client with cookie support
- [ ] Implement crawling queue (breadth-first)

### B2: Link Extraction
- [ ] Implement `ILinkExtractor`
- [ ] CSS selector support (use AngleSharp or similar)
- [ ] Extract links from HTML anchor tags
- [ ] Filter by patterns (include/exclude)

### B3: PDF Downloader
- [ ] Implement `IPdfDownloader`
- [ ] Download PDFs from discovered URLs
- [ ] Basic PDF parsing (title, text extraction)
- [ ] Store PDFs temporarily for processing

### B4: Politeness Policy
- [ ] Implement `IPolitenessPolicy`
- [ ] Respect robots.txt
- [ ] Configurable rate limiting (requests per second)
- [ ] Add crawl delays between requests
- [ ] User-Agent rotation

### B5: TCU Publications Crawler
- [ ] Implement `TcuPublicationsCrawler`
- [ ] Target: tcu_publicacoes (web_crawl strategy)
- [ ] Navigate pagination
- [ ] Extract PDF links
- [ ] Download and queue for processing

### B6: TCU Technical Notes Crawler
- [ ] Implement `TcuTechnicalNotesCrawler`
- [ ] Target: tcu_notas_tecnicas_ti (web_crawl strategy)
- [ ] Adapt to SEFTI site structure
- [ ] Extract specific metadata

### B7: Câmara API Adapter
- [ ] Implement `CamaraApiAdapter`
- [ ] Target: camara_leis_ordinarias (api_pagination)
- [ ] Handle API pagination
- [ ] Transform API responses to internal format
- [ ] Rate limiting for API calls

### B8: DiscoveryEngine Expansion
- [ ] Implement `WebCrawlStrategy` in DiscoveryEngine
- [ ] Implement `ApiPaginationStrategy` in DiscoveryEngine
- [ ] Integrate with Gabi.Crawler
- [ ] Support recursive link discovery
- [ ] Store discovered assets (PDFs) as links

---

## 🔌 INTEGRATION & TESTING

### I1: API Endpoints
- [ ] `POST /api/v1/pipeline/run` - Start pipeline for source
- [ ] `GET /api/v1/pipeline/status/{jobId}` - Get pipeline status
- [ ] `POST /api/v1/pipeline/cancel/{jobId}` - Cancel running pipeline
- [ ] `GET /api/v1/sources/{id}/documents` - List documents for source
- [ ] `GET /api/v1/documents/{id}/hash` - Get document fingerprint

### I2: Zero Kelvin Testing
- [ ] Test full pipeline from zero for tcu_sumulas (smallest)
- [ ] Test full pipeline from zero for tcu_acordaos (largest)
- [ ] Verify idempotency (run twice, same result)
- [ ] Measure throughput (docs/second)
- [ ] Document any manual steps needed

---

## 📊 Success Criteria

| Metric | Target |
|--------|--------|
| Jobs created per source | N (document count) |
| Hash collisions | < 0.01% |
| Duplicate detection rate | > 99% |
| Crawler success rate | > 95% |
| Pipeline end-to-end time | < 24h for full load |
| Zero Kelvin reproducibility | 100% |

---

## 🗓️ Timeline (4 Sprints)

| Sprint | Focus | Agents | Duration |
|--------|-------|--------|----------|
| 1 | Caminho C: Arquitetura | 7 | 1 week |
| 2 | Caminho A: Estruturadas | 8 | 1 week |
| 3 | Caminho B: Crawler | 8 | 1 week |
| 4 | Integration & Testing | 2 | 3 days |

**Nota**: PipelineOrchestrator já existe em `Gabi.Sync/Pipeline/PipelineOrchestrator.cs` e será extraído

**Total: 24 Agents, ~3.5 weeks**

---

## 📚 Documentation

- Update `roadmap.md` with completed phases
- Update `README.md` with new endpoints
- Create `docs/pipeline/ARCHITECTURE.md`
- Create `docs/pipeline/CRAWLER.md`
