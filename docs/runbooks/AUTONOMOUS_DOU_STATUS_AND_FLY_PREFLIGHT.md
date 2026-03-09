# Autonomous DOU Status + Fly Preflight

> Last updated: 2026-03-09

This document is the consolidated handoff for the autonomous DOU pipeline workstream.
It answers four questions in one place:

1. What has already been done in the codebase
2. What remains open
3. What is still technical debt
4. What must be checked before migrating to Fly.io

Use this as the anchor document for future implementation prompts and deployment planning.

## Current Direction

The project is converging on this operating model:

- `INLABS` for recent discovery and download only
- `Liferay` for historical backfill and delayed monthly fallback
- autonomous worker with SQLite registry on its own Fly volume
- public web app that proxies dashboard calls to the worker over Fly private networking
- Elasticsearch on a dedicated Fly machine with its own volume
- BM25 first, embeddings second, verify last
- dashboard as observability surface, not manual control panel

## What Is Already Done

These changes are already implemented in the repository.

### Source Strategy

- `INLABS` was hardened as recent-only infrastructure with an explicit 30-day guardrail.
- Historical ingest remains catalog-backed from `Liferay`.
- Worker registry rows now persist the source used for each file.
- Hybrid routing logic exists in the worker:
  - recent window prefers `INLABS`
  - historical path uses `Liferay`

### Worker Lifecycle

- The file lifecycle was split into explicit stages:
  `DISCOVERED -> DOWNLOADING -> DOWNLOADED -> EXTRACTING -> EXTRACTED -> BM25_INDEXING -> BM25_INDEXED -> EMBEDDING -> EMBEDDED -> VERIFYING -> VERIFIED`
- BM25, embedding, and verify now exist as separate pipeline phases.
- Verified legacy rows can re-enter embedding for backfill when `embedded_at` is missing.

### Dashboard Recovery

- The dashboard no longer silently collapses worker failures into empty states.
- The worker proxy in the web app handles connection failures more explicitly.
- Local bootstrap of the worker registry from `ops/data/dou_catalog_registry.json` is in place.
- The dashboard now receives seeded timeline data for years such as `2002`, instead of showing false emptiness.
- Fresh seeded environments without real historical runs now get a synthetic audit entry (`state-seed`) so the UI does not look broken.

### Tests / Validation Already Run

- Pipeline tests for registry, migration, discovery, worker API, embedder, and related flows passed locally during this workstream.
- Frontend production build passed locally after the dashboard fixes.

## What Remains Open

These are still implementation gaps, not just polish.

### Core Worker Gaps

- `OK` (P6) `pause/resume` is persisted in `pipeline_config` and survives restart; every action is logged in `pipeline_log`; watchdog alerts if paused >48h.
- `OK` (P4) Delayed Liferay monthly fallback implemented: `FALLBACK_PENDING` state, weekly reconciler, age-out transition, Liferay probe and recovery.
- Re-embed and optional re-verify of legacy already-verified corpus still need a first-class backfill policy.
- `OK` Watchdog holiday awareness (P5): Brazilian calendar in pipeline_config, silence detector is business-day aware.

### Done (P3)

- Month-level lifecycle (`KNOWN` → `INLABS_WINDOW` → `WINDOW_CLOSING` → `FALLBACK_ELIGIBLE` → `CLOSED`) is implemented in `dou_catalog_months.catalog_status`.
- Daily job refreshes status; worker also runs refresh on startup.
- Worker API exposes `GET /registry/catalog-months`; dashboard Overview shows catalog coverage vs ingest.

### Deployment Gaps

- Snapshots to Tigris exist in code but are not yet operationally proven on Fly.
- End-to-end Fly private networking between web, worker, and ES still needs real validation.

### Dashboard Gaps

- The dashboard still lacks E2E coverage against a real worker process.
- The dashboard remains tightly coupled to the current worker API shape.

## Persistent Debt

These items may not block local development, but they will matter for long-term trust.

### Architectural Debt

- `OK` SQLite is now the operational source of truth: `dou_catalog_months` and `dou_files` are populated from the JSON only on first-ever bootstrap; `pipeline_config` exists for persisted scheduler/watchdog settings.
- `ops/data/dou_catalog_registry.json` is used only as a one-time seed; if the registry already has catalog data, bootstrap is skipped.
- Catalog bootstrap coverage still uses Elasticsearch presence by `(year_month, section)` as a heuristic.
  That does not prove complete ZIP-level ingest.

### Operational Debt

- The local `state-seed` synthetic run is useful, but production confidence should come from real scheduler activity.
- Browser-level validation of the dashboard is still weaker than API-level validation in this environment.
- `OK` (P5) Watchdog implemented with Brazilian holidays (pipeline_config `holidays_fixed`), rate-limited alerts, Telegram, API `/pipeline/watchdog`, and dashboard Overview.

### Deployment Debt

- The current Fly config still reflects two worker concepts at once:
  - dedicated autonomous worker app
  - ARQ worker process group under the web app
- This drift must be resolved before production deploy.

## What No Longer Makes Sense

These ideas should be treated as obsolete for this project direction.

- Treating `dou_catalog_registry.json` as the long-term system of record
- Relying on manual edits to keep the future catalog fresh
- Treating the dashboard as a manual operations console
- Using public `Liferay` discovery as the primary future discovery mechanism
- Treating the old combined `INGESTING/INGESTED` lifecycle as sufficient
- Assuming the web app's ARQ worker process is the same thing as the new autonomous pipeline worker

## Fly.io Preflight

The checks below should be done before writing final deployment prompts.

Status markers:

- `OK`: already aligned in code or docs
- `PENDING`: not yet proven
- `BLOCKER`: known mismatch that should be fixed before deploy

### 1. Target Topology

- `OK` Production topology is frozen and documented in [TOPOLOGY.md](/home/parallels/dev/gabi-kimi/docs/TOPOLOGY.md):
  - `gabi-dou-frontend` for static SPA
  - `gabi-dou-web` for public API
  - `gabi-dou-worker` for autonomous pipeline + SQLite
  - `gabi-dou-es` for Elasticsearch
  - `gabi-dou-redis` as part of current topology (ARQ/manual upload)
  - `gabi-dou-db` (Postgres) for web/admin identity and data
- `OK` The deploy drift between the autonomous worker app and the ARQ upload worker was narrowed:
  [web fly.toml](/home/parallels/dev/gabi-kimi/ops/deploy/web/fly.toml) now names the Redis/ARQ process `upload_worker`, and [FLY_WORKER_ARQ.md](/home/parallels/dev/gabi-kimi/docs/runbooks/FLY_WORKER_ARQ.md) now treats it explicitly as a manual-upload queue worker instead of the autonomous pipeline worker.

### 2. Health Checks

- `OK` The web health check mismatch was fixed.
  [web fly.toml](/home/parallels/dev/gabi-kimi/ops/deploy/web/fly.toml) now checks `/healthz`, and [web_server.py](/home/parallels/dev/gabi-kimi/src/backend/apps/web_server.py) exposes that endpoint publicly for platform liveness checks.
- `OK` Worker health endpoint exists at `/health`.
- `OK` ES health check exists at `/_cluster/health`.
- `OK` An unprotected public web health endpoint now exists for Fly checks.

### 3. Private Networking

- `OK` Web is configured to call `http://gabi-dou-worker.internal:8081`.
- `OK` Worker is configured to call `http://gabi-dou-es.internal:9200`.
- `PENDING` Validate real `.internal` connectivity on Fly between all three apps.
- `PENDING` Validate the worker bind/listen behavior on Fly.
  The code now binds the worker to `::` on Fly in [main.py](/home/parallels/dev/gabi-kimi/src/backend/worker/main.py), which is the correct direction for Fly private networking, but this still needs live verification.

### 4. Volumes and Storage

- `OK` Worker Fly config declares a dedicated volume for `/data`.
- `OK` ES Fly config declares a dedicated data volume.
- `PENDING` Size the worker volume for `registry.db`, temp ZIPs, logs, and cleanup headroom.
- `PENDING` Size the ES volume for index growth plus merge overhead.
- `PENDING` Validate cleanup behavior for `/data/tmp` after verification.

### 5. Secrets and Environment

- `PENDING` Finalize secrets for `web`:
  - `PGPASSWORD`
  - `GABI_API_TOKENS`
  - `GABI_ADMIN_TOKEN_LABELS`
  - `GABI_AUTH_SECRET`
  - `REDIS_URL` if upload queue remains
  - `QWEN_API_KEY` if chat remains enabled
- `PENDING` Finalize secrets for `worker`:
  - `INLABS_EMAIL`
  - `INLABS_PASSWORD`
  - `OPENAI_API_KEY`
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`
- `PENDING` Finalize Tigris/S3 credentials if ES snapshots remain enabled.

### 6. Data Bootstrap and Idempotency

- `OK` Worker can bootstrap the SQLite registry from `ops/data/dou_catalog_registry.json`.
- `PENDING` Prove first-boot behavior on Fly with an empty worker volume.
- `PENDING` Prove idempotent reruns of `download`, `bm25`, `embed`, and `verify` on Fly.
- `PENDING` Prove that a fresh worker can recover its state after restart from only the volume contents.

### 7. External Integrations

- `PENDING` Test real `INLABS` login/download from Fly worker region.
- `PENDING` Test OpenAI embeddings from Fly with cost-limited small sample.
- `PENDING` Test Telegram alert delivery from Fly.
- `PENDING` Test Elasticsearch snapshot repo registration and at least one restore drill.

### 8. Security

- `OK` The backend already has trusted host, auth, and security middleware.
- `PENDING` Reconcile `GABI_ALLOWED_HOSTS`, `GABI_CORS_ORIGINS`, and final production domains.
- `PENDING` Decide whether Redis remains required in production for manual upload flows.
- `PENDING` Ensure worker and ES stay internal-only.

### 9. Rollback and Recovery

- `PENDING` Define app deploy order.
- `PENDING` Define rollback procedure per app.
- `PENDING` Define worker volume recovery procedure.
- `PENDING` Define ES snapshot restore procedure and recovery time expectations.

### 10. Cost / Capacity

- `PENDING` Validate whether worker `512mb` is enough for ZIP extraction and embeddings in Fly.
- `PENDING` Validate ES `4gb` memory sizing against realistic index load.
- `PENDING` Estimate one-time embedding cost for backfill and steady-state daily cost.

## Extensibility Plan

The catalog must become live and self-extending.

### Principle

The JSON snapshot should seed the system, not define its future.

Future discovery and fallback should be persisted into the SQLite registry so the worker can continue operating without manual edits to `ops/data/dou_catalog_registry.json`.

### Target Model

Keep `dou_files` as the file-level state machine and add an explicit catalog layer if needed for month-level reasoning.

Suggested month-level concepts:

- `year_month`
- `folder_id`
- `group_id`
- `source_of_truth`
- `catalog_status`
- `month_closed`
- `inlabs_window_expires_at`
- `fallback_eligible_at`
- `liferay_discovered_at`
- `last_catalog_reconciled_at`

### Operational Logic

1. JSON bootstrap seeds historical known months/files.
2. `INLABS` discovery keeps recent days fresh inside the recent window.
3. Worker inserts newly discovered recent files directly into SQLite.
4. A catalog reconciler periodically checks whether monthly public `Liferay` ZIPs are now available for recently failed/aged items.
5. If a recent file failed in `INLABS` and later becomes recoverable through a monthly `Liferay` ZIP, the worker should enqueue that fallback automatically.
6. Manual uploads remain possible, but are marked explicitly as `source=manual` and must not become the primary freshness mechanism.

### Dashboard Requirements For Extensibility

The admin dashboard should separate two concepts:

1. Catalog coverage
   - which years/months are known
   - which months have `folder_id`
   - which months are still recent-window only
   - which months are eligible for delayed fallback

2. Pipeline execution state
   - what is discovered
   - downloading
   - extracted
   - bm25 indexed
   - embedded
   - verified
   - failed
   - waiting for monthly fallback

This distinction matters because "catalog known" is not the same thing as "ingested successfully".

## Recommended Next Sequence

1. Resolve Fly deployment drift and health-check blockers.
2. Freeze the final production topology.
3. Define the live catalog extension model in SQLite.
4. Implement the delayed monthly `Liferay` fallback policy.
5. Persist and audit `pause/resume`.
6. Add watchdog holiday awareness.
7. Add dashboard contract/E2E coverage against a real worker.

## How To Continue With Codex

Use this file as the single context anchor:

- [AUTONOMOUS_DOU_STATUS_AND_FLY_PREFLIGHT.md](/home/parallels/dev/gabi-kimi/docs/runbooks/AUTONOMOUS_DOU_STATUS_AND_FLY_PREFLIGHT.md)

### Recommended Prompt Style

Prefer one focused prompt per execution slice.

Good:

- one prompt to remove Fly blockers
- one prompt to implement the live catalog extension model
- one prompt to implement delayed monthly `Liferay` fallback
- one prompt to harden watchdog rules

Avoid:

- one giant prompt asking for deploy, catalog redesign, dashboard redesign, and watchdog hardening all at once

### Best Next Prompt

If the next goal is Fly migration readiness, use:

```text
Use /home/parallels/dev/gabi-kimi/docs/runbooks/AUTONOMOUS_DOU_STATUS_AND_FLY_PREFLIGHT.md as the source of truth.

Execute only the current Fly.io BLOCKER items.
Do not broaden scope beyond Fly blockers.

Goals:
1. Resolve deployment drift between web ARQ worker config and dedicated autonomous worker config.
2. Fix the web health check mismatch.
3. Validate and, if necessary, harden internal networking assumptions for web -> worker -> ES.
4. Update the same runbook in place as items are resolved.

Requirements:
- make code and config changes directly
- run the relevant local validations
- keep notes concise
- after finishing, mark what moved from BLOCKER to OK or PENDING in the runbook
```

### Prompt After Fly Blockers

If the next goal is extensibility beyond the JSON snapshot, use:

```text
Use /home/parallels/dev/gabi-kimi/docs/runbooks/AUTONOMOUS_DOU_STATUS_AND_FLY_PREFLIGHT.md as the source of truth.

Implement the live catalog extension model in SQLite.
Do not work on Fly deploy in this step unless directly required by the schema/API change.

Goals:
1. Define and implement the month-level catalog state needed beyond ops/data/dou_catalog_registry.json.
2. Make the worker persist future discovery state in SQLite instead of depending on manual JSON edits.
3. Prepare the dashboard/API to distinguish catalog coverage from ingest state.
4. Update the same runbook in place with the new data model and remaining gaps.
```

### Prompt For Delayed Fallback

When ready to implement the `INLABS -> later monthly Liferay` recovery path, use:

```text
Use /home/parallels/dev/gabi-kimi/docs/runbooks/AUTONOMOUS_DOU_STATUS_AND_FLY_PREFLIGHT.md as the source of truth.

Implement the delayed fallback policy for recent files that fail inside the INLABS window and later become recoverable through monthly Liferay ZIPs.

Goals:
1. Model the required states in the registry.
2. Add automatic transition into fallback-eligible state when appropriate.
3. Add reconciler logic to discover and queue the monthly fallback automatically.
4. Expose this state clearly in the worker API and dashboard.
5. Update the runbook in place after implementation.
```

### Short Rule

For future conversations, you can usually start with:

```text
Use /home/parallels/dev/gabi-kimi/docs/runbooks/AUTONOMOUS_DOU_STATUS_AND_FLY_PREFLIGHT.md as the source of truth and continue from the next unresolved item.
```

Then add one bounded goal.

## Reference Pointers

- Main target architecture: [AUTONOMOUS_DOU_PIPELINE.md](/home/parallels/dev/gabi-kimi/docs/runbooks/AUTONOMOUS_DOU_PIPELINE.md)
- Existing broader pipeline runbook: [PIPELINE.md](/home/parallels/dev/gabi-kimi/docs/runbooks/PIPELINE.md)
- Fly web security notes: [FLY_WEB_SECURITY.md](/home/parallels/dev/gabi-kimi/docs/runbooks/FLY_WEB_SECURITY.md)
- Fly split deploy notes: [FLY_SPLIT_DEPLOY.md](/home/parallels/dev/gabi-kimi/docs/runbooks/FLY_SPLIT_DEPLOY.md)
- Official Fly docs:
  - https://fly.io/docs/reference/configuration/
  - https://fly.io/docs/networking/private-networking/
  - https://fly.io/docs/volumes/overview/
  - https://fly.io/docs/apps/secrets/
  - https://fly.io/docs/tigris/
