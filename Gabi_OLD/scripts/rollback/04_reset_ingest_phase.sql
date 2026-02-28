-- =============================================================================
-- GABI Rollback: Reset Ingest Phase
-- =============================================================================
-- Purpose: Reset ingest phase to allow reprocessing
-- Usage:   psql -d gabi -f 04_reset_ingest_phase.sql -v source_id="'your_source'"
-- Options: Set include_completed=true to reset completed docs too
-- =============================================================================

\echo '================================================================================'
\echo 'RESETTING INGEST PHASE FOR:' :source_id
\echo '================================================================================'

-- Check if include_completed variable is set, default to false
\if :{?include_completed}
\else
\set include_completed false
\endif

-- Show current state
\echo '\n>>> Current documents status:'
SELECT status, processing_stage, COUNT(*) as count
FROM documents
WHERE source_id = :source_id
  AND removed_from_source_at IS NULL
GROUP BY status, processing_stage
ORDER BY status, processing_stage;

-- Reset documents based on option
\if :include_completed
    \echo '\n>>> FULL RESET: Setting ALL documents to pending (including completed)...'
    UPDATE documents
    SET status = 'pending',
        processing_stage = NULL,
        processing_started_at = NULL,
        processing_completed_at = NULL,
        elasticsearch_id = NULL,
        embedding_id = NULL,
        removed_from_source_at = NULL,
        removed_reason = NULL,
        updated_at = NOW(),
        updated_by = 'rollback_script'
    WHERE source_id = :source_id
      AND removed_from_source_at IS NULL;
\else
    \echo '\n>>> PARTIAL RESET: Setting only failed/processing documents to pending...'
    UPDATE documents
    SET status = 'pending',
        processing_stage = NULL,
        processing_started_at = NULL,
        processing_completed_at = NULL,
        elasticsearch_id = NULL,
        embedding_id = NULL,
        updated_at = NOW(),
        updated_by = 'rollback_script'
    WHERE source_id = :source_id
      AND status IN ('failed', 'processing', 'error', 'pending_projection');
\endif

\echo 'Updated documents: ' || :ROW_COUNT;

-- Clean up embeddings for reset documents
\echo '\n>>> Cleaning up orphaned embeddings...'
DELETE FROM document_embeddings
WHERE document_id IN (
    SELECT id FROM documents
    WHERE source_id = :source_id
      AND status = 'pending'
);

\echo 'Deleted embeddings: ' || :ROW_COUNT;

-- Clean up relationships for reset documents
\echo '\n>>> Cleaning up orphaned relationships...'
DELETE FROM document_relationships
WHERE source_document_id IN (
    SELECT id FROM documents
    WHERE source_id = :source_id
      AND status = 'pending'
);

\echo 'Deleted relationships: ' || :ROW_COUNT;

-- Reset discovered_links ingest_status
\echo '\n>>> Resetting discovered_links ingest_status...'
UPDATE discovered_links
SET ingest_status = 'pending',
    updated_at = NOW(),
    updated_by = 'rollback_script'
WHERE source_id = :source_id
  AND ingest_status IN ('processing', 'failed', 'error');

\echo 'Updated discovered_links: ' || :ROW_COUNT;

-- Show new state
\echo '\n>>> Updated documents status:'
SELECT status, processing_stage, COUNT(*) as count
FROM documents
WHERE source_id = :source_id
  AND removed_from_source_at IS NULL
GROUP BY status, processing_stage
ORDER BY status, processing_stage;

\echo '\n================================================================================'
\echo 'INGEST PHASE RESET COMPLETE'
\echo 'To include completed documents, run with: -v include_completed=true'
\echo '================================================================================'
