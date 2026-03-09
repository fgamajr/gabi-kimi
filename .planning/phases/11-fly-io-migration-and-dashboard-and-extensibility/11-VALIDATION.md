---
phase: 11
slug: fly-io-migration-and-dashboard-and-extensibility
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-09
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (backend) / vitest (frontend) |
| **Config file** | pytest: `pyproject.toml` / vitest: `src/frontend/web/vite.config.ts` |
| **Quick run command** | `python -m pytest tests/test_pipeline/ -x -q` |
| **Full suite command** | `python -m pytest tests/ -q && cd src/frontend/web && npx vitest run` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_pipeline/ -x -q`
- **After every plan wave:** Run full suite
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 11-01-01 | 01 | 1 | SQLite registry | unit | `pytest tests/test_pipeline/test_registry.py` | ❌ W0 | ⬜ pending |
| 11-01-02 | 01 | 1 | State machine | unit | `pytest tests/test_pipeline/test_registry.py::test_transitions` | ❌ W0 | ⬜ pending |
| 11-02-01 | 02 | 1 | Discovery crawler | integration | `pytest tests/test_pipeline/test_discovery.py` | ❌ W0 | ⬜ pending |
| 11-03-01 | 03 | 2 | Downloader | unit | `pytest tests/test_pipeline/test_downloader.py` | ❌ W0 | ⬜ pending |
| 11-04-01 | 04 | 2 | Extractor | unit | `pytest tests/test_pipeline/test_extractor.py` | ❌ W0 | ⬜ pending |
| 11-05-01 | 05 | 2 | ES Ingestor | integration | `pytest tests/test_pipeline/test_ingestor.py` | ❌ W0 | ⬜ pending |
| 11-06-01 | 06 | 3 | Verifier | integration | `pytest tests/test_pipeline/test_verifier.py` | ❌ W0 | ⬜ pending |
| 11-07-01 | 07 | 3 | Orchestrator | unit | `pytest tests/test_pipeline/test_orchestrator.py` | ❌ W0 | ⬜ pending |
| 11-08-01 | 08 | 3 | Worker internal API | integration | `pytest tests/test_pipeline/test_worker_api.py` | ❌ W0 | ⬜ pending |
| 11-09-01 | 09 | 4 | Dashboard React | component | `cd src/frontend/web && npx vitest run src/test/pipeline-dashboard.test.tsx` | ❌ W0 | ⬜ pending |
| 11-10-01 | 10 | 5 | Fly.io deploy | manual | N/A | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_pipeline/` — directory structure
- [ ] `tests/test_pipeline/conftest.py` — shared fixtures (SQLite in-memory, mock ES, mock Liferay)
- [ ] `tests/test_pipeline/test_registry.py` — stubs for SQLite registry + state machine
- [ ] `tests/test_pipeline/test_discovery.py` — stubs for Liferay crawler
- [ ] `tests/test_pipeline/test_downloader.py` — stubs for ZIP downloader
- [ ] `tests/test_pipeline/test_extractor.py` — stubs for ZIP extractor
- [ ] `tests/test_pipeline/test_ingestor.py` — stubs for ES ingestor
- [ ] `tests/test_pipeline/test_verifier.py` — stubs for post-ingest verifier
- [ ] `tests/test_pipeline/test_orchestrator.py` — stubs for pipeline orchestrator
- [ ] `tests/test_pipeline/test_worker_api.py` — stubs for worker internal API

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Fly.io deployment works | Fly.io config | Requires Fly.io account + live deploy | `fly deploy` + verify `/health` |
| ES snapshot to Tigris | Backup | Requires live Tigris bucket | Create snapshot, verify S3 listing |
| Liferay API live discovery | Discovery | Requires live in.gov.br access | Run discovery against prod Liferay |
| Full pipeline end-to-end | Pipeline | Requires all infra running | Trigger via dashboard, monitor 1 month |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
