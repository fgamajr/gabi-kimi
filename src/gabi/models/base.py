"""Modelos base e mixins do SQLAlchemy para o GABI.

Este módulo define as bases e mixins para todos os modelos do banco de dados.
Baseado em GABI_SPECS_FINAL_v1.md Seção 2.7.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# =============================================================================
# Base Declarativa
# =============================================================================

class Base(DeclarativeBase):
    """Base declarativa para todos os modelos SQLAlchemy.
    
    Usa SQLAlchemy 2.0 style com type hints e Mapped[] types.
    """
    pass


# =============================================================================
# Mixins
# =============================================================================

class UUIDMixin:
    """Mixin que adiciona UUID como chave primária.
    
    O UUID é gerado automaticamente no momento da criação do registro.
    """
    
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
        nullable=False,
    )


class TimestampMixin:
    """Mixin que adiciona timestamps de criação e atualização.
    
    - created_at: definido automaticamente na criação
    - updated_at: atualizado automaticamente em cada modificação
    """
    
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Mixin que adiciona suporte a soft delete (exclusão lógica).
    
    Ao invés de remover o registro do banco, ele é marcado como deletado.
    Isso permite auditoria e recuperação de dados.
    
    Campos:
    - is_deleted: flag booleana indicando se o registro foi deletado
    - deleted_at: timestamp da exclusão (None se não deletado)
    - deleted_reason: motivo opcional da exclusão
    - deleted_by: identificador do usuário/sistema que executou a exclusão
    """
    
    is_deleted: Mapped[bool] = mapped_column(
        default=False,
        server_default="false",
        nullable=False,
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        default=None,
        nullable=True,
    )
    deleted_reason: Mapped[Optional[str]] = mapped_column(
        default=None,
        nullable=True,
    )
    deleted_by: Mapped[Optional[str]] = mapped_column(
        default=None,
        nullable=True,
    )


# =============================================================================
# Bases Combinadas
# =============================================================================

class AuditableBase(Base, UUIDMixin, TimestampMixin):
    """Base para modelos que precisam de UUID e timestamps.
    
    Combina:
    - Base: DeclarativeBase do SQLAlchemy
    - UUIDMixin: id UUID como chave primária
    - TimestampMixin: created_at e updated_at automáticos
    
    Use esta base para modelos que precisam de auditoria básica
    mas não necessitam de soft delete.
    """
    
    __abstract__ = True


class SoftDeleteBase(AuditableBase, SoftDeleteMixin):
    """Base completa para modelos com soft delete.
    
    Combina:
    - AuditableBase: Base + UUIDMixin + TimestampMixin
    - SoftDeleteMixin: is_deleted, deleted_at, deleted_reason, deleted_by
    
    Use esta base para modelos que precisam de:
    - Identificação única via UUID
    - Auditoria completa de criação/modificação
    - Suporte a exclusão lógica para recuperação e histórico
    """
    
    __abstract__ = True


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "Base",
    "UUIDMixin",
    "TimestampMixin",
    "SoftDeleteMixin",
    "AuditableBase",
    "SoftDeleteBase",
]
