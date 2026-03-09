# Phase 14: Email + Password Authentication - Context

**Gathered:** 2026-03-09
**Status:** Ready for planning
**Source:** PRD Express Path (inline from user)

<domain>
## Phase Boundary

Add public-facing email+password authentication to GABI Search. Citizens and professionals can create accounts and log in without needing admin-issued Bearer tokens. Existing token auth remains unchanged.

</domain>

<decisions>
## Implementation Decisions

### Schema (Postgres)
- ALTER TABLE auth."user" ADD password_hash TEXT, email_verified BOOLEAN DEFAULT false, login_method TEXT DEFAULT 'token'
- login_method values: 'token' (legacy), 'password', 'both'
- CREATE UNIQUE INDEX idx_user_email_unique ON auth."user"(email) WHERE email IS NOT NULL
- CREATE TABLE auth.login_attempt (id SERIAL PK, email TEXT, ip_address TEXT, success BOOLEAN, attempted_at TIMESTAMPTZ DEFAULT NOW())
- Password hash: bcrypt via passlib (application layer, NOT pgcrypto), cost factor 12

### Auth Endpoints
- POST /api/auth/register: public signup (email, password, display_name) → 201 + session cookie
  - Validations: email format + unique (409), password 8-128 chars, display_name 2-100 chars
  - Creates user with login_method='password', email_verified=false, role='user'
  - Auto-creates session (same mechanism as token login)
- POST /api/auth/login: email+password → session cookie
  - Case-insensitive email lookup (LOWER(email))
  - Generic 401 "Credenciais invalidas" (never reveal if email exists)
  - Brute-force check before password verify
- POST /api/auth/logout: clear session cookie
- GET /api/auth/me: return current user info (works for both password and token sessions)
  - Returns: { id, email, display_name, roles, login_method }

### Brute-force Protection
- >5 failed attempts per email in 15 min → 429
- >20 failed attempts per IP in 15 min → 429
- Log ALL attempts (success+failure) to auth.login_attempt

### Rate Limiting
- /api/auth/register: 10/hour per IP
- /api/auth/login: 20/hour per IP

### Frontend
- Login page: email+password as PRIMARY, "Entrar com chave de acesso" as secondary link
- Register page: name, email, password fields
- Mobile-first: font >= 16px inputs, autocomplete="email" and autocomplete="current-password"
- Show/hide password toggle (eye icon)
- Inline error display (not alert())
- Loading state on submit buttons
- Redirect to home after success
- "Nao tem conta? Criar conta" link on login, "Ja tem conta? Entrar" on register

### Coexistence Rules
- Session cookie is AGNOSTIC — same httpOnly cookie for both methods
- POST /api/auth/session (token login) continues unchanged
- Bearer token middleware continues unchanged
- auth.user.id is the same entity regardless of login method
- A user can have BOTH password AND API tokens

### Security
- bcrypt cost factor 12, NEVER plaintext
- Generic error responses
- Login attempt logging
- Session: httpOnly + Secure + SameSite

### NOT implementing now (future prompts)
- Email verification (field exists, doesn't block)
- Password reset by email
- OAuth / social login
- 2FA / MFA
- Password strength meter

### Claude's Discretion
- Pydantic model naming conventions
- Test file organization
- Error message exact wording (Portuguese)
- How to structure the auth module internally

</decisions>

<specifics>
## Specific Ideas

### Files to modify
BACKEND:
- src/backend/apps/auth.py → add register, login, logout, me
- src/backend/apps/auth_schema.sql → ALTER TABLE + login_attempt table
- src/backend/apps/middleware/security.py → rate limit on new endpoints
- pyproject.toml → add passlib[bcrypt]

FRONTEND:
- src/frontend/web/src/pages/Login.tsx → redesign for email+password
- src/frontend/web/src/pages/Register.tsx → NEW page
- src/frontend/web/src/lib/authApi.ts → add register(), login(), me()
- src/frontend/web/src/routes.tsx → add /register route

DO NOT TOUCH:
- Bearer token middleware (keep intact)
- POST /api/auth/session (token login continues)
- GABI_API_TOKENS bootstrap
- Identity store bootstrap

### Acceptance Criteria (curl tests)
1. Register: POST /api/auth/register → 201 + session cookie
2. Login: POST /api/auth/login → 200 + session cookie
3. Me: GET /api/auth/me with cookie → 200 + user info
4. Token login still works: POST /api/auth/session with Bearer
5. Brute-force: 6th failed attempt → 429
6. Password stored as bcrypt hash ($2b$12$...)
7. Frontend: login shows email+password primary
8. Frontend: token login is secondary/discrete
9. Frontend: register accessible via link
10. Frontend: mobile-friendly

### Adversarial Tests
- UPPERCASE email handling (case-insensitive?)
- Email with accents (jose@example.com)
- XSS in display_name
- Password at 128 chars (max) and 129 (reject)
- Register email that already exists as token-created user (conflict or merge?)

</specifics>

<deferred>
## Deferred Ideas

- Email verification flow (send link, verify, block unverified)
- Password reset via email
- OAuth / social login (Google, gov.br)
- 2FA / MFA
- Password strength meter
- Have I Been Pwned integration

</deferred>

---

*Phase: 14-email-password-authentication*
*Context gathered: 2026-03-09 via PRD Express Path*
