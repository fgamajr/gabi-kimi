-- worker_jobs_schema.sql
-- Admin upload job lifecycle (Phase 2). Applied at app bootstrap.
-- Transitions: queued -> processing -> completed | failed | partial

CREATE SCHEMA IF NOT EXISTS admin;

CREATE TABLE IF NOT EXISTS admin.worker_jobs (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    filename            text NOT NULL,
    storage_key         text NOT NULL,
    file_size_bytes     bigint,
    file_type           text NOT NULL,
    uploaded_by         text,
    status              text NOT NULL DEFAULT 'queued',
    articles_found      integer,
    articles_ingested   integer,
    articles_dup        integer,
    articles_failed     integer,
    error_message       text,
    error_detail        jsonb,
    completed_at        timestamptz,
    CONSTRAINT chk_worker_jobs_file_type CHECK (file_type IN ('xml', 'zip')),
    CONSTRAINT chk_worker_jobs_status CHECK (status IN ('queued', 'processing', 'completed', 'failed', 'partial'))
);

CREATE INDEX IF NOT EXISTS idx_worker_jobs_status ON admin.worker_jobs(status);

CREATE INDEX IF NOT EXISTS idx_worker_jobs_created_at ON admin.worker_jobs(created_at DESC);
