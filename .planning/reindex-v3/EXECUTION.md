# Reindex V3 Execution

## Goal

Turn the reindex-v3 architecture into an implementation sequence that is:

- safe to execute in a dirty repo
- safe to roll back
- measurable at each stage

## Canonical Ownership

- Coordinator docs:
  - `.planning/reindex-v3/ARCHITECTURE.md`
  - `.planning/reindex-v3/EXECUTION.md`
  - `.planning/reindex-v3/RISKS.md`
- Specialist notes:
  - `.planning/reindex-v3/agents/schema-signals.md`
  - `.planning/reindex-v3/agents/chunking.md`
  - `.planning/reindex-v3/agents/cdc-rollout.md`
  - `.planning/reindex-v3/agents/entities-embeddings.md`

The coordinator docs are the source of truth if agent notes disagree.

## Stage A: Parent Reindex

### A1. Reality Gate

- Dump live ES mapping for `gabi_documents`
- Diff with expected schema
- Record field and type mismatches
- Freeze alias contract

Command:

```bash
docker compose exec -T backend python -m src.backend.ingest.reindex_v3 mapping-diff \
  --report /workspace/.planning/reindex-v3/mapping-diff-live-vs-parent-v2.json
```

Current observed baseline:

- `gabi_documents` resolves to `gabi_documents_v1`
- live parent mapping is missing `48` fields from the frozen parent-v2 contract
- shared fields currently match by type and compared field attributes
- `topics` and `topic_primary` are explicitly part of the restored parent-v2 contract

Exit criteria:

- mapping diff exists
- no unresolved blocker on parent-schema compatibility

### A2. Parent Schema and Mapper

- define the parent v2 mapping
- update parent mapper to emit new fields
- add version fields and signal fields
- add freshness maintenance fields

Exit criteria:

- parent mapper emits full v2 contract
- sample docs validate locally

### A3. Parent Backfill Path

- create `gabi_documents_v2`
- backfill from Mongo using the new mapper
- preserve separate cursor and lock state from current live workers

Implemented command surface:

```bash
docker compose exec -T backend python -m src.backend.ingest.reindex_v3 parent-backfill \
  --index gabi_documents_v2 \
  --recreate-index --yes-destroy
```

Supporting commands:

```bash
docker compose exec -T backend python -m src.backend.ingest.reindex_v3 parent-stats \
  --index gabi_documents_v2

docker compose exec -T backend python -m src.backend.ingest.reindex_v3 parent-verify \
  --index gabi_documents_v2 --sample-size 100
```

Smoke validation completed:

- throwaway physical index: `gabi_documents_v2_smoke`
- command: `parent-backfill --index gabi_documents_v2_smoke --recreate-index --yes-destroy --batch-size 50 --max-batches 1`
- result: index created successfully and `50` parent-v2 docs indexed
- alias state: unchanged
- parent DLQ count after smoke run: `0`

Exit criteria:

- parent count parity passes
- sampled field parity passes
- deterministic hash parity passes

### A4. Parent Cutover

- execute a single atomic `_aliases` swap from v1 to v2
- keep v1 intact for rollback

Exit criteria:

- reads resolve through `gabi_documents -> gabi_documents_v2`
- rollback path is tested and documented

## Stage B: Chunk Sidecar

### B1. Chunker Contract

- implement chunk eligibility
- implement deterministic chunk typing and boundaries
- implement hard caps and pruning order
- emit manifest and feature hashes
- emit pruning audit data

Exit criteria:

- same input doc + same versions yields same chunk manifest
- pruning is deterministic and auditable

### B2. Chunk Mapping and Worker

- create `gabi_document_chunks_v1`
- implement chunk index writer with its own cursor/lock
- emit version fields, lineage, and chunk scores

Exit criteria:

- pilot chunk docs index cleanly
- chunk DLQ path exists

### B3. Chunk Pilot

Measure on a bounded sample:

- percent docs chunked
- average chunks per chunked doc
- p95/p99 chunks per doc
- projected total chunk docs
- projected ES store growth
- pruning rate
- CPU time per chunked doc

Exit criteria:

- projected total chunk docs <= 25M
- average chunks per chunked doc <= 5
- p99 chunks per doc <= 8 before deterministic pruning

### B4. Chunk Rollout

- run full chunk backfill only if pilot gates pass
- expose `gabi_document_chunks` only when the active release sets
  `chunk_enabled_flag = true`

Exit criteria:

- chunk alias active
- rollback path tested

## Stage C: Async Propagation and Replay

### C1. Event Model

- define Mongo-backed outbox/change-stream event schema
- define worker idempotency contract
- define replay semantics

Exit criteria:

- event schema documented
- workers can replay by version and cursor

### C2. DLQ Consumers

Add and validate consumers for:

- parent indexing DLQ
- chunk indexing DLQ
- embedding DLQ

Exit criteria:

- failed batches can be replayed without manual data edits
- alert thresholds are documented

## Stage D: Optional Chunk Embeddings

### D1. Embedding Lifecycle

- add lifecycle fields and deterministic `vector_id`
- ensure chunks remain usable when embedding fails

### D2. Embedding Pilot

Pilot only high-priority chunks:

- title/ementa chunks
- highest chunk importance
- highest legal-reference density

Measure:

- throughput
- queue lag
- failure rate
- ES store growth

Exit criteria:

- throughput fits maintenance window
- failure handling works
- no blocker from resource guardrails

## Validation Checklist

### Parent

- count parity
- sampled field parity
- deterministic hash parity
- mapping diff resolved

### Chunk

- deterministic manifest generation
- deterministic pruning
- pruning ledger entries present
- chunk lineage valid

### Entities

- dictionary version persisted
- collision cases are flagged instead of silently merged

### Freshness

- stale detection works from `freshness_last_updated_at` and TTL
- refresh policy is documented and schedulable

### Operations

- alias rollback tested
- DLQ replay tested
- queue lag visible

## Immediate Next Tasks

1. freeze parent-v2 field contract now that the first mapping diff exists
2. define outbox/change-stream event schema
3. define chunk manifest contract
4. define version fields shared by parent/chunk docs
5. wire the new parent-v2 mapper/mapping into a dedicated parent backfill path
