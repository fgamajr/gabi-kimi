# GABI Project - Handover Document & Action Plan

**Generated**: 2026-02-15
**Project**: GABI - TCU Legal Document Ingestion Pipeline
**Stack**: .NET 8 / PostgreSQL 15 / Elasticsearch 8 / Redis 7 / Hangfire / Docker

---

## Executive Summary

GABI is a data ingestion pipeline for TCU (Tribunal de Contas da União) legal documents. The system implements a 6-stage pipeline: **Seed → Discovery → Fetch → Parse → Chunk → Embed → Index**.

**Current Reality**: 
- ✅ Infrastructure works (Docker, Postgres, Redis, ES)
- ✅ Seed + Discovery phases functional for some sources
- ✅ Hangfire queue operational (PostgreSQL-backed)
- ✅ Hangfire dashboard at `/hangfire` with auth filter
- ✅ Serilog in API (JSON format)
- ✅ Tests exist (6 projects, 42+ files)
- ❌ **No Serilog in Worker** (critical observability gap)
- ❌ **No CI/CD** (manual deployment only)
- ❌ **No dead letter queue** (failed jobs silently lost)
- ❌ **Fetch/Ingest are stubs** (no actual content download/processing)
- ⚠️ **Discovery validation incomplete** (only tcu_sumulas tested)
- ⚠️ **Retry duplication** (Hangfire 3 × Polly 3 = 12 attempts)

---

## 1. CURRENT STATE

### 1.1 What's Working ✅

| Component | Status | Evidence |
|-----------|--------|----------|
| PostgreSQL + Migrations | ✅ | 13 sources registered, all tables created |
| Redis | ✅ | In compose, port 6380 (not used by Hangfire) |
| Elasticsearch | ✅ | Healthy, awaiting indexing |
| API (port 5100) | ✅ | Health, Swagger, Auth, Dashboard endpoints |
| Worker (Hangfire) | ✅ | Processing jobs from PostgreSQL-backed queues |
| Hangfire Dashboard | ✅ | `/hangfire` endpoint with `HangfireDashboardAuthFilter` |
| Serilog in API | ✅ | `UseSerilog()` + `CompactJsonFormatter` |
| Seed phase | ✅ | `catalog_seed` loads sources_v2.yaml → PostgreSQL |
| Discovery (partial) | ✅ | StaticUrl + UrlPattern work |
| Unit tests | ✅ | 6 projects with 42+ files exist |
| Zero Kelvin test | ✅ | 14/14 checks pass (tcu_sumulas only) |

### 1.2 What's Partially Working ⚠️

| Component | Issue |
|-----------|-------|
| Discovery for tcu_acordaos | Should produce ~35 links, NOT VALIDATED |
| Discovery for other sources | 11 sources NOT VALIDATED |
| WebCrawl strategy | Returns 0 links (not implemented) |
| ApiPagination strategy | Returns 0 links (not implemented) |
| 0-links "success" | Discovery logs success even with 0 links (silent failure) |
| Retry logic | Hangfire 3 × Polly 3 = 12 total attempts (should consolidate) |

### 1.3 What's NOT Working ❌

| Component | Gap |
|-----------|-----|
| Serilog in Worker | Zero structured logging in most critical process |
| CI/CD Pipeline | No `.github/workflows/` directory |
| Dead Letter Queue | No DLQ table or logic |
| Fetch Executor | Stub - creates documents without content |
| Ingest Executor | Stub - marks complete without processing |

### 1.4 Architecture Clarifications

| Topic | Previous Assumption | Actual Truth (Code Verified) |
|-------|---------------------|------------------------------|
| Hangfire Dashboard | "Not exposed" | ✅ Exposed at `/hangfire` with auth |
| Hangfire Storage | "Redis-backed" | ❌ PostgreSQL via `Hangfire.PostgreSql` |
| Unit Tests | "Zero tests" | ❌ 6 test projects exist (42+ files) |
| Retry Count | "Default 10" | ❌ Already `Attempts = 3` |
| Redis Port | Not mentioned | 6380 externally, 6379 inside Docker |

---

## 2. PROBLEM ANALYSIS & SOLUTION PLAN

### Problem 1: No Serilog in Worker 📝

**Impact**: Worker is the most critical process (runs all jobs) but has no structured logging. Cannot debug production issues.

**Current State**:
- API: `UseSerilog()` + `CompactJsonFormatter` ✅
- Worker: Only `ILogger` with plain console ❌

**Solution**:
```
┌─────────────────────────────────────────────────────────────┐
│ Task                              │ Effort │ Priority      │
├───────────────────────────────────┼────────┼───────────────┤
│ Copy Serilog pattern from API     │ 1h     │ P0 - Sprint 1 │
│ Add JSON console output           │ 0.5h   │ P0 - Sprint 1 │
│ Add correlation IDs per job       │ 1h     │ P1 - Sprint 6 │
└─────────────────────────────────────────────────────────────┘
```

**Verification**: Run Worker → check logs show JSON format with `JobId`, `SourceId` fields.

---

### Problem 2: Retry Strategy Duplication 🔄

**Impact**: Failing jobs retry up to 12 times (3 Hangfire × 3 Polly + initial). Hard to track actual failure rate.

**Current State**:
- `GabiJobRunner`: `[AutomaticRetry(Attempts = 3)]`
- `SourceDiscoveryJobExecutor`: Polly `ResiliencePipeline` with retries

**Solution**:
```
┌─────────────────────────────────────────────────────────────┐
│ Task                              │ Effort │ Priority      │
├───────────────────────────────────┼────────┼───────────────┤
│ Remove Polly retries OR Hangfire  │ 1h     │ P0 - Sprint 1 │
│ Keep Hangfire only (simpler)      │        │               │
└─────────────────────────────────────────────────────────────┘
```

**Recommendation**: Keep Hangfire retry (simpler, observable in dashboard). Remove Polly from discovery executor.

---

### Problem 3: 0-Links Silent Success ⚠️

**Impact**: WebCrawl/ApiPagination return 0 links but log as "success". Masks implementation gaps.

**Solution**:
```
┌─────────────────────────────────────────────────────────────┐
│ Task                              │ Effort │ Priority      │
├───────────────────────────────────┼────────┼───────────────┤
│ Add warning log when LinksTotal=0 │ 0.5h   │ P0 - Sprint 1 │
│ Add flag in discovery_runs table  │ 0.5h   │ P0 - Sprint 1 │
└─────────────────────────────────────────────────────────────┘
```

---

### Problem 4: Discovery Validation Gap 📊

**Impact**: Cannot trust discovery results for most sources.

**Expected vs Actual**:
```
Source                    │ Expected │ Validated │ Status
──────────────────────────┼──────────┼───────────┼─────────
tcu_acordaos (url_pattern)│ ~35      │ ❌        │ NEEDS TEST
tcu_sumulas (static_url)  │ 1        │ ✅        │ PASS
tcu_normas (static_url)   │ 1        │ ❌        │ NEEDS TEST
Other 10 sources          │ 1 each   │ ❌        │ NEEDS TEST
WebCrawl sources (3)      │ many     │ ❌        │ NOT IMPLEMENTED
```

**Solution**:
```
┌─────────────────────────────────────────────────────────────┐
│ Task                              │ Effort │ Priority      │
├───────────────────────────────────┼────────┼───────────────┤
│ Run discovery for ALL 13 sources  │ 1h     │ P0 - Sprint 1 │
│ Validate link counts in DB        │ 1h     │ P0 - Sprint 1 │
│ Update Zero Kelvin test           │ 2h     │ P0 - Sprint 1 │
│ Implement WebCrawl strategy       │ 8h     │ P2 - Sprint 6 │
│ Implement ApiPagination           │ 4h     │ P2 - Sprint 6 │
└─────────────────────────────────────────────────────────────┘
```

---

### Problem 5: No Dead Letter Queue ⚰️

**Impact**: Failed jobs silently lost after max retries, no alerting, no recovery mechanism.

**Solution**:
```
┌─────────────────────────────────────────────────────────────┐
│ Task                              │ Effort │ Priority      │
├───────────────────────────────────┼────────┼───────────────┤
│ Create DlqEntry entity            │ 2h     │ P1 - Sprint 2 │
│ Add migration                     │ 1h     │ P1 - Sprint 2 │
│ Implement Hangfire failure filter │ 2h     │ P1 - Sprint 2 │
│ Add DLQ API endpoints             │ 2h     │ P1 - Sprint 2 │
│ Add alerting (optional)           │ 2h     │ P2 - Later    │
└─────────────────────────────────────────────────────────────┘
```

**DLQ Table Schema**:
```sql
CREATE TABLE dlq_entries (
    id UUID PRIMARY KEY,
    job_type TEXT NOT NULL,
    source_id TEXT,
    payload JSONB,
    error_message TEXT,
    failed_at TIMESTAMPTZ NOT NULL,
    retry_count INT NOT NULL
);
```

---

### Problem 6: Fetch is a Stub 📥

**Current Behavior**: `FetchJobExecutor` creates `DocumentEntity` with `Title = item.Url` (no content downloaded).

**Solution**:
```
┌─────────────────────────────────────────────────────────────┐
│ Task                              │ Effort │ Priority      │
├───────────────────────────────────┼────────┼───────────────┤
│ HTTP streaming download           │ 4h     │ P1 - Sprint 3 │
│ ETag/Last-Modified support        │ 2h     │ P1 - Sprint 3 │
│ CSV streaming parser              │ 6h     │ P1 - Sprint 3 │
│ File storage (local, then S3)     │ 4h     │ P1 - Sprint 3 │
│ Rate limiting per source          │ 2h     │ P1 - Sprint 3 │
│ Wire into FetchJobExecutor        │ 3h     │ P1 - Sprint 3 │
└─────────────────────────────────────────────────────────────┘
```

**Memory Constraint**: 300MB budget - MUST use streaming:
```csharp
// ❌ BAD
var content = await httpClient.GetStringAsync(url);

// ✅ GOOD
using var response = await httpClient.GetAsync(url, HttpCompletionOption.ResponseHeadersRead);
using var stream = await response.Content.ReadAsStreamAsync();
await stream.CopyToAsync(fileStream);
```

**Verification**: 
- Fetch `tcu_sumulas` (1 CSV, ~1MB) → verify file downloaded
- Fetch `tcu_normas` (587MB) → verify no OOM, streams to disk

---

### Problem 7: Ingest is a Stub 🔄

**Current Behavior**: `IngestJobExecutor` marks documents "completed" without processing.

**Solution**:
```
┌─────────────────────────────────────────────────────────────┐
│ Task                              │ Effort │ Priority      │
├───────────────────────────────────┼────────┼───────────────┤
│ CSV row → document parser         │ 4h     │ P1 - Sprint 4 │
│ Content normalization             │ 3h     │ P1 - Sprint 4 │
│ SHA-256 hashing + dedup           │ 3h     │ P1 - Sprint 4 │
│ Elasticsearch bulk indexing       │ 4h     │ P1 - Sprint 4 │
│ Wire into IngestJobExecutor       │ 3h     │ P1 - Sprint 4 │
│ Chunking for embeddings           │ 6h     │ P3 - Future   │
└─────────────────────────────────────────────────────────────┘
```

**Verification**:
- Run full pipeline for `tcu_sumulas`
- Verify `documents` table has real `Content`
- Verify ES index populated
- Run second time → verify 0 new docs (dedup works)

---

### Problem 8: No CI/CD Pipeline 🚀

**Impact**: High deployment risk, no automated testing, slow release cycle.

**Solution**:
```
┌─────────────────────────────────────────────────────────────┐
│ Task                              │ Effort │ Priority      │
├───────────────────────────────────┼────────┼───────────────┤
│ Create .github/workflows/ci.yml   │ 2h     │ P1 - Sprint 5 │
│ Add build + test on PR            │ 1h     │ P1 - Sprint 5 │
│ Add Zero Kelvin to CI             │ 2h     │ P1 - Sprint 5 │
│ Create deploy.yml for Fly.io      │ 3h     │ P1 - Sprint 5 │
│ Audit existing tests              │ 4h     │ P1 - Sprint 5 │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. SPRINT-BASED ACTION PLAN

### Sprint 1: Foundation Fixes (Day 1) — 🔴 P0

| # | Task | Effort | File |
|---|------|--------|------|
| 1.1 | Add Serilog to Worker | 1h | `src/Gabi.Worker/Program.cs`, `Gabi.Worker.csproj` |
| 1.2 | Consolidate retry strategy (remove Polly OR Hangfire) | 1h | `GabiJobRunner.cs`, `SourceDiscoveryJobExecutor.cs` |
| 1.3 | Warn on 0-links success | 1h | `SourceDiscoveryJobExecutor.cs` |
| 1.4 | Run discovery for all 13 sources | 1h | Manual + DB query |
| 1.5 | Validate link counts in DB | 1h | SQL query |
| 1.6 | Update Zero Kelvin for all sources | 2h | `zero-kelvin-test.sh` |

**Total**: 7h

**Verification**:
- `dotnet build` passes
- Zero Kelvin 14/14 (or updated count)
- Worker logs show JSON format
- `tcu_acordaos` = 35 links in DB

---

### Sprint 2: Dead Letter Queue (Day 2) — 🔴 P1

| # | Task | Effort | File |
|---|------|--------|------|
| 2.1 | Create `DlqEntry` entity | 1h | `Gabi.Postgres/Entities/` |
| 2.2 | Add migration | 1h | `Gabi.Postgres/Migrations/` |
| 2.3 | Hangfire failure filter | 2h | `Gabi.Worker/Jobs/DlqFilter.cs` |
| 2.4 | DLQ API endpoints | 2h | `Gabi.Api/Program.cs` |

**Total**: 6h

**Verification**:
- Force job to fail 3 times
- Check DLQ table has entry
- Replay via API → job re-executes

---

### Sprint 3: Real Fetch (Day 3-4) — 🔴 P1

| # | Task | Effort |
|---|------|--------|
| 3.1 | HTTP streaming client | 4h |
| 3.2 | ETag + Last-Modified | 2h |
| 3.3 | CSV streaming parser | 6h |
| 3.4 | Wire into FetchJobExecutor | 3h |
| 3.5 | Rate limiting per source | 2h |

**Total**: 17h

**Verification**:
- Fetch `tcu_sumulas` → document has content
- Fetch `tcu_normas` (587MB) → no OOM

---

### Sprint 4: Real Ingest (Day 5-6) — 🔴 P1

| # | Task | Effort |
|---|------|--------|
| 4.1 | CSV row → document parser | 4h |
| 4.2 | Content normalizer | 3h |
| 4.3 | SHA-256 hasher + dedup | 3h |
| 4.4 | Elasticsearch bulk indexing | 4h |
| 4.5 | Wire into IngestJobExecutor | 3h |

**Total**: 17h

**Verification**:
- Full pipeline `tcu_sumulas` → ES index populated
- Second run → 0 new docs (dedup)

---

### Sprint 5: CI/CD + Testing (Day 7) — 🟡 P1

| # | Task | Effort |
|---|------|--------|
| 5.1 | GitHub Actions CI | 3h |
| 5.2 | Deploy workflow | 3h |
| 5.3 | Audit existing tests | 4h |
| 5.4 | Expand Zero Kelvin | 2h |

**Total**: 12h

**Verification**:
- Push PR → GH Actions runs
- Tag release → Fly.io deploys

---

### Sprint 6: Discovery Strategies + Observability (Day 8-9) — 🟡 P2

| # | Task | Effort |
|---|------|--------|
| 6.1 | WebCrawlStrategy | 8h |
| 6.2 | ApiPaginationStrategy | 4h |
| 6.3 | Prometheus metrics | 6h |
| 6.4 | OpenTelemetry tracing | 6h |
| 6.5 | Grafana dashboard | 3h |

**Total**: 27h

**Verification**:
- `tcu_publicacoes` → PDF links found
- `camara_leis_ordinarias` → paginated results
- Prometheus `/metrics` responds

---

## 4. ANCHORAGE POINTS — DO NOT MISS

### 4.1 Redis Port is 6380
```yaml
# docker-compose.yml
ports:
  - "6380:6379"  # Host uses 6380, container uses 6379
```

### 4.2 Hangfire Uses PostgreSQL (NOT Redis)
```csharp
// Gabi.Worker/Program.cs
.UsePostgreSqlStorage(o => o.UseNpgsqlConnection(connectionString));
```
Redis is in compose but NOT used by Hangfire.

### 4.3 Worker Requires ASP.NET Runtime
```dockerfile
# Dockerfile (Worker) - CRITICAL
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS runtime  # NOT runtime:8.0!
```

### 4.4 Layer Dependencies (ADR-001)
```
Layer 0: Gabi.Contracts    - No dependencies
Layer 1: Gabi.Postgres     - Depends on Contracts
Layer 2: Gabi.Discover     - Depends on Contracts + Postgres
Layer 5: Gabi.Api/Worker   - Depends on all
```
**NEVER**: Lower layer → Higher layer reference

### 4.5 Hangfire Dashboard Already Exists
- URL: `/hangfire`
- Auth: `HangfireDashboardAuthFilter`
- Access: Requires operator role

### 4.6 Discovery "0 Links" is Intentional Failsafe
`SourceDiscoveryJobExecutor` treats `LinksTotal=0` as success. Prevents breaking when WebCrawl/ApiPagination not implemented. Add warning, don't change behavior yet.

### 4.7 Memory Budget: 300MB
Always use streaming for file I/O. Use `streaming-guardian` skill.

### 4.8 SHA-256 for All Hashing
`UrlHash` and `ContentHash` use SHA-256 (64-char hex string).

### 4.9 Soft Delete Only
Never `DELETE FROM documents`. Use `removed_from_source_at` timestamp.

### 4.10 sources_v2.yaml is Source of Truth
All source configuration comes from this YAML. Parse/transform configs exist but not wired.

---

## 5. KEY FILES

| File | Purpose |
|------|---------|
| `src/Gabi.Worker/Program.cs` | Worker entry — NEEDS Serilog |
| `src/Gabi.Api/Program.cs` | API entry — has Serilog ✅ |
| `src/Gabi.Worker/Jobs/GabiJobRunner.cs` | Job dispatcher — has `[AutomaticRetry(Attempts=3)]` |
| `src/Gabi.Worker/Jobs/SourceDiscoveryJobExecutor.cs` | Discovery — has Polly retry (duplicate) |
| `src/Gabi.Worker/Jobs/FetchJobExecutor.cs` | STUB — needs real implementation |
| `src/Gabi.Worker/Jobs/IngestJobExecutor.cs` | STUB — needs real implementation |
| `src/Gabi.Discover/DiscoveryEngine.cs` | Strategy dispatch |
| `sources_v2.yaml` | 13 source definitions |
| `docker-compose.yml` | Infrastructure config |
| `tests/zero-kelvin-test.sh` | E2E test script |

---

## 6. VALIDATION CHECKLIST

Before considering project "production ready":

- [ ] **Sprint 1 Complete**
  - [ ] Serilog in Worker (JSON logs)
  - [ ] Retry consolidated (one mechanism)
  - [ ] All 13 sources validated
  - [ ] Zero Kelvin tests all sources

- [ ] **Sprint 2 Complete**
  - [ ] DLQ table exists
  - [ ] Failed jobs go to DLQ
  - [ ] DLQ API works (list/replay)

- [ ] **Sprint 3-4 Complete**
  - [ ] Fetch downloads real content
  - [ ] Ingest parses CSVs
  - [ ] Elasticsearch indexing works
  - [ ] Deduplication works (SHA-256)

- [ ] **Sprint 5 Complete**
  - [ ] `.github/workflows/ci.yml` exists
  - [ ] Tests run on PR
  - [ ] Zero Kelvin in CI
  - [ ] Automated deployment to Fly.io

---

## 7. SKILLS TO USE

| Skill | When to Use |
|-------|-------------|
| `zero-kelvin` | After infrastructure changes |
| `pipeline-stage-scaffold` | Implementing Fetch/Parse/Chunk stages |
| `contract-first-dev` | Adding new code (layer validation) |
| `streaming-guardian` | Writing I/O code (memory check) |
| `ef-migration-safety` | Database schema changes |
| `brainstorming` | Before implementing new features |

---

## 8. QUICK START COMMANDS

```bash
# Start infrastructure
docker compose up -d

# Run API locally
dotnet run --project src/Gabi.Api --urls "http://localhost:5100"

# Run Worker locally
dotnet run --project src/Gabi.Worker

# Full Docker stack
docker compose --profile api --profile worker up -d

# Get auth token
TOKEN=$(curl -s -X POST http://localhost:5100/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"operator","password":"op123"}' | jq -r .token)

# Access Hangfire Dashboard
open http://localhost:5100/hangfire

# Trigger seed
curl -X POST http://localhost:5100/api/v1/dashboard/seed \
  -H "Authorization: Bearer $TOKEN"

# Trigger discovery
curl -X POST "http://localhost:5100/api/v1/dashboard/sources/tcu_acordaos/phases/discovery" \
  -H "Authorization: Bearer $TOKEN"

# Check discovered links
docker compose exec -T postgres psql -U gabi -d gabi -c \
  "SELECT \"SourceId\", COUNT(*) FROM discovered_links GROUP BY \"SourceId\";"

# Run Zero Kelvin test
./tests/zero-kelvin-test.sh
```

---

**Last Verified**: 2026-02-15
**Next Milestone**: Sprint 1 — Add Serilog to Worker + Validate All Sources
