# CDC + Rollout Note

## Scope
- Use MongoDB as the source of truth for DOU ingest.
- Keep Elasticsearch as an eventually consistent projection, rebuilt from Mongo-backed state.
- Do not make ingest success depend on synchronous ES writes.

## Current Flow
- `sync_dou.py` downloads XML ZIPs, reconstructs documents, and bulk upserts them into MongoDB.
- `es_indexer.py` reads Mongo by `updated_at + _id` cursor, maps docs with `mongo_to_es_v3_full()`, and bulk indexes into ES.
- `es_indexer.py` already has a file lock, DLQ collection, retry logic, and index creation/alias support.
- Live app/search code uses the alias `gabi_documents`, so alias swaps are the reader-facing cutover boundary.

## Propagation Options
### Preferred: Mongo outbox
- Write the parent doc and an outbox event in Mongo as the durable source of truth for downstream propagation.
- Add an outbox collection keyed by `event_id` with `doc_id`, `logical_doc_id`, `content_hash`, `event_type`, `pipeline_version`, and target version fields.
- A worker polls the outbox with an idempotent cursor and updates ES parent/chunk indices independently.

### Compatible fallback: Mongo change streams
- If the deployment topology supports change streams reliably, consume insert/update events from Mongo and translate them into ES index updates.
- Still persist a checkpoint/outbox state so the worker can replay after outages.

### Not recommended for phase 1
- Direct Mongo-to-ES dual-write inside the ingest path.
- Any synchronous Mongo + ES success contract.

## Worker Requirements
- Workers must be idempotent on `event_id + target_index_version`.
- Workers must skip no-op rewrites when `content_hash` and release versions have not changed.
- Workers must be safe to retry after partial bulk failures.
- Workers must write parent and chunk projections independently so one failure does not block the other.
- Workers must preserve deterministic ordering for batch processing and cursor advancement.

## Alias Swap Plan
- Build `gabi_documents_v2` as the new parent index.
- Keep `gabi_documents_v1` intact until parity checks pass.
- Backfill `gabi_documents_v2` from Mongo first, then run a soak period.
- Swap `gabi_documents` to `gabi_documents_v2` with one atomic `_aliases` request.
- Keep the old index available for rollback until the new one proves stable.

## Rollback
- Parent rollback is alias reversal only.
- Chunk rollback is disabling the chunk release flag and removing the chunk alias from readers.
- Keep old cursors and release versions separate so rollback does not corrupt incremental state.
- Do not delete the previous parent index until the new one has survived soak, parity, and reindex replay checks.

## DLQ Ownership
- Parent indexer owns its own DLQ collection.
- Chunk indexer owns a separate DLQ collection keyed by `parent_doc_id + chunker_version + chunk_id`.
- Embedding worker owns a separate embedding DLQ/state trail.
- Each DLQ entry must include the release versions, `doc_id`, failure class, retry count, and last error.
- DLQ replay must be version-aware and safe to run repeatedly.

## Operational Gates
- Mapping diff must pass before any backfill.
- Parent parity must pass before alias swap:
  - count parity
  - deterministic hash parity
  - sampled field parity
- Chunk rollout must be blocked unless the pilot validates:
  - chunk multiplier stays within budget
  - pruning remains deterministic
  - store growth stays within capacity
  - chunk DLQ remains bounded
- Embeddings stay disabled until chunk indexing is stable and the throughput ceiling is measured.
- Any rollout step must stop on sustained ES bulk failures, DLQ growth, or resource pressure.

## Implementation Touchpoints
- `src/backend/ingest/sync_dou.py`
- `src/backend/ingest/es_indexer.py`
- new outbox/change-stream worker module
- new release/version collections in Mongo
- new parent and chunk index mappings
