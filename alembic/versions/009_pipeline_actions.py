"""Create pipeline_actions table for persistent control-plane state.

Revision ID: 009_pipeline_actions
Revises: 008_dashboard_indexes
Create Date: 2026-02-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "009_pipeline_actions"
down_revision: Union[str, None] = "008_dashboard_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pipeline_actions",
        sa.Column(
            "action_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "source_id",
            sa.String(),
            sa.ForeignKey("source_registry.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("phase", sa.String(length=50), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="requested",
        ),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("task_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_index(
        "idx_pipeline_actions_source_date",
        "pipeline_actions",
        ["source_id", "created_at"],
    )
    op.create_index("idx_pipeline_actions_status", "pipeline_actions", ["status"])
    op.create_index("idx_pipeline_actions_action", "pipeline_actions", ["action"])


def downgrade() -> None:
    op.drop_index("idx_pipeline_actions_action", table_name="pipeline_actions")
    op.drop_index("idx_pipeline_actions_status", table_name="pipeline_actions")
    op.drop_index("idx_pipeline_actions_source_date", table_name="pipeline_actions")
    op.drop_table("pipeline_actions")

