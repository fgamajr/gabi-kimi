# Reindex V3 Architecture

## Goal

Upgrade the DOU indexing pipeline from a parent-document-only Elasticsearch
index into a versioned, auditable, rollout-safe system that supports:

- richer parent metadata and explicit index-time signals
- deterministic selective chunk indexing
- versioned entity resolution
- optional chunk embeddings after storage and throughput validation

This document is the canonical contract for implementation. Tactical notes and
slice-specific details live under `.planning/reindex-v3/agents/`.

## Current Reality

- MongoDB is the source of truth for DOU parent documents.
- Live search reads the `gabi_documents` alias, which currently points to
  `gabi_documents_v1`.
- The live DOU index is parent-document only. There is no DOU chunk sidecar
  index today.
- The checked-in code supports more fields than the live index currently
  exposes, so mapping drift must be measured before rollout.
- The DOU embedding path exists in code but has no live coverage today.

## Non-Goals

- No query understanding changes.
- No query-time ranking design.
- No source-of-truth migration away from MongoDB in this phase.
- No new vector database in this phase.

## Target Topology

### Parent Index

- Alias: `gabi_documents`
- New physical index: `gabi_documents_v2`
- Unit: one logical DOU act/document per ES doc
- `topics` and `topic_primary` are restored in this contract and are not deferred

### Chunk Index

- Alias: `gabi_document_chunks`
- New physical index: `gabi_document_chunks_v1`
- Unit: one deterministic evidence chunk per ES doc

### Source of Truth and Propagation

- MongoDB remains authoritative.
- Writes land in Mongo first.
- Elasticsearch updates happen asynchronously from Mongo-backed events.
- ES is always rebuildable from Mongo + versioned config state.

## Phase 0: Mapping Reality Gate

Before any reindex:

1. Dump the live mapping for `gabi_documents`.
2. Diff it against the expected parent schema.
3. Produce a report with:
   - missing fields
   - extra live fields
   - type mismatches
   - analyzer/setting mismatches
4. Freeze alias ownership as contract:
   - `gabi_documents` for parent reads
   - `gabi_document_chunks` for chunk reads

## Parent Schema Additions

### Operational Metadata

- `schema_version`
- `pipeline_fingerprint`
- `signal_version`
- `entity_dictionary_version`
- `entity_resolution_version`
- `chunker_version`
- `embedding_version`
- `freshness_version`
- `chunk_index_version`
- `chunk_enabled_flag`
- `legal_update_version`

### Existing Mongo-Derived Fields Promoted to ES

- `indexed_at`
- `updated_at`
- `edition_type`
- `is_extra_edition`
- `reconstruction_status`
- `reconstruction_confidence`
- `part_count`
- `split_segment_index`
- `was_blob_split`
- `was_page_fragment_merged`

### Explicit Index-Time Signals

All numeric signals are stored as normalized `float` values in `0..1` unless
otherwise stated.

- `authority_score`
- `entity_density`
- `legal_reference_density`
- `legal_action_score`
- `reconstruction_trust_score`
- `freshness_score`
- `time_decay_precomputed`

### Freshness Maintenance Fields

- `days_since_pub`
- `freshness_bucket`
- `freshness_last_updated_at`
- `freshness_ttl_sec`
- `freshness_is_stale`

### Reranker Feed Fields

- `rerank_text`
- `lead_passage`
- `citation_anchors`
- `article_anchors`
- `rerank_feature_version`

### Legal Relation Fields

- `relation_action_types`
- `relation_target_keys`
- `procedure_refs_flat`
- `signer_roles_flat`
- `targets_prior_norm`

## Entity Resolution Contract

Entity resolution is a dedicated stage between enrichment and ES mapping.

### Per-Mention Outputs

- `entity_surface`
- `entity_normalized`
- `entity_canonical_id`
- `entity_type`
- `entity_confidence`
- `resolution_method`

### Flattened Retrieval Fields

- `org_canonical_ids`
- `org_aliases`
- `person_canonical_ids`
- `person_role_keys`
- `norm_canonical_ids`
- `procedure_canonical_ids`

### Persistence and Versioning

- Entity dictionaries and releases are persisted in Mongo collections.
- Every indexed doc stores the dictionary and resolution versions that were
  applied.
- Canonical ID collisions must be detected and unresolved mentions must be
  routed to review instead of being force-merged.

## Chunking Contract

### Eligibility

Chunk a parent doc only if one of the following is true:

- `texto_length > 1500`
- `is_multipart`
- `was_blob_split`
- `was_page_fragment_merged`
- structural HTML markers indicate meaningful sections

### Hard Limits

- `MAX_CHUNKS_PER_DOC = 8`
- `HARD_LIMIT = 12`

### Deterministic Pruning

If raw chunk candidates exceed the limits:

1. Pre-truncate candidates at `HARD_LIMIT`.
2. Compute deterministic priority.
3. Sort by:
   - `priority DESC`
   - `char_start ASC`
   - `chunk_seq ASC`
4. Keep the first `MAX_CHUNKS_PER_DOC`.

Priority components:

- title/ementa chunk boost
- normative/article section boost
- `chunk_importance_score`
- `chunk_entity_density`
- `chunk_legal_density`
- normalized reference density

### Hashes

- `chunk_manifest_hash`
  - based only on chunk boundaries, offsets, order, and `chunker_version`
- `chunk_feature_hash`
  - based on enrichment-derived fields and `pipeline_fingerprint`

This keeps chunk structure reproducible even when enrichers evolve.

### Chunk Fields

- `chunk_id`
- `parent_doc_id`
- `logical_doc_id`
- `chunk_seq`
- `chunk_type`
- `char_start`
- `char_end`
- `text`
- `rerank_text`
- copied parent metadata needed for retrieval
- `chunk_quality_score`
- `chunk_importance_score`
- `chunk_entity_density`
- `chunk_legal_density`
- `chunk_reference_count`
- `chunk_manifest_hash`
- `chunk_feature_hash`

## Truncation and Auditability

No chunk pruning may be silent.

For every pruned doc, store:

- `raw_chunk_candidate_count`
- `retained_chunk_count`
- `pruned_chunk_count`
- `pruning_reason`
- `pruning_audit_version`

Persist a pruning ledger in Mongo keyed by:

- `doc_id`
- `chunker_version`
- `chunk_manifest_hash`

## Embedding Contract

Embeddings are phase 3, not phase 1.

- The first chunk rollout is lexical-only.
- Only after storage and throughput gates pass do we enable chunk embeddings.
- Vectors stay in Elasticsearch in this phase.

Chunk embedding lifecycle fields:

- `embedding_status = pending | done | failed | skipped`
- `embedding_version`
- `embedding_last_attempt_at`
- `embedding_attempt_count`
- `embedding_error_code`
- `vector_id`

`vector_id` must be deterministic from `chunk_id + embedding_version`.

If embedding fails, the chunk remains lexically indexed and queryable.

## Legal Update Integrity

Legal updates must trigger downstream recompute events for affected docs/chunks
when a new act appears to revoke, retify, alter, or otherwise target prior
norms. This phase stores hints and recompute hooks, not authoritative vigency.

## Resource Governor

Every worker must run under explicit limits:

- max parent indexing QPS
- max chunk generation QPS
- max concurrent embedding batches
- max bulk size
- heap and memory guard thresholds
- pause conditions on rejection rate, queue lag, or DLQ growth

## Rollout Principle

Roll out in three safe stages:

1. Parent reindex and alias cleanup
2. Chunk sidecar rollout
3. Optional embedding rollout

Each stage must be independently reversible.
