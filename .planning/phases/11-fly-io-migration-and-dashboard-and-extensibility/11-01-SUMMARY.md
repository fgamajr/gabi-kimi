---
phase: 11-fly-io-migration-and-dashboard-and-extensibility
plan: 01
subsystem: infra
tags: [fly.io, elasticsearch, docker, deployment, worker]

requires:
  - phase: 10-legacy-cleanup
    provides: "Clean codebase ready for infrastructure migration"
provides:
  - "Elasticsearch Fly.io machine config (fly.toml + Dockerfile + entrypoint + config)"
  - "Worker Fly.io machine config (fly.toml + Dockerfile + requirements)"
  - "Inter-machine .internal DNS networking pattern"
affects: [11-02, 11-03, 11-04, 11-05]

tech-stack:
  added: [elasticsearch-8.15.2, python-3.12-slim, apscheduler, aiosqlite]
  patterns: [fly-internal-dns, volume-permission-fix-entrypoint, non-root-docker-user]

key-files:
  created:
    - ops/deploy/es/fly.toml
    - ops/deploy/es/Dockerfile
    - ops/deploy/es/entrypoint.sh
    - ops/deploy/es/elasticsearch.yml
    - ops/deploy/worker/fly.toml
    - ops/deploy/worker/Dockerfile
    - ops/deploy/worker/requirements-worker.txt
  modified: []

key-decisions:
  - "ES health check via /_cluster/health on port 9200 using [checks] block"
  - "Worker health check on port 8081 using [checks] block (not http_service)"
  - "Both machines use deploy.strategy = immediate (no rolling deploys for single instances)"

patterns-established:
  - "Volume permission fix: entrypoint.sh runs chown then drops to service user via su-exec"
  - "Internal-only machines: no [http_service] or [[services]] blocks, health via [checks]"
  - "Inter-machine communication via {app-name}.internal DNS"

requirements-completed: [FLY-01, FLY-02, FLY-04]

duration: 1min
completed: 2026-03-09
---

# Phase 11 Plan 01: ES and Worker Machine Configs Summary

**Fly.io deployment configs for Elasticsearch (performance-2x, 4GB) and Worker (shared-cpu-1x, 512MB) with internal-only networking via .internal DNS**

## Performance

- **Duration:** 1 min
- **Started:** 2026-03-09T12:50:15Z
- **Completed:** 2026-03-09T12:51:31Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Elasticsearch machine config with 4GB RAM, 50GB volume, Portuguese text analysis defaults
- Worker machine config with APScheduler pipeline dependencies and /data volume
- Both machines internal-only in gru region with .internal DNS networking

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Elasticsearch machine deployment config** - `70c2174` (feat)
2. **Task 2: Create Worker machine deployment config** - `4b5ae67` (feat)

## Files Created/Modified
- `ops/deploy/es/fly.toml` - ES Fly.io machine config (performance-2x, 4GB, gru)
- `ops/deploy/es/Dockerfile` - ES 8.15.2 image with volume permission entrypoint
- `ops/deploy/es/entrypoint.sh` - Fixes volume ownership then drops to elasticsearch user
- `ops/deploy/es/elasticsearch.yml` - Single-node config with Portuguese analyzer
- `ops/deploy/worker/fly.toml` - Worker Fly.io machine config (shared-cpu-1x, 512MB)
- `ops/deploy/worker/Dockerfile` - Python 3.12 image with non-root gabi user
- `ops/deploy/worker/requirements-worker.txt` - APScheduler, aiosqlite, fastapi, httpx, etc.

## Decisions Made
- ES health check uses /_cluster/health endpoint via [checks] block (not http_service since ES is internal-only)
- Worker health check on port 8081 via [checks] block
- Both machines use immediate deploy strategy (single instances, no rolling deploy needed)
- curl installed in worker image for HEALTHCHECK instruction

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- ES and Worker machine configs ready for `fly deploy`
- Web machine config already exists at ops/deploy/web/fly.toml
- Next plan (11-02) can build the autonomous pipeline on this infrastructure

---
*Phase: 11-fly-io-migration-and-dashboard-and-extensibility*
*Completed: 2026-03-09*
