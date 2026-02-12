"""Create data_catalog table

Revision ID: 004
Revises: 003_audit_functions
Create Date: 2026-02-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '004_create_data_catalog'
down_revision: Union[str, None] = '003_audit_functions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    """Create data_catalog table for data governance."""
    op.create_table(
        'data_catalog',
        sa.Column('id', sa.String(255), nullable=False),
        sa.Column('asset_type', sa.String(50), nullable=False, server_default='dataset'),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('owner_email', sa.String(255), nullable=True),
        sa.Column('sensitivity', sa.String(20), nullable=True),
        sa.Column('pii_fields', postgresql.JSONB(), nullable=True, server_default='[]'),
        sa.Column('quality_score', sa.Integer(), nullable=True),
        sa.Column('quality_issues', postgresql.JSONB(), nullable=True, server_default='[]'),
        sa.Column('last_quality_check', sa.DateTime(timezone=True), nullable=True),
        sa.Column('retention_days', sa.Integer(), nullable=True, server_default='2555'),
        sa.Column('purge_after', sa.DateTime(timezone=True), nullable=True),
        sa.Column('record_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('size_bytes', sa.BigInteger(), nullable=True, server_default='0'),
        sa.Column('schema', postgresql.JSONB(), nullable=True, server_default='{}'),
        sa.Column('source_id', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.Column('last_accessed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for common queries
    op.create_index('idx_catalog_type', 'data_catalog', ['asset_type'])
    op.create_index('idx_catalog_name', 'data_catalog', ['name'])
    op.create_index('idx_catalog_owner', 'data_catalog', ['owner_email'])
    op.create_index('idx_catalog_sensitivity', 'data_catalog', ['sensitivity'])
    op.create_index('idx_catalog_source', 'data_catalog', ['source_id'])
    op.create_index('idx_catalog_quality', 'data_catalog', ['quality_score'])
    op.create_index(
        'idx_catalog_purge_after',
        'data_catalog',
        ['purge_after'],
        postgresql_where=sa.text('purge_after IS NOT NULL')
    )


def downgrade():
    """Drop data_catalog table."""
    op.drop_index('idx_catalog_purge_after', table_name='data_catalog')
    op.drop_index('idx_catalog_quality', table_name='data_catalog')
    op.drop_index('idx_catalog_source', table_name='data_catalog')
    op.drop_index('idx_catalog_sensitivity', table_name='data_catalog')
    op.drop_index('idx_catalog_owner', table_name='data_catalog')
    op.drop_index('idx_catalog_name', table_name='data_catalog')
    op.drop_index('idx_catalog_type', table_name='data_catalog')
    op.drop_table('data_catalog')
