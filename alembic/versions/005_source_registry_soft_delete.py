"""Add soft delete columns to source_registry

Revision ID: 005
Revises: 004_create_data_catalog
Create Date: 2026-02-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '005_source_registry_soft_delete'
down_revision: Union[str, None] = '004_create_data_catalog'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    """Add is_deleted, deleted_at, deleted_reason and deleted_by columns to source_registry table."""
    # Add is_deleted column
    op.add_column(
        'source_registry',
        sa.Column(
            'is_deleted',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment="Flag de soft delete"
        )
    )
    
    # Add deleted_reason column
    op.add_column(
        'source_registry',
        sa.Column(
            'deleted_reason',
            sa.Text(),
            nullable=True,
            comment="Motivo da exclusão"
        )
    )
    
    # Add deleted_by column
    op.add_column(
        'source_registry',
        sa.Column(
            'deleted_by',
            sa.String(),
            nullable=True,
            comment="Identificador de quem realizou o soft delete"
        )
    )
    
    # Create index for soft delete filtering
    op.create_index(
        'idx_source_is_deleted',
        'source_registry',
        ['is_deleted']
    )
    
    # Create index for status + is_deleted filtering
    op.create_index(
        'idx_source_status_deleted',
        'source_registry',
        ['status', 'is_deleted']
    )


def downgrade():
    """Remove soft delete columns from source_registry table."""
    op.drop_index('idx_source_status_deleted', table_name='source_registry')
    op.drop_index('idx_source_is_deleted', table_name='source_registry')
    op.drop_column('source_registry', 'deleted_by')
    op.drop_column('source_registry', 'deleted_reason')
    op.drop_column('source_registry', 'is_deleted')
