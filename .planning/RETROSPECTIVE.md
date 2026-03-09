# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — GABI Admin Upload

**Shipped:** 2026-03-09
**Phases:** 13 | **Plans:** 22 | **Timeline:** 31 days

### What Was Built
- Full admin document upload pipeline (Tigris blob storage, streaming API, ARQ workers, XML/ZIP processing)
- React admin UI (drag-drop upload, job dashboard, SSE real-time progress, retry)
- Autonomous DOU ingestion pipeline (SQLite registry, Liferay discovery, multi-era ZIP extraction, ES indexing)
- Fly.io 3-machine architecture (ES 4GB, Worker 512MB, Web 512MB) with .internal DNS
- 5-tab admin dashboard (Overview, Timeline, Pipeline, Logs, Settings)
- Unified pipeline architectural reference document (740+ lines)
- Security hardening (auth guard, rate limiting, access logging)

### What Worked
- Phase-per-capability decomposition kept each phase focused and testable
- Fly.io machine separation prevented OOM issues — right call to avoid BackgroundTask
- SQLite WAL mode for pipeline registry was simpler than extending Postgres
- Liferay JSONWS API discovery with HEAD probe fallback was reliable
- Rapid phase 1-10 execution (all in one day) for well-scoped upload pipeline
- Phase 11 expansion (7 plans) handled the large Fly.io migration scope well

### What Was Inefficient
- VERIFICATION.md files were skipped for phases 01-10, creating tech debt that surfaced during audit
- SUMMARY.md files lack `requirements_completed` and `one_liner` frontmatter fields — making automated accomplishment extraction impossible
- Traceability table went stale for phases 11-12 and needed a dedicated Phase 13 to fix
- Phase 12 (documentation) grew to 4 plans because the ULTRA MEGA PROMPT scope expanded mid-milestone

### Patterns Established
- `.internal` DNS networking pattern for Fly.io multi-machine apps
- APScheduler pause/resume flag pattern for scheduler control
- httpx proxy pattern for forwarding internal API requests
- Module-level `_registry` injection for testable worker modules
- MonthCard with Radix Collapsible for timeline UI

### Key Lessons
1. **Run audit early, not just at milestone end** — Phase 13 was reactive gap closure that could have been caught during Phase 11
2. **Keep traceability tables in sync** — manually updating them after each phase prevents drift
3. **VERIFICATION.md is cheap insurance** — skipping it for "obviously working" phases creates noise in audits
4. **Documentation phases expand scope** — spec documents (Phase 12) tend to grow; budget accordingly
5. **Single integration gap can delay milestone** — the proxy auth gap (FLY-03) was minor but required a full phase to close properly

### Cost Observations
- Model mix: primarily opus for execution, sonnet for research/planning
- Notable: Phases 1-10 executed extremely fast (single day) due to clear requirements and small scope per phase

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Timeline | Phases | Key Change |
|-----------|----------|--------|------------|
| v1.0 | 31 days | 13 | Initial milestone; established GSD workflow with audit |

### Top Lessons (Verified Across Milestones)

1. Keep traceability tables in sync after each phase
2. Run audits incrementally, not just at milestone end
