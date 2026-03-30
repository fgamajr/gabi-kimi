# Reindex V3 Risks

## Critical Risks

### 1. Mapping Drift Between Code and Live ES

The live alias-backed DOU index does not fully match the checked-in mapping
contract. Reindex work can silently target the wrong assumptions unless the
live mapping is dumped and diffed first.

Mitigation:

- mandatory phase-0 mapping diff
- do not start parent backfill until diff blockers are resolved

### 2. Silent Inconsistency Between Mongo and ES

If Elasticsearch is updated synchronously in the ingest path or if propagation
semantics are undefined, Mongo and ES can diverge without a safe replay path.

Mitigation:

- Mongo-only source-of-truth contract
- async propagation from outbox/change-stream events
- idempotent workers

### 3. Chunk Explosion

Selective chunking still risks large ES growth if caps and pruning are not
enforced deterministically.

Mitigation:

- `MAX_CHUNKS_PER_DOC = 8`
- `HARD_LIMIT = 12`
- pilot gates on projected total chunk docs, average, and p99 chunk counts

### 4. Non-Deterministic Chunk Manifests

If chunk selection depends on mutable enrichment without separating structural
and feature hashes, reindexes become irreproducible.

Mitigation:

- `chunk_manifest_hash` based only on boundaries and offsets
- `chunk_feature_hash` based on enrichment outputs
- deterministic pruning order

### 5. Legal Update Integrity

Retifications, revocations, and other legal updates can leave derived evidence
stale if affected parents/chunks are not recomputed.

Mitigation:

- store legal relation hints
- emit downstream recompute events
- version legal update handling

### 6. Irreversible Truncation Without Audit

Chunk pruning can discard legally important clauses if the system does not
preserve a pruning ledger.

Mitigation:

- pruning ledger in Mongo
- pruning counts and reason stored per doc
- replay by `doc_id + chunker_version + chunk_manifest_hash`

### 7. Entity Canonical ID Collisions

Legal entities can be incorrectly merged if canonical IDs are assigned without
conflict detection and persistence versioning.

Mitigation:

- dictionary releases in Mongo
- `entity_version_applied` on docs
- collision detection with review path

### 8. Freshness Drift

Any freshness-derived score can silently degrade if recomputation is not
scheduled and staleness is not surfaced.

Mitigation:

- `freshness_last_updated_at`
- `freshness_ttl_sec`
- `freshness_is_stale`

### 9. Embedding Pipeline Fragility

Embeddings are useful but not required for lexical chunk utility. If failures
block indexing, rollout risk rises sharply.

Mitigation:

- embeddings are phase 3
- lexical chunk rollout first
- `embedding_status` lifecycle fields
- chunk remains searchable without vector

### 10. Resource Collapse on Single-Node ES

Chunk growth, embeddings, and heavy backfills can exhaust ES memory or create
rejection storms.

Mitigation:

- explicit resource governor
- worker throttling
- stop conditions on rejection rate, lag, and memory pressure

## Rollback Risks

### Parent Rollback

Risk:

- partial cutover or non-atomic alias manipulation

Mitigation:

- one `_aliases` call only
- keep v1 intact until rollback risk is retired

### Chunk Rollback

Risk:

- chunk consumers assume chunk availability after alias removal

Mitigation:

- `chunk_enabled_flag`
- `chunk_index_version`
- disable consumers before alias removal

## Operational Watchlist

- parent indexing DLQ size
- chunk indexing DLQ size
- embedding DLQ size
- queue lag
- ES rejection rate
- projected chunk count
- projected ES store growth
- embedding throughput

## Open Questions To Close During Execution

- whether Change Streams are available in the deployed Mongo topology
- where the mapping diff command/report should live
- whether chunk pruning audits need a dedicated API/report path
- whether legal-update invalidation should be immediate or batched
