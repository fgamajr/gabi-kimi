"""Partial indexes para queries de agregação do dashboard.

Revision ID: 008_dashboard_indexes
Revises: 007_chunks_soft_delete
Create Date: 2026-02-10
"""

from typing import Sequence, Union

from alembic import op

revision: str = "008_dashboard_indexes"
down_revision: Union[str, None] = "007_chunks_soft_delete"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Chunks com embedding (contagem de embeddings no dashboard)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chunks_has_embedding
        ON document_chunks (document_id)
        WHERE embedding IS NOT NULL AND is_deleted = false
        """
    )

    # Documentos indexados no ES
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_docs_es_indexed
        ON documents (id)
        WHERE es_indexed = true AND is_deleted = false
        """
    )

    # Documentos ativos por source (para aggregate por fonte)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_docs_active_source
        ON documents (source_id)
        WHERE is_deleted = false
        """
    )

    # DLQ pendentes
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_dlq_pending
        ON dlq_messages (status)
        WHERE status IN ('pending', 'retrying')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_dlq_pending")
    op.execute("DROP INDEX IF EXISTS idx_docs_active_source")
    op.execute("DROP INDEX IF EXISTS idx_docs_es_indexed")
    op.execute("DROP INDEX IF EXISTS idx_chunks_has_embedding")
