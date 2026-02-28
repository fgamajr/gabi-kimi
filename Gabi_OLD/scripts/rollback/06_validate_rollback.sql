-- =============================================================================
-- GABI Rollback: Validate Rollback
-- =============================================================================
-- Purpose: Verify rollback was successful before restarting
-- Usage:   psql -d gabi -f 06_validate_rollback.sql -v source_id="'your_source'"
-- =============================================================================

\echo '================================================================================'
\echo 'VALIDATING ROLLBACK FOR:' :source_id
\echo '================================================================================'

-- Check 1: Pipeline State
\echo '\n>>> CHECK 1: Pipeline State'
SELECT 
    source_id,
    state,
    active_phase,
    CASE 
        WHEN state = 'idle' THEN '✓ PASS - Pipeline is idle'
        WHEN state = 'stopped' THEN '✓ PASS - Pipeline is stopped'
        WHEN state = 'paused' THEN '⚠ WARNING - Pipeline is paused (resume or stop before restart)'
        WHEN state = 'running' THEN '✗ FAIL - Pipeline is still running!'
        ELSE '✗ FAIL - Unknown state: ' || state
    END as validation
FROM source_pipeline_state
WHERE source_id = :source_id;

-- Check 2: No Active Jobs
\echo '\n>>> CHECK 2: No Active Jobs in job_registry'
SELECT 
    COUNT(*) as active_jobs,
    CASE 
        WHEN COUNT(*) = 0 THEN '✓ PASS - No active jobs'
        ELSE '✗ FAIL - ' || COUNT(*) || ' active jobs found! Run reset script.'
    END as validation
FROM job_registry
WHERE source_id = :source_id
  AND status IN ('running', 'processing');

-- Check 3: No Active Ingest Jobs
\echo '\n>>> CHECK 3: No Active Ingest Jobs'
SELECT 
    COUNT(*) as active_ingest_jobs,
    CASE 
        WHEN COUNT(*) = 0 THEN '✓ PASS - No active ingest jobs'
        ELSE '✗ FAIL - ' || COUNT(*) || ' active ingest jobs found!'
    END as validation
FROM ingest_jobs
WHERE source_id = :source_id
  AND status IN ('pending', 'running');

-- Check 4: No Stuck Fetch Items
\echo '\n>>> CHECK 4: No Stuck Fetch Items'
SELECT 
    COUNT(*) as stuck_fetch_items,
    CASE 
        WHEN COUNT(*) = 0 THEN '✓ PASS - No stuck fetch items'
        ELSE '⚠ WARNING - ' || COUNT(*) || ' fetch items still processing (may be OK if recently started)'
    END as validation
FROM fetch_items
WHERE source_id = :source_id
  AND status = 'processing'
  AND started_at < NOW() - INTERVAL '1 hour';

-- Check 5: No Stuck Documents
\echo '\n>>> CHECK 5: No Stuck Documents'
SELECT 
    COUNT(*) as stuck_documents,
    CASE 
        WHEN COUNT(*) = 0 THEN '✓ PASS - No stuck documents'
        ELSE '⚠ WARNING - ' || COUNT(*) || ' documents still processing (may be OK if recently started)'
    END as validation
FROM documents
WHERE source_id = :source_id
  AND status = 'processing'
  AND processing_started_at < NOW() - INTERVAL '1 hour';

-- Check 6: No Orphaned Embeddings
\echo '\n>>> CHECK 6: No Orphaned Embeddings'
SELECT 
    COUNT(*) as orphaned_embeddings,
    CASE 
        WHEN COUNT(*) = 0 THEN '✓ PASS - No orphaned embeddings'
        ELSE '⚠ WARNING - ' || COUNT(*) || ' orphaned embeddings found (should be cleaned up)'
    END as validation
FROM document_embeddings de
WHERE NOT EXISTS (
    SELECT 1 FROM documents d WHERE d.id = de.document_id
);

-- Check 7: No Orphaned Relationships
\echo '\n>>> CHECK 7: No Orphaned Relationships'
SELECT 
    COUNT(*) as orphaned_relationships,
    CASE 
        WHEN COUNT(*) = 0 THEN '✓ PASS - No orphaned relationships'
        ELSE '⚠ WARNING - ' || COUNT(*) || ' orphaned relationships found'
    END as validation
FROM document_relationships dr
WHERE NOT EXISTS (
    SELECT 1 FROM documents d WHERE d.id = dr.source_document_id
);

-- Summary
\echo '\n>>> ROLLBACK VALIDATION SUMMARY'
WITH checks AS (
    SELECT 1 as check_num, 
           CASE WHEN (SELECT COUNT(*) FROM job_registry WHERE source_id = :source_id AND status IN ('running', 'processing')) = 0 
                THEN 1 ELSE 0 END as passed
    UNION ALL
    SELECT 2, 
           CASE WHEN (SELECT COUNT(*) FROM ingest_jobs WHERE source_id = :source_id AND status IN ('pending', 'running')) = 0 
                THEN 1 ELSE 0 END
    UNION ALL
    SELECT 3, 
           CASE WHEN (SELECT state FROM source_pipeline_state WHERE source_id = :source_id) IN ('idle', 'stopped') 
                THEN 1 ELSE 0 END
)
SELECT 
    SUM(passed) as checks_passed,
    COUNT(*) as total_checks,
    CASE 
        WHEN SUM(passed) = COUNT(*) THEN '✓ ALL CHECKS PASSED - Safe to restart pipeline'
        WHEN SUM(passed) >= COUNT(*) - 1 THEN '⚠ MOST CHECKS PASSED - Review warnings before restart'
        ELSE '✗ SOME CHECKS FAILED - Address issues before restart'
    END as overall_status
FROM checks;

\echo '\n================================================================================'
\echo 'VALIDATION COMPLETE'
\echo '================================================================================'
