# Chunking Implementation Note

## Scope
Deterministic DOU chunking for the reindex-v3 effort, based on the current
`dou_processor.py` and `reconstruction.py` flow and the existing BTCU chunk
pattern in `tcu_btcu_processor.py` / `tcu_btcu_ingest.py`.

## Current Code Reality
- DOU today is parent-doc oriented. `DouProcessor.process_zip()` reconstructs
  multipart XML, merges page fragments, optionally splits oversized blobs, then
  emits one `DouDocument` per logical act.
- Existing chunk-adjacent behavior is limited to:
  - multipart merge via `group_and_merge_articles()`
  - page-fragment merge via `merge_page_fragments()`
  - blob split via `split_blob_reconstructed()`
- BTCU is the reference pattern for flat chunk docs:
  - chunk docs have `parent_*_id`, `chunk_sequence`, `deterministic_hash`
  - ingest is chunk-first and ES-stored, not parent-child joined

## Chunking Rules
- Chunk eligibility should be deterministic and narrow in phase 1:
  - `texto_length > 1500`
  - `is_multipart`
  - `was_blob_split`
  - `was_page_fragment_merged`
  - strong structural markers in HTML or reconstructed text
- Preferred chunk types:
  - `title`
  - `ementa`
  - `article_block`
  - `annex_block`
  - `signature_block`
  - `reference_block`
  - `table_like_block`
- Keep chunks structure-first. Do not invent semantic chunk boundaries that
  cannot be reproduced from the stored parent doc.

## Hard Limits
- Add explicit caps:
  - `MAX_CHUNKS_PER_DOC = 8`
  - `HARD_LIMIT = 12`
- If a document produces more than `HARD_LIMIT` candidates, truncate the
  candidate set before scoring.
- If more than `MAX_CHUNKS_PER_DOC` remain, keep only the top-ranked chunks.
- Deterministic pruning order:
  - `priority DESC`
  - `char_start ASC`
  - `chunk_seq ASC`
- Priority should be computed from stable, index-time features only:
  - title / ementa presence
  - normative section presence
  - legal reference density
  - entity density
  - structural importance
  - parent authority / reconstruction confidence

## Hashing And Auditability
- Separate two hashes:
  - `chunk_manifest_hash`: based only on parent text, offsets, chunk order,
    `chunker_version`, and boundary decisions
  - `chunk_feature_hash`: based on enrichment-derived features such as entity
    and reference outputs
- This keeps structural determinism independent from extractor evolution.
- Add a pruning ledger collection so truncation is auditable:
  - `doc_id`
  - `logical_doc_id`
  - `chunker_version`
  - `pipeline_fingerprint`
  - raw candidate count
  - retained count
  - pruned count
  - pruning reason
  - retained chunk IDs

## Code Touchpoints
- `src/backend/ingest/reconstruction.py`
  - expose a chunk manifest builder on top of reconstructed articles
  - make structural boundaries deterministic and versioned
- `src/backend/ingest/dou_processor.py`
  - emit chunk candidates from `ReconstructedArticle`
  - preserve source lineage, offsets, and reconstruction flags
  - write parent-level chunk metadata back to Mongo
- `src/backend/ingest/es_indexer.py`
  - support a second ES target for chunk docs
  - keep the parent sync path unchanged
- `src/backend/ingest/embed_indexer.py`
  - embed chunk docs only after chunk docs exist in ES
  - preserve `embedding_status` and retry state per chunk
- `src/backend/search/es_index_v3_full.json`
  - add chunk-friendly fields to the parent schema only if they are needed for
    parent-level evidence and rollback
- New chunk index mapping file
  - define `chunk_id`, `parent_doc_id`, `chunk_seq`, `chunk_type`, offsets,
    `chunk_manifest_hash`, `chunk_feature_hash`, and embedding fields

## Implementation Order
1. Make chunk manifest generation deterministic in `reconstruction.py`.
2. Emit chunk candidates in `dou_processor.py` and persist pruning ledger data.
3. Add the chunk index mapping and a chunk ES writer.
4. Add chunk embedding backfill after chunk indexing is stable.
5. Validate with a small pilot corpus before enabling full historical backfill.

## Acceptance Checks
- Same parent content must always yield the same chunk manifest hash for the
  same `chunker_version`.
- Chunk pruning must be reproducible across reindex runs.
- No parent document should exceed the hard cap without recording a pruning
  ledger entry.
- BTCU-style chunk docs remain the model for shape and operational behavior.
