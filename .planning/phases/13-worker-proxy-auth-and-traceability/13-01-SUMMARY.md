---
phase: 13-worker-proxy-auth-and-traceability
plan: 01
subsystem: auth
tags: [fastapi, httpx, rate-limiting, security, proxy]

# Dependency graph
requires:
  - phase: 11-fly-io-migration
    provides: Worker proxy route, require_admin_access, RateLimiter, log_security_event
provides:
  - Admin auth guard on /api/worker/* proxy route
  - Rate limiting at 60 req/min per principal
  - WORKER_PROXY_AUTH_ENABLED environment toggle
  - Proxy access logging via log_security_event
  - proxy_auth_enabled field in /healthz response
  - Phase 13 requirements section in REQUIREMENTS.md
  - Traceability audit with all entries Complete
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Conditional auth dependency: _require_proxy_auth returns None when toggle disabled"
    - "Per-principal rate limiting on proxy route (vs per-IP on public endpoints)"

key-files:
  created:
    - tests/test_proxy_auth.py
  modified:
    - src/backend/apps/web_server.py
    - .planning/REQUIREMENTS.md

key-decisions:
  - "Override _require_proxy_auth (not require_admin_access) for proxy-specific DI override"
  - "Rate limit keyed on auth.token_id (per-principal) rather than IP"
  - "Access logging always active regardless of auth toggle"

patterns-established:
  - "Conditional DI dependency pattern: return None to skip auth, AuthPrincipal to enforce"

requirements-completed: [FLY-03]

# Metrics
duration: 6min
completed: 2026-03-09
---

# Phase 13 Plan 01: Worker Proxy Auth & Traceability Summary

**Admin auth guard with 60/min rate limiting and env toggle on /api/worker/* proxy, plus REQUIREMENTS.md traceability audit closing FLY-03 gap**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-09T22:08:48Z
- **Completed:** 2026-03-09T22:14:24Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Worker proxy route now requires admin auth (Depends(_require_proxy_auth)) closing the last unprotected admin-facing endpoint
- Rate limiting at 60 req/min per principal with Retry-After header on 429
- Environment toggle WORKER_PROXY_AUTH_ENABLED (default: true) with startup WARNING when disabled
- All proxy access logged with user identity, endpoint path, method, and IP
- /healthz endpoint surfaces proxy_auth_enabled boolean for monitoring
- REQUIREMENTS.md traceability table fully audited: all 64 entries show Complete
- Phase 13 requirements section added with AUTH-01 through AUTH-05 and TRACE-01

## Task Commits

Each task was committed atomically:

1. **Task 1 (TDD RED): Failing tests** - `a797117` (test)
2. **Task 1 (TDD GREEN): Auth guard + rate limiter + toggle + logging** - `bd73a21` (feat)
3. **Task 2: REQUIREMENTS.md traceability + Phase 13 section** - `ed47b8f` (chore)

_TDD task had separate RED and GREEN commits._

## Files Created/Modified
- `tests/test_proxy_auth.py` - 7 tests: auth rejection, admin access, rate limit, logging, toggle, healthz, traceability assertion
- `src/backend/apps/web_server.py` - Auth guard, rate limiter, toggle constants, conditional auth dependency, access logging, healthz update, startup warning
- `.planning/REQUIREMENTS.md` - Phase 13 section, FLY-03 Complete, 6 new traceability entries, coverage counts updated

## Decisions Made
- Used _require_proxy_auth wrapper (not direct require_admin_access) as the Depends target, enabling conditional bypass via toggle
- Rate limiting keyed on auth.token_id (per-principal) rather than IP, since proxy is admin-only
- Access logging fires regardless of auth toggle state (always log who accessed what)
- Proxy timeout increased from 10s to 30s per context decision

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test base_url for TrustedHostMiddleware**
- **Found during:** Task 1 (TDD GREEN phase)
- **Issue:** Tests used `base_url="http://test"` which was rejected by TrustedHostMiddleware (400)
- **Fix:** Changed to `base_url="http://localhost"` which is in the allowed hosts list
- **Files modified:** tests/test_proxy_auth.py
- **Verification:** All tests pass with correct host
- **Committed in:** bd73a21

**2. [Rule 1 - Bug] Fixed dependency override target for proxy auth**
- **Found during:** Task 1 (TDD GREEN phase)
- **Issue:** Tests overrode `require_admin_access` but proxy uses `_require_proxy_auth` as the Depends target; override had no effect
- **Fix:** Changed all overrides to target `_require_proxy_auth` directly
- **Files modified:** tests/test_proxy_auth.py
- **Verification:** All 6 proxy tests pass

**3. [Rule 1 - Bug] Fixed httpx mock intercepting test ASGI transport**
- **Found during:** Task 1 (TDD GREEN phase)
- **Issue:** `@patch("httpx.AsyncClient.request")` intercepted both test transport and proxy outbound, bypassing ASGI app entirely
- **Fix:** Created `_patch_outbound_proxy()` that patches only bare `httpx.AsyncClient()` (no transport arg) while passing through ASGITransport-based clients
- **Files modified:** tests/test_proxy_auth.py
- **Verification:** All tests correctly route through ASGI app

---

**Total deviations:** 3 auto-fixed (3 bugs in test setup)
**Impact on plan:** All auto-fixes necessary for test correctness. No scope creep. Production code unchanged.

## Issues Encountered
None beyond the test mocking issues documented as deviations above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All admin-facing routes now have auth guards (proxy was the last gap)
- REQUIREMENTS.md fully audited with 64 entries all showing Complete
- No blockers or concerns

---
*Phase: 13-worker-proxy-auth-and-traceability*
*Completed: 2026-03-09*
