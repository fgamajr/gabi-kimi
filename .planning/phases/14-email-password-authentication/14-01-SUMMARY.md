---
phase: 14-email-password-authentication
plan: 01
subsystem: auth
tags: [bcrypt, passlib, fastapi, password-auth, brute-force, rate-limiting, session-cookie]

requires:
  - phase: none
    provides: existing token auth and session infrastructure
provides:
  - "POST /api/auth/register — email+password user creation with 201 + session cookie"
  - "POST /api/auth/login — email+password authentication with brute-force protection"
  - "POST /api/auth/logout — session cookie clearance"
  - "GET /api/auth/me — unified user info for both password and token sessions"
  - "resolve_identity_for_user_id — fallback session resolution for password users"
  - "auth.login_attempt table for brute-force tracking"
affects: [frontend-auth-forms, email-verification, password-reset]

tech-stack:
  added: [passlib, bcrypt, email-validator]
  patterns: [bcrypt-cost-12, timing-equalization-on-failed-lookup, brute-force-per-email-and-ip]

key-files:
  created: [tests/test_auth_password.py]
  modified: [src/backend/dbsync/auth_schema.sql, src/backend/apps/auth.py, src/backend/apps/identity_store.py, src/backend/apps/web_server.py, requirements.txt]

key-decisions:
  - "Pinned bcrypt<5.0 for passlib compatibility (bcrypt 5.0 broke password length handling)"
  - "Password users store user UUID as session sub, resolved via resolve_identity_for_user_id fallback"
  - "Brute-force: 5 failed/15min per email, 20 failed/15min per IP (in DB, not Redis)"
  - "Rate limiting: register 10/hr/IP, login 20/hr/IP (via existing RateLimiter)"
  - "Generic 401 message for all auth failures (never reveals email existence)"

patterns-established:
  - "Timing equalization: always run verify_password against DUMMY_HASH on missing email"
  - "Password user session coexistence: same cookie mechanism, different identity resolution path"
  - "DB-based brute-force check before password verification"

requirements-completed: [SCHEMA-01, SCHEMA-02, SCHEMA-03, AUTH-01, AUTH-02, AUTH-03, AUTH-04, SEC-01, SEC-02, SEC-03, SEC-04, SEC-05, SEC-06, SEC-07, COEX-01, COEX-02, COEX-03]

duration: 4min
completed: 2026-03-09
---

# Phase 14 Plan 01: Backend Email+Password Auth Summary

**Bcrypt password auth with register/login/logout/me endpoints, brute-force protection, and session coexistence with existing token auth**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-09T23:10:45Z
- **Completed:** 2026-03-09T23:14:46Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- Four new auth endpoints (register, login, logout, me) with full Pydantic validation
- Bcrypt password hashing (cost 12) via passlib with timing equalization on failed lookups
- Brute-force protection: 5 attempts/15min per email, 20 attempts/15min per IP
- Session cookie resolution fallback for password users (resolve_identity_for_user_id)
- All existing token auth endpoints and bearer middleware untouched

## Task Commits

Each task was committed atomically:

1. **Task 1: Schema migration + password hashing + identity store functions**
   - `84e9ad2` (test) — failing tests for password auth functions (TDD RED)
   - `2586949` (feat) — schema migration, password hashing, identity store functions (TDD GREEN)
2. **Task 2: Register, login, logout, me endpoints with rate limiting** - `918416c` (feat)

## Files Created/Modified
- `src/backend/dbsync/auth_schema.sql` - Added password_hash, email_verified, login_method columns; login_attempt table; email unique index
- `src/backend/apps/auth.py` - Added hash_password, verify_password, DUMMY_HASH; resolve_identity_for_user_id fallback in session resolution
- `src/backend/apps/identity_store.py` - Added create_password_user, find_user_by_email, log_login_attempt, check_brute_force, resolve_identity_for_user_id
- `src/backend/apps/web_server.py` - Added register, login, logout, me endpoints with rate limiting and Pydantic models
- `requirements.txt` - Added passlib[bcrypt], bcrypt<5.0, email-validator
- `tests/test_auth_password.py` - 11 tests covering pure functions and import signatures

## Decisions Made
- Pinned bcrypt<5.0 for passlib compatibility (bcrypt 5.0 changed password length handling behavior)
- Used DB-based brute-force tracking (auth.login_attempt table) rather than Redis
- Password users reuse the same session cookie mechanism; identity resolved via user UUID fallback

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Pinned bcrypt<5.0 for passlib compatibility**
- **Found during:** Task 1 (TDD GREEN phase)
- **Issue:** bcrypt 5.0 raises ValueError on password verification due to changed length handling
- **Fix:** Pinned bcrypt>=4.0,<5.0 in requirements.txt; downgraded from 5.0.0 to 4.0.1
- **Files modified:** requirements.txt
- **Verification:** All 11 tests pass with bcrypt 4.0.1
- **Committed in:** 2586949 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Essential fix for bcrypt/passlib compatibility. No scope creep.

## Issues Encountered
None beyond the bcrypt version pinning noted above.

## User Setup Required
None - no external service configuration required. Schema DDL will be applied automatically via ensure_identity_schema on startup.

## Next Phase Readiness
- Backend auth endpoints ready for frontend integration (plan 14-02)
- Email verification and password reset can be added incrementally
- Schema migration will auto-apply on next backend startup

---
*Phase: 14-email-password-authentication*
*Completed: 2026-03-09*
