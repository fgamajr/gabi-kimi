-- =============================================================================
-- GABI Rollback: Check Source Status
-- =============================================================================
-- Purpose: Verify current state before performing rollback
-- Usage:   psql -d gabi -f 01_check_source_status.sql -v source_id="'your_source'"
-- =============================================================================

\echo '================================================================================'
\echo 'SOURCE STATUS CHECK FOR:' :source_id
\echo '================================================================================'

-- Pipeline State
\echo '\n>>> Pipeline State:'
SELECT source_id, state, active_phase, paused_by, paused_at, last_resumed_at, updated_at
FROM source_pipeline_state
WHERE source_id = :source_id;

-- Job Registry Summary
\echo '\n>>> Job Registry (Last 10):'
SELECT job_id, job_type, status, created_at, started_at, completed_at,
       COALESCE(LEFT(error_message, 80), '') as error_preview
FROM job_registry
WHERE source_id = :source_id
ORDER BY created_at DESC
LIMIT 10;

-- Discovered Links Summary
\echo '\n>>> Discovered Links Status:'
SELECT 
    status,
    discovery_status,
    fetch_status,
    ingest_status,
    COUNT(*) as count
FROM discovered_links
WHERE source_id = :source_id
GROUP BY status, discovery_status, fetch_status, ingest_status
ORDER BY count DESC;

-- Fetch Items Summary
\echo '\n>>> Fetch Items Status:'
SELECT status, COUNT(*) as count
FROM fetch_items
WHERE source_id = :source_id
GROUP BY status
ORDER BY count DESC;

-- Documents Summary
\echo '\n>>> Documents Status:'
SELECT 
    status, 
    processing_stage,
    COUNT(*) as count
FROM documents
WHERE source_id = :source_id
  AND removed_from_source_at IS NULL
GROUP BY status, processing_stage
ORDER BY count DESC;

-- Active Jobs
\echo '\n>>> Active Ingest Jobs:'
SELECT id, job_type, status, scheduled_at, started_at, attempts, max_attempts
FROM ingest_jobs
WHERE source_id = :source_id
  AND status IN ('pending', 'running')
ORDER BY scheduled_at;

-- DLQ Entries
\echo '\n>>> DLQ Entries (Last 5):'
SELECT id, job_type, status, failed_at, error_type, 
       COALESCE(LEFT(error_message, 80), '') as error_preview
FROM dlq_entries
WHERE source_id = :source_id
ORDER BY failed_at DESC
LIMIT 5;

-- Totals Summary
\echo '\n>>> TOTALS SUMMARY:'
SELECT
    (SELECT COUNT(*) FROM discovered_links WHERE source_id = :source_id) as total_links,
    (SELECT COUNT(*) FROM fetch_items WHERE source_id = :source_id) as total_fetch_items,
    (SELECT COUNT(*) FROM documents WHERE source_id = :source_id AND removed_from_source_at IS NULL) as total_active_docs,
    (SELECT COUNT(*) FROM documents WHERE source_id = :source_id AND status = 'completed' AND removed_from_source_at IS NULL) as completed_docs,
    (SELECT COUNT(*) FROM job_registry WHERE source_id = :source_id) as total_jobs,
    (SELECT COUNT(*) FROM job_registry WHERE source_id = :source_id AND status IN ('running', 'processing')) as active_jobs;

\echo '\n================================================================================'
\echo 'STATUS CHECK COMPLETE'
\echo '================================================================================'
