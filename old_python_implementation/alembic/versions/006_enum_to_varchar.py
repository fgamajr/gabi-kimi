"""Convert PostgreSQL ENUM columns to VARCHAR for compatibility.

The SQLAlchemy models use plain String/mapped_column(String) but migration 001
created the columns with PostgreSQL native ENUM types. This causes insert/update
failures when the Python code sends plain strings into ENUM-typed columns.

Additionally, the Python SourceType enum has values (url_pattern, static_url,
api_query) that were never added to the DB source_type enum, so those sources
would always fail.

This migration converts all ENUM columns to VARCHAR, preserving existing data.

Revision ID: 006_enum_to_varchar
Revises: 005_source_registry_soft_delete
Create Date: 2026-02-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '006_enum_to_varchar'
down_revision: Union[str, None] = '005_source_registry_soft_delete'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# All enum columns that need conversion: (table, column, enum_type_name)
ENUM_COLUMNS = [
    ("source_registry", "type", "source_type"),
    ("source_registry", "status", "source_status"),
    ("source_registry", "sensitivity", "sensitivity_level"),
    ("documents", "status", "document_status"),
    ("execution_manifests", "status", "execution_status"),
    ("dlq_messages", "status", "dlq_status"),
    ("audit_log", "event_type", "audit_event_type"),
    ("audit_log", "severity", "audit_severity"),
    ("lineage_nodes", "node_type", "lineage_node_type"),
    ("lineage_edges", "edge_type", "lineage_edge_type"),
]


def upgrade() -> None:
    """Convert all ENUM columns to VARCHAR, then drop the ENUM types."""
    
    # Step 1: Gather and drop ALL indexes on tables that have ENUM columns.
    # PostgreSQL bakes the column type into partial-index WHERE expressions,
    # so ANY index that touches an ENUM column (even indirectly via WHERE)
    # must be dropped before ALTER TYPE.
    # Instead of enumerating them by hand, drop them dynamically.
    op.execute("""
        DO $$
        DECLARE
            idx RECORD;
        BEGIN
            FOR idx IN
                SELECT i.indexname, i.tablename
                FROM pg_indexes i
                LEFT JOIN pg_constraint c
                    ON c.conname = i.indexname
                   AND c.conrelid = (i.schemaname || '.' || i.tablename)::regclass
                WHERE i.schemaname = 'public'
                  AND i.tablename IN (
                      'source_registry', 'documents', 'execution_manifests',
                      'dlq_messages', 'audit_log', 'lineage_nodes', 'lineage_edges'
                  )
                  -- keep primary key and unique-constraint indexes
                  AND i.indexname NOT LIKE '%_pkey'
                  AND c.conname IS NULL
            LOOP
                EXECUTE format('DROP INDEX IF EXISTS %I', idx.indexname);
            END LOOP;
        END $$;
    """)
    
    # Drop views that depend on enum-typed columns (audit_log views)
    op.execute("DROP VIEW IF EXISTS audit_security_events CASCADE")
    op.execute("DROP VIEW IF EXISTS audit_log_statistics CASCADE")
    op.execute("DROP VIEW IF EXISTS audit_log_recent CASCADE")
    
    # Drop functions that have enum-typed parameters
    op.execute("DROP FUNCTION IF EXISTS insert_audit_event CASCADE")
    op.execute("DROP FUNCTION IF EXISTS verify_audit_chain CASCADE")
    op.execute("DROP FUNCTION IF EXISTS get_audit_chain_summary CASCADE")
    op.execute("DROP FUNCTION IF EXISTS get_audit_events_by_resource CASCADE")
    op.execute("DROP FUNCTION IF EXISTS archive_old_audit_logs CASCADE")
    
    # Drop audit hash trigger (uses ::text cast but safer to recreate)
    op.execute("DROP TRIGGER IF EXISTS calculate_audit_hash_trigger ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS calculate_audit_hash CASCADE")
    
    # Drop CHECK constraints on lineage tables
    op.execute("ALTER TABLE lineage_nodes DROP CONSTRAINT IF EXISTS chk_lineage_node_type")
    op.execute("ALTER TABLE lineage_edges DROP CONSTRAINT IF EXISTS chk_lineage_edge_type")
    
    # Also drop unique constraints that might reference enum columns
    # (these are safe to keep but let's be thorough)
    
    # Step 2: Convert each column from ENUM to VARCHAR
    for table, column, enum_name in ENUM_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN \"{column}\" "
            f"TYPE VARCHAR USING \"{column}\"::text"
        )
    
    # Step 3: Drop old ENUM types with CASCADE (server_default values may still reference them)
    enum_types = sorted(set(e[2] for e in ENUM_COLUMNS))
    for enum_name in enum_types:
        op.execute(f"DROP TYPE IF EXISTS {enum_name} CASCADE")
    
    # Step 4: Recreate important indexes (IF NOT EXISTS for safety, since we
    # only dropped indexes on ENUM-bearing tables, not all tables).
    
    # source_registry indexes
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_source_status ON source_registry (status) "
        "WHERE status = 'active'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_source_next_sync ON source_registry (next_scheduled_sync) "
        "WHERE next_scheduled_sync IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_source_status_errors ON source_registry "
        "(status, consecutive_errors, last_error_at) "
        "WHERE status IN ('error', 'paused')"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_source_status_deleted ON source_registry "
        "(status, is_deleted)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_source_doc_count ON source_registry (document_count DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_source_is_deleted ON source_registry (is_deleted)")
    
    # documents indexes
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_source ON documents (source_id) "
        "WHERE is_deleted = false"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_fingerprint ON documents USING hash (fingerprint)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_status ON documents (status) "
        "WHERE is_deleted = false"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_ingested ON documents (ingested_at DESC) "
        "WHERE is_deleted = false"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_source_status_date ON documents "
        "(source_id, status, ingested_at DESC) WHERE is_deleted = false"
    )
    
    # execution_manifests indexes
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_executions_source ON execution_manifests "
        "(source_id, started_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_executions_status ON execution_manifests (status) "
        "WHERE status IN ('pending', 'running')"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_executions_date ON execution_manifests (started_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_executions_active ON execution_manifests "
        "(source_id, status, started_at) "
        "WHERE status IN ('pending', 'running')"
    )
    
    # dlq_messages indexes
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_dlq_status_retry ON dlq_messages "
        "(status, next_retry_at) "
        "WHERE status IN ('pending', 'retrying')"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_dlq_source ON dlq_messages "
        "(source_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_dlq_created ON dlq_messages (created_at) "
        "WHERE status = 'exhausted'"
    )
    
    # audit_log indexes
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log (timestamp DESC)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_log "
        "(event_type, timestamp DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_resource ON audit_log (resource_type, resource_id)"
    )
    
    # document_chunks indexes
    op.execute("CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks (document_id)")
    
    # lineage indexes
    op.execute("CREATE INDEX IF NOT EXISTS idx_lineage_source ON lineage_edges (source_node)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_lineage_target ON lineage_edges (target_node)")
    
    # Step 5: Recreate CHECK constraints for lineage tables
    op.execute(
        "ALTER TABLE lineage_nodes ADD CONSTRAINT chk_lineage_node_type "
        "CHECK (node_type IN ('source', 'transform', 'dataset', 'document', 'api'))"
    )
    op.execute(
        "ALTER TABLE lineage_edges ADD CONSTRAINT chk_lineage_edge_type "
        "CHECK (edge_type IN ('produced', 'input_to', 'output_to', 'derived_from', 'api_call'))"
    )
    
    # Step 6: Recreate audit hash trigger (works fine with VARCHAR columns)
    op.execute("""
        CREATE OR REPLACE FUNCTION calculate_audit_hash()
        RETURNS TRIGGER AS $$
        DECLARE
            prev_hash TEXT;
            data_to_hash TEXT;
        BEGIN
            SELECT event_hash INTO prev_hash
            FROM audit_log
            ORDER BY timestamp DESC, id DESC
            LIMIT 1;
            
            NEW.previous_hash := COALESCE(prev_hash, '0');
            
            data_to_hash := 
                COALESCE(NEW.event_type::text, '') || '|' ||
                COALESCE(NEW.severity::text, '') || '|' ||
                COALESCE(NEW.user_id::text, '') || '|' ||
                COALESCE(NEW.resource_type::text, '') || '|' ||
                COALESCE(NEW.resource_id::text, '') || '|' ||
                COALESCE(NEW.timestamp::text, NOW()::text) || '|' ||
                NEW.previous_hash || '|' ||
                COALESCE(NEW.request_id::text, '') || '|' ||
                COALESCE(NEW.correlation_id::text, '');
            
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
    """Recreate ENUM types and convert columns back.
    
    NOTE: This is a best-effort downgrade. If data contains values not in the
    original enum, this will fail.
    """
    # Recreate ENUMs
    op.execute("CREATE TYPE source_type AS ENUM ('api', 'web', 'file', 'crawler')")
    op.execute("CREATE TYPE source_status AS ENUM ('active', 'paused', 'error', 'disabled')")
    op.execute("CREATE TYPE execution_status AS ENUM ('pending', 'running', 'success', 'partial_success', 'failed', 'cancelled')")
    op.execute("CREATE TYPE document_status AS ENUM ('active', 'updated', 'deleted', 'error')")
    op.execute("CREATE TYPE dlq_status AS ENUM ('pending', 'retrying', 'exhausted', 'resolved', 'archived')")
    op.execute("CREATE TYPE sensitivity_level AS ENUM ('public', 'internal', 'restricted', 'confidential')")
    op.execute(
        "CREATE TYPE audit_event_type AS ENUM ("
        "'document_viewed', 'document_searched', 'document_created', "
        "'document_updated', 'document_deleted', 'document_reindexed', "
        "'sync_started', 'sync_completed', 'sync_failed', 'sync_cancelled', "
        "'config_changed', 'user_login', 'user_logout', 'permission_changed', "
        "'dlq_message_created', 'dlq_message_resolved', 'quality_check_failed')"
    )
    op.execute("CREATE TYPE audit_severity AS ENUM ('debug', 'info', 'warning', 'error', 'critical')")
    op.execute("CREATE TYPE lineage_node_type AS ENUM ('source', 'transform', 'dataset', 'document', 'api')")
    op.execute("CREATE TYPE lineage_edge_type AS ENUM ('produced', 'input_to', 'output_to', 'derived_from', 'api_call')")
    
    # Convert back
    for table, column, enum_name in ENUM_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN \"{column}\" "
            f"TYPE {enum_name} USING \"{column}\"::{enum_name}"
        )
