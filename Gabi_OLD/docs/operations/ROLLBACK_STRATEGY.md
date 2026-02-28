# GABI Pipeline Rollback Strategy

> **Purpose**: Safe recovery from partial failures during pipeline execution.
> **Scope**: Source-level rollback operations for all pipeline phases.

---

## Table of Contents

1. [Overview](#overview)
2. [Pre-Rollback Checklist](#pre-rollback-checklist)
3. [Database Backup](#database-backup)
4. [Rollback Commands](#rollback-commands)
   - [1. Reset job_registry Status](#1-reset-job_registry-status)
   - [2. Clean Up Partial fetch_items](#2-clean-up-partial-fetch_items)
   - [3. Remove Partially Ingested Documents](#3-remove-partially-ingested-documents)
   - [4. Restart From Specific Stage](#4-restart-from-specific-stage)
5. [Stage-Specific Rollback Procedures](#stage-specific-rollback-procedures)
6. [Emergency Procedures](#emergency-procedures)
7. [Validation After Rollback](#validation-after-rollback)

---

## Overview

The GABI pipeline processes data through these stages:

```
Discovery → Fetch → Ingest (Parse → Chunk → Embed → Index)
```

Each stage has corresponding database tables that track state:

| Stage | Primary Tables | Status Fields |
|-------|---------------|---------------|
| Discovery | `discovered_links`, `discovery_runs` | `DiscoveryStatus` |
| Fetch | `fetch_items`, `fetch_runs` | `FetchStatus` |
| Ingest | `documents`, `ingest_jobs` | `Status`, `ProcessingStage` |
| All | `job_registry`, `source_pipeline_state` | `Status`, `State` |

---

## Pre-Rollback Checklist

Before performing any rollback:

- [ ] Identify the failing source: `source_id = '...'`
- [ ] Identify the failing stage: `discovery`, `fetch`, or `ingest`
- [ ] Confirm current pipeline state is not `running` (or pause first)
- [ ] **Create database backup** (see [Database Backup](#database-backup))
- [ ] Verify no active jobs in Hangfire dashboard
- [ ] Document reason for rollback in incident log

---

## Database Backup

### Before Major Operations

```bash
# Full database backup (recommended)
pg_dump -h localhost -p 5433 -U postgres -d gabi -F c -f "gabi_backup_$(date +%Y%m%d_%H%M%S).dump"

# Or backup specific source data only
pg_dump -h localhost -p 5433 -U postgres -d gabi \
  --table="discovered_links" \
  --table="fetch_items" \
  --table="documents" \
  --table="document_embeddings" \
  --table="job_registry" \
  --table="ingest_jobs" \
  --table="source_pipeline_state" \
  --table="workflow_events" \
  -F c -f "gabi_source_rollback_$(date +%Y%m%d_%H%M%S).dump"
```

### Quick Data Export (JSON)

```sql
-- Export pre-rollback state for audit
COPY (
  SELECT json_agg(row_to_json(t))
  FROM (
    SELECT source_id, status, job_type, created_at 
    FROM job_registry 
    WHERE source_id = 'YOUR_SOURCE_ID'
  ) t
) TO '/tmp/job_registry_backup.json';
```

---

## Rollback Commands

### 1. Reset job_registry Status

**Use case**: A job is stuck in `running` or `processing` state after worker crash.

```sql
-- View current jobs for source
SELECT job_id, job_type, status, created_at, started_at, completed_at, error_message
FROM job_registry
WHERE source_id = 'YOUR_SOURCE_ID'
ORDER BY created_at DESC;

-- Reset stuck jobs to 'failed' (allowing retry)
UPDATE job_registry
SET status = 'failed',
    error_message = COALESCE(error_message, '') || ' | Manually reset due to rollback',
    completed_at = NOW()
WHERE source_id = 'YOUR_SOURCE_ID'
  AND status IN ('running', 'processing', 'pending')
  AND created_at < NOW() - INTERVAL '1 hour';  -- Only old jobs

-- Alternative: Reset specific job by ID
UPDATE job_registry
SET status = 'failed',
    completed_at = NOW(),
    error_message = 'Reset for retry after incident'
WHERE job_id = 'YOUR_JOB_ID';
```

### 2. Clean Up Partial fetch_items

**Use case**: Fetch phase partially completed with corrupt/incomplete data.

```sql
-- View fetch_items status summary
SELECT status, COUNT(*) as count
FROM fetch_items
WHERE source_id = 'YOUR_SOURCE_ID'
GROUP BY status;

-- Option A: Reset ALL fetch_items to pending (full refetch)
UPDATE fetch_items
SET status = 'pending',
    attempts = 0,
    last_error = NULL,
    started_at = NULL,
    completed_at = NULL
WHERE source_id = 'YOUR_SOURCE_ID';

-- Option B: Reset only failed/processing items (preserve completed)
UPDATE fetch_items
SET status = 'pending',
    attempts = 0,
    last_error = NULL,
    started_at = NULL,
    completed_at = NULL
WHERE source_id = 'YOUR_SOURCE_ID'
  AND status IN ('failed', 'processing', 'error');

-- Option C: Delete fetch_items for specific failed run
DELETE FROM fetch_items
WHERE source_id = 'YOUR_SOURCE_ID'
  AND fetch_run_id = 'YOUR_FETCH_RUN_ID';

-- Also reset discovered_links fetch_status
UPDATE discovered_links
SET fetch_status = 'pending'
WHERE source_id = 'YOUR_SOURCE_ID'
  AND fetch_status IN ('processing', 'failed');
```

### 3. Remove Partially Ingested Documents

**Use case**: Ingest phase created incomplete/corrupt documents that need reprocessing.

```sql
-- View document status summary
SELECT status, processing_stage, COUNT(*) as count
FROM documents
WHERE source_id = 'YOUR_SOURCE_ID'
GROUP BY status, processing_stage;

-- Option A: Soft delete all documents for source (safest)
UPDATE documents
SET status = 'deleted',
    removed_from_source_at = NOW(),
    removed_reason = 'Rollback: removing partial ingest'
WHERE source_id = 'YOUR_SOURCE_ID'
  AND status != 'deleted'
  AND removed_from_source_at IS NULL;

-- Option B: Reset only failed/processing documents to pending
UPDATE documents
SET status = 'pending',
    processing_stage = NULL,
    processing_started_at = NULL,
    processing_completed_at = NULL,
    elasticsearch_id = NULL,
    embedding_id = NULL
WHERE source_id = 'YOUR_SOURCE_ID'
  AND status IN ('failed', 'processing', 'error');

-- Option C: Hard delete documents for a specific fetch_item (CASCADE to embeddings)
DELETE FROM documents
WHERE source_id = 'YOUR_SOURCE_ID'
  AND fetch_item_id = YOUR_FETCH_ITEM_ID;

-- Clean up orphaned embeddings (documents no longer exist)
DELETE FROM document_embeddings de
WHERE NOT EXISTS (
  SELECT 1 FROM documents d WHERE d.id = de.document_id
);

-- Clean up orphaned relationships
DELETE FROM document_relationships dr
WHERE NOT EXISTS (
  SELECT 1 FROM documents d WHERE d.id = dr.source_document_id
);
```

### 4. Restart From Specific Stage

**Use case**: Need to restart pipeline from a specific phase.

#### 4.1 Reset to Discovery Stage

```sql
-- Reset discovered_links to pending
UPDATE discovered_links
SET status = 'pending',
    discovery_status = 'pending',
    fetch_status = 'pending',
    ingest_status = 'pending',
    process_attempts = 0,
    last_processed_at = NULL
WHERE source_id = 'YOUR_SOURCE_ID';

-- Clear fetch_items (will be recreated from discovery)
DELETE FROM fetch_items WHERE source_id = 'YOUR_SOURCE_ID';

-- Reset or delete documents
UPDATE documents
SET status = 'deleted',
    removed_from_source_at = NOW(),
    removed_reason = 'Rollback: full pipeline restart'
WHERE source_id = 'YOUR_SOURCE_ID'
  AND removed_from_source_at IS NULL;

-- Reset pipeline state
UPDATE source_pipeline_state
SET state = 'idle',
    active_phase = NULL,
    updated_at = NOW()
WHERE source_id = 'YOUR_SOURCE_ID';

-- Clean up ingest_jobs
DELETE FROM ingest_jobs
WHERE source_id = 'YOUR_SOURCE_ID'
  AND status IN ('pending', 'running');
```

#### 4.2 Reset to Fetch Stage (Preserve Discovery)

```sql
-- Keep discovered_links as completed, reset fetch_status
UPDATE discovered_links
SET fetch_status = 'pending',
    ingest_status = 'pending'
WHERE source_id = 'YOUR_SOURCE_ID'
  AND discovery_status = 'completed';

-- Reset fetch_items
UPDATE fetch_items
SET status = 'pending',
    attempts = 0,
    last_error = NULL,
    started_at = NULL,
    completed_at = NULL
WHERE source_id = 'YOUR_SOURCE_ID';

-- Reset documents created from failed fetch
UPDATE documents
SET status = 'deleted',
    removed_from_source_at = NOW(),
    removed_reason = 'Rollback: fetch restart'
WHERE source_id = 'YOUR_SOURCE_ID'
  AND status IN ('pending', 'processing', 'failed');

-- Update pipeline state
UPDATE source_pipeline_state
SET state = 'idle',
    active_phase = NULL,
    updated_at = NOW()
WHERE source_id = 'YOUR_SOURCE_ID';
```

#### 4.3 Reset to Ingest Stage (Preserve Fetch)

```sql
-- Keep discovered_links and fetch_items as completed
UPDATE discovered_links
SET ingest_status = 'pending'
WHERE source_id = 'YOUR_SOURCE_ID'
  AND fetch_status = 'completed';

-- Reset documents to pending (will be re-ingested)
UPDATE documents
SET status = 'pending',
    processing_stage = NULL,
    processing_started_at = NULL,
    processing_completed_at = NULL,
    elasticsearch_id = NULL,
    embedding_id = NULL,
    removed_from_source_at = NULL,
    removed_reason = NULL
WHERE source_id = 'YOUR_SOURCE_ID'
  AND status IN ('completed', 'completed_metadata_only', 'failed', 'processing');

-- Clear embeddings for these documents
DELETE FROM document_embeddings
WHERE document_id IN (
  SELECT id FROM documents 
  WHERE source_id = 'YOUR_SOURCE_ID' 
    AND status = 'pending'
);

-- Clear relationships
DELETE FROM document_relationships
WHERE source_document_id IN (
  SELECT id FROM documents 
  WHERE source_id = 'YOUR_SOURCE_ID' 
    AND status = 'pending'
);

-- Update pipeline state
UPDATE source_pipeline_state
SET state = 'idle',
    active_phase = NULL,
    updated_at = NOW()
WHERE source_id = 'YOUR_SOURCE_ID';
```

---

## Stage-Specific Rollback Procedures

### Discovery Phase Failure

```sql
-- 1. Identify failed discovery run
SELECT * FROM discovery_runs
WHERE source_id = 'YOUR_SOURCE_ID'
ORDER BY started_at DESC LIMIT 5;

-- 2. Reset discovered_links from failed run
UPDATE discovered_links
SET status = 'pending',
    discovery_status = 'pending',
    fetch_status = 'pending',
    ingest_status = 'pending'
WHERE source_id = 'YOUR_SOURCE_ID'
  AND id IN (
    SELECT link_id FROM execution_manifest
    WHERE discovery_run_id = 'FAILED_RUN_ID'
  );

-- 3. Mark discovery run as failed
UPDATE discovery_runs
SET status = 'failed',
    completed_at = NOW()
WHERE id = 'FAILED_RUN_ID';

-- 4. Reset pipeline state
UPDATE source_pipeline_state
SET state = 'idle',
    active_phase = NULL
WHERE source_id = 'YOUR_SOURCE_ID';
```

### Fetch Phase Failure

```sql
-- 1. Check fetch run status
SELECT * FROM fetch_runs
WHERE source_id = 'YOUR_SOURCE_ID'
ORDER BY started_at DESC LIMIT 5;

-- 2. Reset stuck fetch_items
UPDATE fetch_items
SET status = 'pending',
    attempts = 0,
    last_error = NULL
WHERE source_id = 'YOUR_SOURCE_ID'
  AND status = 'processing'
  AND started_at < NOW() - INTERVAL '2 hours';

-- 3. Mark fetch run as failed
UPDATE fetch_runs
SET status = 'failed',
    completed_at = NOW()
WHERE id = 'FAILED_RUN_ID';

-- 4. Clean up partial documents from failed fetch
DELETE FROM documents
WHERE source_id = 'YOUR_SOURCE_ID'
  AND fetch_item_id IN (
    SELECT id FROM fetch_items
    WHERE fetch_run_id = 'FAILED_RUN_ID'
      AND status = 'failed'
  );
```

### Ingest Phase Failure

```sql
-- 1. Find documents stuck in processing
SELECT id, external_id, processing_stage, processing_started_at
FROM documents
WHERE source_id = 'YOUR_SOURCE_ID'
  AND status = 'processing'
  AND processing_started_at < NOW() - INTERVAL '2 hours';

-- 2. Reset stuck documents to pending
UPDATE documents
SET status = 'pending',
    processing_stage = NULL,
    processing_started_at = NULL
WHERE source_id = 'YOUR_SOURCE_ID'
  AND status = 'processing'
  AND processing_started_at < NOW() - INTERVAL '2 hours';

-- 3. Clean up partial embeddings
DELETE FROM document_embeddings
WHERE document_id IN (
  SELECT id FROM documents
  WHERE source_id = 'YOUR_SOURCE_ID'
    AND status = 'pending'
);

-- 4. Clear failed documents from Elasticsearch (if needed)
-- This requires API call to ES, not SQL
```

---

## Emergency Procedures

### Nuclear Option: Full Source Reset

> **WARNING**: This removes ALL data for a source. Use with extreme caution.

```sql
-- Start transaction
BEGIN;

-- 1. Verify source exists and record count
SELECT 
  (SELECT COUNT(*) FROM discovered_links WHERE source_id = 'YOUR_SOURCE_ID') as links,
  (SELECT COUNT(*) FROM fetch_items WHERE source_id = 'YOUR_SOURCE_ID') as fetch_items,
  (SELECT COUNT(*) FROM documents WHERE source_id = 'YOUR_SOURCE_ID') as documents;

-- 2. Soft delete all documents
UPDATE documents
SET status = 'deleted',
    removed_from_source_at = NOW(),
    removed_reason = 'Nuclear rollback: full source reset'
WHERE source_id = 'YOUR_SOURCE_ID'
  AND removed_from_source_at IS NULL;

-- 3. Delete fetch_items
DELETE FROM fetch_items WHERE source_id = 'YOUR_SOURCE_ID';

-- 4. Reset discovered_links
UPDATE discovered_links
SET status = 'pending',
    discovery_status = 'pending',
    fetch_status = 'pending',
    ingest_status = 'pending',
    process_attempts = 0
WHERE source_id = 'YOUR_SOURCE_ID';

-- 5. Clear jobs
DELETE FROM ingest_jobs WHERE source_id = 'YOUR_SOURCE_ID';
UPDATE job_registry
SET status = 'cancelled',
    completed_at = NOW()
WHERE source_id = 'YOUR_SOURCE_ID'
  AND status IN ('pending', 'running', 'processing');

-- 6. Reset pipeline state
UPDATE source_pipeline_state
SET state = 'idle',
    active_phase = NULL,
    paused_by = NULL,
    paused_at = NULL,
    updated_at = NOW()
WHERE source_id = 'YOUR_SOURCE_ID';

-- 7. Clean up DLQ entries for source
UPDATE dlq_entries
SET status = 'archived',
    notes = COALESCE(notes, '') || ' | Archived due to source reset'
WHERE source_id = 'YOUR_SOURCE_ID'
  AND status = 'pending';

-- COMMIT or ROLLBACK based on verification
-- COMMIT;
-- ROLLBACK;
```

### Corrupted Document Cleanup

```sql
-- Find documents with NULL/empty content but completed status
SELECT id, external_id, source_id, content IS NULL as content_null, LENGTH(content) as content_length
FROM documents
WHERE source_id = 'YOUR_SOURCE_ID'
  AND status = 'completed'
  AND (content IS NULL OR LENGTH(TRIM(content)) = 0);

-- Reset them to pending for reprocessing
UPDATE documents
SET status = 'pending',
    processing_stage = NULL,
    processing_started_at = NULL,
    processing_completed_at = NULL
WHERE source_id = 'YOUR_SOURCE_ID'
  AND status = 'completed'
  AND (content IS NULL OR LENGTH(TRIM(content)) = 0);

-- Or soft delete if they should be removed
UPDATE documents
SET status = 'deleted',
    removed_from_source_at = NOW(),
    removed_reason = 'Empty content after ingest'
WHERE source_id = 'YOUR_SOURCE_ID'
  AND status = 'completed'
  AND (content IS NULL OR LENGTH(TRIM(content)) = 0);
```

---

## Validation After Rollback

### Verify Rollback Success

```sql
-- Check job_registry has no running/processing jobs
SELECT status, COUNT(*) 
FROM job_registry 
WHERE source_id = 'YOUR_SOURCE_ID'
GROUP BY status;

-- Check pipeline state is idle
SELECT source_id, state, active_phase, updated_at
FROM source_pipeline_state
WHERE source_id = 'YOUR_SOURCE_ID';

-- Verify fetch_items status
SELECT status, COUNT(*) 
FROM fetch_items 
WHERE source_id = 'YOUR_SOURCE_ID'
GROUP BY status;

-- Verify document status
SELECT status, COUNT(*) 
FROM documents 
WHERE source_id = 'YOUR_SOURCE_ID'
  AND removed_from_source_at IS NULL
GROUP BY status;

-- Check for orphaned embeddings
SELECT COUNT(*) as orphaned_embeddings
FROM document_embeddings de
WHERE NOT EXISTS (
  SELECT 1 FROM documents d WHERE d.id = de.document_id
);
```

### Re-enqueue Job After Rollback

Use the API to restart the pipeline:

```bash
# Get token
TOKEN=$(curl -s -X POST http://localhost:5100/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"YOUR_PASSWORD"}' | jq -r '.token')

# Restart from discovery
curl -X POST http://localhost:5100/api/v1/dashboard/sources/YOUR_SOURCE_ID/phases/discovery \
  -H "Authorization: Bearer $TOKEN"

# Or restart from fetch (if discovery was successful)
curl -X POST http://localhost:5100/api/v1/dashboard/sources/YOUR_SOURCE_ID/phases/fetch \
  -H "Authorization: Bearer $TOKEN"

# Or restart from ingest (if fetch was successful)
curl -X POST http://localhost:5100/api/v1/dashboard/sources/YOUR_SOURCE_ID/phases/ingest \
  -H "Authorization: Bearer $TOKEN"

# Or run full pipeline
curl -X POST http://localhost:5100/api/v1/dashboard/sources/YOUR_SOURCE_ID/run-pipeline \
  -H "Authorization: Bearer $TOKEN"
```

---

## Summary: Quick Reference

| Scenario | SQL Command Pattern |
|----------|---------------------|
| Job stuck running | `UPDATE job_registry SET status='failed' WHERE ...` |
| Refetch all | `UPDATE fetch_items SET status='pending' WHERE source_id='...'` |
| Re-ingest all | `UPDATE documents SET status='pending' WHERE source_id='...'` |
| Full reset | See [Nuclear Option](#nuclear-option-full-source-reset) |
| Emergency stop | `UPDATE source_pipeline_state SET state='stopped' WHERE ...` |

---

## Related Documentation

- [Architecture Overview](../architecture/LAYERED_ARCHITECTURE.md)
- [Chaos Playbook](../reliability/CHAOS_PLAYBOOK.md)
- [Database Schema](../database/SCHEMA.md)
