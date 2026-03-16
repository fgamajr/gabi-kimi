# Reindex V2 Execution Plan

## Goal

Rebuild Elasticsearch from zero without mutating the existing raw Mongo corpus,
while fixing the two root problems:

- missing XML metadata and derived search fields
- broken multipart/page-fragment document boundaries

## Phase Order

### Phase 0

Restore logical document boundaries.

- parse all XMLs in a ZIP before emitting any logical document
- group filename/idMateria multipart fragments
- merge page-break continuation fragments
- filter index/table-of-contents artifacts before indexing
- split blob XMLs that contain multiple acts after reconstruction
- emit `logical_doc_id`, `is_multipart`, `multipart_seq`
- keep source provenance for every merged record

Exit criteria:

- golden sample of multipart acts passes manual QA
- no false merges in the curated validation set

### Phase 1

Produce the locked 16-field minimum contract.

- normalize `organ`, `section`, `doc_type`
- compute `edition_id` and `edition_date`
- compute `deterministic_hash`
- extract `primary_signer`
- assign `parse_quality_score`
- emit `source_url` when available

Exit criteria:

- minimum-v2 mapper emits all 16 fields
- truncation and timezone policies are frozen

### Phase 2

Expand the source document model.

- add full XML/article attributes
- add titles, notes, class hierarchy, IDs, and provenance hashes
- add structured signatures and legal references
- preserve raw and normalized variants side by side
- preserve DOU-specific sanitization and fragment-detection heuristics

Exit criteria:

- Mongo v2-enriched records are stable
- missing-field gap from v1 is closed at source level

### Phase 3

Expand ES beyond the minimum canary shape.

- add approved secondary search fields
- keep heavy, noisy, or low-confidence fields out of the first cutover
- only promote fields after query-quality verification

## Repo Artifacts

- field contract: [REINDEX_V2_MINIMUM.md](/home/parallels/dev/gabi-kimi/docs/REINDEX_V2_MINIMUM.md)
- minimum ES mapping: [es_index_min_v2.json](/home/parallels/dev/gabi-kimi/src/backend/search/es_index_min_v2.json)
- minimum ES mapper: [es_v2_minimal.py](/home/parallels/dev/gabi-kimi/src/backend/ingest/es_v2_minimal.py)
- local canary orchestration: [reindex_v2.py](/home/parallels/dev/gabi-kimi/src/backend/ingest/reindex_v2.py)

## Local Canary Command

```bash
docker compose exec -T backend python -m src.backend.ingest.reindex_v2 local-canary \
  --glob 'ops/data/raw_export/2002/01/*.zip' \
  --mongo-collection documents_v2_dryrun \
  --es-index gabi_documents_v2_minimal_dryrun \
  --cursor /tmp/es_sync_cursor_v2_dryrun.json \
  --drop-collection \
  --recreate-index \
  --report /tmp/reindex_v2_dryrun_report.json
```

## Runtime Rule

The live application remains on ES v1 until the minimum-v2 canary passes. The
new mapping and mapper are opt-in and should only be used through explicit
schema selection in the indexer.
