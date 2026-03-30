# Reindex V3: Parent Schema and Signal Contract

Owner scope: parent DOU document schema only.

## Current Path

The live DOU parent flow is:

- `src/backend/ingest/dou_processor.py` builds enriched `DouDocument` records
- `src/backend/ingest/es_v3_full.py` maps Mongo docs to ES source fields
- `src/backend/search/es_index_v3_full.json` defines the ES mapping
- `src/backend/ingest/es_indexer.py` syncs Mongo -> ES
- `src/backend/ingest/sync_dou.py` triggers the post-ingest ES sync
- `src/backend/main.py` reads from the alias-backed ES index

Live runtime currently points the alias `gabi_documents` at `gabi_documents_v1`, so v3 work must be treated as a new physical parent index plus alias cutover.

## Parent Schema Additions For V3

Add these parent-level fields to the v3 parent index and mapper:

- `schema_version: keyword` (`"v3"`)
- `pipeline_fingerprint: keyword`
- `signal_version: keyword`
- `entity_dictionary_version: keyword`
- `entity_resolution_version: keyword`
- `chunk_index_version: keyword`
- `chunk_enabled_flag: boolean`
- `freshness_version: keyword`
- `embedding_version: keyword`
- `legal_update_version: keyword`
- `indexed_at: date`
- `updated_at: date`
- `edition_type: keyword`
- `is_extra_edition: boolean`
- `reconstruction_status: keyword`
- `reconstruction_confidence: float` (`0.0..1.0`)
- `part_count: integer`
- `split_segment_index: integer`
- `was_blob_split: boolean`
- `was_page_fragment_merged: boolean`
- `raw_chunk_candidate_count: integer`
- `retained_chunk_count: integer`
- `pruned_chunk_count: integer`
- `pruning_reason: keyword`
- `pruning_audit_version: keyword`

Existing fields that should stay in the v3 parent contract:

- `doc_id`, `logical_doc_id`, `deterministic_hash`
- `identifica`, `normalized_title`, `ementa`, `body_plain`, `search_all`
- `art_type`, `art_type_normalized`, `art_category`, `art_class_hierarchy`
- `issuing_organ`, `organization_path`, `affected_entities_normalized`
- `section`, `edition_number`, `edition_id`, `edition_date`, `page_number`, `pub_date`
- `document_number`, `document_year`
- `primary_signer`, `primary_signer_normalized`, `signers_all_flat`, `has_multiple_signers`, `signature_count`
- `references_flat`, `reference_types`, `reference_count`
- `is_tombstone`, `is_retification`, `is_revocation`
- `parse_quality_score`, `text_language`
- `source_url`, `source_zip`
- `topics`, `topic_primary`

## Explicit Signal Fields

Add these as materialized numeric signals on the parent doc. All are index-time fields, not query logic.

- `authority_score: float` in `0.0..1.0`
- `freshness_score: float` in `0.0..1.0`
- `entity_density: float` in `0.0..1.0`
- `legal_reference_density: float` in `0.0..1.0`
- `legal_action_score: float` in `0.0..1.0`
- `reconstruction_trust_score: float` in `0.0..1.0`
- `time_decay_precomputed: float` in `0.0..1.0`
- `days_since_pub: integer` in `0..20000`
- `freshness_bucket: keyword` with values like `d0_30`, `d31_180`, `d181_730`, `d730_plus`
- `freshness_is_stale: boolean`
- `freshness_last_updated_at: date`
- `freshness_ttl_sec: integer`

Derived relation / rerank preparation fields:

- `relation_action_types: keyword[]`
- `relation_target_keys: keyword[]`
- `procedure_refs_flat: keyword[]`
- `signer_roles_flat: keyword[]`
- `rerank_text: text`
- `lead_passage: text`
- `citation_anchors: keyword[]`
- `article_anchors: keyword[]`
- `rerank_feature_version: keyword`

## Freshness Maintenance

Freshness must be a maintained index field, not a one-shot stamp.

- Recompute `days_since_pub`, `freshness_bucket`, `freshness_score`, `time_decay_precomputed`, and `freshness_is_stale` on a schedule
- Refresh cadence by bucket:
  - `d0_30`: daily
  - `d31_180`: weekly
  - `d181_730`: monthly
  - `d730_plus`: monthly or on-demand only
- Mark stale when `now - freshness_last_updated_at > freshness_ttl_sec`
- Store `freshness_version` so policy changes can be replayed and compared

## Mapping-Diff Tasks Before Rollout

Before building v3, diff the live alias-backed mapping against the expected v3 contract.

1. Dump live mapping for `gabi_documents` and physical index mapping for `gabi_documents_v1`.
2. Diff live vs expected fields:
   - missing fields
   - extra fields
   - type mismatches
   - analyzer mismatches
   - vector mapping mismatches
3. Confirm parent-only contract:
   - no accidental chunk fields in the parent index
   - no missing retrieval-critical fields from the current `es_v3_full` mapper
4. Verify mapper and mapping agree on:
   - field names
   - types
   - nullability/exclusion policy
   - date formats
5. Confirm the sync path writes the new versioned fields:
   - `src/backend/ingest/dou_processor.py`
   - `src/backend/ingest/es_v3_full.py`
   - `src/backend/ingest/es_indexer.py`

## File Touchpoints

- `src/backend/ingest/dou_processor.py` for source enrichment and new parent metadata
- `src/backend/ingest/es_v3_full.py` for Mongo -> ES field mapping
- `src/backend/search/es_index_v3_full.json` for ES mapping additions
- `src/backend/ingest/es_indexer.py` for sync and parity checks
- `src/backend/ingest/sync_dou.py` for ingest-triggered index sync
- `src/backend/main.py` for alias-backed read-path expectations

## Phased Implementation

### Phase 1

- Add versioning and freshness fields to the parent mapper and ES mapping
- Add explicit numeric signal fields with bounded ranges
- Add `rerank_text` and anchor fields for later evidence assembly

### Phase 2

- Wire freshness refresh jobs and stale detection
- Persist version fields in Mongo and propagate them through ES sync
- Add mapping diff checks to the reindex preflight

### Phase 3

- Run parent backfill into `gabi_documents_v2`
- Validate parity and signal completeness
- Alias-swap `gabi_documents` only after parent checks pass
