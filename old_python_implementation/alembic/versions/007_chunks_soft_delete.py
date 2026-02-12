"""Add soft-delete columns to document_chunks.

The DocumentChunk model extends SoftDeleteBase (which provides is_deleted,
deleted_at, deleted_reason, deleted_by) but migration 001 omitted these columns.

Revision ID: 007_chunks_soft_delete
Revises: 006_enum_to_varchar
Create Date: 2026-02-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '007_chunks_soft_delete'
down_revision: Union[str, None] = '006_enum_to_varchar'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('document_chunks', sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('document_chunks', sa.Column('deleted_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('document_chunks', sa.Column('deleted_reason', sa.Text(), nullable=True))
    op.add_column('document_chunks', sa.Column('deleted_by', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('document_chunks', 'deleted_by')
    op.drop_column('document_chunks', 'deleted_reason')
    op.drop_column('document_chunks', 'deleted_at')
    op.drop_column('document_chunks', 'is_deleted')
