# Requirements: GABI v1.1 User Auth

**Defined:** 2026-03-09
**Core Value:** Users can find any published legal act in the DOU quickly and read it in a clean, professional interface

## v1.1 Requirements

Requirements for v1.1 release. Public-facing email+password authentication.

### Schema

- [ ] **SCHEMA-01**: auth.user table extended with password_hash, email_verified, login_method columns
- [ ] **SCHEMA-02**: Unique index on auth.user(email) WHERE email IS NOT NULL
- [ ] **SCHEMA-03**: auth.login_attempt table tracks email, ip_address, success, attempted_at

### Auth Endpoints

- [ ] **AUTH-01**: POST /api/auth/register creates user with email+password, assigns 'user' role, creates session
- [ ] **AUTH-02**: POST /api/auth/login authenticates by email+password (case-insensitive), creates session cookie
- [ ] **AUTH-03**: POST /api/auth/logout clears session cookie
- [ ] **AUTH-04**: GET /api/auth/me returns current user info (works for both password and token sessions)

### Security

- [ ] **SEC-01**: Passwords hashed with bcrypt cost factor 12 via passlib (application layer, not pgcrypto)
- [ ] **SEC-02**: Brute-force protection: >5 failed attempts per email in 15 min blocks login (429)
- [ ] **SEC-03**: Brute-force protection: >20 failed attempts per IP in 15 min blocks login (429)
- [ ] **SEC-04**: Generic error responses ("Credenciais invalidas") — never reveal if email exists
- [ ] **SEC-05**: Rate limit /api/auth/register at 10/hour per IP
- [ ] **SEC-06**: Rate limit /api/auth/login at 20/hour per IP
- [ ] **SEC-07**: Login attempt logging (email, IP, success, timestamp) in auth.login_attempt

### Frontend

- [ ] **UI-01**: Login page with email+password as primary, "chave de acesso" as secondary link
- [ ] **UI-02**: Register page with name, email, password fields
- [ ] **UI-03**: Mobile-first inputs (font >= 16px, autocomplete attributes)
- [ ] **UI-04**: Show/hide password toggle, inline error display, loading state on buttons
- [ ] **UI-05**: Redirect to home after successful login/register

### Coexistence

- [ ] **COEX-01**: Token login (POST /api/auth/session) continues working unchanged
- [ ] **COEX-02**: Bearer token auth in middleware continues working unchanged
- [ ] **COEX-03**: Session cookie is agnostic — same cookie regardless of login method

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
| SCHEMA-01 | Phase 14 | Pending |
| SCHEMA-02 | Phase 14 | Pending |
| SCHEMA-03 | Phase 14 | Pending |
| AUTH-01 | Phase 14 | Pending |
| AUTH-02 | Phase 14 | Pending |
| AUTH-03 | Phase 14 | Pending |
| AUTH-04 | Phase 14 | Pending |
| SEC-01 | Phase 14 | Pending |
| SEC-02 | Phase 14 | Pending |
| SEC-03 | Phase 14 | Pending |
| SEC-04 | Phase 14 | Pending |
| SEC-05 | Phase 14 | Pending |
| SEC-06 | Phase 14 | Pending |
| SEC-07 | Phase 14 | Pending |
| UI-01 | Phase 14 | Pending |
| UI-02 | Phase 14 | Pending |
| UI-03 | Phase 14 | Pending |
| UI-04 | Phase 14 | Pending |
| UI-05 | Phase 14 | Pending |
| COEX-01 | Phase 14 | Pending |
| COEX-02 | Phase 14 | Pending |
| COEX-03 | Phase 14 | Pending |

**Coverage:**
- v1.1 requirements: 22 total
- Mapped to phases: 22
- Unmapped: 0

---
*Requirements defined: 2026-03-09*
*Last updated: 2026-03-09 after v1.1 milestone definition*
