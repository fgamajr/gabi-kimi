-- registry_schema.sql
-- Temporal legal registry: concept → version → occurrence
-- Append-only, immutable, evidence-anchored.
--
-- Compiled from sources_v3.identity-test.yaml identity contract.
-- YAML is law; this schema is the faithful compilation.

-- ============================================================================
-- Schema
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS registry;
SET search_path = registry, public;

-- ============================================================================
-- Tables
-- ============================================================================

-- editions: temporal container bound to frozen evidence.
-- edition_id = sha256(publication_date | edition_number | section | listing_sha256)
-- Two captures of the same government edition with different listing hashes
-- produce different edition rows. The archive records observations, not intent.
CREATE TABLE registry.editions (
    edition_id          char(64) PRIMARY KEY,
    publication_date    date NOT NULL,
    edition_number      text,
    edition_section     text,
    listing_sha256      char(64),
    first_seen_at       timestamptz NOT NULL DEFAULT now()
);

-- concepts: legal act identity (hash + strategy only).
-- The hash IS the identity. No semantic fields — those live in versions.
-- Strategy is recorded for observability (which tier matched).
CREATE TABLE registry.concepts (
    natural_key_hash    char(64) PRIMARY KEY,
    strategy            text NOT NULL,
    first_seen_at       timestamptz NOT NULL DEFAULT now()
);

-- versions: content snapshot of a concept.
-- Cardinality: one natural_key_hash → many content_hashes
-- (YAML: natural_key_hash_to_content_hash: one_to_many)
CREATE TABLE registry.versions (
    id                  bigserial PRIMARY KEY,
    natural_key_hash    char(64) NOT NULL REFERENCES registry.concepts(natural_key_hash),
    content_hash        char(64) NOT NULL,
    body_text_semantic  text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (natural_key_hash, content_hash)
);

-- occurrences: when/where a version appeared.
-- Cardinality: one content_hash → many occurrence_hashes
-- (YAML: content_hash_to_occurrence_hash: one_to_many)
-- YAML constraint: unique(occurrence_hash) — enforced by PRIMARY KEY.
CREATE TABLE registry.occurrences (
    occurrence_hash     char(64) PRIMARY KEY,
    edition_id          char(64) NOT NULL REFERENCES registry.editions(edition_id),
    version_id          bigint NOT NULL REFERENCES registry.versions(id),
    page_number         text,
    source_url          text,
    source_file         text,
    ingested_at         timestamptz NOT NULL DEFAULT now()
);

-- ingestion_log: audit trail with decision provenance.
-- decision_basis JSONB records which INSERTs returned rows — the proof.
-- No immutability triggers — append-only audit table.
CREATE TABLE registry.ingestion_log (
    id                  bigserial PRIMARY KEY,
    occurrence_hash     char(64) NOT NULL,
    action              text NOT NULL,
    natural_key_hash    char(64),
    content_hash        char(64),
    edition_id          char(64),
    source_file         text,
    decision_basis      jsonb NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- ============================================================================
-- Indexes (from YAML indexes block + FK coverage)
-- ============================================================================

CREATE INDEX idx_versions_natural_key ON registry.versions(natural_key_hash);
CREATE INDEX idx_versions_content ON registry.versions(content_hash);
CREATE INDEX idx_occurrences_edition ON registry.occurrences(edition_id);
CREATE INDEX idx_occurrences_version ON registry.occurrences(version_id);
CREATE INDEX idx_editions_pubdate ON registry.editions(publication_date);
CREATE INDEX idx_log_occurrence ON registry.ingestion_log(occurrence_hash);

-- ============================================================================
-- Immutability: REVOKE + BEFORE triggers
-- ============================================================================

-- Privilege-level protection: revoke UPDATE/DELETE from PUBLIC.
REVOKE UPDATE, DELETE ON registry.editions FROM PUBLIC;
REVOKE UPDATE, DELETE ON registry.concepts FROM PUBLIC;
REVOKE UPDATE, DELETE ON registry.versions FROM PUBLIC;
REVOKE UPDATE, DELETE ON registry.occurrences FROM PUBLIC;

-- Belt-and-suspenders: BEFORE triggers that raise on real mutations.
-- Allows no-op updates (ROW(NEW.*) IS NOT DISTINCT FROM ROW(OLD.*))
-- required by the INSERT...ON CONFLICT DO UPDATE...RETURNING xmax trick.
CREATE OR REPLACE FUNCTION registry.deny_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'immutable table: DELETE forbidden on registry.%', TG_TABLE_NAME;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        -- Allow no-op updates required by INSERT...ON CONFLICT DO UPDATE...RETURNING (xmax trick).
        -- If every column is identical, this is a conflict-resolution no-op, not a real mutation.
        IF ROW(NEW.*) IS NOT DISTINCT FROM ROW(OLD.*) THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'immutable table: UPDATE forbidden on registry.%', TG_TABLE_NAME;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_no_update_editions BEFORE UPDATE ON registry.editions
    FOR EACH ROW EXECUTE FUNCTION registry.deny_mutation();
CREATE TRIGGER trg_no_delete_editions BEFORE DELETE ON registry.editions
    FOR EACH ROW EXECUTE FUNCTION registry.deny_mutation();

CREATE TRIGGER trg_no_update_concepts BEFORE UPDATE ON registry.concepts
    FOR EACH ROW EXECUTE FUNCTION registry.deny_mutation();
CREATE TRIGGER trg_no_delete_concepts BEFORE DELETE ON registry.concepts
    FOR EACH ROW EXECUTE FUNCTION registry.deny_mutation();

CREATE TRIGGER trg_no_update_versions BEFORE UPDATE ON registry.versions
    FOR EACH ROW EXECUTE FUNCTION registry.deny_mutation();
CREATE TRIGGER trg_no_delete_versions BEFORE DELETE ON registry.versions
    FOR EACH ROW EXECUTE FUNCTION registry.deny_mutation();

CREATE TRIGGER trg_no_update_occurrences BEFORE UPDATE ON registry.occurrences
    FOR EACH ROW EXECUTE FUNCTION registry.deny_mutation();
CREATE TRIGGER trg_no_delete_occurrences BEFORE DELETE ON registry.occurrences
    FOR EACH ROW EXECUTE FUNCTION registry.deny_mutation();

-- ============================================================================
-- Explanation queries
-- ============================================================================

-- 1. Full history of an act (concept → versions → occurrences → editions)
--
-- SELECT c.natural_key_hash, c.strategy,
--        v.content_hash, v.created_at AS version_created,
--        o.occurrence_hash, o.page_number, o.source_url,
--        e.publication_date, e.edition_number, e.edition_section
-- FROM registry.concepts c
-- JOIN registry.versions v ON v.natural_key_hash = c.natural_key_hash
-- JOIN registry.occurrences o ON o.version_id = v.id
-- JOIN registry.editions e ON e.edition_id = o.edition_id
-- WHERE c.natural_key_hash = $1
-- ORDER BY e.publication_date, v.created_at;

-- 2. Latest version of a concept
--
-- SELECT v.*
-- FROM registry.versions v
-- WHERE v.natural_key_hash = $1
-- ORDER BY v.created_at DESC
-- LIMIT 1;

-- 3. First publication of a concept
--
-- SELECT e.publication_date, o.source_url, o.page_number
-- FROM registry.occurrences o
-- JOIN registry.editions e ON e.edition_id = o.edition_id
-- JOIN registry.versions v ON v.id = o.version_id
-- WHERE v.natural_key_hash = $1
-- ORDER BY e.publication_date ASC
-- LIMIT 1;

-- 4. Republications (same content in multiple editions)
--
-- SELECT v.content_hash, count(DISTINCT o.edition_id) AS editions
-- FROM registry.versions v
-- JOIN registry.occurrences o ON o.version_id = v.id
-- GROUP BY v.content_hash
-- HAVING count(DISTINCT o.edition_id) > 1;

-- 5. Modifications across time (version history for a concept)
--
-- SELECT v.content_hash, v.created_at,
--        min(e.publication_date) AS first_published
-- FROM registry.versions v
-- JOIN registry.occurrences o ON o.version_id = v.id
-- JOIN registry.editions e ON e.edition_id = o.edition_id
-- WHERE v.natural_key_hash = $1
-- GROUP BY v.content_hash, v.created_at
-- ORDER BY first_published;
