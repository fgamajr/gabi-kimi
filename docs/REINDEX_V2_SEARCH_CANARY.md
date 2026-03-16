# Reindex V2 Search Canary

This document records the first field expansion on top of the locked
`v2_minimal` contract.

## Purpose

Keep the minimal 16-field canary intact while adding the next BM25-oriented
retrieval fields to a separate opt-in schema for query-quality evaluation.

## Schema

- ES schema: `v2_search`
- mapping: [es_index_v2_search.json](/home/parallels/dev/gabi-kimi/src/backend/search/es_index_v2_search.json)
- mapper: [es_v2_search.py](/home/parallels/dev/gabi-kimi/src/backend/ingest/es_v2_search.py)

## Promoted Fields

All `v2_minimal` fields, plus:

- `normalized_title`
- `text_language`
- `search_all`
- `references_flat`
- `reference_types`
- `reference_count`
- `signers_all_flat`
- `has_multiple_signers`
- `signature_count`
- `organization_path`
- `art_class_hierarchy`
- `document_number`
- `document_year`
- `affected_entities_normalized`

## Why These Fields

- `search_all` improves BM25 recall across title, summary, body, references,
  signers, and affected entities without embeddings.
- `normalized_title` supports exact-title boosting and dedup checks.
- signer/reference/entity fields support legal-style filtering and reranking.
- hierarchy and act-number fields improve known-item retrieval.

## Command

```bash
docker compose exec -T backend python -m src.backend.ingest.reindex_v2 local-canary \
  --schema v2_search \
  --glob 'ops/data/raw_export/2002/01/*.zip' \
  --mongo-collection documents_v2_canary \
  --es-index gabi_documents_v2_search_canary \
  --cursor /tmp/es_sync_cursor_v2_search_canary.json \
  --drop-collection \
  --recreate-index
```
