-- =============================================================================
-- GABI Rollback: Reset Job Registry
-- =============================================================================
-- Purpose: Reset stuck jobs to allow retry
-- Usage:   psql -d gabi -f 02_reset_job_registry.sql -v source_id="'your_source'"
-- =============================================================================

\echo '================================================================================'
\echo 'RESETTING JOB REGISTRY FOR:' :source_id
\echo '================================================================================'

-- Show current state
\echo '\n>>> Current job_registry status:'
SELECT status, COUNT(*) as count
FROM job_registry
WHERE source_id = :source_id
GROUP BY status;

-- Reset stuck jobs (older than 1 hour)
\echo '\n>>> Resetting stuck jobs to failed...'
UPDATE job_registry
SET status = 'failed',
    error_message = COALESCE(error_message, '') || ' | Manually reset due to rollback at ' || NOW(),
    completed_at = NOW()
WHERE source_id = :source_id
  AND status IN ('running', 'processing', 'pending')
  AND created_at < NOW() - INTERVAL '1 hour';

\echo 'Updated rows: ' || :ROW_COUNT;

-- Show new state
\echo '\n>>> Updated job_registry status:'
SELECT status, COUNT(*) as count
FROM job_registry
WHERE source_id = :source_id
GROUP BY status;

\echo '\n================================================================================'
\echo 'JOB REGISTRY RESET COMPLETE'
\echo '================================================================================'
