-- dou_schema.sql
-- DOU publication schema: documents, media, signatures, references.
-- Designed for full-text search, image reconstruction, and NLP enrichment.
--
-- Complements the registry.* audit schema with a rich, queryable layer.

-- ============================================================================
-- Schema
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS dou;
SET search_path = dou, public;

-- ============================================================================
-- Tables
-- ============================================================================

-- source_zip: provenance record for each downloaded ZIP bundle.
CREATE TABLE dou.source_zip (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    filename        text NOT NULL UNIQUE,
    month           text,                       -- YYYY-MM
    section         text,                       -- do1, do2, do3, etc.
    sha256          char(64) NOT NULL,
    size_bytes      bigint,
    downloaded_at   timestamptz DEFAULT now(),
    xml_count       integer,
    image_count     integer
);

CREATE INDEX idx_source_zip_month ON dou.source_zip(month);

-- edition: one DOU edition (e.g. DO1 of 2026-02-27, edição 39).
CREATE TABLE dou.edition (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    publication_date    date NOT NULL,
    edition_number      text,                   -- "39", "39-A"
    section             text NOT NULL,          -- do1, do1e, do1a, do2, do2e, do3, do3e
    is_extra            boolean NOT NULL DEFAULT false,
    source_zip_id       uuid REFERENCES dou.source_zip(id) ON DELETE SET NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (publication_date, edition_number, section)
);

CREATE INDEX idx_edition_date ON dou.edition(publication_date);
CREATE INDEX idx_edition_section ON dou.edition(section);

-- document: a single legal act / publication.
CREATE TABLE dou.document (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    edition_id          uuid NOT NULL REFERENCES dou.edition(id) ON DELETE CASCADE,

    -- INLabs identifiers
    id_materia          text NOT NULL,
    id_oficio           text,
    xml_name            text,                   -- original article@name attribute

    -- Classification
    art_type            text NOT NULL,          -- normalized lowercase: "portaria"
    art_type_raw        text,                   -- original casing from XML
    art_category        text,                   -- slash-delimited org path
    art_class           text[],                 -- 12-level hierarchy array
    page_number         text,

    -- Content fields
    identifica          text,                   -- act title/header
    ementa              text,                   -- summary/abstract
    titulo              text,                   -- section title
    sub_titulo          text,
    body_html           text NOT NULL,          -- original HTML from <Texto>
    body_plain          text NOT NULL,          -- HTML stripped to text

    -- Extracted structured fields
    document_number     text,                   -- from identifica, e.g. "772"
    document_year       integer,                -- from identifica or pub_date
    issuing_organ       text,                   -- first segment of art_category

    -- Identity / dedup
    content_hash        char(64),
    natural_key_hash    char(64),
    identity_strategy   text,                   -- strict/medium/weak/fallback/none

    -- Provenance
    source_xml_path     text,                   -- relative path in ZIP
    is_multipart        boolean NOT NULL DEFAULT false,
    multipart_index     integer,                -- NULL=single, 1/2/3=part index

    created_at          timestamptz NOT NULL DEFAULT now()
);

-- Full-text search (generated column + GIN index)
ALTER TABLE dou.document
    ADD COLUMN body_tsvector tsvector
    GENERATED ALWAYS AS (
        to_tsvector('pg_catalog.portuguese', coalesce(identifica, '') || ' ' || coalesce(ementa, '') || ' ' || body_plain)
    ) STORED;

CREATE INDEX idx_document_fts ON dou.document USING GIN (body_tsvector);
CREATE INDEX idx_document_id_materia ON dou.document(id_materia);
CREATE UNIQUE INDEX idx_document_id_materia_unique ON dou.document(id_materia);
CREATE INDEX idx_document_art_type ON dou.document(art_type);
CREATE INDEX idx_document_number_year ON dou.document(document_number, document_year);
CREATE INDEX idx_document_edition ON dou.document(edition_id);
CREATE INDEX idx_document_content_hash ON dou.document(content_hash);
CREATE INDEX idx_document_natural_key ON dou.document(natural_key_hash);
CREATE INDEX idx_document_issuing_organ ON dou.document(issuing_organ);

-- document_chunk: contextual chunks for hybrid/vector retrieval and RAG grounding.
CREATE TABLE dou.document_chunk (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id         uuid NOT NULL REFERENCES dou.document(id) ON DELETE CASCADE,
    chunk_index         integer NOT NULL,           -- 0-based order within document
    chunk_text          text NOT NULL,              -- original chunk text
    chunk_text_norm     text NOT NULL,              -- normalized text for fallback lookup
    chunk_char_start    integer NOT NULL,           -- offset in normalized body text
    chunk_char_end      integer NOT NULL,           -- exclusive offset
    token_estimate      integer NOT NULL,           -- rough token estimate
    heading_context     text,                       -- title/header context used for embeddings
    metadata_json       jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX idx_document_chunk_document ON dou.document_chunk(document_id);
CREATE INDEX idx_document_chunk_created ON dou.document_chunk(created_at);
CREATE INDEX idx_document_chunk_metadata_gin ON dou.document_chunk USING GIN (metadata_json);

-- document_media: images/attachments stored as bytea (or external URL fallback).
CREATE TABLE dou.document_media (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id             uuid NOT NULL REFERENCES dou.document(id) ON DELETE CASCADE,
    media_name              text NOT NULL,          -- name without extension, e.g. "1_MPESCA_27_001"
    media_type              text,                   -- MIME type, e.g. "image/jpeg"
    file_extension          text,                   -- ".jpg", ".png"
    data                    bytea,                   -- binary content (nullable when external_url is used)
    size_bytes              integer,
    sequence_in_document    integer,                -- order of appearance in <Texto>
    source_filename         text,                   -- original filename in ZIP
    external_url            text,                   -- original image URL when binary is unavailable
    created_at              timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_document_media_document ON dou.document_media(document_id);

-- document_signature: signataries extracted from HTML.
CREATE TABLE dou.document_signature (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id             uuid NOT NULL REFERENCES dou.document(id) ON DELETE CASCADE,
    person_name             text NOT NULL,
    role_title              text,                   -- cargo (nullable)
    sequence_in_document    integer,
    created_at              timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_document_signature_document ON dou.document_signature(document_id);
CREATE INDEX idx_document_signature_person ON dou.document_signature(person_name);

-- normative_reference: legislative references cited in text.
CREATE TABLE dou.normative_reference (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id         uuid NOT NULL REFERENCES dou.document(id) ON DELETE CASCADE,
    reference_type      text NOT NULL,          -- "lei", "decreto", "resolução", etc.
    reference_number    text,                   -- "12.846/2013"
    reference_date      text,                   -- "29 de junho de 2009"
    reference_text      text NOT NULL,          -- full match snippet
    issuing_body        text,                   -- "MPA/MMA", "GECEX"
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_normative_ref_document ON dou.normative_reference(document_id);
CREATE INDEX idx_normative_ref_type_number ON dou.normative_reference(reference_type, reference_number);

-- procedure_reference: administrative process references.
CREATE TABLE dou.procedure_reference (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id             uuid NOT NULL REFERENCES dou.document(id) ON DELETE CASCADE,
    procedure_type          text NOT NULL,      -- "processo_etico", "processo_sei", "proad"
    procedure_identifier    text NOT NULL,      -- "0096/2023", "64575.008146/2024-57"
    created_at              timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_procedure_ref_document ON dou.procedure_reference(document_id);
CREATE INDEX idx_procedure_ref_identifier ON dou.procedure_reference(procedure_identifier);

-- ============================================================================
-- Helper views
-- ============================================================================

-- Quick document search view with edition context
CREATE OR REPLACE VIEW dou.v_document_full AS
SELECT
    d.id,
    d.id_materia,
    e.publication_date,
    e.edition_number,
    e.section,
    e.is_extra,
    d.art_type,
    d.art_type_raw,
    d.art_category,
    d.document_number,
    d.document_year,
    d.issuing_organ,
    d.identifica,
    d.ementa,
    d.body_plain,
    d.body_html,
    d.page_number,
    d.content_hash,
    d.natural_key_hash,
    d.identity_strategy,
    d.is_multipart,
    d.source_xml_path,
    d.created_at,
    (SELECT count(*) FROM dou.document_media dm WHERE dm.document_id = d.id) AS media_count,
    (SELECT count(*) FROM dou.document_signature ds WHERE ds.document_id = d.id) AS signature_count
FROM dou.document d
JOIN dou.edition e ON e.id = d.edition_id;


-- ============================================================================
-- Materialized Views
-- ============================================================================

-- suggest_cache: autocomplete for organs, act types (used by chat + suggest API)
-- REFRESH after ingest: REFRESH MATERIALIZED VIEW CONCURRENTLY dou.suggest_cache;
CREATE MATERIALIZED VIEW IF NOT EXISTS dou.suggest_cache AS

SELECT 'orgao'::text AS cat, issuing_organ AS term, count(*) AS cnt
FROM dou.document
WHERE issuing_organ IS NOT NULL AND issuing_organ != ''
GROUP BY issuing_organ

UNION ALL

SELECT 'tipo'::text AS cat, art_type AS term, count(*) AS cnt
FROM dou.document
WHERE art_type IS NOT NULL AND art_type != ''
GROUP BY art_type

UNION ALL

SELECT 'tipo_raw'::text AS cat, art_type_raw AS term, count(*) AS cnt
FROM dou.document
WHERE art_type_raw IS NOT NULL AND art_type_raw != ''
GROUP BY art_type_raw

WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_suggest_cache_uniq ON dou.suggest_cache (cat, term);
CREATE INDEX IF NOT EXISTS idx_suggest_cache_cat_term ON dou.suggest_cache (cat, term);
