-- =============================================================================
-- GABI - Gerador Automático de Boletins por Inteligência Artificial
-- Schema Inicial do PostgreSQL
-- Versão: 1.0.0
-- Baseado em: GABI_SPECS_FINAL_v1.md - Seção 2.7.1
-- =============================================================================

-- =============================================================================
-- EXTENSÕES
-- =============================================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================================================
-- ENUMS
-- =============================================================================
CREATE TYPE source_type AS ENUM ('api', 'web', 'file', 'crawler');
CREATE TYPE source_status AS ENUM ('active', 'paused', 'error', 'disabled');
CREATE TYPE execution_status AS ENUM ('pending', 'running', 'success', 'partial_success', 'failed', 'cancelled');
CREATE TYPE document_status AS ENUM ('active', 'updated', 'deleted', 'error');
CREATE TYPE dlq_status AS ENUM ('pending', 'retrying', 'exhausted', 'resolved', 'archived');
CREATE TYPE sensitivity_level AS ENUM ('public', 'internal', 'restricted', 'confidential');

CREATE TYPE audit_event_type AS ENUM (
    'document_viewed', 'document_searched', 'document_created', 
    'document_updated', 'document_deleted', 'document_reindexed',
    'sync_started', 'sync_completed', 'sync_failed', 'sync_cancelled',
    'config_changed', 'user_login', 'user_logout', 'permission_changed',
    'dlq_message_created', 'dlq_message_resolved', 'quality_check_failed'
);

-- =============================================================================
-- TABELA: source_registry
-- Registro de fontes de dados configuráveis
-- =============================================================================
CREATE TABLE source_registry (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    type source_type NOT NULL,
    status source_status NOT NULL DEFAULT 'active',
    config_hash TEXT NOT NULL,
    config_json JSONB NOT NULL DEFAULT '{}',
    
    -- Estatísticas
    document_count INTEGER NOT NULL DEFAULT 0,
    total_documents_ingested BIGINT NOT NULL DEFAULT 0,
    last_document_at TIMESTAMPTZ,
    
    -- Execução
    last_sync_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    next_scheduled_sync TIMESTAMPTZ,
    
    -- Error tracking
    consecutive_errors INTEGER NOT NULL DEFAULT 0,
    last_error_message TEXT,
    last_error_at TIMESTAMPTZ,
    
    -- Governança
    owner_email TEXT NOT NULL,
    sensitivity sensitivity_level NOT NULL DEFAULT 'internal',
    retention_days INTEGER NOT NULL DEFAULT 2555,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índices otimizados para source_registry
CREATE INDEX idx_source_status ON source_registry(status) WHERE status = 'active';
CREATE INDEX idx_source_next_sync ON source_registry(next_scheduled_sync) 
    WHERE next_scheduled_sync IS NOT NULL;
CREATE INDEX idx_source_type ON source_registry(type);

-- =============================================================================
-- TABELA: documents
-- Documentos processados e indexados
-- =============================================================================
CREATE TABLE documents (
    -- Identificadores
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id TEXT NOT NULL UNIQUE,
    source_id TEXT NOT NULL REFERENCES source_registry(id) ON DELETE CASCADE,
    
    -- Conteúdo
    fingerprint TEXT NOT NULL,
    fingerprint_algorithm TEXT NOT NULL DEFAULT 'sha256',
    title TEXT,
    content_preview TEXT,
    content_hash TEXT,  -- Hash do conteúdo completo
    content_size_bytes INTEGER,
    
    -- Metadados
    metadata JSONB NOT NULL DEFAULT '{}',
    url TEXT,
    content_type TEXT,
    language TEXT DEFAULT 'pt-BR',
    
    -- Status
    status document_status NOT NULL DEFAULT 'active',
    version INTEGER NOT NULL DEFAULT 1,
    
    -- Soft delete
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TIMESTAMPTZ,
    deleted_reason TEXT,
    deleted_by TEXT,
    
    -- Timestamps
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reindexed_at TIMESTAMPTZ,
    
    -- Consistência cross-store (ES = Elasticsearch)
    es_indexed BOOLEAN NOT NULL DEFAULT FALSE,
    es_indexed_at TIMESTAMPTZ,
    chunks_count INTEGER NOT NULL DEFAULT 0
);

-- Índices otimizados para documents
CREATE INDEX idx_documents_source ON documents(source_id) WHERE is_deleted = FALSE;
CREATE INDEX idx_documents_fingerprint ON documents USING hash(fingerprint);
CREATE INDEX idx_documents_status ON documents(status) WHERE is_deleted = FALSE;
CREATE INDEX idx_documents_ingested ON documents(ingested_at DESC) WHERE is_deleted = FALSE;
CREATE INDEX idx_documents_metadata ON documents USING gin(metadata jsonb_path_ops);
CREATE INDEX idx_documents_es_sync ON documents(es_indexed, updated_at) 
    WHERE es_indexed = FALSE OR es_indexed_at < updated_at;
CREATE INDEX idx_documents_content_hash ON documents(content_hash) WHERE content_hash IS NOT NULL;
CREATE INDEX idx_documents_deleted ON documents(is_deleted, deleted_at) WHERE is_deleted = TRUE;

-- Índice composto para queries comuns
CREATE INDEX idx_documents_source_active_date 
    ON documents(source_id, is_deleted, ingested_at DESC) 
    WHERE is_deleted = FALSE;

-- Índice para busca por título
CREATE INDEX idx_documents_title_trgm ON documents USING gin(title gin_trgm_ops);

-- =============================================================================
-- TABELA: document_chunks
-- Chunks de documentos com embeddings vetoriais
-- =============================================================================
CREATE TABLE document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    
    -- Conteúdo
    chunk_text TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    char_count INTEGER NOT NULL,
    
    -- Vetor (384 dimensões - IMUTÁVEL conforme ADR-001)
    embedding vector(384),
    embedding_model TEXT,
    embedded_at TIMESTAMPTZ,
    
    -- Metadados
    metadata JSONB NOT NULL DEFAULT '{}',
    section_type TEXT,  -- 'artigo', 'paragrafo', 'ementa', etc
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE(document_id, chunk_index)
);

-- Índice vetorial HNSW (superior ao IVFFlat para workloads mistas)
-- Configuração: m=16, ef_construction=64 conforme especificação
CREATE INDEX idx_chunks_embedding_hnsw
ON document_chunks
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- Índices de performance para document_chunks
CREATE INDEX idx_chunks_document ON document_chunks(document_id);
CREATE INDEX idx_chunks_text_search ON document_chunks USING gin(chunk_text gin_trgm_ops);
CREATE INDEX idx_chunks_section ON document_chunks(section_type) WHERE section_type IS NOT NULL;
CREATE INDEX idx_chunks_embedding_model ON document_chunks(embedding_model) WHERE embedding_model IS NOT NULL;

-- Índice composto para queries paginadas por chunk
CREATE INDEX idx_chunks_document_index ON document_chunks(document_id, chunk_index);

-- =============================================================================
-- TABELA: execution_manifests
-- Manifestos de execução do pipeline com checkpoint/resume
-- =============================================================================
CREATE TABLE execution_manifests (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id TEXT NOT NULL REFERENCES source_registry(id) ON DELETE CASCADE,
    
    -- Status
    status execution_status NOT NULL DEFAULT 'pending',
    trigger TEXT NOT NULL,  -- 'scheduled', 'manual', 'api', 'retry'
    triggered_by TEXT,  -- user_id ou 'system'
    
    -- Timestamps
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    
    -- Estatísticas detalhadas
    stats JSONB NOT NULL DEFAULT '{
        "urls_discovered": 0,
        "urls_new": 0,
        "urls_updated": 0,
        "urls_skipped": 0,
        "urls_failed": 0,
        "documents_fetched": 0,
        "documents_parsed": 0,
        "documents_deduplicated": 0,
        "documents_indexed": 0,
        "documents_failed": 0,
        "chunks_created": 0,
        "embeddings_generated": 0,
        "bytes_processed": 0,
        "processing_time_ms": 0,
        "errors": []
    }',
    
    -- Checkpoint para resume
    checkpoint JSONB,  -- Último estado processado
    last_processed_url TEXT,
    
    -- Performance
    duration_seconds FLOAT,
    memory_peak_mb FLOAT,
    
    -- Error
    error_message TEXT,
    error_traceback TEXT,
    
    -- Logging
    logs TEXT[] DEFAULT '{}'
);

-- Índices otimizados para execution_manifests
CREATE INDEX idx_executions_source ON execution_manifests(source_id, started_at DESC);
CREATE INDEX idx_executions_status ON execution_manifests(status) WHERE status IN ('pending', 'running');
CREATE INDEX idx_executions_date ON execution_manifests(started_at DESC);
CREATE INDEX idx_executions_trigger ON execution_manifests(trigger, started_at DESC);

-- =============================================================================
-- TABELA: dlq_messages
-- Dead Letter Queue com retry logic
-- =============================================================================
CREATE TABLE dlq_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id TEXT NOT NULL REFERENCES source_registry(id) ON DELETE CASCADE,
    run_id UUID REFERENCES execution_manifests(run_id) ON DELETE SET NULL,
    
    -- Identificação
    url TEXT NOT NULL,
    document_id TEXT,
    
    -- Error
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    error_traceback TEXT,
    error_hash TEXT,  -- Para agrupar erros similares
    
    -- Retry
    status dlq_status NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 5,
    retry_strategy TEXT DEFAULT 'exponential_backoff',
    next_retry_at TIMESTAMPTZ,
    last_retry_at TIMESTAMPTZ,
    
    -- Resolução
    resolved_at TIMESTAMPTZ,
    resolved_by TEXT,
    resolution_notes TEXT,
    
    -- Payload
    payload JSONB NOT NULL DEFAULT '{}',
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at TIMESTAMPTZ
);

-- Índices otimizados para dlq_messages
CREATE INDEX idx_dlq_status_retry ON dlq_messages(status, next_retry_at) 
    WHERE status IN ('pending', 'retrying');
CREATE INDEX idx_dlq_source ON dlq_messages(source_id, created_at DESC);
CREATE INDEX idx_dlq_error_hash ON dlq_messages(error_hash) WHERE error_hash IS NOT NULL;
CREATE INDEX idx_dlq_created ON dlq_messages(created_at) WHERE status = 'exhausted';
CREATE INDEX idx_dlq_document ON dlq_messages(document_id) WHERE document_id IS NOT NULL;

-- =============================================================================
-- TABELA: audit_log
-- Log de auditoria IMUTÁVEL com hash chain
-- =============================================================================
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Evento
    event_type audit_event_type NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('debug', 'info', 'warning', 'error', 'critical')),
    
    -- Usuário
    user_id TEXT,
    user_email TEXT,
    session_id TEXT,
    ip_address INET,
    user_agent TEXT,
    
    -- Recurso
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    
    -- Detalhes
    action_details JSONB NOT NULL DEFAULT '{}',
    before_state JSONB,
    after_state JSONB,
    
    -- Integridade (hash chain)
    previous_hash TEXT,
    event_hash TEXT NOT NULL,
    
    -- Request tracing
    request_id TEXT,
    correlation_id TEXT
);

-- Índices otimizados para audit_log
CREATE INDEX idx_audit_timestamp ON audit_log(timestamp DESC);
CREATE INDEX idx_audit_user ON audit_log(user_id, timestamp DESC) WHERE user_id IS NOT NULL;
CREATE INDEX idx_audit_resource ON audit_log(resource_type, resource_id);
CREATE INDEX idx_audit_event_type ON audit_log(event_type, timestamp DESC);
CREATE INDEX idx_audit_request ON audit_log(request_id) WHERE request_id IS NOT NULL;
CREATE INDEX idx_audit_correlation ON audit_log(correlation_id) WHERE correlation_id IS NOT NULL;

-- Revogar UPDATE/DELETE (imutabilidade do audit log)
REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC;

-- =============================================================================
-- TABELA: data_catalog
-- Catálogo de dados para governança
-- =============================================================================
CREATE TABLE data_catalog (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    
    -- Governança
    owner_email TEXT NOT NULL,
    sensitivity sensitivity_level NOT NULL DEFAULT 'internal',
    pii_fields JSONB NOT NULL DEFAULT '[]',
    
    -- Qualidade
    quality_score INTEGER CHECK (quality_score BETWEEN 0 AND 100),
    quality_issues JSONB NOT NULL DEFAULT '[]',
    last_quality_check TIMESTAMPTZ,
    
    -- Retenção
    retention_days INTEGER NOT NULL DEFAULT 2555,
    
    -- Estatísticas
    record_count INTEGER NOT NULL DEFAULT 0,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    last_updated TIMESTAMPTZ,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índices para data_catalog
CREATE INDEX idx_catalog_owner ON data_catalog(owner_email);
CREATE INDEX idx_catalog_sensitivity ON data_catalog(sensitivity);
CREATE INDEX idx_catalog_quality ON data_catalog(quality_score) WHERE quality_score IS NOT NULL;

-- =============================================================================
-- TABELA: lineage_nodes
-- Nós do grafo de lineage
-- =============================================================================
CREATE TABLE lineage_nodes (
    node_id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL CHECK (node_type IN ('source', 'transform', 'dataset', 'document', 'api')),
    name TEXT NOT NULL,
    description TEXT,
    properties JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índices para lineage_nodes
CREATE INDEX idx_lineage_nodes_type ON lineage_nodes(node_type);

-- =============================================================================
-- TABELA: lineage_edges
-- Arestas do grafo de lineage
-- =============================================================================
CREATE TABLE lineage_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_node TEXT NOT NULL REFERENCES lineage_nodes(node_id) ON DELETE CASCADE,
    target_node TEXT NOT NULL REFERENCES lineage_nodes(node_id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL CHECK (edge_type IN ('produced', 'input_to', 'output_to', 'derived_from', 'api_call')),
    properties JSONB NOT NULL DEFAULT '{}',
    run_id UUID REFERENCES execution_manifests(run_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE(source_node, target_node, edge_type)
);

-- Índices otimizados para lineage_edges
CREATE INDEX idx_lineage_source ON lineage_edges(source_node);
CREATE INDEX idx_lineage_target ON lineage_edges(target_node);
CREATE INDEX idx_lineage_type ON lineage_edges(edge_type);
CREATE INDEX idx_lineage_run ON lineage_edges(run_id) WHERE run_id IS NOT NULL;

-- =============================================================================
-- TABELA: change_detection_cache
-- Cache para detecção de mudanças
-- =============================================================================
CREATE TABLE change_detection_cache (
    url TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source_registry(id) ON DELETE CASCADE,
    
    -- Headers HTTP
    etag TEXT,
    last_modified TEXT,
    
    -- Hash do conteúdo
    content_hash TEXT,
    content_length BIGINT,
    
    -- Estado
    last_checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_changed_at TIMESTAMPTZ,
    check_count INTEGER NOT NULL DEFAULT 0,
    change_count INTEGER NOT NULL DEFAULT 0
);

-- Índices para change_detection_cache
CREATE INDEX idx_change_detection_source ON change_detection_cache(source_id);
CREATE INDEX idx_change_detection_checked ON change_detection_cache(last_checked_at);
CREATE INDEX idx_change_detection_content_hash ON change_detection_cache(content_hash) WHERE content_hash IS NOT NULL;

-- =============================================================================
-- FUNCTIONS & TRIGGERS
-- =============================================================================

-- Function: Atualiza updated_at automaticamente
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers para updated_at
CREATE TRIGGER update_documents_updated_at BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_document_chunks_updated_at BEFORE UPDATE ON document_chunks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_source_registry_updated_at BEFORE UPDATE ON source_registry
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_dlq_messages_updated_at BEFORE UPDATE ON dlq_messages
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_data_catalog_updated_at BEFORE UPDATE ON data_catalog
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_execution_manifests_updated_at BEFORE UPDATE ON execution_manifests
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Function: Hash chain para audit_log
CREATE OR REPLACE FUNCTION calculate_audit_hash()
RETURNS TRIGGER AS $$
DECLARE
    prev_hash TEXT;
    data_to_hash TEXT;
BEGIN
    -- Buscar hash anterior
    SELECT event_hash INTO prev_hash
    FROM audit_log
    ORDER BY timestamp DESC
    LIMIT 1;
    
    NEW.previous_hash := COALESCE(prev_hash, '0');
    
    -- Calcular hash do evento atual
    data_to_hash := NEW.event_type || '|' || 
                    COALESCE(NEW.user_id, '') || '|' || 
                    COALESCE(NEW.resource_id, '') || '|' ||
                    NEW.timestamp::text || '|' ||
                    NEW.previous_hash;
    
    NEW.event_hash := encode(digest(data_to_hash, 'sha256'), 'hex');
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger para hash chain do audit_log
CREATE TRIGGER calculate_audit_hash_trigger
    BEFORE INSERT ON audit_log
    FOR EACH ROW
    EXECUTE FUNCTION calculate_audit_hash();

-- =============================================================================
-- COMMENTS (Documentação das tabelas e colunas)
-- =============================================================================

COMMENT ON TABLE source_registry IS 'Registro de fontes de dados configuráveis para ingestão';
COMMENT ON TABLE documents IS 'Documentos processados e indexados no sistema';
COMMENT ON TABLE document_chunks IS 'Chunks de documentos com embeddings vetoriais (384 dimensões)';
COMMENT ON TABLE execution_manifests IS 'Manifestos de execução do pipeline com checkpoint/resume';
COMMENT ON TABLE dlq_messages IS 'Dead Letter Queue para mensagens que falharam processamento';
COMMENT ON TABLE audit_log IS 'Log de auditoria IMUTÁVEL com hash chain para integridade';
COMMENT ON TABLE data_catalog IS 'Catálogo de dados para governança e qualidade';
COMMENT ON TABLE lineage_nodes IS 'Nós do grafo de lineage de dados';
COMMENT ON TABLE lineage_edges IS 'Arestas do grafo de lineage de dados';
COMMENT ON TABLE change_detection_cache IS 'Cache para detecção de mudanças em URLs';

COMMENT ON COLUMN document_chunks.embedding IS 'Embedding vetorial de 384 dimensões (conforme ADR-001)';
COMMENT ON COLUMN audit_log.event_hash IS 'Hash SHA256 da cadeia de eventos para integridade';
COMMENT ON COLUMN documents.is_deleted IS 'Soft delete - documento logicamente removido';
COMMENT ON COLUMN documents.es_indexed IS 'Flag de sincronização com Elasticsearch';

-- =============================================================================
-- FIM DO SCHEMA
-- =============================================================================
