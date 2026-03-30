# Reindex v3 - Entity Resolution and Embedding Lifecycle

## Scope
- Owns entity/reference resolution persistence, versioning, and chunk embedding lifecycle.
- Explicitly excludes chunking mechanics, alias rollout, and parent schema design beyond fields needed by this slice.

## Current State
- DOU entity extraction is already conservative and flat:
  - `field_extractors.py` extracts normative references, procedure references, signatures, and organ hints.
  - `dou_processor.py` turns those into `NormativeReference`, `ProcedureReference`, `Signature`, `references_flat`, `signers_all_flat`, `affected_entities`, and `search_all`.
- The current ES mapper (`es_v3_full.py`) only forwards flattened fields.
- DOU embeddings are whole-document and append-only-ish:
  - `embed_indexer.py` builds one text blob from `identifica + ementa + texto`
  - writes `embedding`, `embedding_status`, and `embedding_model`
  - uses `pending -> processing -> done/skipped/pending` state transitions
- The TCU embedding pipeline (`tcu_embed.py`) is the closest lifecycle precedent:
  - explicit pending/processing/done/skipped/failed states
  - retry and recovery for stale processing docs

## Required Entity Resolution Contract
- Add a real resolution layer, not just normalized strings.
- Every resolved mention should carry:
  - `entity_surface`
  - `entity_normalized`
  - `entity_canonical_id`
  - `entity_type`
  - `entity_confidence`
  - `resolution_method`
- Persist dictionary state in Mongo, not only in code:
  - `entity_dictionary`
  - `entity_dictionary_releases`
  - `entity_resolution_runs`
- Version every doc against the dictionary snapshot that produced it:
  - `entity_dictionary_version`
  - `entity_resolution_version`
  - `entity_version_applied`
- Canonical IDs should be stable and type-prefixed:
  - `ORG_STF`, `ORG_MINSAUDE`, `LAW_8112`, `DEC_1234`, `PROC_123/2025`
- Collision handling:
  - if the same canonical ID appears with conflicting type or incompatible normalized forms, mark unresolved
  - store a review record instead of silently merging
  - keep the original surface text and aliases for later replay

## Embedding Lifecycle Contract
- Keep embeddings in Elasticsearch for phase 1.
- Add explicit fields for chunk docs and parent docs:
  - `embedding_status`: `pending | processing | done | skipped | failed`
  - `embedding_model`
  - `embedding_version`
  - `vector_id`
  - `embedding_attempts`
  - `embedding_queued_at`
  - `embedding_updated_at`
  - `embedding_error`
- `vector_id` should be deterministic and versioned:
  - `vector_id = {chunk_id}:{embedding_version}`
  - parent docs may use `{logical_doc_id}:{embedding_version}` if parent vectors are enabled later
- Embedding failure behavior:
  - do not block lexical indexing
  - leave the doc searchable without a vector
  - mark `failed` or `pending` with a retry budget
  - use a DLQ for terminal failures and stale claims
- Recovery behavior:
  - stale `processing` docs should be reset by a watchdog job
  - the watchdog should use the same pattern already used in `embed_indexer.py` and `tcu_embed.py`

## Storage and Versioning Recommendation
- Use Mongo as the persistence layer for resolution artifacts and release metadata.
- Recommended collections:
  - `entity_dictionary`
  - `entity_dictionary_releases`
  - `entity_resolution_runs`
  - `embedding_runs`
  - `embedding_dlq`
- Recommended per-run metadata:
  - `pipeline_fingerprint`
  - `source_collection`
  - `dictionary_version`
  - `embedding_version`
  - `chunker_version`
  - `started_at`
  - `finished_at`
- This makes resolution replays deterministic and lets us reprocess only affected docs when dictionaries change.

## Code Touchpoints
- `src/backend/ingest/field_extractors.py`
  - add canonicalization helpers and collision-safe entity normalization
  - expand normative/procedure outputs into canonical-key friendly shapes
- `src/backend/ingest/dou_processor.py`
  - assemble resolved entity records
  - add version tags and canonical IDs to Mongo documents
  - keep current flat fields for backward compatibility
- `src/backend/data/models/document.py`
  - add optional model fields for versioned entity and embedding metadata
- `src/backend/ingest/es_v3_full.py`
  - map versioned entity and embedding fields into ES docs
  - preserve current legacy flat fields during transition
- `src/backend/search/es_index_v3_full.json`
  - add mappings for entity/version/embedding lifecycle fields
  - keep `dynamic: false` behavior, so every field must be declared up front
- `src/backend/ingest/embed_indexer.py`
  - move to chunk-oriented embedding targets when chunk index is available
  - write `embedding_version`, `vector_id`, and explicit failure states
  - preserve lexical indexing on failures
- `src/backend/ingest/tcu_embed.py`
  - reuse its stale-processing and retry patterns as the lifecycle template

## Implementation Order
1. Add Mongo persistence for entity dictionary releases and embedding runs.
2. Add versioned entity fields to the Mongo document shape.
3. Map the new fields into ES via the v3 mapper and mapping.
4. Add embedding lifecycle fields and deterministic `vector_id`.
5. Switch embedding backfill to chunk docs when the chunk index is ready.
6. Add DLQ/replay tooling for failed entity resolution or embedding batches.

## Notes
- Keep person resolution conservative until we have strong disambiguation metadata.
- Do not collapse aliases into a single canonical ID unless the confidence and type match are both high.
- If embedding storage fails, lexical retrieval must still work and the doc must remain eligible for later retry.
