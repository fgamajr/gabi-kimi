-- analytics_cache_schema.sql
-- Materialized views for fast /api/analytics reads.

CREATE SCHEMA IF NOT EXISTS admin;
CREATE SCHEMA IF NOT EXISTS dou;
SET search_path = dou, public;

CREATE TABLE IF NOT EXISTS admin.analytics_cache_state (
    id                  boolean PRIMARY KEY DEFAULT true CHECK (id),
    last_refreshed_at   timestamptz,
    last_duration_ms    integer,
    last_refresh_source text,
    last_status         text,
    last_error          text,
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE MATERIALIZED VIEW IF NOT EXISTS dou.analytics_overview_cache AS
SELECT
    count(*)::bigint AS total_documents,
    (count(DISTINCT issuing_organ) FILTER (WHERE issuing_organ IS NOT NULL AND issuing_organ <> ''))::bigint AS total_organs,
    (count(DISTINCT art_type) FILTER (WHERE art_type IS NOT NULL AND art_type <> ''))::bigint AS total_types,
    (SELECT min(publication_date) FROM dou.edition) AS date_min,
    (SELECT max(publication_date) FROM dou.edition) AS date_max
FROM dou.document
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_analytics_overview_cache_singleton
    ON dou.analytics_overview_cache ((1));

CREATE MATERIALIZED VIEW IF NOT EXISTS dou.analytics_section_monthly_cache AS
SELECT
    date_trunc('month', e.publication_date)::date AS month,
    count(*) FILTER (WHERE e.section = 'do1' AND NOT COALESCE(e.is_extra, false))::bigint AS do1,
    count(*) FILTER (WHERE e.section = 'do2')::bigint AS do2,
    count(*) FILTER (WHERE e.section = 'do3')::bigint AS do3,
    count(*) FILTER (WHERE COALESCE(e.is_extra, false) OR e.section IN ('do1e', 'e'))::bigint AS extra,
    count(*)::bigint AS total
FROM dou.document d
JOIN dou.edition e ON e.id = d.edition_id
GROUP BY 1
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_analytics_section_monthly_cache_month
    ON dou.analytics_section_monthly_cache (month);

CREATE MATERIALIZED VIEW IF NOT EXISTS dou.analytics_art_type_totals_cache AS
SELECT
    COALESCE(NULLIF(trim(art_type), ''), 'outros') AS art_type,
    count(*)::bigint AS cnt
FROM dou.document
GROUP BY 1
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_analytics_art_type_totals_cache_type
    ON dou.analytics_art_type_totals_cache (art_type);

CREATE MATERIALIZED VIEW IF NOT EXISTS dou.analytics_art_type_monthly_cache AS
SELECT
    date_trunc('month', e.publication_date)::date AS month,
    COALESCE(NULLIF(trim(d.art_type), ''), 'outros') AS art_type,
    count(*)::bigint AS cnt
FROM dou.document d
JOIN dou.edition e ON e.id = d.edition_id
GROUP BY 1, 2
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_analytics_art_type_monthly_cache_key
    ON dou.analytics_art_type_monthly_cache (month, art_type);

CREATE MATERIALIZED VIEW IF NOT EXISTS dou.analytics_top_organs_cache AS
SELECT
    issuing_organ,
    count(*)::bigint AS cnt
FROM dou.document
WHERE issuing_organ IS NOT NULL AND issuing_organ <> ''
GROUP BY issuing_organ
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_analytics_top_organs_cache_organ
    ON dou.analytics_top_organs_cache (issuing_organ);

CREATE MATERIALIZED VIEW IF NOT EXISTS dou.analytics_section_totals_cache AS
SELECT
    e.section,
    count(*)::bigint AS cnt
FROM dou.document d
JOIN dou.edition e ON e.id = d.edition_id
GROUP BY e.section
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_analytics_section_totals_cache_section
    ON dou.analytics_section_totals_cache (section);

CREATE MATERIALIZED VIEW IF NOT EXISTS dou.analytics_latest_documents_cache AS
SELECT
    d.id::text AS id,
    d.identifica,
    d.ementa,
    d.issuing_organ,
    d.art_type,
    e.publication_date,
    e.section,
    d.page_number,
    COALESCE(NULLIF(regexp_replace(d.page_number, '[^0-9]', '', 'g'), ''), '0')::integer AS page_sort
FROM dou.document d
JOIN dou.edition e ON e.id = d.edition_id
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_analytics_latest_documents_cache_id
    ON dou.analytics_latest_documents_cache (id);

CREATE INDEX IF NOT EXISTS idx_analytics_latest_documents_cache_order
    ON dou.analytics_latest_documents_cache (publication_date DESC, page_sort DESC, id DESC);
