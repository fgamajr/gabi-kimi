-- =============================================================================
-- GABI Rollback: Reset Fetch Phase
-- =============================================================================
-- Purpose: Reset fetch phase to allow refetching
-- Usage:   psql -d gabi -f 03_reset_fetch_phase.sql -v source_id="'your_source'"
-- Options: Set full_reset=true to reset ALL fetch_items, false for failed only
-- =============================================================================

\echo '================================================================================'
\echo 'RESETTING FETCH PHASE FOR:' :source_id
\echo '================================================================================'

-- Check if full_reset variable is set, default to false
\if :{?full_reset}
\else
\set full_reset false
\endif

-- Show current state
\echo '\n>>> Current fetch_items status:'
SELECT status, COUNT(*) as count
FROM fetch_items
WHERE source_id = :source_id
GROUP BY status;

\echo '\n>>> Current discovered_links fetch_status:'
SELECT fetch_status, COUNT(*) as count
FROM discovered_links
WHERE source_id = :source_id
GROUP BY fetch_status;

-- Reset fetch_items
\if :full_reset
    \echo '\n>>> FULL RESET: Setting ALL fetch_items to pending...'
    UPDATE fetch_items
    SET status = 'pending',
        attempts = 0,
        last_error = NULL,
        started_at = NULL,
        completed_at = NULL,
        updated_at = NOW(),
        updated_by = 'rollback_script'
    WHERE source_id = :source_id;
\else
    \echo '\n>>> PARTIAL RESET: Setting only failed/processing fetch_items to pending...'
    UPDATE fetch_items
    SET status = 'pending',
        attempts = 0,
        last_error = NULL,
        started_at = NULL,
        completed_at = NULL,
        updated_at = NOW(),
        updated_by = 'rollback_script'
    WHERE source_id = :source_id
      AND status IN ('failed', 'processing', 'error');
\endif

\echo 'Updated fetch_items: ' || :ROW_COUNT;

-- Reset discovered_links fetch_status
\echo '\n>>> Resetting discovered_links fetch_status...'
UPDATE discovered_links
SET fetch_status = 'pending',
    ingest_status = 'pending',
    updated_at = NOW(),
    updated_by = 'rollback_script'
WHERE source_id = :source_id
  AND fetch_status IN ('processing', 'failed', 'error');

\echo 'Updated discovered_links: ' || :ROW_COUNT;

-- Reset fetch_runs if they exist
\echo '\n>>> Marking incomplete fetch_runs as failed...'
UPDATE fetch_runs
SET status = 'failed',
    completed_at = NOW(),
    error_summary = COALESCE(error_summary, '') || ' | Marked failed by rollback script'
WHERE source_id = :source_id
  AND status IN ('running', 'pending');

\echo 'Updated fetch_runs: ' || :ROW_COUNT;

-- Show new state
\echo '\n>>> Updated fetch_items status:'
SELECT status, COUNT(*) as count
FROM fetch_items
WHERE source_id = :source_id
GROUP BY status;

\echo '\n================================================================================'
\echo 'FETCH PHASE RESET COMPLETE'
\echo 'To perform FULL reset (all items), run with: -v full_reset=true'
\echo '================================================================================'
