-- Migration: Job Queue System
-- Description: Dead Letter Queue for failed jobs from ingest_jobs table

-- ═════════════════════════════════════════════════════════════════════════════
-- Dead Letter Queue Table
-- Stores permanently failed jobs for manual review
-- ═════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS job_dlq (
    id BIGSERIAL PRIMARY KEY,
    original_job_id BIGINT NOT NULL REFERENCES ingest_jobs(id),
    
    -- Failure information
    error_message TEXT NOT NULL,
    error_type VARCHAR(100) NOT NULL DEFAULT 'ExecutionFailed',
    stack_trace TEXT,
    
    -- Context at failure
    failed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    worker_id VARCHAR(100),
    retry_count INTEGER NOT NULL DEFAULT 0,
    
    -- DLQ management
    status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending, retrying, archived, resolved
    resolution_notes TEXT,
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolved_by VARCHAR(100),
    
    -- For replay attempts
    retry_after TIMESTAMP WITH TIME ZONE,
    
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- ═════════════════════════════════════════════════════════════════════════════
-- Indexes for DLQ
-- ═════════════════════════════════════════════════════════════════════════════
CREATE INDEX IF NOT EXISTS idx_dlq_status ON job_dlq (status, failed_at);
CREATE INDEX IF NOT EXISTS idx_dlq_source ON job_dlq (original_job_id);
CREATE INDEX IF NOT EXISTS idx_dlq_failed_at ON job_dlq (failed_at DESC);

-- ═════════════════════════════════════════════════════════════════════════════
-- Comments for documentation
-- ═════════════════════════════════════════════════════════════════════════════
COMMENT ON TABLE job_dlq IS 'Dead Letter Queue for permanently failed ingestion jobs';
COMMENT ON COLUMN job_dlq.status IS 'pending, retrying, archived, resolved';
