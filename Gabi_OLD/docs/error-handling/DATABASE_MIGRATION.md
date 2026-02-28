# Database Migration Guide for Enhanced Error Handling

## Overview

This migration adds columns to support:
1. Enhanced DLQ entries with error categorization and context
2. Per-fetch-item retry tracking
3. Circuit breaker state

## Migration SQL

### Step 1: Enhance DLQ Entries Table

```sql
-- Add new columns to dlq_entries table
ALTER TABLE dlq_entries 
    ADD COLUMN IF NOT EXISTS error_category VARCHAR(20) DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS error_code VARCHAR(50) DEFAULT '',
    ADD COLUMN IF NOT EXISTS error_context JSONB,
    ADD COLUMN IF NOT EXISTS suggested_action VARCHAR(500),
    ADD COLUMN IF NOT EXISTS is_recoverable BOOLEAN DEFAULT true,
    ADD COLUMN IF NOT EXISTS first_failed_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS total_retry_duration INTERVAL,
    ADD COLUMN IF NOT EXISTS failure_signature VARCHAR(16),
    ADD COLUMN IF NOT EXISTS similar_failure_count INTEGER DEFAULT 0;

-- Create index for failure signature lookups
CREATE INDEX IF NOT EXISTS idx_dlq_entries_failure_signature 
    ON dlq_entries(failure_signature) 
    WHERE status = 'pending';

-- Create index for error category analysis
CREATE INDEX IF NOT EXISTS idx_dlq_entries_category_status 
    ON dlq_entries(error_category, status);

-- Create index for source-based queries
CREATE INDEX IF NOT EXISTS idx_dlq_entries_source_category 
    ON dlq_entries(source_id, error_category) 
    WHERE status = 'pending';
```

### Step 2: Enhance Fetch Items Table

```sql
-- Add retry tracking columns to fetch_items table
ALTER TABLE fetch_items
    ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS first_failed_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS last_failed_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS retry_history JSONB,
    ADD COLUMN IF NOT EXISTS last_error_category VARCHAR(20),
    ADD COLUMN IF NOT EXISTS last_error_code VARCHAR(50),
    ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS circuit_broken_until TIMESTAMP WITH TIME ZONE;

-- Create index for circuit breaker queries
CREATE INDEX IF NOT EXISTS idx_fetch_items_circuit 
    ON fetch_items(source_id, circuit_broken_until) 
    WHERE status = 'pending';

-- Create index for retry analysis
CREATE INDEX IF NOT EXISTS idx_fetch_items_retry_category 
    ON fetch_items(source_id, last_error_category, retry_count) 
    WHERE status = 'failed';
```

### Step 3: Create Views for Monitoring

```sql
-- View: DLQ summary by category
CREATE OR REPLACE VIEW v_dlq_summary AS
SELECT 
    error_category,
    error_code,
    status,
    COUNT(*) as count,
    MIN(failed_at) as earliest_failure,
    MAX(failed_at) as latest_failure,
    COUNT(DISTINCT source_id) as affected_sources
FROM dlq_entries
GROUP BY error_category, error_code, status;

-- View: Fetch items requiring attention
CREATE OR REPLACE VIEW v_fetch_items_attention AS
SELECT 
    fi.id,
    fi.source_id,
    fi.url,
    fi.status,
    fi.retry_count,
    fi.last_error_category,
    fi.last_error_code,
    fi.consecutive_failures,
    fi.circuit_broken_until,
    CASE 
        WHEN fi.circuit_broken_until > NOW() THEN 'circuit_open'
        WHEN fi.retry_count >= 3 THEN 'high_retry'
        WHEN fi.consecutive_failures >= 3 THEN 'failing_pattern'
        ELSE 'needs_review'
    END as attention_reason
FROM fetch_items fi
WHERE 
    fi.status IN ('failed', 'pending')
    AND (
        fi.circuit_broken_until > NOW()
        OR fi.retry_count >= 3
        OR fi.consecutive_failures >= 3
    );

-- View: Failure patterns for bulk operations
CREATE OR REPLACE VIEW v_failure_patterns AS
SELECT 
    failure_signature,
    error_category,
    error_code,
    suggested_action,
    is_recoverable,
    COUNT(*) as occurrence_count,
    COUNT(DISTINCT source_id) as affected_sources,
    MIN(failed_at) as first_seen,
    MAX(failed_at) as last_seen,
    STRING_AGG(DISTINCT source_id, ', ') as source_ids
FROM dlq_entries
WHERE status = 'pending'
    AND failure_signature IS NOT NULL
GROUP BY failure_signature, error_category, error_code, suggested_action, is_recoverable
HAVING COUNT(*) >= 2
ORDER BY occurrence_count DESC;
```

## Entity Framework Migration

### Create Migration

```bash
# From repository root
dotnet ef migrations add EnhanceErrorHandling \
    --project src/Gabi.Postgres \
    --startup-project src/Gabi.Api \
    --context GabiDbContext
```

### Migration Class (Auto-generated)

The migration will be auto-generated based on entity changes. Key points:

1. **New properties on `DlqEntryEntity`**:
   - `ErrorCategory` (string, max 20)
   - `ErrorCode` (string, max 50)
   - `ErrorContext` (jsonb)
   - `SuggestedAction` (string, max 500)
   - `IsRecoverable` (bool)
   - `FirstFailedAt` (DateTime?)
   - `TotalRetryDuration` (TimeSpan)
   - `FailureSignature` (string, max 16)
   - `SimilarFailureCount` (int)

2. **New properties on `FetchItemEntity`**:
   - `RetryCount` (int)
   - `FirstFailedAt` (DateTime?)
   - `LastFailedAt` (DateTime?)
   - `RetryHistory` (jsonb)
   - `LastErrorCategory` (string, max 20)
   - `LastErrorCode` (string, max 50)
   - `ConsecutiveFailures` (int)
   - `CircuitBrokenUntil` (DateTime?)

## Rollback

```sql
-- Rollback DLQ changes
DROP INDEX IF EXISTS idx_dlq_entries_failure_signature;
DROP INDEX IF EXISTS idx_dlq_entries_category_status;
DROP INDEX IF EXISTS idx_dlq_entries_source_category;

ALTER TABLE dlq_entries 
    DROP COLUMN IF EXISTS error_category,
    DROP COLUMN IF EXISTS error_code,
    DROP COLUMN IF EXISTS error_context,
    DROP COLUMN IF EXISTS suggested_action,
    DROP COLUMN IF EXISTS is_recoverable,
    DROP COLUMN IF EXISTS first_failed_at,
    DROP COLUMN IF EXISTS total_retry_duration,
    DROP COLUMN IF EXISTS failure_signature,
    DROP COLUMN IF EXISTS similar_failure_count;

-- Rollback fetch_items changes
DROP INDEX IF EXISTS idx_fetch_items_circuit;
DROP INDEX IF EXISTS idx_fetch_items_retry_category;

ALTER TABLE fetch_items
    DROP COLUMN IF EXISTS retry_count,
    DROP COLUMN IF EXISTS first_failed_at,
    DROP COLUMN IF EXISTS last_failed_at,
    DROP COLUMN IF EXISTS retry_history,
    DROP COLUMN IF EXISTS last_error_category,
    DROP COLUMN IF EXISTS last_error_code,
    DROP COLUMN IF EXISTS consecutive_failures,
    DROP COLUMN IF EXISTS circuit_broken_until;

-- Drop views
DROP VIEW IF EXISTS v_dlq_summary;
DROP VIEW IF EXISTS v_fetch_items_attention;
DROP VIEW IF EXISTS v_failure_patterns;
```

## Data Migration (Optional)

If you want to populate the new columns for existing DLQ entries:

```sql
-- Classify existing DLQ entries
UPDATE dlq_entries
SET 
    error_category = CASE 
        WHEN error_type LIKE '%HttpRequestException%' AND error_message LIKE '%404%' THEN 'permanent'
        WHEN error_type LIKE '%HttpRequestException%' AND error_message LIKE '%429%' THEN 'throttled'
        WHEN error_type LIKE '%HttpRequestException%' AND error_message LIKE '%40%' THEN 'authentication'
        WHEN error_type LIKE '%HttpRequestException%' AND error_message LIKE '%50%' THEN 'transient'
        WHEN error_type LIKE '%NullReference%' OR error_type LIKE '%Argument%' THEN 'bug'
        ELSE 'transient'
    END,
    error_code = CASE 
        WHEN error_message LIKE '%404%' THEN 'HTTP_404'
        WHEN error_message LIKE '%429%' THEN 'HTTP_429'
        WHEN error_message LIKE '%401%' THEN 'HTTP_401'
        WHEN error_message LIKE '%403%' THEN 'HTTP_403'
        WHEN error_type LIKE '%Timeout%' THEN 'TIMEOUT'
        ELSE 'UNCLASSIFIED'
    END,
    is_recoverable = CASE 
        WHEN error_message LIKE '%404%' OR error_type LIKE '%NullReference%' THEN false
        ELSE true
    END
WHERE error_category = 'unknown';
```

## Verification

```sql
-- Verify DLQ columns
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'dlq_entries'
ORDER BY ordinal_position;

-- Verify fetch_items columns
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'fetch_items'
ORDER BY ordinal_position;

-- Test views
SELECT * FROM v_dlq_summary LIMIT 5;
SELECT * FROM v_failure_patterns LIMIT 5;
```
