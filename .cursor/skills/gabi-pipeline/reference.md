# GABI Pipeline — Reference

- **AGENTS.md** (repo root): Async Patterns, Invariants, Key Files (`sources_v2.yaml`), Fetch SSRF mitigation.
- **Pipeline state and backpressure:** `SourcePipelineStateEntity`, `IsSourcePausedOrStoppedAsync`, `PipelineBackpressureConfig`, `PipelineEmbedBatchConfig` (from `sources_v2.yaml` defaults).
- **Queues:** Hangfire queues include `seed`, `discovery`, `fetch`, `ingest`, `embed`, `default`. Single-in-flight per source for discovery/fetch/ingest; embed_and_index can run multiple jobs per source.
- **Zero Kelvin E2E:** `./tests/zero-kelvin-test.sh` — validates pipeline from scratch; use for regression after pipeline changes.

Use this file when you need exact type names or script paths; the main skill keeps only the rules needed for typical pipeline edits.
