"""Modelos de Lineage (Data Lineage) para o GABI.

Este módulo define os modelos para rastreamento de linhagem de dados,
representando um Grafo Acíclico Direcionado (DAG) de dependências.
Baseado em GABI_SPECS_FINAL_v1.md Seção 2.7.1 (lineage_nodes, lineage_edges).

Invariante: Grafo acíclico direcionado (DAG) - não permite ciclos.
"""

from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID

from sqlalchemy import ForeignKey, func, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from gabi.models.base import Base
from gabi.types import LineageNodeType, LineageEdgeType


# =============================================================================
# Modelo LineageNode
# =============================================================================

class LineageNode(Base):
    """Nó de linhagem de dados no DAG.
    
    Representa uma entidade no grafo de linhagem: fonte, transformação,
    dataset, documento ou API. Cada nó é identificado por um node_id único.
    
    Campos:
        node_id: Identificador único do nó (chave primária)
        node_type: Tipo do nó (source, transform, dataset, document, api)
        name: Nome descritivo do nó
        description: Descrição detalhada (opcional)
        properties: Metadados adicionais em JSONB
        created_at: Timestamp de criação
    
    Invariante DAG: Não pode haver ciclos no grafo de linhagem.
    """
    
    __tablename__ = "lineage_nodes"
    
    def __init__(self, **kwargs):
        """Initialize with default properties if not provided."""
        if 'properties' not in kwargs or kwargs['properties'] is None:
            kwargs['properties'] = {}
        super().__init__(**kwargs)
    
    # Identificação
    node_id: Mapped[str] = mapped_column(
        primary_key=True,
        nullable=False,
    )
    
    # Tipo do nó com constraint CHECK
    node_type: Mapped[LineageNodeType] = mapped_column(
        nullable=False,
    )
    
    # Metadados
    name: Mapped[str] = mapped_column(
        nullable=False,
    )
    description: Mapped[Optional[str]] = mapped_column(
        nullable=True,
    )
    
    # Propriedades extensíveis
    properties: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=func.now(),
    )
    
    __table_args__ = (
        CheckConstraint(
            "node_type IN ('source', 'transform', 'dataset', 'document', 'api')",
            name="chk_lineage_node_type"
        ),
    )
    
    def __repr__(self) -> str:
        return (
            f"<LineageNode("
            f"node_id={self.node_id!r}, "
            f"node_type={self.node_type.value}, "
            f"name={self.name!r}"
            f")>"
        )


# =============================================================================
# Modelo LineageEdge
# =============================================================================

class LineageEdge(Base):
    """Aresta de linhagem de dados no DAG.
    
    Representa uma relação direcionada entre dois nós de linhagem.
    A aresta vai de source_node (origem) para target_node (destino).
    
    Campos:
        id: UUID único da aresta (chave primária)
        source_node: Referência para o nó origem (FK lineage_nodes)
        target_node: Referência para o nó destino (FK lineage_nodes)
        edge_type: Tipo da relação (produced, input_to, output_to, etc.)
        properties: Metadados adicionais em JSONB
        run_id: Referência para a execução que criou a aresta (FK execution_manifests)
        created_at: Timestamp de criação
    
    Constraints:
        - UNIQUE(source_node, target_node, edge_type): Evita duplicatas
        - ON DELETE CASCADE: Remove arestas quando nós são deletados
        - Invariante DAG: Não permite ciclos (a ser validado na aplicação)
    """
    
    __tablename__ = "lineage_edges"
    
    def __init__(self, **kwargs):
        """Initialize with default properties if not provided."""
        if 'properties' not in kwargs or kwargs['properties'] is None:
            kwargs['properties'] = {}
        super().__init__(**kwargs)
    
    # Identificação
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
        nullable=False,
    )
    
    # Relações com nós (ON DELETE CASCADE)
    source_node: Mapped[str] = mapped_column(
        ForeignKey("lineage_nodes.node_id", ondelete="CASCADE"),
        nullable=False,
    )
    target_node: Mapped[str] = mapped_column(
        ForeignKey("lineage_nodes.node_id", ondelete="CASCADE"),
        nullable=False,
    )
    
    # Tipo da aresta
    edge_type: Mapped[LineageEdgeType] = mapped_column(
        nullable=False,
    )
    
    # Propriedades extensíveis
    properties: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    
    # Referência para execução (ON DELETE SET NULL)
    run_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("execution_manifests.run_id", ondelete="SET NULL"),
        nullable=True,
    )
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=func.now(),
    )
    
    __table_args__ = (
        # Constraint única para evitar arestas duplicadas
        UniqueConstraint(
            "source_node", "target_node", "edge_type",
            name="uq_lineage_edge_source_target_type"
        ),
        # Constraint CHECK para tipos válidos
        CheckConstraint(
            "edge_type IN ('produced', 'input_to', 'output_to', 'derived_from', 'api_call')",
            name="chk_lineage_edge_type"
        ),
    )
    
    def __repr__(self) -> str:
        return (
            f"<LineageEdge("
            f"id={self.id}, "
            f"{self.source_node!r} -> {self.target_node!r}, "
            f"edge_type={self.edge_type.value}"
            f")>"
        )
    
    def is_self_loop(self) -> bool:
        """Verifica se a aresta é um auto-loop (source == target).
        
        Auto-loops são proibidos em DAGs válidos.
        """
        return self.source_node == self.target_node


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "LineageNode",
    "LineageEdge",
]
