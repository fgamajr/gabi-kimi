# Field Inventory: MongoDB → Elasticsearch v3_full

## Legend
- **ES** = indexed in `v3_full` schema
- **—** = not indexed (internal/pipeline-only)

## All MongoDB fields (from sample document)

| # | MongoDB field | ES v3_full field | Type | Purpose |
|---|---|---|---|---|
| 1 | `_id` | `doc_id` | keyword | Document ID (SHA-256 hash) |
| 2 | `logical_doc_id` | `logical_doc_id` | keyword | Stable dedup ID |
| 3 | `identifica` | `identifica` | text (pt_br_full) | Document title — primary search field |
| 4 | `normalized_title` | `normalized_title` | keyword | Lowercase title for exact match |
| 5 | `ementa` | `ementa` | text (pt_br_full) | Summary/abstract |
| 6 | `texto` | `body_plain` | text (pt_br_folded) | Full body text |
| 7 | `search_all` | `search_all` | text (pt_br_full) | Denormalized: title+body+refs+signers+organs |
| 8 | `art_type` | `art_type` | keyword | Document type (PORTARIA, LEI, etc.) |
| 9 | `art_type_normalized` | `art_type_normalized` | keyword | Lowercase art_type |
| 10 | `art_category` | `art_category` | text+keyword | Org/category path |
| 11 | `art_class_hierarchy` | `art_class_hierarchy` | keyword[] | Classification tree |
| 12 | `issuing_organ` | `issuing_organ` | text+keyword | Issuing government body |
| 13 | `orgao` | (via issuing_organ fallback) | — | Alias for issuing_organ |
| 14 | `organization_path` | `organization_path` | keyword[] | Org hierarchy array |
| 15 | `affected_entities` | — | — | Raw entities (normalized version indexed) |
| 16 | `affected_entities_normalized` | `affected_entities_normalized` | keyword[] | Normalized entity names |
| 17 | `section` | `section` | keyword | DO1, DO2, DO3, DOE |
| 18 | `section_normalized` | (via section fallback) | — | Used as source for section |
| 19 | `section_code` | — | — | Duplicate of section |
| 20 | `edition` | `edition_number` | keyword | Edition identifier |
| 21 | `edition_date` | `edition_date` | date | Publication edition date |
| 22 | `edition_id` | `edition_id` | keyword | Unique edition hash |
| 23 | `edition_type` | — | — | "regular" / "extra" (use is_extra_edition) |
| 24 | `page` | `page_number` | keyword | Page number |
| 25 | `pub_date` | `pub_date` | date | Publication date |
| 26 | `pub_name` | — | — | Duplicate of section (DO1, DO2) |
| 27 | `published_at` | — | — | Duplicate of pub_date |
| 28 | `structured.act_number` | `document_number` | keyword | Act/portaria number |
| 29 | `structured.act_year` | `document_year` | integer | Act year |
| 30 | `structured.signer` | (via primary_signer fallback) | — | Fallback for primary_signer |
| 31 | `primary_signer` | `primary_signer` | keyword | Main signer name |
| 32 | `primary_signer_normalized` | `primary_signer_normalized` | keyword | Lowercase signer |
| 33 | `signers_all_flat` | `signers_all_flat` | keyword[] | All signer names |
| 34 | `signatures` | — | — | Full signature objects (flat fields indexed) |
| 35 | `has_multiple_signers` | `has_multiple_signers` | boolean | Multiple signers flag |
| 36 | `signature_count` | `signature_count` | integer | Number of signers |
| 37 | `references` | — | — | Full reference objects (flat fields indexed) |
| 38 | `references_flat` | `references_flat` | keyword[] | ["portaria 309", "lei 8.112"] |
| 39 | `reference_types` | `reference_types` | keyword[] | ["lei", "portaria"] |
| 40 | `reference_count` | `reference_count` | integer | Number of references |
| 41 | `normative_references` | — | — | Full reference objects (flat fields indexed) |
| 42 | `procedure_references` | — | — | Usually empty |
| 43 | `is_tombstone` | `is_tombstone` | boolean | Document revoked |
| 44 | `is_retification` | `is_retification` | boolean | Is a correction |
| 45 | `is_revocation` | `is_revocation` | boolean | Is a revocation |
| 46 | `is_multipart` | `is_multipart` | boolean | Multi-part document |
| 47 | `multipart_seq` | `multipart_seq` | integer | Part sequence number |
| 48 | `multipart_index` | — | — | Duplicate of multipart_seq |
| 49 | `part_count` | — | — | Low value for search |
| 50 | `parse_quality_score` | `parse_quality_score` | float | Quality ranking signal |
| 51 | `text_language` | `text_language` | keyword | "pt-BR" |
| 52 | `source_url` | `source_url` | keyword | Original DOU page URL |
| 53 | `source_zip` | `source_zip` | keyword | Source ZIP file |
| 54 | `content_hash` | — | — | Internal dedup hash |
| 55 | `content_html` | — | — | Raw HTML (texto has clean text) |
| 56 | `natural_key_hash` | — | — | Internal dedup hash |
| 57 | `occurrence_hash` | — | — | Internal dedup hash |
| 58 | `deterministic_hash` | `deterministic_hash` | keyword | Validation hash |
| 59 | `source_id` | — | — | Internal XML reference |
| 60 | `source_type` | — | — | Always "liferay" |
| 61 | `source_xml_path` | — | — | Internal XML path |
| 62 | `merged_from_xml_paths` | — | — | Internal pipeline data |
| 63 | `xml_name` | — | — | Duplicate of art_type |
| 64 | `art_type_raw` | — | — | Duplicate of art_type |
| 65 | `pdf_page` | — | — | Duplicate of source_url |
| 66 | `identity_strategy` | — | — | Internal pipeline flag |
| 67 | `extraction_method` | — | — | Internal pipeline flag |
| 68 | `reconstruction_status` | — | — | Internal pipeline flag |
| 69 | `reconstruction_confidence` | — | — | Internal pipeline metric |
| 70 | `reconstruction_notes` | — | — | Internal pipeline data |
| 71 | `parse_errors` | — | — | Internal pipeline data |
| 72 | `metadata` | — | — | Internal pipeline metadata |
| 73 | `has_images` | — | — | Low search value |
| 74 | `image_count` | — | — | Low search value |
| 75 | `is_extra_edition` | — | — | Derivable from edition_type |
| 76 | `was_blob_split` | — | — | Internal pipeline flag |
| 77 | `was_page_fragment_merged` | — | — | Internal pipeline flag |
| 78 | `was_sanitized` | — | — | Internal pipeline flag |
| 79 | `indexed_at` | — | — | Mongo-internal timestamp |
| 80 | `updated_at` | — | — | Cursor pagination only |
| 81 | `embedding_status` | — | — | embed_indexer state machine |
| 82 | `embedding_attempts` | — | — | embed_indexer retry counter |

## Summary

| Category | Mongo fields | ES v3_full fields |
|---|---|---|
| **Indexed** | 40 (source) | 40 (ES fields) |
| **Not indexed** | 42 | — |
| **Total** | 82 | 40 |

### Not indexed — by reason

| Reason | Count | Examples |
|---|---|---|
| Internal pipeline/dedup | 18 | content_hash, extraction_method, metadata |
| Duplicate/alias | 12 | orgao, pub_name, xml_name, art_type_raw |
| Nested objects (flat version indexed) | 3 | signatures, references, normative_references |
| Low search value | 5 | has_images, part_count, is_extra_edition |
| Cursor/state machine | 4 | updated_at, indexed_at, embedding_status |
