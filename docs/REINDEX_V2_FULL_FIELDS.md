# Reindex V2 Full Field Contract

This is the approved parse/store target for the v2 ingest redesign.

## Raw Source Fields

- `source_zip`
- `source_xml_path`
- `xml_name`
- `source_file`
- `source_type`
- `raw_id`
- `id_materia`
- `id_oficio`
- `name`
- `pub_name`
- `pub_date`
- `edition_number`
- `number_page`
- `pdf_page`
- `art_type_raw`
- `art_category`
- `art_class_raw`
- `art_size`
- `art_notes`
- `highlight_type`
- `highlight_priority`
- `highlight`
- `highlight_image`
- `highlight_image_name`
- `identifica`
- `ementa`
- `data_text`
- `titulo`
- `sub_titulo`
- `texto_html`
- `texto_plain`
- `autores_xml`

## Normalized Metadata

- `section`
- `section_code`
- `section_normalized`
- `art_type`
- `art_type_normalized`
- `issuing_organ`
- `organization_path`
- `organization_path_string`
- `art_class_hierarchy`
- `is_extra_edition`
- `is_retification`
- `is_revocation`
- `canonical_source_url`

## Identity And Provenance

- `_id`
- `logical_doc_id`
- `document_number`
- `document_year`
- `natural_key_hash`
- `content_hash`
- `occurrence_hash`
- `edition_id`
- `identity_strategy`
- `listing_sha256`
- `zip_sha256`
- `zip_filename`
- `zip_size_bytes`
- `xml_count_in_zip`
- `image_count_in_zip`

## Multipart And Reconstruction

- `is_multipart`
- `multipart_index`
- `multipart_seq`
- `part_number`
- `part_count`
- `merged_from_xml_paths`
- `was_page_fragment_merged`
- `was_blob_split`
- `split_segment_index`
- `continuation_of`
- `continued_by`
- `reconstruction_status`
- `reconstruction_notes`
- `reconstruction_confidence`

## Signatures

- `signatures[]`
- `signatures[].person_name`
- `signatures[].person_name_normalized`
- `signatures[].role_title`
- `signatures[].role_title_normalized`
- `signatures[].sequence`
- `signatures[].is_placeholder`
- `signatures[].extraction_source`
- `signatures[].context_snippet`
- `primary_signer`
- `primary_signer_normalized`
- `signers_all_flat`
- `has_multiple_signers`
- `signature_count`
- `signature_place`
- `signature_date`

## Normative References

- `normative_references[]`
- `normative_references[].reference_type`
- `normative_references[].reference_number`
- `normative_references[].reference_year`
- `normative_references[].reference_date`
- `normative_references[].reference_full`
- `normative_references[].reference_text`
- `normative_references[].issuing_body`
- `normative_references[].is_amendment`
- `normative_references[].is_revocation`
- `references_flat`
- `reference_types`
- `reference_count`

## Procedure References

- `procedure_references[]`
- `procedure_references[].procedure_type`
- `procedure_references[].procedure_identifier`
- `procedure_references[].procedure_year`
- `procedure_references[].procedure_body`

## Entities

- `affected_entities`
- `affected_entities_normalized`
- `affected_people`
- `affected_places`

## Media And Assets

- `images[]`
- `images[].name`
- `images[].source`
- `images[].sequence`
- `images[].alt_text`
- `images[].context_snippet`
- `images[].original_filename`
- `images[].storage_path`
- `images[].content_type`
- `images[].size_bytes`
- `images[].width_px`
- `images[].height_px`
- `images[].availability_status`
- `has_images`
- `image_count`
- `has_tables`
- `table_count`
- `has_anexos`
- `anexo_count`
- `anexos`

## Analytics And Quality

- `word_count`
- `char_count`
- `has_ementa`
- `year`
- `month`
- `day`
- `quarter`
- `decade`
- `day_of_week`
- `is_weekend`
- `is_start_of_month`
- `is_end_of_month`
- `parse_quality_score`
- `parse_errors`
- `extraction_method`
- `was_sanitized`
- `sanitization_reason`

## Lifecycle And Tombstones

- `metadata.ingestion_timestamp`
- `metadata.last_updated`
- `metadata.processing_version`
- `metadata.parser_version`
- `metadata.normalizer_version`
- `metadata.origin_file`
- `metadata.extraction_warnings`
- `metadata.validation_errors`
- `metadata.ingested_by`
- `is_tombstone`
- `tombstone_ref_id`
- `edition_type`
- `published_at`
- `indexed_at`
- `updated_at`

## BM25-First Additions

- `search_all`
- `normalized_title`
- `text_language`
- optional `passages[]`

## Deferred

- `usage.*`
- `enrichment.*`
- `embedding_*`
