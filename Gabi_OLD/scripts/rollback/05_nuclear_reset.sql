-- =============================================================================
-- GABI Rollback: Nuclear Reset (FULL SOURCE RESET)
-- =============================================================================
-- WARNING: This script performs a COMPLETE reset of a source.
--          ALL data will be marked deleted and need to be re-fetched.
-- Usage:   psql -d gabi -f 05_nuclear_reset.sql -v source_id="'your_source'"
-- =============================================================================

\echo '================================================================================'
\echo '⚠️  NUCLEAR RESET FOR:' :source_id
\echo '⚠️  THIS WILL DELETE ALL DATA FOR THIS SOURCE!'
\echo '================================================================================'

-- Show what will be affected
\echo '\n>>> DATA THAT WILL BE AFFECTED:'
SELECT
    (SELECT COUNT(*) FROM discovered_links WHERE source_id = :source_id) as links,
    (SELECT COUNT(*) FROM fetch_items WHERE source_id = :source_id) as fetch_items,
    (SELECT COUNT(*) FROM documents WHERE source_id = :source_id AND removed_from_source_at IS NULL) as active_docs,
    (SELECT COUNT(*) FROM documents WHERE source_id = :source_id) as total_docs,
    (SELECT COUNT(*) FROM job_registry WHERE source_id = :source_id) as jobs,
    (SELECT COUNT(*) FROM ingest_jobs WHERE source_id = :source_id) as ingest_jobs,
    (SELECT COUNT(*) FROM dlq_entries WHERE source_id = :source_id) as dlq_entries;

\echo '\n>>> Press Ctrl+C to cancel, or wait 5 seconds to continue...'
\prompt 'Press Enter to continue (or Ctrl+C to cancel)...' pause

-- Start transaction
BEGIN;

\echo '\n>>> Step 1/7: Soft deleting all documents...'
UPDATE documents
SET status = 'deleted',
    removed_from_source_at = NOW(),
    removed_reason = 'Nuclear rollback: full source reset',
    updated_at = NOW(),
    updated_by = 'nuclear_rollback_script'
WHERE source_id = :source_id
  AND removed_from_source_at IS NULL;

\echo 'Documents soft deleted: ' || :ROW_COUNT;

\echo '\n>>> Step 2/7: Deleting fetch_items...'
DELETE FROM fetch_items 
WHERE source_id = :source_id;

\echo 'Fetch items deleted: ' || :ROW_COUNT;

\echo '\n>>> Step 3/7: Resetting discovered_links...'
UPDATE discovered_links
SET status = 'pending',
    discovery_status = 'pending',
    fetch_status = 'pending',
    ingest_status = 'pending',
    process_attempts = 0,
    last_processed_at = NULL,
    updated_at = NOW(),
    updated_by = 'nuclear_rollback_script'
WHERE source_id = :source_id;

\echo 'Discovered links reset: ' || :ROW_COUNT;

\echo '\n>>> Step 4/7: Cleaning up ingest_jobs...'
DELETE FROM ingest_jobs 
WHERE source_id = :source_id;

\echo 'Ingest jobs deleted: ' || :ROW_COUNT;

\echo '\n>>> Step 5/7: Cancelling active job_registry entries...'
UPDATE job_registry
SET status = 'cancelled',
    completed_at = NOW(),
    error_message = 'Cancelled by nuclear rollback'
WHERE source_id = :source_id
  AND status IN ('pending', 'running', 'processing');

\echo 'Job registry entries cancelled: ' || :ROW_COUNT;

\echo '\n>>> Step 6/7: Resetting pipeline state...'
UPDATE source_pipeline_state
SET state = 'idle',
    active_phase = NULL,
    paused_by = NULL,
    paused_at = NULL,
    updated_at = NOW()
WHERE source_id = :source_id;

\echo 'Pipeline state reset: ' || :ROW_COUNT;

\echo '\n>>> Step 7/7: Archiving DLQ entries...'
UPDATE dlq_entries
SET status = 'archived',
    notes = COALESCE(notes, '') || ' | Archived due to nuclear source reset at ' || NOW()
WHERE source_id = :source_id
  AND status = 'pending';

\echo 'DLQ entries archived: ' || :ROW_COUNT;

\echo '\n>>> FINAL STATE:'
SELECT
    (SELECT COUNT(*) FROM discovered_links WHERE source_id = :source_id AND status = 'pending') as pending_links,
    (SELECT COUNT(*) FROM fetch_items WHERE source_id = :source_id) as fetch_items,
    (SELECT COUNT(*) FROM documents WHERE source_id = :source_id AND removed_from_source_at IS NULL) as active_docs,
    (SELECT state FROM source_pipeline_state WHERE source_id = :source_id) as pipeline_state;

\echo '\n================================================================================'
\echo '⚠️  NUCLEAR RESET COMPLETE - REVIEW AND COMMIT'
\echo '================================================================================'
\echo 'Review the changes above. To finalize:'
\echo '  COMMIT;  -- to apply changes'
\echo '  ROLLBACK; -- to cancel changes'
\echo ''
\echo '⚠️  WARNING: You must manually run COMMIT or ROLLBACK!'
\echo '================================================================================'
