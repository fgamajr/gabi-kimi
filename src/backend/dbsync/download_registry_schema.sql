-- Download Registry Schema
-- =========================
--
-- Tracks which ZIP files have been downloaded to avoid re-downloading.
-- This schema is used by the automated pipeline to maintain state
-- across runs.

CREATE SCHEMA IF NOT EXISTS ingest;

-- Table: downloaded_zips
-- Tracks metadata about downloaded ZIP files
CREATE TABLE IF NOT EXISTS ingest.downloaded_zips (
    id SERIAL PRIMARY KEY,
    
    -- Publication metadata
    section TEXT NOT NULL,              -- do1, do2, do3, do1e, etc.
    publication_date DATE NOT NULL,     -- First day of month for monthly ZIPs
    edition_number TEXT,                -- e.g., "123" (often empty for monthly bundles)
    edition_type TEXT NOT NULL,         -- regular, extra, special
    
    -- File metadata
    filename TEXT NOT NULL,             -- Server filename (e.g., S01012026.zip)
    local_filename TEXT NOT NULL,       -- Local filename after download
    folder_id INTEGER NOT NULL,         -- Liferay folder ID
    file_size BIGINT,                   -- File size in bytes
    
    -- Download metadata
    sha256 TEXT,                        -- SHA-256 checksum
    downloaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    download_status TEXT NOT NULL,      -- success, failed, skipped
    error_message TEXT,                 -- Error message if download failed
    retry_count INTEGER NOT NULL DEFAULT 0,
    
    -- Evidence chain
    listing_sha256 TEXT,                -- SHA-256 of the catalog listing (if available)
    
    -- Constraints
    UNIQUE(section, publication_date, filename)
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_downloaded_zips_section_date 
    ON ingest.downloaded_zips(section, publication_date);

CREATE INDEX IF NOT EXISTS idx_downloaded_zips_status 
    ON ingest.downloaded_zips(download_status);

CREATE INDEX IF NOT EXISTS idx_downloaded_zips_downloaded_at 
    ON ingest.downloaded_zips(downloaded_at);

-- View: pending_downloads
-- Shows ZIPs that need to be downloaded (not yet downloaded or failed)
CREATE OR REPLACE VIEW ingest.pending_downloads AS
SELECT 
    section,
    publication_date,
    edition_type,
    filename,
    folder_id,
    retry_count
FROM ingest.downloaded_zips
WHERE download_status = 'failed' 
    AND retry_count < 3  -- Allow up to 3 retries
UNION
SELECT 
    section,
    publication_date,
    edition_type,
    filename,
    folder_id,
    0 as retry_count
FROM ingest.downloaded_zips
WHERE download_status = 'pending';

-- View: download_statistics
-- Provides summary statistics about downloads
CREATE OR REPLACE VIEW ingest.download_statistics AS
SELECT 
    COUNT(*) as total_downloads,
    COUNT(*) FILTER (WHERE download_status = 'success') as successful_downloads,
    COUNT(*) FILTER (WHERE download_status = 'failed') as failed_downloads,
    COUNT(*) FILTER (WHERE download_status = 'skipped') as skipped_downloads,
    SUM(file_size) FILTER (WHERE download_status = 'success') as total_bytes_downloaded,
    MIN(downloaded_at) as first_download,
    MAX(downloaded_at) as last_download
FROM ingest.downloaded_zips;

-- Function: mark_download_success
-- Marks a download as successful
CREATE OR REPLACE FUNCTION ingest.mark_download_success(
    p_section TEXT,
    p_publication_date DATE,
    p_filename TEXT,
    p_file_size BIGINT,
    p_sha256 TEXT,
    p_local_filename TEXT
) RETURNS VOID AS $$
BEGIN
    INSERT INTO ingest.downloaded_zips (
        section,
        publication_date,
        edition_number,
        edition_type,
        filename,
        local_filename,
        folder_id,
        file_size,
        sha256,
        download_status,
        error_message,
        retry_count
    ) VALUES (
        p_section,
        p_publication_date,
        '',  -- edition_number (empty for monthly bundles)
        'regular',  -- edition_type
        p_filename,
        p_local_filename,
        0,  -- folder_id (will be updated later)
        p_file_size,
        p_sha256,
        'success',
        NULL,
        0
    )
    ON CONFLICT (section, publication_date, filename) 
    DO UPDATE SET
        file_size = EXCLUDED.file_size,
        sha256 = EXCLUDED.sha256,
        local_filename = EXCLUDED.local_filename,
        download_status = 'success',
        error_message = NULL,
        retry_count = 0,
        downloaded_at = NOW();
END;
$$ LANGUAGE plpgsql;

-- Function: mark_download_failed
-- Marks a download as failed and increments retry count
CREATE OR REPLACE FUNCTION ingest.mark_download_failed(
    p_section TEXT,
    p_publication_date DATE,
    p_filename TEXT,
    p_error_message TEXT
) RETURNS VOID AS $$
BEGIN
    INSERT INTO ingest.downloaded_zips (
        section,
        publication_date,
        edition_number,
        edition_type,
        filename,
        local_filename,
        folder_id,
        file_size,
        sha256,
        download_status,
        error_message,
        retry_count
    ) VALUES (
        p_section,
        p_publication_date,
        '',
        'regular',
        p_filename,
        '',
        0,
        NULL,
        NULL,
        'failed',
        p_error_message,
        1
    )
    ON CONFLICT (section, publication_date, filename) 
    DO UPDATE SET
        download_status = 'failed',
        error_message = EXCLUDED.error_message,
        retry_count = ingest.downloaded_zips.retry_count + 1,
        downloaded_at = NOW();
END;
$$ LANGUAGE plpgsql;

-- Function: is_already_downloaded
-- Checks if a ZIP has already been successfully downloaded
CREATE OR REPLACE FUNCTION ingest.is_already_downloaded(
    p_section TEXT,
    p_publication_date DATE,
    p_filename TEXT
) RETURNS BOOLEAN AS $$
DECLARE
    v_exists BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM ingest.downloaded_zips
        WHERE section = p_section
            AND publication_date = p_publication_date
            AND filename = p_filename
            AND download_status = 'success'
    ) INTO v_exists;
    
    RETURN v_exists;
END;
$$ LANGUAGE plpgsql;

-- Comments
COMMENT ON TABLE ingest.downloaded_zips IS
    'Tracks downloaded DOU ZIP files to avoid re-downloading';

COMMENT ON COLUMN ingest.downloaded_zips.section IS
    'DOU section code (do1, do2, do3, do1e, etc.)';

COMMENT ON COLUMN ingest.downloaded_zips.publication_date IS
    'Publication date (first day of month for monthly bundles)';

COMMENT ON COLUMN ingest.downloaded_zips.download_status IS
    'Download status: success, failed, or skipped';

COMMENT ON COLUMN ingest.downloaded_zips.retry_count IS
    'Number of retry attempts for failed downloads';
