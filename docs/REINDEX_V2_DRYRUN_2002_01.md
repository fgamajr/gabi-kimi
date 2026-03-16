## Reindex V2 Dry-Run: January 2002 Sample

Date: 2026-03-16

Scope:
- `ops/data/raw_export/2002/01/S01012002.zip`
- `ops/data/raw_export/2002/01/S02012002.zip`
- `ops/data/raw_export/2002/01/S03012002.zip`

Target canary surfaces:
- Mongo collection: `documents_v2_dryrun`
- Elasticsearch index: `gabi_documents_v2_minimal_dryrun`
- ES schema: `v2_minimal`

### What Ran

1. Rebuilt backend image with the new ZIP-wide reconstruction parser.
2. Dropped `documents_v2_dryrun`.
3. Reingested the 3 ZIPs through `DouProcessor.process_zip()`.
4. Backfilled `gabi_documents_v2_minimal_dryrun`.
5. Refreshed ES stats and inspected signer quality.

### Dry-Run Results

- `S01012002.zip`: `4,253` logical documents
- `S02012002.zip`: `3,069` logical documents
- `S03012002.zip`: `5,771` logical documents
- Total written: `13,093`
- Final Mongo count: `13,045`
- Final ES count: `13,045`
- Count delta: `0`

The write count is higher than final count because some logical documents were upserted more than once during replay.

### Reconstruction Signals

- `was_page_fragment_merged`: confirmed in sample data
- `was_blob_split`: confirmed in sample data
- `is_multipart`: parser path supports it, but this local sample did not include true multipart `-1/-2/...` XML families
- index-like documents were detected and skipped

### Signer Quality

Before the signer fix, placeholder office references such as `(Of. El. nº 52/2002)` leaked into `primary_signer`.

After the fix:
- placeholder `primary_signer`: `0`
- docs with placeholder entries inside `signatures[]`: `3,781`
- docs with at least one searchable signer in `signers_all_flat`: `5,359`
- docs where placeholders were preserved in `signatures[]` but `primary_signer` became `null`: `1,940`

Current signer contract:
- keep placeholder signatures in `signatures[]` for provenance
- exclude placeholders from `primary_signer`
- exclude placeholders from `signers_all_flat`
- exclude placeholders from `search_all`

### ES Canary Status

The v2 minimal ES canary is consistent after refresh:

- cluster status: `green`
- Mongo count: `13,045`
- ES count: `13,045`
- deleted docs: `0`

### What This Validates

- ZIP-wide parsing works
- page-fragment merge path works on real data
- blob split path works on real data
- index skipping works on real data
- v2 Mongo canary collection path works
- v2 minimal ES canary path works
- signer placeholder filtering works

### Real Multipart Regression Fixture

The repo contains real INLabs XML fixtures for a true multipart family:

- `600_20260227_23639293-1.xml`
- `600_20260227_23639293-2.xml`

Validation path:

- built a temporary ZIP from the real fixture XMLs plus one single-part neighbor
- ran the current `DouProcessor.process_zip()` against it
- verified:
  - output logical documents: `2`
  - merged multipart doc id: `23639293`
  - `is_multipart: true`
  - `part_count: 2`
  - `merged_from_xml_paths` includes both `-1` and `-2`
  - merged HTML contains `multipart-break`
  - `source_url` preserves the `pdfPage` query parameters

Regression script:

- [test_reindex_v2_multipart.py](/home/parallels/dev/gabi-kimi/ops/test_reindex_v2_multipart.py)

### Remaining Gaps

1. True multipart reconstruction is validated on real XML fixtures, but not yet on a locally downloaded production ZIP from the current registry snapshot.
2. Tombstone / legal lifecycle logic is still scaffolded, not validated.
3. The broader full-field ES expansion is intentionally deferred until after P0 canary confidence improves.

### Next Recommended Step

Find a real ZIP containing multipart sibling XML files and run the same canary flow against it:

- ingest into `documents_v2_dryrun`
- verify merged `logical_doc_id`
- confirm `part_count > 1`
- confirm one legal act no longer appears as multiple ES documents
