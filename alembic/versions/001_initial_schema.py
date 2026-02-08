"""
001_initial_schema

Migração inicial do schema do GABI.
Cria todas as tabelas base, enums, extensões e índices.

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-02-06 16:55:00.000000+00:00

INVARIANTES:
- Dimensionalidade 384 em embedding (ADR-001)
- CASCADE nas FKs apropriadas
- Extensões pgvector, uuid-ossp, pg_trgm

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Execute a migração de criação do schema inicial."""
    
    # =======================================================================
    # 1. EXTENSÕES POSTGRESQL
    # =======================================================================
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")
    op.execute("CREATE EXTENSION IF NOT EXISTS \"vector\"")
    op.execute("CREATE EXTENSION IF NOT EXISTS \"pg_trgm\"")
    op.execute("CREATE EXTENSION IF NOT EXISTS \"pgcrypto\"")
    
    # =======================================================================
    # 2. ENUMS
    # =======================================================================
    # Source enums - create with checkfirst=True
    source_type = postgresql.ENUM('api', 'web', 'file', 'crawler', name='source_type', create_type=True)
    source_type.create(op.get_bind(), checkfirst=True)
    
    source_status = postgresql.ENUM('active', 'paused', 'error', 'disabled', name='source_status', create_type=True)
    source_status.create(op.get_bind(), checkfirst=True)
    
    # Execution enum
    execution_status = postgresql.ENUM('pending', 'running', 'success', 'partial_success', 'failed', 'cancelled', name='execution_status', create_type=True)
    execution_status.create(op.get_bind(), checkfirst=True)
    
    # Document enum
    document_status = postgresql.ENUM('active', 'updated', 'deleted', 'error', name='document_status', create_type=True)
    document_status.create(op.get_bind(), checkfirst=True)
    
    # DLQ enum
    dlq_status = postgresql.ENUM('pending', 'retrying', 'exhausted', 'resolved', 'archived', name='dlq_status', create_type=True)
    dlq_status.create(op.get_bind(), checkfirst=True)
    
    # Governance enums
    sensitivity_level = postgresql.ENUM('public', 'internal', 'restricted', 'confidential', name='sensitivity_level', create_type=True)
    sensitivity_level.create(op.get_bind(), checkfirst=True)
    
    audit_event_type = postgresql.ENUM(
        'document_viewed', 'document_searched', 'document_created', 
        'document_updated', 'document_deleted', 'document_reindexed',
        'sync_started', 'sync_completed', 'sync_failed', 'sync_cancelled',
        'config_changed', 'user_login', 'user_logout', 'permission_changed',
        'dlq_message_created', 'dlq_message_resolved', 'quality_check_failed',
        name='audit_event_type', create_type=True
    )
    audit_event_type.create(op.get_bind(), checkfirst=True)
    
    audit_severity = postgresql.ENUM('debug', 'info', 'warning', 'error', 'critical', name='audit_severity', create_type=True)
    audit_severity.create(op.get_bind(), checkfirst=True)
    
    # Lineage enums
    lineage_node_type = postgresql.ENUM('source', 'transform', 'dataset', 'document', 'api', name='lineage_node_type', create_type=True)
    lineage_node_type.create(op.get_bind(), checkfirst=True)
    
    lineage_edge_type = postgresql.ENUM('produced', 'input_to', 'output_to', 'derived_from', 'api_call', name='lineage_edge_type', create_type=True)
    lineage_edge_type.create(op.get_bind(), checkfirst=True)
    
    # =======================================================================
    # 3. TABELA: source_registry
    # =======================================================================
    op.create_table(
        'source_registry',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('type', postgresql.ENUM('api', 'web', 'file', 'crawler', name='source_type', create_type=False), nullable=False),
        sa.Column('status', postgresql.ENUM('active', 'paused', 'error', 'disabled', name='source_status', create_type=False), server_default='active', nullable=False),
        sa.Column('config_hash', sa.String(), nullable=False),
        sa.Column('config_json', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        # Estatísticas
        sa.Column('document_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_documents_ingested', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_document_at', sa.DateTime(timezone=True), nullable=True),
        # Execução
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_scheduled_sync', sa.DateTime(timezone=True), nullable=True),
        # Error tracking
        sa.Column('consecutive_errors', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_error_message', sa.Text(), nullable=True),
        sa.Column('last_error_at', sa.DateTime(timezone=True), nullable=True),
        # Governança
        sa.Column('owner_email', sa.String(), nullable=False),
        sa.Column('sensitivity', postgresql.ENUM('public', 'internal', 'restricted', 'confidential', name='sensitivity_level', create_type=False), server_default='internal', nullable=False),
        sa.Column('retention_days', sa.Integer(), server_default='2555', nullable=False),
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        # Primary Key
        sa.PrimaryKeyConstraint('id'),
        # Comentário
        comment='Registro de fontes de dados configuradas no sources.yaml'
    )
    
    # Índices source_registry
    op.create_index(
        'idx_source_status',
        'source_registry',
        ['status'],
        postgresql_where=sa.text("status = 'active'")
    )
    op.create_index(
        'idx_source_next_sync',
        'source_registry',
        ['next_scheduled_sync'],
        postgresql_where=sa.text('next_scheduled_sync IS NOT NULL')
    )
    
    # =======================================================================
    # 4. TABELA: documents
    # =======================================================================
    op.create_table(
        'documents',
        sa.Column('id', sa.UUID(as_uuid=False), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('document_id', sa.String(), nullable=False),
        sa.Column('source_id', sa.String(), nullable=False),
        # Conteúdo
        sa.Column('fingerprint', sa.String(), nullable=False),
        sa.Column('fingerprint_algorithm', sa.String(), server_default='sha256', nullable=False),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('content_preview', sa.Text(), nullable=True),
        sa.Column('content_hash', sa.String(), nullable=True),
        sa.Column('content_size_bytes', sa.Integer(), nullable=True),
        # Metadados
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('url', sa.String(), nullable=True),
        sa.Column('content_type', sa.String(), nullable=True),
        sa.Column('language', sa.String(), server_default='pt-BR', nullable=False),
        # Status
        sa.Column('status', postgresql.ENUM('active', 'updated', 'deleted', 'error', name='document_status', create_type=False), server_default='active', nullable=False),
        sa.Column('version', sa.Integer(), server_default='1', nullable=False),
        # Soft delete
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_reason', sa.Text(), nullable=True),
        sa.Column('deleted_by', sa.String(), nullable=True),
        # Timestamps
        sa.Column('ingested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('reindexed_at', sa.DateTime(timezone=True), nullable=True),
        # Elasticsearch sync
        sa.Column('es_indexed', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('es_indexed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('chunks_count', sa.Integer(), server_default='0', nullable=False),
        # Constraints
        sa.ForeignKeyConstraint(['source_id'], ['source_registry.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('document_id'),
        # Comentário
        comment='Documentos jurídicos processados pelo pipeline GABI'
    )
    
    # Índices documents
    op.create_index('idx_documents_source', 'documents', ['source_id'], postgresql_where=sa.text('is_deleted = false'))
    op.create_index('idx_documents_fingerprint', 'documents', ['fingerprint'], postgresql_using='hash')
    op.create_index('idx_documents_status', 'documents', ['status'], postgresql_where=sa.text('is_deleted = false'))
    op.create_index('idx_documents_ingested', 'documents', [sa.text('ingested_at DESC')], postgresql_where=sa.text('is_deleted = false'))
    op.create_index('idx_documents_metadata', 'documents', ['metadata'], postgresql_using='gin', postgresql_ops={'metadata': 'jsonb_path_ops'})
    op.create_index(
        'idx_documents_es_sync',
        'documents',
        ['es_indexed', 'updated_at'],
        postgresql_where=sa.text('es_indexed = false OR es_indexed_at < updated_at')
    )
    op.create_index(
        'idx_documents_source_active_date',
        'documents',
        ['source_id', 'is_deleted', sa.text('ingested_at DESC')],
        postgresql_where=sa.text('is_deleted = false')
    )
    
    # =======================================================================
    # 5. TABELA: document_chunks (com vector(384) - ADR-001)
    # =======================================================================
    op.create_table(
        'document_chunks',
        sa.Column('id', sa.UUID(as_uuid=False), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('document_id', sa.String(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        # Conteúdo
        sa.Column('chunk_text', sa.Text(), nullable=False),
        sa.Column('token_count', sa.Integer(), nullable=False),
        sa.Column('char_count', sa.Integer(), nullable=False),
        # Vetor (384 dimensões - IMUTÁVEL)
        sa.Column('embedding', Vector(384), nullable=True),  # Vector(384)
        sa.Column('embedding_model', sa.String(), nullable=True),
        sa.Column('embedded_at', sa.DateTime(timezone=True), nullable=True),
        # Metadados
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('section_type', sa.String(), nullable=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        # Constraints
        sa.ForeignKeyConstraint(['document_id'], ['documents.document_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('document_id', 'chunk_index', name='uq_document_chunk_index'),
        # Comentário
        comment='Chunks de documentos com embeddings vetoriais (384 dimensões)'
    )
    
        # Índices document_chunks
    op.create_index('idx_chunks_document', 'document_chunks', ['document_id'])
    op.create_index('idx_chunks_text_search', 'document_chunks', ['chunk_text'], postgresql_using='gin', postgresql_ops={'chunk_text': 'gin_trgm_ops'})
    op.create_index('idx_chunks_section', 'document_chunks', ['section_type'], postgresql_where=sa.text('section_type IS NOT NULL'))
    
    # Índice vetorial HNSW (superior ao IVFFlat)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw 
        ON document_chunks 
        USING hnsw (embedding vector_cosine_ops) 
        WITH (m = 16, ef_construction = 64)
    """)
    
    # =======================================================================
    # 6. TABELA: execution_manifests
    # =======================================================================
    op.create_table(
        'execution_manifests',
        sa.Column('run_id', sa.UUID(as_uuid=False), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('source_id', sa.String(), nullable=False),
        # Status
        sa.Column('status', postgresql.ENUM('pending', 'running', 'success', 'partial_success', 'failed', 'cancelled', name='execution_status', create_type=False), server_default='pending', nullable=False),
        sa.Column('trigger', sa.String(), nullable=False),
        sa.Column('triggered_by', sa.String(), nullable=True),
        # Timestamps
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        # Estatísticas e Checkpoint
        sa.Column('stats', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('checkpoint', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('last_processed_url', sa.Text(), nullable=True),
        # Performance
        sa.Column('duration_seconds', sa.Float(), nullable=True),
        sa.Column('memory_peak_mb', sa.Float(), nullable=True),
        # Error tracking
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_traceback', sa.Text(), nullable=True),
        sa.Column('logs', postgresql.ARRAY(sa.Text()), nullable=True),
        # Constraints
        sa.ForeignKeyConstraint(['source_id'], ['source_registry.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('run_id'),
        # Comentário
        comment='Manifesto de execução de ingestão de dados com checkpoint para resume'
    )
    
    # Índices execution_manifests
    op.create_index('idx_executions_source', 'execution_manifests', ['source_id', sa.text('started_at DESC')])
    op.create_index('idx_executions_status', 'execution_manifests', ['status'], postgresql_where=sa.text("status IN ('pending', 'running')"))
    op.create_index('idx_executions_date', 'execution_manifests', [sa.text('started_at DESC')])
    
    # =======================================================================
    # 7. TABELA: dlq_messages
    # =======================================================================
    op.create_table(
        'dlq_messages',
        sa.Column('id', sa.UUID(as_uuid=False), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('source_id', sa.String(), nullable=False),
        sa.Column('run_id', sa.UUID(as_uuid=False), nullable=True),
        # Identificação
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('document_id', sa.Text(), nullable=True),
        # Error
        sa.Column('error_type', sa.Text(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=False),
        sa.Column('error_traceback', sa.Text(), nullable=True),
        sa.Column('error_hash', sa.Text(), nullable=True),
        # Retry
        sa.Column('status', postgresql.ENUM('pending', 'retrying', 'exhausted', 'resolved', 'archived', name='dlq_status', create_type=False), server_default='pending', nullable=False),
        sa.Column('retry_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('max_retries', sa.Integer(), server_default='5', nullable=False),
        sa.Column('retry_strategy', sa.Text(), server_default='exponential_backoff', nullable=False),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_retry_at', sa.DateTime(timezone=True), nullable=True),
        # Resolução
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_by', sa.Text(), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        # Payload
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        # Constraints
        sa.ForeignKeyConstraint(['run_id'], ['execution_manifests.run_id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['source_id'], ['source_registry.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        # Comentário
        comment='Mensagens da Dead Letter Queue para falhas de processamento'
    )
    
    # Índices dlq_messages
    op.create_index(
        'idx_dlq_status_retry',
        'dlq_messages',
        ['status', 'next_retry_at'],
        postgresql_where=sa.text("status IN ('pending', 'retrying')")
    )
    op.create_index('idx_dlq_source', 'dlq_messages', ['source_id', sa.text('created_at DESC')])
    op.create_index('idx_dlq_error_hash', 'dlq_messages', ['error_hash'], postgresql_where=sa.text('error_hash IS NOT NULL'))
    op.create_index('idx_dlq_created', 'dlq_messages', ['created_at'], postgresql_where=sa.text("status = 'exhausted'"))
    
    # =======================================================================
    # 8. TABELA: audit_log (IMUTÁVEL)
    # =======================================================================
    op.create_table(
        'audit_log',
        sa.Column('id', sa.UUID(as_uuid=False), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        # Evento
        sa.Column('event_type', postgresql.ENUM('document_viewed', 'document_searched', 'document_created', 'document_updated', 'document_deleted', 'document_reindexed', 'sync_started', 'sync_completed', 'sync_failed', 'sync_cancelled', 'config_changed', 'user_login', 'user_logout', 'permission_changed', 'dlq_message_created', 'dlq_message_resolved', 'quality_check_failed', name='audit_event_type', create_type=False), nullable=False),
        sa.Column('severity', postgresql.ENUM('debug', 'info', 'warning', 'error', 'critical', name='audit_severity', create_type=False), server_default='info', nullable=False),
        # Usuário
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('user_email', sa.String(), nullable=True),
        sa.Column('session_id', sa.String(), nullable=True),
        sa.Column('ip_address', postgresql.INET(), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        # Recurso
        sa.Column('resource_type', sa.String(), nullable=True),
        sa.Column('resource_id', sa.String(), nullable=True),
        # Detalhes
        sa.Column('action_details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('before_state', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('after_state', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Integridade (hash chain)
        sa.Column('previous_hash', sa.String(length=64), nullable=True),
        sa.Column('event_hash', sa.String(length=64), nullable=False),
        # Request tracing
        sa.Column('request_id', sa.String(), nullable=True),
        sa.Column('correlation_id', sa.String(), nullable=True),
        # Constraints
        sa.PrimaryKeyConstraint('id'),
        # Comentário
        comment='Log de auditoria imutável com hash chain para integridade'
    )
    
    # Índices audit_log
    op.create_index('idx_audit_timestamp', 'audit_log', [sa.text('timestamp DESC')])
    op.create_index('idx_audit_user', 'audit_log', ['user_id', sa.text('timestamp DESC')], postgresql_where=sa.text('user_id IS NOT NULL'))
    op.create_index('idx_audit_resource', 'audit_log', ['resource_type', 'resource_id'])
    op.create_index('idx_audit_event_type', 'audit_log', ['event_type', sa.text('timestamp DESC')])
    op.create_index('idx_audit_request', 'audit_log', ['request_id'], postgresql_where=sa.text('request_id IS NOT NULL'))
    
    # Revogar UPDATE/DELETE na audit_log (imutabilidade)
    op.execute('REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC')
    
    # =======================================================================
    # 9. TABELA: lineage_nodes
    # =======================================================================
    op.create_table(
        'lineage_nodes',
        sa.Column('node_id', sa.String(), nullable=False),
        sa.Column('node_type', postgresql.ENUM('source', 'transform', 'dataset', 'document', 'api', name='lineage_node_type', create_type=False), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('properties', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        # Constraints
        sa.PrimaryKeyConstraint('node_id'),
        sa.CheckConstraint("node_type IN ('source', 'transform', 'dataset', 'document', 'api')", name='chk_lineage_node_type'),
        # Comentário
        comment='Nós do grafo de linhagem de dados (DAG)'
    )
    
    # =======================================================================
    # 10. TABELA: lineage_edges
    # =======================================================================
    op.create_table(
        'lineage_edges',
        sa.Column('id', sa.UUID(as_uuid=False), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('source_node', sa.String(), nullable=False),
        sa.Column('target_node', sa.String(), nullable=False),
        sa.Column('edge_type', postgresql.ENUM('produced', 'input_to', 'output_to', 'derived_from', 'api_call', name='lineage_edge_type', create_type=False), nullable=False),
        sa.Column('properties', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('run_id', sa.UUID(as_uuid=False), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        # Constraints
        sa.ForeignKeyConstraint(['run_id'], ['execution_manifests.run_id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['source_node'], ['lineage_nodes.node_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_node'], ['lineage_nodes.node_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_node', 'target_node', 'edge_type', name='uq_lineage_edge_source_target_type'),
        sa.CheckConstraint("edge_type IN ('produced', 'input_to', 'output_to', 'derived_from', 'api_call')", name='chk_lineage_edge_type'),
        # Comentário
        comment='Arestas do grafo de linhagem de dados (DAG)'
    )
    
    # Índices lineage_edges
    op.create_index('idx_lineage_source', 'lineage_edges', ['source_node'])
    op.create_index('idx_lineage_target', 'lineage_edges', ['target_node'])
    
    # =======================================================================
    # 11. TABELA: change_detection_cache
    # =======================================================================
    op.create_table(
        'change_detection_cache',
        sa.Column('id', sa.String(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('source_id', sa.String(), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        # Headers HTTP
        sa.Column('etag', sa.Text(), nullable=True),
        sa.Column('last_modified', sa.Text(), nullable=True),
        # Hash do conteúdo
        sa.Column('content_hash', sa.Text(), nullable=True),
        sa.Column('content_length', sa.Integer(), nullable=True),
        # Estado
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_changed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('check_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('change_count', sa.Integer(), server_default='0', nullable=False),
        # Constraints
        sa.ForeignKeyConstraint(['source_id'], ['source_registry.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_id', 'url', name='uq_change_detection_url_source'),
        # Comentário
        comment='Cache de detecção de mudanças em recursos remotos'
    )
    
    # Índices change_detection_cache
    op.create_index('idx_change_detection_source', 'change_detection_cache', ['source_id'])
    op.create_index('idx_change_detection_checked', 'change_detection_cache', ['last_checked_at'])
    
    # =======================================================================
    # FUNCTIONS & TRIGGERS
    # =======================================================================
    
    # Função para atualizar updated_at automaticamente
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql'
    """)
    
    # Triggers para atualização automática de updated_at
    op.execute("""
        CREATE TRIGGER update_documents_updated_at 
        BEFORE UPDATE ON documents 
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()
    """)
    op.execute("""
        CREATE TRIGGER update_document_chunks_updated_at 
        BEFORE UPDATE ON document_chunks 
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()
    """)
    op.execute("""
        CREATE TRIGGER update_source_registry_updated_at 
        BEFORE UPDATE ON source_registry 
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()
    """)
    op.execute("""
        CREATE TRIGGER update_dlq_messages_updated_at 
        BEFORE UPDATE ON dlq_messages 
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()
    """)
    
    # Função para hash chain do audit_log
    op.execute("""
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
        $$ LANGUAGE plpgsql
    """)
    
    op.execute("""
        CREATE TRIGGER calculate_audit_hash_trigger
        BEFORE INSERT ON audit_log
        FOR EACH ROW
        EXECUTE FUNCTION calculate_audit_hash()
    """)


def downgrade() -> None:
    """Reverta a migração removendo todas as tabelas e enums."""
    
    # Remover tabelas (ordem inversa devido a FKs)
    op.drop_table('change_detection_cache')
    op.drop_table('lineage_edges')
    op.drop_table('lineage_nodes')
    op.drop_table('audit_log')
    op.drop_table('dlq_messages')
    op.drop_table('execution_manifests')
    # Drop vector index first
    op.execute("DROP INDEX IF EXISTS idx_chunks_embedding_hnsw")
    op.drop_table('document_chunks')
    op.drop_table('documents')
    op.drop_table('source_registry')
    
    # Remover enums
    sa.Enum(name='lineage_edge_type').drop(op.get_bind())
    sa.Enum(name='lineage_node_type').drop(op.get_bind())
    sa.Enum(name='audit_severity').drop(op.get_bind())
    sa.Enum(name='audit_event_type').drop(op.get_bind())
    sa.Enum(name='sensitivity_level').drop(op.get_bind())
    sa.Enum(name='dlq_status').drop(op.get_bind())
    sa.Enum(name='document_status').drop(op.get_bind())
    sa.Enum(name='execution_status').drop(op.get_bind())
    sa.Enum(name='source_status').drop(op.get_bind())
    sa.Enum(name='source_type').drop(op.get_bind())
    
    # Remover funções
    op.execute("DROP FUNCTION IF EXISTS calculate_audit_hash()")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column()")
