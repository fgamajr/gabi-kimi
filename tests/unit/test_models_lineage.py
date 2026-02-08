"""Testes unitários para os modelos de Lineage.

Testa propriedades, métodos e comportamentos dos modelos de linhagem.
"""

from __future__ import annotations

import pytest
from uuid import uuid4

from gabi.models.lineage import (
    LineageNode,
    LineageEdge,
    LineageNodeType,
    LineageEdgeType,
)


class TestLineageNodeCreation:
    """Testes para criação de LineageNode."""
    
    def test_node_creation_with_required_fields(self):
        """Verifica criação com campos obrigatórios."""
        node = LineageNode(
            node_id="source_001",
            node_type=LineageNodeType.SOURCE,
            name="Fonte de Dados",
        )
        assert node.node_id == "source_001"
        assert node.node_type == LineageNodeType.SOURCE
        assert node.name == "Fonte de Dados"
    
    def test_node_default_properties_is_empty_dict(self):
        """Verifica que properties padrão é dict vazio."""
        node = LineageNode(
            node_id="source_001",
            node_type=LineageNodeType.SOURCE,
            name="Fonte",
        )
        assert node.properties == {}


class TestLineageNodeTypes:
    """Testes para tipos de LineageNode."""
    
    def test_node_type_values(self):
        """Verifica valores de LineageNodeType."""
        assert LineageNodeType.SOURCE.value == "source"
        assert LineageNodeType.TRANSFORM.value == "transform"
        assert LineageNodeType.DATASET.value == "dataset"
        assert LineageNodeType.DOCUMENT.value == "document"
        assert LineageNodeType.API.value == "api"


class TestLineageNodeConstraints:
    """Testes para constraints de LineageNode."""
    
    def test_has_check_constraint_for_node_type(self):
        """Verifica que há CHECK constraint para node_type."""
        table_args = LineageNode.__table_args__
        assert any("chk_lineage_node_type" in str(arg) for arg in table_args)


class TestLineageNodeRepr:
    """Testes para representação string de LineageNode."""
    
    def test_repr_contains_node_id(self):
        """Verifica que repr contém node_id."""
        node = LineageNode(
            node_id="my_node",
            node_type=LineageNodeType.SOURCE,
            name="My Node",
        )
        repr_str = repr(node)
        assert "my_node" in repr_str
    
    def test_repr_contains_node_type(self):
        """Verifica que repr contém node_type."""
        node = LineageNode(
            node_id="my_node",
            node_type=LineageNodeType.DATASET,
            name="My Node",
        )
        repr_str = repr(node)
        assert "dataset" in repr_str
    
    def test_repr_contains_name(self):
        """Verifica que repr contém name."""
        node = LineageNode(
            node_id="my_node",
            node_type=LineageNodeType.SOURCE,
            name="Test Name",
        )
        repr_str = repr(node)
        assert "Test Name" in repr_str


class TestLineageEdgeCreation:
    """Testes para criação de LineageEdge."""
    
    def test_edge_creation_with_required_fields(self):
        """Verifica criação com campos obrigatórios."""
        edge = LineageEdge(
            source_node="node_a",
            target_node="node_b",
            edge_type=LineageEdgeType.PRODUCED,
        )
        assert edge.source_node == "node_a"
        assert edge.target_node == "node_b"
        assert edge.edge_type == LineageEdgeType.PRODUCED
    
    def test_edge_default_properties_is_empty_dict(self):
        """Verifica que properties padrão é dict vazio."""
        edge = LineageEdge(
            source_node="node_a",
            target_node="node_b",
            edge_type=LineageEdgeType.PRODUCED,
        )
        assert edge.properties == {}


class TestLineageEdgeTypes:
    """Testes para tipos de LineageEdge."""
    
    def test_edge_type_values(self):
        """Verifica valores de LineageEdgeType."""
        assert LineageEdgeType.PRODUCED.value == "produced"
        assert LineageEdgeType.INPUT_TO.value == "input_to"
        assert LineageEdgeType.OUTPUT_TO.value == "output_to"
        assert LineageEdgeType.DERIVED_FROM.value == "derived_from"
        assert LineageEdgeType.API_CALL.value == "api_call"


class TestLineageEdgeConstraints:
    """Testes para constraints de LineageEdge."""
    
    def test_has_unique_constraint_for_source_target_type(self):
        """Verifica que há constraint única para source_node + target_node + edge_type."""
        from sqlalchemy import UniqueConstraint
        table_args = LineageEdge.__table_args__
        # Check for UniqueConstraint with the expected columns
        has_constraint = any(
            isinstance(arg, UniqueConstraint) and 
            {"source_node", "target_node", "edge_type"}.issubset(set(arg.columns.keys()))
            for arg in table_args
        )
        assert has_constraint
    
    def test_has_check_constraint_for_edge_type(self):
        """Verifica que há CHECK constraint para edge_type."""
        table_args = LineageEdge.__table_args__
        assert any("chk_lineage_edge_type" in str(arg) for arg in table_args)


class TestLineageEdgeSelfLoop:
    """Testes para detecção de auto-loop."""
    
    def test_is_self_loop_returns_true_when_source_equals_target(self):
        """Verifica que is_self_loop retorna True quando source == target."""
        edge = LineageEdge(
            source_node="node_a",
            target_node="node_a",
            edge_type=LineageEdgeType.PRODUCED,
        )
        assert edge.is_self_loop() is True
    
    def test_is_self_loop_returns_false_when_source_differs_from_target(self):
        """Verifica que is_self_loop retorna False quando source != target."""
        edge = LineageEdge(
            source_node="node_a",
            target_node="node_b",
            edge_type=LineageEdgeType.PRODUCED,
        )
        assert edge.is_self_loop() is False


class TestLineageEdgeRepr:
    """Testes para representação string de LineageEdge."""
    
    def test_repr_contains_source_node(self):
        """Verifica que repr contém source_node."""
        edge = LineageEdge(
            source_node="source_1",
            target_node="target_1",
            edge_type=LineageEdgeType.PRODUCED,
        )
        repr_str = repr(edge)
        assert "source_1" in repr_str
    
    def test_repr_contains_target_node(self):
        """Verifica que repr contém target_node."""
        edge = LineageEdge(
            source_node="source_1",
            target_node="target_1",
            edge_type=LineageEdgeType.PRODUCED,
        )
        repr_str = repr(edge)
        assert "target_1" in repr_str
    
    def test_repr_contains_edge_type(self):
        """Verifica que repr contém edge_type."""
        edge = LineageEdge(
            source_node="source_1",
            target_node="target_1",
            edge_type=LineageEdgeType.DERIVED_FROM,
        )
        repr_str = repr(edge)
        assert "derived_from" in repr_str
