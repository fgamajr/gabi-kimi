# Source Conversion Matrix (v0)

Date: 2026-02-24

## Summary

- Total sources: 34
- text_ready: 10
- metadata_only_until_converter: 17
- metadata_only_until_transcript: 0
- disabled: 7

## Observed Root Causes (from latest snapshot)

- fetch_skipped_format: 16
- ok: 9
- pipeline_disabled_or_source_disabled: 7
- empty_content_after_fetch: 1
- no_documents_materialized: 1

## Priority Batch (before external indexing)

1. json_api empty-content fallback + metadata_only classification.
2. pdf/html/json converter path for link_only sources with pipeline enabled.
3. ingest gate: process only text_ready; keep metadata_only out of failure bucket.
4. zero-kelvin assertions: enforce ingest for text_ready only.