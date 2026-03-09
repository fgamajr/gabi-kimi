# Roadmap: GABI

## Milestones

- ✅ **v1.0 GABI Admin Upload** — Phases 1-13 (shipped 2026-03-09)
- 🚧 **v1.1 User Auth** — Phase 14 (in progress)

## Phases

<details>
<summary>✅ v1.0 GABI Admin Upload (Phases 1-13) — SHIPPED 2026-03-09</summary>

- [x] Phase 1: Storage Foundation (1/1 plans) — completed 2026-03-08
- [x] Phase 2: Job Control Schema (1/1 plans) — completed 2026-03-08
- [x] Phase 3: Upload API (1/1 plans) — completed 2026-03-08
- [x] Phase 4: Worker Infrastructure (1/1 plans) — completed 2026-03-08
- [x] Phase 5: Single XML Processing (1/1 plans) — completed 2026-03-08
- [x] Phase 6: ZIP Processing (1/1 plans) — completed 2026-03-08
- [x] Phase 7: Upload UI (1/1 plans) — completed 2026-03-08
- [x] Phase 8: Job Dashboard (1/1 plans) — completed 2026-03-08
- [x] Phase 9: Live Status and Retry (1/1 plans) — completed 2026-03-08
- [x] Phase 10: Legacy Cleanup (1/1 plans) — completed 2026-03-08
- [x] Phase 11: Fly.io Migration & Dashboard (7/7 plans) — completed 2026-03-09
- [x] Phase 12: Fly.io Pre-flight (4/4 plans) — completed 2026-03-09
- [x] Phase 13: Worker Proxy Auth & Traceability (1/1 plans) — completed 2026-03-09

</details>

### 🚧 v1.1 User Auth (In Progress)

- [x] **Phase 14: Email + Password Authentication** - Public-facing email/password login and registration with brute-force protection (completed 2026-03-09)

## Phase Details

### Phase 14: Email + Password Authentication
**Goal:** Citizens and professionals can create accounts and log in with email+password while existing token auth continues working unchanged
**Depends on:** Phase 13
**Plans:** 2/2 plans complete
**Requirements**: SCHEMA-01, SCHEMA-02, SCHEMA-03, AUTH-01, AUTH-02, AUTH-03, AUTH-04, SEC-01, SEC-02, SEC-03, SEC-04, SEC-05, SEC-06, SEC-07, UI-01, UI-02, UI-03, UI-04, UI-05, COEX-01, COEX-02, COEX-03
**Success Criteria** (what must be TRUE):
  1. User can register with email+password and immediately use the app
  2. User can log in with email+password and get the same httpOnly session cookie
  3. Token login (POST /api/auth/session) continues working unchanged
  4. After 5 failed login attempts for an email, 6th attempt returns 429
  5. Frontend login page shows email+password as primary, token as secondary
  6. GET /api/auth/me returns user info regardless of login method

Plans:
- [ ] 14-01-PLAN.md -- Schema migration + bcrypt password hashing + auth endpoints (register, login, logout, me) + brute-force protection
- [ ] 14-02-PLAN.md -- Frontend login/register pages + authApi client + routing

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> ... -> 13 -> 14

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1-13 | v1.0 | 22/22 | Complete | 2026-03-09 |
| 14. Email + Password Auth | 2/2 | Complete   | 2026-03-09 | - |

---
_Full v1.0 details: `.planning/milestones/v1.0-ROADMAP.md`_
