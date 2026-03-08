---
phase: 04-worker-infrastructure
plan: "01"
subsystem: infra
tags: arq, redis, fly.io, process-groups, worker

requires:
  - phase: 02-job-control-schema
    provides: admin.worker_jobs (Phase 5 will consume)
provides:
  - fly.toml web + worker process groups with correct entrypoints
  - ARQ worker process connecting to Redis (REDIS_URL), 1GB RAM
  - test_task for enqueue verification
  - Runbook for local and Fly worker run
affects: Phase 5 Single XML Processing

tech-stack:
  added: arq>=0.27, src/backend/workers/arq_worker.py
  patterns: WorkerSettings + RedisSettings.from_dsn, [processes] + [[vm]] per process

key-files:
  created: src/backend/workers/__init__.py, src/backend/workers/arq_worker.py, docs/runbooks/FLY_WORKER_ARQ.md
  modified: requirements.txt, ops/deploy/web/requirements.txt, ops/deploy/web/fly.toml

key-decisions:
  - "Worker command: arq src.backend.workers.arq_worker.WorkerSettings (same image as web)"
  - "http_service processes = [web] so only web receives HTTP"

patterns-established:
  - "ARQ worker in dedicated workers/ module; test task for Phase 4, real job processing in Phase 5"

requirements-completed: [INFRA-03, INFRA-04]

duration: 12
completed: "2026-03-08"
---

# Phase 4 Plan 01: Worker Infrastructure Summary

**ARQ worker process group on Fly.io with Redis, 1GB RAM; fly.toml web + worker; test task enqueue verification.**

## Performance

- **Duration:** ~12 min
- **Tasks:** 4
- **Files created:** 3; **Files modified:** 3

## Accomplishments

- arq>=0.27 added to requirements.txt and ops/deploy/web/requirements.txt
- src/backend/workers/arq_worker.py: WorkerSettings, RedisSettings.from_dsn(REDIS_URL), test_task(ctx, msg)
- fly.toml: [processes] web (python ops/bin/web_server.py), worker (arq ... WorkerSettings); [http_service] processes = ["web"]; [[vm]] web 512mb, [[vm]] worker 1gb
- docs/runbooks/FLY_WORKER_ARQ.md: Fly process groups, local worker run, enqueue test_task example

## Task Commits

1. **Task 1: arq dependency** - `821d20c` (chore)
2. **Task 2: Worker module** - `28beca0` (feat)
3. **Task 3: fly.toml process groups** - `2e47ceb` (feat)
4. **Task 4: Runbook** - `3a0119a` (docs)

## Files Created/Modified

- `src/backend/workers/__init__.py`, `src/backend/workers/arq_worker.py` - ARQ WorkerSettings, test_task
- `docs/runbooks/FLY_WORKER_ARQ.md` - Fly + local worker docs
- `requirements.txt`, `ops/deploy/web/requirements.txt` - arq>=0.27
- `ops/deploy/web/fly.toml` - processes, vm per process, worker 1gb

## Decisions Made

- Single Docker image for web and worker; worker entrypoint is arq CLI with module path.
- Worker VM 1GB to satisfy success criteria and prepare for Phase 5 XML processing.

## Deviations from Plan

None.

## Issues Encountered

None.

## Self-Check: PASSED

- workers/arq_worker.py, fly.toml [processes], FLY_WORKER_ARQ.md exist. Commits 821d20c, 28beca0, 2e47ceb, 3a0119a present.

---
*Phase: 04-worker-infrastructure*
*Completed: 2026-03-08*
