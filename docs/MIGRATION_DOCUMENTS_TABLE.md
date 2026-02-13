# Migration: Documents Table

## Overview

Migration para criar a tabela `documents` que suportará a fase futura de ingestão de documentos.

## Migration Script

```sql
-- Migration: CreateDocumentsTable
-- Created: 2025-02-12

CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    link_id BIGINT NOT NULL REFERENCES discovered_links(id) ON DELETE CASCADE,
    source_id VARCHAR(100) NOT NULL,
    document_id VARCHAR(255),
    title TEXT,
    content TEXT,
    content_url VARCHAR(2048),
    content_hash VARCHAR(64),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    processing_stage VARCHAR(50),
    processing_started_at TIMESTAMPTZ,
    processing_completed_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}',
    embedding_id UUID,
    elasticsearch_id VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    xmin BIGINT NOT NULL DEFAULT 0
);

-- Indexes for performance
CREATE INDEX idx_documents_link_id ON documents(link_id);
CREATE INDEX idx_documents_status ON documents(status);
CREATE INDEX idx_documents_created_at ON documents(created_at);
CREATE INDEX idx_documents_source_id ON documents(source_id);
CREATE INDEX idx_documents_content_hash ON documents(content_hash);

-- GIN index for metadata JSONB queries
CREATE INDEX idx_documents_metadata ON documents USING GIN(metadata);

-- Trigger to update xmin for optimistic concurrency
CREATE OR REPLACE FUNCTION update_xmin()
RETURNS TRIGGER AS $$
BEGIN
    NEW.xmin = OLD.xmin + 1;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER documents_update_xmin
    BEFORE UPDATE ON documents
    FOR EACH ROW
    EXECUTE FUNCTION update_xmin();

-- Trigger to auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER documents_update_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

## EF Core Migration Command

```bash
cd /home/fgamajr/dev/gabi-kimi

dotnet ef migrations add CreateDocumentsTable \
  --project src/Gabi.Postgres \
  --startup-project src/Gabi.Api \
  --output-dir Migrations

dotnet ef database update \
  --project src/Gabi.Postgres \
  --startup-project src/Gabi.Api
```

## Rollback

```bash
dotnet ef database update <previous-migration> \
  --project src/Gabi.Postgres \
  --startup-project src/Gabi.Api
```

## Notes

- Table is currently empty and not actively used
- Structure prepared for future ingest phase
- Foreign key with CASCADE DELETE: when a link is deleted, its documents are also deleted
- JSONB metadata allows flexible schema for source-specific fields
