---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: User Auth
current_plan: 2 of 2
status: executing
stopped_at: Completed 16-01-PLAN.md
last_updated: "2026-03-11T03:27:37.774Z"
last_activity: 2026-03-11
progress:
  total_phases: 3
  completed_phases: 1
  total_plans: 9
  completed_plans: 4
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-09)

**Core value:** Users can find any published legal act in the DOU quickly and read it in a clean, professional interface
**Current focus:** Phase 16 - Tear Down (BM25-only pipeline simplification)

## Current Position

Phase: 16 of 16 (Tear Down)
Current Plan: 2 of 2
Total Plans in Phase: 2
Status: Executing
Last activity: 2026-03-11

Progress: [==========] 100%

## Accumulated Context

### Decisions

- [v1.0]: All decisions preserved in PROJECT.md Key Decisions table
- [v1.1]: bcrypt via passlib (application layer, not pgcrypto) for password hashing
- [v1.1]: Session cookie agnostic — same httpOnly cookie for both password and token login
- [v1.1]: Brute-force: 5 attempts/15min per email, 20 attempts/15min per IP
- [14-01]: Pinned bcrypt<5.0 for passlib compatibility
- [14-01]: Password users store user UUID as session sub, resolved via resolve_identity_for_user_id fallback
- [14-01]: DB-based brute-force tracking in auth.login_attempt table
- [Phase 14]: Login page dual-mode: email+password primary, token secondary toggle
- [Phase 14]: Portuguese error messages mapped from HTTP status codes (401, 409, 422, 429)
- [Phase 14]: All form inputs use text-base (16px) to prevent iOS auto-zoom
- [16-02]: BM25_INDEXED dual-path transitions (VERIFYING default, EMBEDDING for future re-enablement)
- [16-02]: Embed job disabled by default via _job_enabled dict, not removed from scheduler
- [16-02]: PG port changed from 5433 to 5432 in local docker-compose
- [Phase 16]: User performed manual Fly.io app destruction via dashboard instead of CLI

### Roadmap Evolution

- Phase 15 added: Fly flies
- Phase 16 added: Tear down

### Performance Metrics

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 14    | 01   | 4min     | 2     | 6     |
| Phase 14 P02 | 3min | 3 tasks | 6 files |
| 16    | 02   | 9min     | 2     | 6     |
| Phase 16 P01 | 3min | 2 tasks | 2 files |

## Session Continuity

Last session: 2026-03-11T03:27:37.772Z
Stopped at: Completed 16-01-PLAN.md
Resume: Phase 16 complete
