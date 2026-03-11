# Requirements: GABI v1.1 User Auth

**Defined:** 2026-03-09
**Core Value:** Users can find any published legal act in the DOU quickly and read it in a clean, professional interface

## v1.1 Requirements

Requirements for v1.1 release. Public-facing email+password authentication.

### Schema

- [x] **SCHEMA-01**: auth.user table extended with password_hash, email_verified, login_method columns
- [x] **SCHEMA-02**: Unique index on auth.user(email) WHERE email IS NOT NULL
- [x] **SCHEMA-03**: auth.login_attempt table tracks email, ip_address, success, attempted_at

### Auth Endpoints

- [x] **AUTH-01**: POST /api/auth/register creates user with email+password, assigns 'user' role, creates session
- [x] **AUTH-02**: POST /api/auth/login authenticates by email+password (case-insensitive), creates session cookie
- [x] **AUTH-03**: POST /api/auth/logout clears session cookie
- [x] **AUTH-04**: GET /api/auth/me returns current user info (works for both password and token sessions)

### Security

- [x] **SEC-01**: Passwords hashed with bcrypt cost factor 12 via passlib (application layer, not pgcrypto)
- [x] **SEC-02**: Brute-force protection: >5 failed attempts per email in 15 min blocks login (429)
- [x] **SEC-03**: Brute-force protection: >20 failed attempts per IP in 15 min blocks login (429)
- [x] **SEC-04**: Generic error responses ("Credenciais invalidas") — never reveal if email exists
- [x] **SEC-05**: Rate limit /api/auth/register at 10/hour per IP
- [x] **SEC-06**: Rate limit /api/auth/login at 20/hour per IP
- [x] **SEC-07**: Login attempt logging (email, IP, success, timestamp) in auth.login_attempt

### Frontend

- [x] **UI-01**: Login page with email+password as primary, "chave de acesso" as secondary link
- [x] **UI-02**: Register page with name, email, password fields
- [x] **UI-03**: Mobile-first inputs (font >= 16px, autocomplete attributes)
- [x] **UI-04**: Show/hide password toggle, inline error display, loading state on buttons
- [x] **UI-05**: Redirect to home after successful login/register

### Coexistence

- [x] **COEX-01**: Token login (POST /api/auth/session) continues working unchanged
- [x] **COEX-02**: Bearer token auth in middleware continues working unchanged
- [x] **COEX-03**: Session cookie is agnostic — same cookie regardless of login method

## v2 Requirements

Deferred to future release.

### Auth Enhancements

- **AUTHV2-01**: Email verification flow (send link, verify, block unverified)
- **AUTHV2-02**: Password reset via email
- **AUTHV2-03**: OAuth / social login (Google, gov.br)
- **AUTHV2-04**: 2FA / MFA
- **AUTHV2-05**: Password strength meter
- **AUTHV2-06**: Have I Been Pwned integration

## Out of Scope

| Feature | Reason |
|---------|--------|
| Email verification (blocking) | Field exists but doesn't block — future prompt |
| OAuth / social login | Complexity; email+password sufficient for v1.1 |
| Password reset by email | Future prompt |
| 2FA / MFA | Future prompt |
| In-browser document editor | Read-only platform |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SCHEMA-01 | Phase 14 | Complete |
| SCHEMA-02 | Phase 14 | Complete |
| SCHEMA-03 | Phase 14 | Complete |
| AUTH-01 | Phase 14 | Complete |
| AUTH-02 | Phase 14 | Complete |
| AUTH-03 | Phase 14 | Complete |
| AUTH-04 | Phase 14 | Complete |
| SEC-01 | Phase 14 | Complete |
| SEC-02 | Phase 14 | Complete |
| SEC-03 | Phase 14 | Complete |
| SEC-04 | Phase 14 | Complete |
| SEC-05 | Phase 14 | Complete |
| SEC-06 | Phase 14 | Complete |
| SEC-07 | Phase 14 | Complete |
| UI-01 | Phase 14 | Complete |
| UI-02 | Phase 14 | Complete |
| UI-03 | Phase 14 | Complete |
| UI-04 | Phase 14 | Complete |
| UI-05 | Phase 14 | Complete |
| COEX-01 | Phase 14 | Complete |
| COEX-02 | Phase 14 | Complete |
| COEX-03 | Phase 14 | Complete |

**Coverage:**
- v1.1 requirements: 22 total
- Mapped to phases: 22
- Unmapped: 0

## Phase 16: Teardown & Industrial Dashboard

### Fly.io Teardown

- [ ] **TEAR-01**: All gabi-dou-* Fly apps destroyed (frontend, web, worker, es, redis, pg)
- [ ] **TEAR-02**: Secrets saved locally before destruction
- [ ] **TEAR-03**: fly apps list returns no gabi-dou results

### Local Development

- [x] **LOCAL-01**: Docker-based local stack: ES (9200), PG (5432), Worker (8081), Web (8080), Frontend (5173)
- [x] **LOCAL-02**: No Redis dependency — in-memory fallback for single-machine dev

### Pipeline Simplification

- [x] **PIPE-01**: Embedding stage bypassed/disabled — search works with BM25+ES only
- [x] **PIPE-02**: Pipeline stages reduced to: Discovery → Download → Extract → BM25 Index → Verify

### Industrial Dashboard

- [ ] **DASH-01**: GET /registry/plant-status returns all stage data (state, queue_depth, throughput, errors, cost)
- [ ] **DASH-02**: POST /pipeline/stage/{name}/pause|resume|trigger controls individual stages
- [ ] **DASH-03**: SCADA-style dashboard with left-to-right pipeline flow layout
- [ ] **DASH-04**: Stage visual states: AUTO (green), PAUSED (yellow), ERROR (red), IDLE (gray)
- [ ] **DASH-05**: Responsive layout: horizontal (desktop), 2-row (tablet), vertical (mobile)
- [ ] **DASH-06**: Storage tanks display (ES index %, disk usage %, system health)

---
*Requirements defined: 2026-03-09*
*Last updated: 2026-03-10 after Phase 16 PRD definition*
