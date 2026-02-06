"""Base SQLAlchemy models and mixins for GABI.

This module provides the foundation for all database models in the GABI system,
including mixins for UUID primary keys, timestamps, and soft delete functionality.
Uses SQLAlchemy 2.0 style with Mapped type annotations.
"""

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Naming convention for database constraints
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models.
    
    Provides metadata with naming convention for consistent constraint naming.
    """
    
    metadata = MetaData(naming_convention=convention)


class UUIDMixin:
    """Mixin that adds a UUID primary key to models.
    
    Automatically generates a UUID4 for each new record.
    """
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    """Mixin that adds automatic timestamp fields to models.
    
    Tracks when records are created and last updated.
    """
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Mixin that adds soft delete functionality to models.
    
    Instead of permanently deleting records, marks them as deleted
    with metadata about when, why, and by whom.
    """
    
    is_deleted: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    deleted_reason: Mapped[Optional[str]] = mapped_column(
        nullable=True,
    )
    deleted_by: Mapped[Optional[str]] = mapped_column(
        nullable=True,
    )


class AuditableBase(Base, UUIDMixin, TimestampMixin):
    """Abstract base class for auditable models.
    
    Combines UUID primary key and timestamp tracking.
    Inherit from this class for models that need audit trails.
    """
    
    __abstract__ = True


class SoftDeleteBase(AuditableBase, SoftDeleteMixin):
    """Abstract base class for models with soft delete support.
    
    Combines UUID primary key, timestamp tracking, and soft delete functionality.
    Inherit from this class for models that support soft deletion.
    """
    
    __abstract__ = True
