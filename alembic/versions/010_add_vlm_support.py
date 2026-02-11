"""Add VLM support tables.

Revision ID: 010_add_vlm_support
Revises: 009_pipeline_actions
Create Date: 2026-02-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "010_add_vlm_support"
down_revision: Union[str, None] = "009_pipeline_actions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create VLM support tables."""
    
    # Table for storing page images
    op.create_table(
        "page_images",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("image_data", sa.LargeBinary(), nullable=True),  # NULL if stored in S3
        sa.Column("s3_key", sa.String(length=512), nullable=True),
        sa.Column("image_format", sa.String(length=10), server_default="png"),
        sa.Column("image_width", sa.Integer(), nullable=True),
        sa.Column("image_height", sa.Integer(), nullable=True),
        sa.Column("dpi", sa.Integer(), server_default="150"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "page_number", name="uix_page_images_doc_page"),
    )
    
    # Index for faster lookups
    op.create_index("idx_page_images_document", "page_images", ["document_id"])
    
    # Table for VLM extractions
    op.create_table(
        "vlm_extractions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("extraction_model", sa.String(length=100), nullable=True),
        sa.Column("extraction_mode", sa.String(length=50), nullable=True),
        sa.Column("raw_response", sa.JSON(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("structured_content", sa.JSON(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    
    op.create_index("idx_vlm_extractions_document", "vlm_extractions", ["document_id"])
    op.create_index("idx_vlm_extractions_model", "vlm_extractions", ["extraction_model"])
    
    # Optional: ColPali image embeddings for visual search
    op.create_table(
        "page_image_embeddings",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(128), nullable=True),  # ColPali uses 128-dim
        sa.Column("model", sa.String(length=100), server_default="colpali-v1.2"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "page_number", name="uix_page_img_emb_doc_page"),
    )
    
    op.create_index("idx_page_img_emb_document", "page_image_embeddings", ["document_id"])
    
    # HNSW index for fast similarity search (optional, can be created later)
    # op.execute(
    #     "CREATE INDEX idx_page_img_emb_hnsw ON page_image_embeddings "
    #     "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    # )


def downgrade() -> None:
    """Drop VLM support tables."""
    
    op.drop_table("page_image_embeddings")
    op.drop_table("vlm_extractions")
    op.drop_table("page_images")
