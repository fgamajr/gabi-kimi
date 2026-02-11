"""Pipeline action model for control-plane requests.

Persists start/stop/restart requests so control state is not process-local.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from gabi.models.base import Base


class PipelineAction(Base):
    """Persistent record of a pipeline control action."""

    __tablename__ = "pipeline_actions"

    action_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_registry.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[Optional[UUID]] = mapped_column(nullable=True)
    phase: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="requested",
        server_default="requested",
    )
    requested_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    task_ids: Mapped[Optional[List[str]]] = mapped_column(JSONB, nullable=True)
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_pipeline_actions_source_date", "source_id", "created_at"),
        Index("idx_pipeline_actions_status", "status"),
        Index("idx_pipeline_actions_action", "action"),
    )

