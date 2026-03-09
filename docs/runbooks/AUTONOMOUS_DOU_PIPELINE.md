# Autonomous DOU Pipeline

> Last updated: 2026-03-09

This runbook captures the target architecture for the zero-touch DOU pipeline and the admin dashboard that observes it.
It is the authoritative reference for future implementation prompts in this repository.

For the current implementation state, open gaps, Fly.io migration blockers, and extensibility planning, see:

- [AUTONOMOUS_DOU_STATUS_AND_FLY_PREFLIGHT.md](/home/parallels/dev/gabi-kimi/docs/runbooks/AUTONOMOUS_DOU_STATUS_AND_FLY_PREFLIGHT.md)

## Non-Negotiables

- The system is autonomous by default. Human actions are exception paths.
- Historical ingest and recent ingest are separate source problems.
- BM25 availability comes before embeddings.
- The pipeline must be idempotent at file level and document level.
- The dashboard is for observability, audit, and controlled exception handling.

## Source Strategy

### INLABS

- Use INLABS only for discovery and download of recent publications.
- Operator constraint for this project: INLABS is treated as a 30-day window source.
- Do not plan or implement any historical backfill through INLABS.
- If an implementation prompt suggests INLABS for 2002-2019, that prompt is wrong.

### Liferay / in.gov.br

- Use direct Liferay URLs for the historical catalog.
- Use Liferay as the authoritative bulk source for 2002-2019.
- Use Liferay as a delayed fallback for recent months when INLABS did not update successfully and the monthly ZIP later becomes available on `www.in.gov.br`.

### Hybrid Operational Rule

- Recent steady state:
  - Prefer INLABS for daily discovery inside the recent window.
  - If INLABS fails today, alert and retry.
  - If recovery does not happen and the month later closes with a public Liferay ZIP, use that ZIP as best-effort fallback.
- Historical steady state:
  - Use the catalog-backed Liferay pipeline only.
- Search steady state before full backfill completes:
  - Hybrid retrieval must work over the indexed subset that already exists.
  - Missing historical months are a coverage issue, not a reason to block recent ingest.

## Worker Architecture

The worker should converge toward a single registry-backed lifecycle:

`DISCOVERED -> DOWNLOADING -> DOWNLOADED -> EXTRACTING -> EXTRACTED -> BM25_INDEXING -> BM25_INDEXED -> EMBEDDING -> EMBEDDED -> VERIFYING -> VERIFIED`

Failure states must preserve stage-specific retry policy and audit log entries. If the current codebase still uses the simpler `INGESTING/INGESTED` model, treat that as transitional and migrate without breaking the dashboard contract.

## Dashboard Rules

- UI stack: React + TypeScript + Tailwind + TanStack Query + `shadcn/ui`.
- Dashboard posture: observability-first.
- Required tabs:
  - Overview
  - Timeline
  - Pipeline
  - Logs
  - Settings
- Auto-refresh every 30 seconds.
- Keyboard shortcuts:
  - `1-5` for tabs
  - `R` refresh
  - `P` pause/resume scheduler
- Surface UTC timestamps from the backend; show BRT context in copy where needed.

## Adversarial Convergence

For any significant module or prompt revision, run a four-agent review:

1. Claude: architecture and boundaries
2. Kimi: failure analysis and edge cases
3. Qwen: convergence and implementation pragmatism
4. ZAI/GLM: auditability, determinism, and veto conditions

Minimum review questions:

- Does the plan ever use INLABS outside the recent 30-day window?
- Does fallback to Liferay avoid blocking recent daily operation?
- Can a full re-run accidentally create embedding cost runaway?
- Does SQLite remain safe under dashboard polling plus worker writes?
- Are timestamps unambiguous across UTC and BRT?
- Can a federal audit reconstruct what happened from logs and registry rows?

## Official References To Reuse

- Official INLABS repository: `Imprensa-Nacional/inlabs`
- Reuse existing patterns from the official Python downloader instead of inventing an incompatible client shape.
- Prefer adapting the official login/download flow into local abstractions, then harden it with retries, observability, and rate limiting.

## Implementation Guidance For Future Agents

When writing prompts for implementation agents, include all of the following:

- INLABS is recent-only for this project and must not be used for historical backfill.
- Historical data comes from catalog-mapped Liferay URLs.
- Recent fallback can degrade to Liferay monthly ZIPs only when they become available later.
- BM25 must become searchable before embeddings are complete.
- The dashboard exists to observe and audit the organism, not to replace automation with buttons.

## Persistent Debt

Snapshot as of 2026-03-09 after the hybrid source integration, lifecycle split, local registry bootstrap, and dashboard recovery work.

### Highest Priority

- `pause/resume` is still not durable across restart and does not leave a persistent audit trail.
- The recent-source fallback policy is not fully modeled yet:
  recent failures in the INLABS window should age into a deliberate Liferay monthly ZIP recovery path when that ZIP becomes available later.
- Re-embed and re-verify of already `VERIFIED` legacy corpus still needs an explicit, auditable backfill policy instead of opportunistic execution.

### Operational Integrity

- The local/dashboard bootstrap currently creates a synthetic `state-seed` run so the UI does not look broken on a seeded registry with no real worker history.
  This is correct for local observability, but production confidence should come from real scheduler runs, not synthetic history.
- Catalog bootstrap coverage still uses `(year_month, section)` presence in Elasticsearch as a heuristic.
  This is pragmatic, but it does not prove that every ZIP in that month/section was fully ingested.
- Watchdog holiday logic is still missing.
  The "3 business days with no new DOU" rule can still false-positive around holidays and long closures.

### Dashboard / API Contract

- The dashboard is still tightly coupled to the current worker API shape.
  Add contract tests or E2E coverage against a real worker process before treating the UI as stable.
- Browser-level visual validation is still incomplete in this environment.
  Recent fixes were validated by API responses, startup behavior, tests, and frontend build, not by full browser automation.

### Recommended Resume Order

1. Persist and audit `pause/resume`.
2. Implement the delayed recent fallback from failed INLABS discovery/download to later Liferay monthly ZIP recovery.
3. Add explicit backfill policy for re-embed and optional re-verify of legacy `VERIFIED` files.
4. Harden watchdog business-day logic with a holiday calendar.
5. Add dashboard E2E coverage against a live worker.
