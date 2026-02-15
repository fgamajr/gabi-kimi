# Hard Times: Main Goal vs Main Barrier

## Main Goal (from current implementation)
Build a production-grade, restartable legal data pipeline that can reliably run:

`seed -> discovery -> fetch -> ingest`

with operational control via API, auditable runs, and Zero Kelvin reproducibility.

In practical terms, this app is trying to become a dependable ingestion engine where:
- sources are seeded from `sources_v2.yaml`,
- links are discovered and tracked,
- content is fetched and processed,
- documents become searchable/indexable,
- operators can rerun/resume safely after failures.

## Main Barrier (single biggest blocker)
The pipeline is structurally incomplete between discovery and ingestion.

Today:
- `fetch` is still a stub (`src/Gabi.Worker/Jobs/FetchJobExecutor.cs`).
- `ingest` is still a stub in worker execution flow.
- there is no explicit `fetch_items` layer to model real cardinality (`discovery 1:M fetch`, `fetch M:N ingest`).

So the system has good progress in Seed and Discovery orchestration, but it cannot yet enforce true end-to-end phase progression/resume semantics with integrity.

## Why this blocks further progress
Without the real fetch layer and proper phase artifacts:
- smart-resume/manual-resume cannot be trustworthy across all phases,
- phase statuses become ambiguous (link-level status is not enough),
- rollback/compensation logic stays theoretical,
- production confidence is capped, even if Seed/Discovery are stable.

## Bottom line
You are no longer blocked by API shape or seed basics.
You are blocked by core pipeline semantics and missing implementation of the middle of the pipeline.

If this is solved first (`fetch_items` + real fetch + ingest integration), everything else (resume, rollback, fail-safe, canary confidence) becomes much easier and more deterministic.
