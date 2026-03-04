-- bm25_schema.sql
-- Okapi BM25 search infrastructure for DOU documents.
--
-- Provides true BM25 ranking on top of PostgreSQL native tsvector/GIN,
-- with pre-computed term statistics (IDF) and document lengths for scoring.
--
-- Depends on: dou_schema.sql (dou.document, dou.edition, body_tsvector, GIN)
--
-- Usage:
--   SELECT * FROM dou.bm25_search('portaria ministério saúde');
--   SELECT * FROM dou.bm25_search('licitação pregão eletrônico', 50);
--   SELECT * FROM dou.bm25_search_filtered('saúde pública',
--                    date_from := '2024-01-01', p_section := 'do1');

SET search_path = dou, public;

-- ============================================================================
-- 1. Document length column (BM25 length normalization)
-- ============================================================================

ALTER TABLE dou.document
    ADD COLUMN IF NOT EXISTS body_word_count integer;

-- Index for fast NULL filtering during incremental refresh
CREATE INDEX IF NOT EXISTS idx_document_word_count_null
    ON dou.document(id) WHERE body_word_count IS NULL;

-- ============================================================================
-- 2. Term statistics (materialized) — IDF component
-- ============================================================================
-- ts_stat() scans all tsvectors and aggregates per-lexeme statistics:
--   ndoc   = number of documents containing the lexeme
--   nentry = total occurrences across all documents

CREATE MATERIALIZED VIEW IF NOT EXISTS dou.bm25_term_stats AS
SELECT word     AS lexeme,
       ndoc     AS doc_freq,
       nentry   AS total_freq
FROM ts_stat('SELECT body_tsvector FROM dou.document')
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_bm25_term_lexeme
    ON dou.bm25_term_stats(lexeme);

-- ============================================================================
-- 3. Corpus statistics (materialized)
-- ============================================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS dou.bm25_corpus_stats AS
SELECT count(*)::bigint                              AS total_docs,
       coalesce(avg(body_word_count)::float8, 300.0) AS avg_doc_length,
       now()                                         AS refreshed_at
FROM dou.document;

-- ============================================================================
-- 4. BM25 search function (unfiltered)
-- ============================================================================
--
-- Okapi BM25 formula:
--   score(D, Q) = Σ IDF(qi) · tf(qi,D)·(k1+1) / [tf(qi,D) + k1·(1-b+b·|D|/avgdl)]
--
-- IDF(qi) = ln( (N - df(qi) + 0.5) / (df(qi) + 0.5) + 1 )
--
-- Default parameters: k1=1.2 (saturation), b=0.75 (length normalization)

CREATE OR REPLACE FUNCTION dou.bm25_search(
    query_text  text,
    max_results integer DEFAULT 20,
    p_k1        float8  DEFAULT 1.2,
    p_b         float8  DEFAULT 0.75
)
RETURNS TABLE(
    doc_id          uuid,
    score           float8,
    identifica      text,
    ementa          text,
    art_type        text,
    pub_date        date,
    edition_section text,
    snippet         text
)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_N     bigint;
    v_avgdl float8;
    v_tsq   tsquery;
    v_pre   integer;
BEGIN
    SELECT cs.total_docs, cs.avg_doc_length
      INTO v_N, v_avgdl
      FROM dou.bm25_corpus_stats cs;

    IF v_N IS NULL OR v_N = 0 THEN RETURN; END IF;
    IF v_avgdl <= 0 THEN v_avgdl := 300.0; END IF;

    -- websearch_to_tsquery supports "phrases", OR, -exclude
    v_tsq := websearch_to_tsquery('pg_catalog.portuguese', query_text);

    -- Two-pass: fast ts_rank pre-select, then precise BM25 re-rank
    v_pre := LEAST(max_results * 25, 500);

    RETURN QUERY
    WITH
    q_lex AS (
        SELECT (t).lexeme
        FROM unnest(to_tsvector('pg_catalog.portuguese', query_text)) t
    ),
    -- Pass 1: fast ts_rank pre-selection
    pre AS (
        SELECT d.id, d.body_tsvector, d.body_word_count
        FROM dou.document d
        WHERE d.body_tsvector @@ v_tsq
        ORDER BY ts_rank(d.body_tsvector, v_tsq) DESC
        LIMIT v_pre
    ),
    -- Pass 2: precise BM25 scoring on pre-selected candidates
    scored AS (
        SELECT p.id,
               SUM(
                   ln((v_N - COALESCE(ts.doc_freq, 1)::float8 + 0.5)
                      / (COALESCE(ts.doc_freq, 1)::float8 + 0.5) + 1.0)
                   * (COALESCE(array_length(dv.positions, 1), 1)::float8 * (p_k1 + 1.0))
                   / (COALESCE(array_length(dv.positions, 1), 1)::float8
                      + p_k1 * (1.0 - p_b
                                + p_b * COALESCE(p.body_word_count, v_avgdl) / v_avgdl))
               ) AS bm25
        FROM pre p
        CROSS JOIN LATERAL unnest(p.body_tsvector) AS dv
        INNER JOIN q_lex ql ON ql.lexeme = dv.lexeme
        LEFT  JOIN dou.bm25_term_stats ts ON ts.lexeme = dv.lexeme
        GROUP BY p.id
    ),
    top_n AS (
        SELECT s.id, s.bm25
        FROM scored s
        ORDER BY s.bm25 DESC
        LIMIT max_results
    )
    SELECT tn.id,
           tn.bm25,
           d.identifica,
           d.ementa,
           d.art_type,
           e.publication_date,
           e.section,
           ts_headline('pg_catalog.portuguese', d.body_plain, v_tsq,
                       'MaxWords=60, MinWords=25, StartSel=>>>, StopSel=<<<')
    FROM top_n tn
    JOIN dou.document d ON d.id = tn.id
    JOIN dou.edition e  ON e.id = d.edition_id
    ORDER BY tn.bm25 DESC;
END;
$$;

-- ============================================================================
-- 5. BM25 search with filters (date, section, art_type)
-- ============================================================================

CREATE OR REPLACE FUNCTION dou.bm25_search_filtered(
    query_text      text,
    max_results     integer DEFAULT 20,
    date_from       date    DEFAULT NULL,
    date_to         date    DEFAULT NULL,
    p_section       text    DEFAULT NULL,
    p_art_type      text    DEFAULT NULL,
    p_issuing_organ text    DEFAULT NULL,
    p_k1            float8  DEFAULT 1.2,
    p_b             float8  DEFAULT 0.75
)
RETURNS TABLE(
    doc_id          uuid,
    score           float8,
    identifica      text,
    ementa          text,
    art_type        text,
    pub_date        date,
    edition_section text,
    snippet         text
)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_N     bigint;
    v_avgdl float8;
    v_tsq   tsquery;
    v_pre   integer;
BEGIN
    SELECT cs.total_docs, cs.avg_doc_length
      INTO v_N, v_avgdl
      FROM dou.bm25_corpus_stats cs;

    IF v_N IS NULL OR v_N = 0 THEN RETURN; END IF;
    IF v_avgdl <= 0 THEN v_avgdl := 300.0; END IF;

    -- websearch_to_tsquery supports "phrases", OR, -exclude
    v_tsq := websearch_to_tsquery('pg_catalog.portuguese', query_text);

    -- Two-pass: fast ts_rank pre-select, then precise BM25 re-rank
    v_pre := LEAST(max_results * 25, 500);

    RETURN QUERY
    WITH
    q_lex AS (
        SELECT (t).lexeme
        FROM unnest(to_tsvector('pg_catalog.portuguese', query_text)) t
    ),
    -- Pass 1: fast ts_rank pre-selection with filters
    pre AS (
        SELECT d.id, d.body_tsvector, d.body_word_count
        FROM dou.document d
        JOIN dou.edition e ON e.id = d.edition_id
        WHERE d.body_tsvector @@ v_tsq
          AND (date_from       IS NULL OR e.publication_date >= date_from)
          AND (date_to         IS NULL OR e.publication_date <= date_to)
          AND (p_section       IS NULL OR e.section = p_section)
          AND (p_art_type      IS NULL OR d.art_type = p_art_type)
          AND (p_issuing_organ IS NULL OR d.issuing_organ = p_issuing_organ)
        ORDER BY ts_rank(d.body_tsvector, v_tsq) DESC
        LIMIT v_pre
    ),
    -- Pass 2: precise BM25 scoring on pre-selected candidates
    scored AS (
        SELECT p.id,
               SUM(
                   ln((v_N - COALESCE(ts.doc_freq, 1)::float8 + 0.5)
                      / (COALESCE(ts.doc_freq, 1)::float8 + 0.5) + 1.0)
                   * (COALESCE(array_length(dv.positions, 1), 1)::float8 * (p_k1 + 1.0))
                   / (COALESCE(array_length(dv.positions, 1), 1)::float8
                      + p_k1 * (1.0 - p_b
                                + p_b * COALESCE(p.body_word_count, v_avgdl) / v_avgdl))
               ) AS bm25
        FROM pre p
        CROSS JOIN LATERAL unnest(p.body_tsvector) AS dv
        INNER JOIN q_lex ql ON ql.lexeme = dv.lexeme
        LEFT  JOIN dou.bm25_term_stats ts ON ts.lexeme = dv.lexeme
        GROUP BY p.id
    ),
    top_n AS (
        SELECT s.id, s.bm25
        FROM scored s
        ORDER BY s.bm25 DESC
        LIMIT max_results
    )
    SELECT tn.id,
           tn.bm25,
           d.identifica,
           d.ementa,
           d.art_type,
           e.publication_date,
           e.section,
           ts_headline('pg_catalog.portuguese', d.body_plain, v_tsq,
                       'MaxWords=60, MinWords=25, StartSel=>>>, StopSel=<<<')
    FROM top_n tn
    JOIN dou.document d ON d.id = tn.id
    JOIN dou.edition e  ON e.id = d.edition_id
    ORDER BY tn.bm25 DESC;
END;
$$;

-- ============================================================================
-- 6. Refresh procedure (call after new ingestions)
-- ============================================================================

CREATE OR REPLACE FUNCTION dou.bm25_refresh()
RETURNS TABLE(updated_word_counts bigint, total_terms bigint, total_docs bigint)
LANGUAGE plpgsql AS $$
DECLARE
    v_updated bigint;
    v_terms   bigint;
    v_docs    bigint;
BEGIN
    -- Update word counts for new documents (incremental)
    WITH updated AS (
        UPDATE dou.document
        SET body_word_count = cardinality(
            regexp_split_to_array(trim(body_plain), '\s+')
        )
        WHERE body_word_count IS NULL
          AND body_plain IS NOT NULL
          AND body_plain <> ''
        RETURNING 1
    )
    SELECT count(*) INTO v_updated FROM updated;

    -- Rebuild term statistics
    REFRESH MATERIALIZED VIEW CONCURRENTLY dou.bm25_term_stats;

    -- Rebuild corpus statistics (no CONCURRENTLY — single-row, no unique index)
    REFRESH MATERIALIZED VIEW dou.bm25_corpus_stats;

    SELECT count(*) INTO v_terms FROM dou.bm25_term_stats;
    SELECT cs.total_docs INTO v_docs FROM dou.bm25_corpus_stats cs;

    RETURN QUERY SELECT v_updated, v_terms, v_docs;
END;
$$;

-- ============================================================================
-- 7. Index statistics view
-- ============================================================================

CREATE OR REPLACE VIEW dou.v_bm25_stats AS
SELECT cs.total_docs,
       cs.avg_doc_length,
       cs.refreshed_at,
       (SELECT count(*) FROM dou.bm25_term_stats)      AS vocabulary_size,
       (SELECT sum(total_freq) FROM dou.bm25_term_stats) AS total_term_freq,
       (SELECT count(*) FROM dou.document
        WHERE body_word_count IS NULL)                   AS docs_missing_word_count
FROM dou.bm25_corpus_stats cs;
