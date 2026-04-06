-- Archive legacy raw tables after canonical raw.* tables are validated.
-- Preconditions:
--   1) Backfill: python -m ops.migrations.source_separate_raw --confirm [--relax-count-check]
--   2) Parity checks (canonical vs legacy counts, or documented columnar CSV path)
--   3) Pause ingest jobs during the rename window
--
-- raw.tcu_acordaos (typed layer, not one of the 11): archive only when unused, e.g.:
--   DO $$ BEGIN
--     IF to_regclass('raw.tcu_acordaos') IS NOT NULL THEN
--       EXECUTE 'ALTER TABLE raw.tcu_acordaos RENAME TO _archive_tcu_acordaos';
--     END IF;
--   END $$;

BEGIN;

DO $$
BEGIN
  IF to_regclass('raw.dou_documents_raw_data') IS NOT NULL THEN
    EXECUTE 'ALTER TABLE raw.dou_documents_raw_data RENAME TO _archive_dou_documents_raw_data';
  END IF;
END $$;

DO $$
BEGIN
  IF to_regclass('raw.tcu_acordaos_raw_data') IS NOT NULL THEN
    EXECUTE 'ALTER TABLE raw.tcu_acordaos_raw_data RENAME TO _archive_tcu_acordaos_raw_data';
  END IF;
END $$;

DO $$
BEGIN
  IF to_regclass('raw.tcu_btcu_raw_data') IS NOT NULL THEN
    EXECUTE 'ALTER TABLE raw.tcu_btcu_raw_data RENAME TO _archive_tcu_btcu_raw_data';
  END IF;
END $$;

DO $$
BEGIN
  IF to_regclass('raw.tcu_normas_raw_data') IS NOT NULL THEN
    EXECUTE 'ALTER TABLE raw.tcu_normas_raw_data RENAME TO _archive_tcu_normas_raw_data';
  END IF;
END $$;

DO $$
BEGIN
  IF to_regclass('raw.tcu_publicacoes_raw_data') IS NOT NULL THEN
    EXECUTE 'ALTER TABLE raw.tcu_publicacoes_raw_data RENAME TO _archive_tcu_publicacoes_raw_data';
  END IF;
END $$;

COMMIT;

-- After monitoring (1–2 days), optional destructive cleanup:
-- DROP TABLE IF EXISTS raw._archive_dou_documents_raw_data;
-- DROP TABLE IF EXISTS raw._archive_tcu_acordaos_raw_data;
-- DROP TABLE IF EXISTS raw._archive_tcu_btcu_raw_data;
-- DROP TABLE IF EXISTS raw._archive_tcu_normas_raw_data;
-- DROP TABLE IF EXISTS raw._archive_tcu_publicacoes_raw_data;
