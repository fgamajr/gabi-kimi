"""
002_indexes_constraints

Migração de índices adicionais e constraints para otimização de queries.
Adiciona índices compostos, parciais e GIN para JSONB.

Revision ID: 002_indexes_constraints
Revises: 001_initial_schema
Create Date: 2026-02-06 16:56:00.000000+00:00

INVARIANTES:
- Índices otimizados para queries frequentes do pipeline
- Índices parciais para dados ativos (is_deleted = false)
- Índices GIN para buscas em JSONB

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002_indexes_constraints'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Execute a migração de índices adicionais e constraints."""
    
    # =======================================================================
    # 1. ÍNDICES COMPOSTOS OTIMIZADOS
    # =======================================================================
    
    # source_registry: índice composto para queries de fontes ativas com erro
    op.create_index(
        'idx_source_status_errors',
        'source_registry',
        ['status', 'consecutive_errors', 'last_error_at'],
        postgresql_where=sa.text("status IN ('error', 'paused')")
    )
    
    # source_registry: índice para ordenação por document_count
    op.create_index(
        'idx_source_doc_count',
        'source_registry',
        [sa.text('document_count DESC')],
        postgresql_where=sa.text('is_deleted = false')
    )
    
    # documents: índice para ordenação por data de ingestão
    op.create_index(
        'idx_documents_ingested_sort',
        'documents',
        [sa.text('ingested_at DESC')],
        postgresql_where=sa.text('is_deleted = false')
    )
    
    # documents: índice composto para busca por fonte + status + data
    op.create_index(
        'idx_documents_source_status_date',
        'documents',
        ['source_id', 'status', sa.text('ingested_at DESC')],
        postgresql_where=sa.text('is_deleted = false')
    )
    
    # documents: índice composto para filtrar por fonte e soft delete
    op.create_index(
        'idx_documents_source_deleted',
        'documents',
        ['source_id', 'is_deleted'],
        postgresql_where=sa.text('is_deleted = false')
    )
    
    # documents: índice para busca por conteúdo + data
    op.create_index(
        'idx_documents_content_type_date',
        'documents',
        ['content_type', sa.text('ingested_at DESC')],
        postgresql_where=sa.text('is_deleted = false AND content_type IS NOT NULL')
    )
    
    # documents: índice para documentos não indexados no ES
    op.create_index(
        'idx_documents_not_indexed',
        'documents',
        ['source_id', 'updated_at'],
        postgresql_where=sa.text('es_indexed = false AND is_deleted = false')
    )
    
    # documents: índice para documentos reindexados recentemente
    op.create_index(
        'idx_documents_reindexed',
        'documents',
        [sa.text('reindexed_at DESC')],
        postgresql_where=sa.text('reindexed_at IS NOT NULL')
    )
    
    # document_chunks: índice composto para busca por documento + seção
    op.create_index(
        'idx_chunks_doc_section',
        'document_chunks',
        ['document_id', 'section_type', 'chunk_index'],
        postgresql_where=sa.text('section_type IS NOT NULL')
    )
    
    # document_chunks: índice para ordenação por token_count
    op.create_index(
        'idx_chunks_token_count',
        'document_chunks',
        [sa.text('token_count DESC')],
        postgresql_where=sa.text('token_count > 0')
    )
    
    # execution_manifests: índice composto para execuções ativas
    op.create_index(
        'idx_executions_active',
        'execution_manifests',
        ['source_id', 'status', 'started_at'],
        postgresql_where=sa.text("status IN ('pending', 'running')")
    )
    
    # execution_manifests: índice para estatísticas por período
    op.create_index(
        'idx_executions_stats',
        'execution_manifests',
        ['source_id', sa.text('started_at DESC'), 'status'],
        postgresql_where=sa.text('completed_at IS NOT NULL')
    )
    
    # dlq_messages: índice composto para retry
    op.create_index(
        'idx_dlq_retry_compound',
        'dlq_messages',
        ['status', 'retry_count', 'next_retry_at'],
        postgresql_where=sa.text("status IN ('pending', 'retrying')")
    )
    
    # dlq_messages: índice para agrupamento por error_type
    op.create_index(
        'idx_dlq_error_type',
        'dlq_messages',
        ['error_type', sa.text('created_at DESC')]
    )
    
    # =======================================================================
    # 2. ÍNDICES PARCIAIS (WHERE is_deleted = false)
    # =======================================================================
    
    # documents: índice parcial para título (busca textual)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_title_partial 
        ON documents (title) 
        WHERE is_deleted = false AND title IS NOT NULL
    """)
    
    # documents: índice parcial para URL
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_url_partial 
        ON documents (url) 
        WHERE is_deleted = false AND url IS NOT NULL
    """)
    
    # documents: índice parcial para language
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_language_partial 
        ON documents (language) 
        WHERE is_deleted = false
    """)
    
    # source_registry: índice parcial para fontes ativas (não deletadas)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_source_active_partial 
        ON source_registry (type, next_scheduled_sync) 
        WHERE status = 'active' AND is_deleted = false
    """)
    
    # source_registry: índice composto para status e soft delete
    op.create_index(
        'idx_source_status_deleted',
        'source_registry',
        ['status', 'is_deleted']
    )
    
    # change_detection_cache: índice parcial para URLs não verificadas recentemente
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_change_detection_stale 
        ON change_detection_cache (source_id, last_checked_at) 
        WHERE last_checked_at < NOW() - INTERVAL '1 hour'
    """)
    
    # =======================================================================
    # 3. ÍNDICES GIN PARA JSONB
    # =======================================================================
    
    # source_registry: índice GIN para config_json
    op.create_index(
        'idx_source_config_gin',
        'source_registry',
        ['config_json'],
        postgresql_using='gin',
        postgresql_ops={'config_json': 'jsonb_path_ops'}
    )
    
    # execution_manifests: índice GIN para checkpoint (resume)
    op.create_index(
        'idx_executions_checkpoint_gin',
        'execution_manifests',
        ['checkpoint'],
        postgresql_using='gin',
        postgresql_ops={'checkpoint': 'jsonb_path_ops'}
    )
    
    # execution_manifests: índice GIN para stats
    op.create_index(
        'idx_executions_stats_gin',
        'execution_manifests',
        ['stats'],
        postgresql_using='gin',
        postgresql_ops={'stats': 'jsonb_path_ops'}
    )
    
    # dlq_messages: índice GIN para payload
    op.create_index(
        'idx_dlq_payload_gin',
        'dlq_messages',
        ['payload'],
        postgresql_using='gin',
        postgresql_ops={'payload': 'jsonb_path_ops'}
    )
    
    # audit_log: índice GIN para action_details
    op.create_index(
        'idx_audit_details_gin',
        'audit_log',
        ['action_details'],
        postgresql_using='gin',
        postgresql_ops={'action_details': 'jsonb_path_ops'}
    )
    
    # audit_log: índice GIN para before_state e after_state
    op.create_index(
        'idx_audit_before_state_gin',
        'audit_log',
        ['before_state'],
        postgresql_using='gin',
        postgresql_ops={'before_state': 'jsonb_path_ops'}
    )
    
    op.create_index(
        'idx_audit_after_state_gin',
        'audit_log',
        ['after_state'],
        postgresql_using='gin',
        postgresql_ops={'after_state': 'jsonb_path_ops'}
    )
    
    # lineage_nodes: índice GIN para properties
    op.create_index(
        'idx_lineage_node_props_gin',
        'lineage_nodes',
        ['properties'],
        postgresql_using='gin',
        postgresql_ops={'properties': 'jsonb_path_ops'}
    )
    
    # lineage_edges: índice GIN para properties
    op.create_index(
        'idx_lineage_edge_props_gin',
        'lineage_edges',
        ['properties'],
        postgresql_using='gin',
        postgresql_ops={'properties': 'jsonb_path_ops'}
    )
    
    # =======================================================================
    # 4. ÍNDICES PARA FULL-TEXT SEARCH
    # =======================================================================
    
    # documents: índice para content_preview (trigram)
    op.create_index(
        'idx_documents_preview_trgm',
        'documents',
        ['content_preview'],
        postgresql_using='gin',
        postgresql_ops={'content_preview': 'gin_trgm_ops'}
    )
    
    # =======================================================================
    # 5. CONSTRAINTS ADICIONAIS
    # =======================================================================
    
    # documents: constraint para garantir version > 0
    op.create_check_constraint(
        'chk_documents_version_positive',
        'documents',
        sa.text('version > 0')
    )
    
    # documents: constraint para deleted_at só existir se is_deleted = true
    op.create_check_constraint(
        'chk_documents_deleted_consistency',
        'documents',
        sa.text('(is_deleted = false AND deleted_at IS NULL) OR (is_deleted = true AND deleted_at IS NOT NULL)')
    )
    
    # source_registry: constraint para retention_days positivo
    op.create_check_constraint(
        'chk_source_retention_positive',
        'source_registry',
        sa.text('retention_days > 0')
    )
    
    # document_chunks: constraint para token_count positivo
    op.create_check_constraint(
        'chk_chunks_token_positive',
        'document_chunks',
        sa.text('token_count > 0')
    )
    
    # document_chunks: constraint para char_count positivo
    op.create_check_constraint(
        'chk_chunks_char_positive',
        'document_chunks',
        sa.text('char_count > 0')
    )
    
    # document_chunks: constraint para chunk_index não negativo
    op.create_check_constraint(
        'chk_chunks_index_non_negative',
        'document_chunks',
        sa.text('chunk_index >= 0')
    )
    
    # dlq_messages: constraint para retry_count <= max_retries
    op.create_check_constraint(
        'chk_dlq_retry_limit',
        'dlq_messages',
        sa.text('retry_count <= max_retries')
    )
    
    # dlq_messages: constraint para retry_count >= 0
    op.create_check_constraint(
        'chk_dlq_retry_non_negative',
        'dlq_messages',
        sa.text('retry_count >= 0')
    )
    
    # execution_manifests: constraint para duration_seconds positivo
    op.create_check_constraint(
        'chk_execution_duration_positive',
        'execution_manifests',
        sa.text('duration_seconds IS NULL OR duration_seconds >= 0')
    )
    
    # execution_manifests: constraint para memory_peak_mb positivo
    op.create_check_constraint(
        'chk_execution_memory_positive',
        'execution_manifests',
        sa.text('memory_peak_mb IS NULL OR memory_peak_mb >= 0')
    )
    
    # =======================================================================
    # 6. ÍNDICES PARA FOREIGN KEYS (performance em JOINs)
    # =======================================================================
    
    # lineage_edges: índice para source_node + target_node (grafo bidirecional)
    op.create_index(
        'idx_lineage_edge_bidirectional',
        'lineage_edges',
        ['source_node', 'target_node', 'edge_type']
    )
    
    # lineage_edges: índice para run_id
    op.create_index(
        'idx_lineage_edge_run',
        'lineage_edges',
        ['run_id'],
        postgresql_where=sa.text('run_id IS NOT NULL')
    )
    
    # change_detection_cache: índice para source_id + content_hash (dedup)
    op.create_index(
        'idx_change_detection_hash',
        'change_detection_cache',
        ['source_id', 'content_hash'],
        postgresql_where=sa.text('content_hash IS NOT NULL')
    )


def downgrade() -> None:
    """Reverta a migração removendo índices e constraints adicionais."""
    
    # =======================================================================
    # 1. REMOVER ÍNDICES (ordem inversa)
    # =======================================================================
    
    # FK performance indexes
    op.drop_index('idx_change_detection_hash', table_name='change_detection_cache')
    op.drop_index('idx_lineage_edge_run', table_name='lineage_edges')
    op.drop_index('idx_lineage_edge_bidirectional', table_name='lineage_edges')
    
    # Full-text search
    op.drop_index('idx_documents_preview_trgm', table_name='documents')
    
    # GIN indexes
    op.drop_index('idx_lineage_edge_props_gin', table_name='lineage_edges')
    op.drop_index('idx_lineage_node_props_gin', table_name='lineage_nodes')
    op.drop_index('idx_audit_after_state_gin', table_name='audit_log')
    op.drop_index('idx_audit_before_state_gin', table_name='audit_log')
    op.drop_index('idx_audit_details_gin', table_name='audit_log')
    op.drop_index('idx_dlq_payload_gin', table_name='dlq_messages')
    op.drop_index('idx_executions_stats_gin', table_name='execution_manifests')
    op.drop_index('idx_executions_checkpoint_gin', table_name='execution_manifests')
    op.drop_index('idx_source_config_gin', table_name='source_registry')
    
    # Partial indexes
    op.execute("DROP INDEX IF EXISTS idx_change_detection_stale")
    op.execute("DROP INDEX IF EXISTS idx_source_active_partial")
    op.execute("DROP INDEX IF EXISTS idx_documents_language_partial")
    op.execute("DROP INDEX IF EXISTS idx_documents_url_partial")
    op.execute("DROP INDEX IF EXISTS idx_documents_title_partial")
    
    # Compound indexes
    op.drop_index('idx_dlq_error_type', table_name='dlq_messages')
    op.drop_index('idx_dlq_retry_compound', table_name='dlq_messages')
    op.drop_index('idx_executions_stats', table_name='execution_manifests')
    op.drop_index('idx_executions_active', table_name='execution_manifests')
    op.drop_index('idx_chunks_token_count', table_name='document_chunks')
    op.drop_index('idx_chunks_doc_section', table_name='document_chunks')
    op.drop_index('idx_documents_reindexed', table_name='documents')
    op.drop_index('idx_documents_not_indexed', table_name='documents')
    op.drop_index('idx_documents_content_type_date', table_name='documents')
    op.drop_index('idx_documents_source_status_date', table_name='documents')
    op.drop_index('idx_documents_source_deleted', table_name='documents')
    op.drop_index('idx_documents_ingested_sort', table_name='documents')
    op.drop_index('idx_source_doc_count', table_name='source_registry')
    op.drop_index('idx_source_status_errors', table_name='source_registry')
    op.drop_index('idx_source_status_deleted', table_name='source_registry')
    
    # =======================================================================
    # 2. REMOVER CONSTRAINTS
    # =======================================================================
    
    op.drop_constraint('chk_execution_memory_positive', 'execution_manifests', type_='check')
    op.drop_constraint('chk_execution_duration_positive', 'execution_manifests', type_='check')
    op.drop_constraint('chk_dlq_retry_non_negative', 'dlq_messages', type_='check')
    op.drop_constraint('chk_dlq_retry_limit', 'dlq_messages', type_='check')
    op.drop_constraint('chk_chunks_index_non_negative', 'document_chunks', type_='check')
    op.drop_constraint('chk_chunks_char_positive', 'document_chunks', type_='check')
    op.drop_constraint('chk_chunks_token_positive', 'document_chunks', type_='check')
    op.drop_constraint('chk_source_retention_positive', 'source_registry', type_='check')
    op.drop_constraint('chk_documents_deleted_consistency', 'documents', type_='check')
    op.drop_constraint('chk_documents_version_positive', 'documents', type_='check')
