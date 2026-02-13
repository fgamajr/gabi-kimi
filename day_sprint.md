# Dashboard Integration & Security Hardening Sprint

## 🎯 Objective
Integrate the `user-first-view` React dashboard with the Gabi API, implementing a granular "Source -> Link" data model and a robust security layer.

## 🏗 Phase 1: Architecture & Contracts (Granularity)
Align the API with the dashboard's needs, focusing on the new "Per-Link" granularity and honest pipeline status.

### 1.1 New DTOs & Models
- [ ] Create `SourceDetailsResponse` (Start with `SourceDetailDto`)
- [ ] Enhance `DiscoveredLinkDto` with:
  - `Status` (pending, processed, error)
  - `DocumentCount` (from metadata)
  - `PipelineStatus` (object with status per stage)
- [ ] Create `LinkIngestStatsDto` for detailed link limits/stats.

### 1.2 Granular Endpoints
Implement paginated, filterable endpoints to support the "Source Details" view.
- [ ] `GET /api/v1/sources/{id}/links`
  - Query Params: `page`, `pageSize`, `status`, `sort`
- [ ] `GET /api/v1/sources/{id}/links/{linkId}`
- [ ] `GET /api/v1/sources/{id}` (Enhanced details)

### 1.3 Pipeline Reality Check
- [ ] Update `SourceCatalogService` to return `planned` status for `ingest`, `indexing`, `embedding` stages.
- [ ] Ensure `harvest` (discovery) reflects real-time status.

## 🔐 Phase 2: Security Hardening (Zero Trust)
Implement a production-grade security layer before exposing the API to the refined dashboard.

### 2.1 Authentication & Authorization
- [ ] **JWT Bearer Auth**:
  - Add `Microsoft.AspNetCore.Authentication.JwtBearer`
  - Configure Token Validation (Issuer, Audience, Lifetime)
  - Add `Login` endpoint (Mock/Simple for MVP or Identity if preferred)
- [ ] **RBAC Policies**:
  - Define Roles: `Admin`, `Operator`, `Viewer`
  - Apply `[Authorize(Policy = "...")]` to endpoints.

### 2.2 Middleware Hardening
- [ ] **Global Exception Handler**: Standardize error responses, hide stack traces.
- [ ] **Rate Limiting**:
  - 100 req/min for Read
  - 10 req/min for Write
- [ ] **CORS**: Restrict to dashboard origin only.
- [ ] **Security Headers**: HSTS, X-Content-Type-Options, etc.
- [ ] **Request Limits**: Set body size limits (e.g., 1MB).

## 🧩 Phase 3: Dashboard Integration (Frontend)
Adapt the `user-first-view` codebase to consume the Gabi API.

### 3.1 API Client Adaptation
- [ ] Update `api.ts` to use the new endpoints.
- [ ] Implement JWT token handling (interceptor for Bearer token).

### 3.2 Component Updates
- [ ] **Source Cards**: Link to new "Source Details" page.
- [ ] **Source Details Page**:
  - Implement `LinksTable` (Server-side pagination).
  - Show per-link status.
- [ ] **Pipeline Visualization**: Handle "planned" stages gracefully (greyed out or labeled).

## 🧪 Phase 4: Verification
- [ ] **Security Tests**: Verify 401/403 for unauthorized access.
- [ ] **Integration Tests**: Verify pagination and filtering on new endpoints.
- [ ] **E2E**: Manual verify dashboard flows against local Gabi instance.
