# Codex Full Plan (Back-in-Time) - Resilient Pipeline Architecture

Date: 2026-02-14
Scope: End-to-end blueprint for implementing a world-class fail-safe pipeline for `seed -> discovery -> fetch -> ingest`, as if we could restart the design from scratch, while preserving a realistic migration path from the current system.

## 1. Executive Summary
If we could go back, we would start with:
- Explicit per-phase data model (not a single link-centric status model).
- Idempotency and resume semantics defined before coding workers.
- State machine invariants tested before implementation.
- Run-level and item-level observability designed up front.

This plan describes:
- Target architecture and schema.
- Smart-resume and manual-resume behavior.
- Rollback/compensation model.
- Implementation waves.
- Test and operational validation (including Zero Kelvin).

## 2. Product Goals and Non-Negotiables
Goals:
- Reliability under partial failures.
- Deterministic resume with no uncontrolled duplication.
- Safe incremental updates when `sources_v2.yaml` changes.
- Operational clarity: phase, run, source, and item status must be queryable.
- Production-safe deployment with controlled blast radius.

Non-negotiables:
- Idempotent writes across all phases.
- Explicit transitions with auditable state changes.
- No destructive runtime rollbacks as default behavior.
- E2E cold-start validation before promoting major changes.

## 3. Back-in-Time Architecture (What should have existed from day 1)
## 3.1 Phase Model
Pipeline phases with explicit handoff artifacts:
1. Seed: source catalog upsert and source config snapshot.
2. Discovery: produce `discovered_links`.
3. Fetch: produce `fetch_items` and fetched content metadata.
4. Ingest: produce normalized `documents` and ingest outcomes.

## 3.2 Cardinality
- `Seed -> Discovery`: 1:1 per source execution context.
- `Discovery -> Fetch`: 1:M (one discovered link can fan out).
- `Fetch -> Ingest`: M:N (one fetch can produce many docs, docs can map to multiple fetch artifacts by policy).

## 3.3 Status Layers
- Run status: execution summary of a phase run.
- Item status: lifecycle of each item in a phase.
- Derived completion: computed from parent-child chain, not guessed from one table.

## 4. Target Data Model
## 4.1 Core Tables
- `source_registry`
- `seed_runs`
- `discovery_runs`
- `discovered_links`
- `fetch_runs`
- `fetch_items`
- `ingest_runs`
- `ingest_jobs`
- `documents`
- `pipeline_actions` (manual control/audit)
- Optional: `ingest_job_fetch_items` junction for explicit M:N mapping

## 4.2 Key Constraints
- Unique natural keys and hashes for idempotency per phase.
- FK integrity between phase outputs and downstream inputs.
- Partial unique indexes for active records where needed.
- Strict status enums and transition guardrails.

## 4.3 Minimal Status Enum (per phase item)
- `pending`
- `queued`
- `processing`
- `completed`
- `failed`
- `skipped`
- `cancelled`
- `stale`

## 5. Smart Resume Design
## 5.1 Scope
Resume operates primarily at item level and secondarily at run/source level.

## 5.2 Behavior
- Never reprocess `completed` unless forced by manual action.
- Resume `pending`, `failed` (retry-eligible), and orphan `processing` items.
- Detect orphan processing by heartbeat/lock timeout.

## 5.3 Scheduling Policy
- Priority order:
  1. retry-eligible `failed`
  2. oldest `pending`
  3. fairness slice across sources
- Anti-starvation: minimum quota per active source.

## 5.4 Checkpointing
- Every state transition writes timestamp + actor/worker + reason.
- Parent run progress derived from item counters, not ad-hoc strings.

## 6. Manual Resume Design
## 6.1 API Capabilities
Manual control endpoints must support:
- Resume by source.
- Resume by phase.
- Resume by run.
- Resume only failed items.
- Resume one explicit item (link/fetch item/ingest job).

## 6.2 Action Contract
Every manual command creates a `pipeline_actions` record with:
- `action_id`, actor, reason, scope, filters, dry-run flag, created_at.
- Accepted/rejected state and execution summary.

## 6.3 Source YAML Changes
- New source: insert into `source_registry`, seed status pending.
- Existing source changed: upsert config and create incremental run; preserve historical runs.
- Removed source: disable (`enabled=false`), do not delete history.

## 7. Rollback and Compensation
## 7.1 Principle
Default rollback is logical, not destructive:
- Mark status + reason.
- Continue from consistent checkpoints.

## 7.2 Per Phase
- Discovery fails mid-batch: keep valid discovered links, mark run failed/partial.
- Fetch fails partial: keep completed fetch items, resume failed/pending.
- Ingest fails partial: keep committed documents/jobs, resume failed/pending.

## 7.3 Physical Rollback
Allowed only in controlled maintenance flows with explicit operator action and full audit trail.

## 8. Idempotency Strategy
## 8.1 Idempotency Keys
- Seed: source id + config hash + run context.
- Discovery: source id + normalized URL hash.
- Fetch: discovered_link_id + fetch target fingerprint.
- Ingest: fetch_item_id + content hash + transformation version.

## 8.2 Write Policy
- Upsert where semantic identity is stable.
- Insert-only where history matters (runs/actions/events).
- Prevent duplicate fanout with unique constraints.

## 9. Observability and SLOs
## 9.1 Metrics
- Queue depth by phase.
- Throughput by phase.
- Success/failure/retry rates.
- Stuck item count and age.
- Resume effectiveness (items recovered without manual intervention).

## 9.2 Logs and Traces
- Correlate by run_id, source_id, item_id.
- Structured logs with transition events.
- Trace parent-child phase propagation.

## 9.3 SLO Starter Set
- Seed completion success >= 99% per run.
- Discovery success >= 98% per source run.
- Mean recovery time for partial failures < target threshold.

## 10. Security and Governance
- RBAC on manual actions (viewer/operator/admin).
- Immutable audit trail for control actions.
- Rate limits for control endpoints.
- Redaction policy for sensitive metadata in logs.

## 11. Implementation Waves (from current state to target)
## Wave 0 - Freeze and Alignment
- Freeze contracts for status transitions and action semantics.
- Publish ADR covering cardinality and phase boundaries.

## Wave 1 - Data Foundation
- Add `fetch_runs`, `fetch_items`, and needed FKs/junctions.
- Add `pipeline_actions`.
- Preserve compatibility with existing `discovered_links` and `ingest_jobs`.

## Wave 2 - Fetch Real Implementation
- Replace fetch stub with real executor.
- Write fetch outputs into `fetch_items` with idempotency.
- Add retries and transition guards.

## Wave 3 - Ingest Rewire
- Ingest reads from `fetch_items` (not only link-level queueing).
- Track ingest status per ingest artifact.
- Add run-level aggregation.

## Wave 4 - Smart Resume
- Implement orphan detection, retry policies, fairness scheduler.
- Add operational metrics and dashboards.

## Wave 5 - Manual Resume APIs
- Implement scoped resume endpoints.
- Add dry-run preview and action audit UI/API.

## Wave 6 - Hardening and Cleanup
- Remove transitional paths.
- Tighten constraints and simplify legacy compatibility code.

## 12. TDD and Verification Plan
## 12.1 Test Categories
- State machine tests per phase.
- Idempotency tests for duplicate triggers.
- Resume tests (auto/manual).
- Migration compatibility tests.
- E2E cold-start and repeatability tests.

## 12.2 Zero Kelvin E2E Matrix
Scenario A (normal):
- Clean infra -> seed -> validate DB -> discovery -> validate DB.

Scenario B (idempotent repeat):
- Trigger seed/discovery again -> validate no bad duplication and expected counters.

Scenario C (fail-safe):
- Clean infra -> discovery without seed -> controlled failure path.

Required outputs:
- Run summaries by phase.
- DB counts and status distributions.
- Failure reasons and recovery behavior.

## 13. Delivery Governance
- Feature flags for major phase rewiring.
- Canary rollout before full promotion.
- Runbooks for recovery operations.
- Explicit rollback plan per deploy wave.

## 14. Acceptance Criteria
A release is considered ready only if:
- Cardinality model is enforced in schema and code.
- Smart resume works after simulated crashes.
- Manual resume works per scope and is auditable.
- E2E Zero Kelvin scenarios pass with objective DB validation.
- No hidden dependency on ad-hoc manual DB fixes.

## 15. What We Would Do Differently (explicit retrospective)
If this had been done from day 1:
1. Create explicit phase artifacts (`fetch_items`) before implementing discovery status extensions.
2. Define transition invariants and idempotency keys before worker code.
3. Make Zero Kelvin a merge gate for pipeline changes.
4. Treat run-state and item-state as separate first-class concerns.
5. Ship manual controls and audit logs early for operational safety.

## 16. Immediate Next Step (pragmatic)
Start with Wave 0 + Wave 1 now:
- Finalize ADR/contract.
- Add missing schema for fetch layer and pipeline actions.
- Keep current seed/discovery behavior stable while introducing migration-safe compatibility.

This gives the highest leverage with lowest operational risk and sets the foundation for real smart-resume/manual-resume implementation.
