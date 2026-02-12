"""Sistema de Data Lineage do GABI.

Rastreia origem e transformações dos dados através de um
grafo acíclico direcionado (DAG).
Baseado em GABI_SPECS_FINAL_v1.md Seção 2.7.1 (lineage_nodes, lineage_edges).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy import select, desc, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from gabi.types import LineageNodeType, LineageEdgeType
from gabi.models.lineage import LineageNode, LineageEdge
from gabi.config import settings

logger = logging.getLogger(__name__)


@dataclass
class LineagePath:
    """Caminho no grafo de lineage.
    
    Attributes:
        nodes: Lista de nós no caminho
        edges: Lista de arestas no caminho
        distance: Distância (número de arestas)
    """
    nodes: List[LineageNode] = field(default_factory=list)
    edges: List[LineageEdge] = field(default_factory=list)
    
    @property
    def distance(self) -> int:
        """Número de arestas no caminho."""
        return len(self.edges)


@dataclass
class LineageGraph:
    """Subgrafo de lineage.
    
    Attributes:
        nodes: Nós do grafo
        edges: Arestas do grafo
        root_node: Nó raiz (se aplicável)
    """
    nodes: List[LineageNode] = field(default_factory=list)
    edges: List[LineageEdge] = field(default_factory=list)
    root_node: Optional[LineageNode] = None
    
    def get_upstream(self, node_id: str) -> List[LineageNode]:
        """Retorna nós upstream (fontes) do nó."""
        upstream = []
        for edge in self.edges:
            if edge.target_node == node_id:
                for node in self.nodes:
                    if node.node_id == edge.source_node:
                        upstream.append(node)
        return upstream
    
    def get_downstream(self, node_id: str) -> List[LineageNode]:
        """Retorna nós downstream (consumidores) do nó."""
        downstream = []
        for edge in self.edges:
            if edge.source_node == node_id:
                for node in self.nodes:
                    if node.node_id == edge.target_node:
                        downstream.append(node)
        return downstream


class LineageTracker:
    """Rastreador de lineage de dados.
    
    Gerencia o grafo de lineage, rastreando:
    - Origem dos dados (sources)
    - Transformações aplicadas
    - Datasets produzidos
    - Documentos processados
    
    Implementa um DAG (grafo acíclico direcionado) onde:
    - Nós representam entidades (source, transform, dataset, document)
    - Arestas representam relações de produção/consumo
    
    Attributes:
        db_session: Sessão do banco de dados
        enabled: Se lineage está habilitado
    """
    
    def __init__(
        self,
        db_session: AsyncSession,
        enabled: bool = True,
    ):
        self.db_session = db_session
        self.enabled = enabled and settings.lineage_enabled
        logger.info(f"LineageTracker inicializado (enabled={self.enabled})")
    
    async def create_node(
        self,
        node_id: str,
        node_type: LineageNodeType,
        name: str,
        description: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None,
    ) -> Optional[LineageNode]:
        """Cria nó no grafo de lineage.
        
        Args:
            node_id: Identificador único
            node_type: Tipo do nó
            name: Nome descritivo
            description: Descrição detalhada
            properties: Propriedades adicionais
            
        Returns:
            Nó criado ou None
        """
        if not self.enabled:
            return None
        
        try:
            # Verifica se já existe
            result = await self.db_session.execute(
                select(LineageNode).where(LineageNode.node_id == node_id)
            )
            existing = result.scalar_one_or_none()
            
            if existing:
                logger.debug(f"Nó {node_id} já existe")
                return existing
            
            # Cria nó
            node = LineageNode(
                node_id=node_id,
                node_type=node_type,
                name=name,
                description=description,
                properties=properties or {},
            )
            
            self.db_session.add(node)
            await self.db_session.commit()
            
            logger.debug(f"Nó {node_id} criado ({node_type.value})")
            return node
            
        except Exception as e:
            logger.error(f"Erro ao criar nó {node_id}: {e}")
            await self.db_session.rollback()
            return None
    
    async def create_edge(
        self,
        source_node: str,
        target_node: str,
        edge_type: LineageEdgeType,
        properties: Optional[Dict[str, Any]] = None,
        run_id: Optional[UUID] = None,
    ) -> Optional[LineageEdge]:
        """Cria aresta no grafo de lineage.
        
        Args:
            source_node: Nó origem
            target_node: Nó destino
            edge_type: Tipo da relação
            properties: Propriedades adicionais
            run_id: ID da execução
            
        Returns:
            Aresta criada ou None
        """
        if not self.enabled:
            return None
        
        # Validação: não permite auto-loop
        if source_node == target_node:
            logger.warning(f"Auto-loop detectado e prevenido: {source_node}")
            return None
        
        try:
            # Verifica se aresta já existe
            result = await self.db_session.execute(
                select(LineageEdge).where(
                    and_(
                        LineageEdge.source_node == source_node,
                        LineageEdge.target_node == target_node,
                        LineageEdge.edge_type == edge_type,
                    )
                )
            )
            existing = result.scalar_one_or_none()
            
            if existing:
                logger.debug(f"Aresta {source_node}->{target_node} já existe")
                return existing
            
            # Verifica se criaria ciclo
            would_cycle = await self._would_create_cycle(source_node, target_node)
            if would_cycle:
                logger.warning(
                    f"Ciclo detectado e prevenido: {source_node} -> {target_node}"
                )
                return None
            
            # Cria aresta
            edge = LineageEdge(
                source_node=source_node,
                target_node=target_node,
                edge_type=edge_type,
                properties=properties or {},
                run_id=run_id,
            )
            
            self.db_session.add(edge)
            await self.db_session.commit()
            
            logger.debug(f"Aresta {source_node}->{target_node} criada ({edge_type.value})")
            return edge
            
        except Exception as e:
            logger.error(f"Erro ao criar aresta {source_node}->{target_node}: {e}")
            await self.db_session.rollback()
            return None
    
    async def _would_create_cycle(
        self,
        source_node: str,
        target_node: str,
    ) -> bool:
        """Verifica se adicionar aresta criaria ciclo.
        
        Implementa busca em profundidade para detectar
        se target_node já alcança source_node.
        
        Args:
            source_node: Nó origem proposto
            target_node: Nó destino proposto
            
        Returns:
            True se criaria ciclo
        """
        # Se target == source, é ciclo
        if target_node == source_node:
            return True
        
        # Busca se target já alcança source
        visited: Set[str] = set()
        stack = [target_node]
        
        while stack:
            current = stack.pop()
            if current == source_node:
                return True
            
            if current in visited:
                continue
            visited.add(current)
            
            # Busca nós downstream de current
            result = await self.db_session.execute(
                select(LineageEdge.target_node).where(
                    LineageEdge.source_node == current
                )
            )
            downstream = result.scalars().all()
            stack.extend(downstream)
        
        return False
    
    async def get_node(self, node_id: str) -> Optional[LineageNode]:
        """Obtém nó por ID.
        
        Args:
            node_id: ID do nó
            
        Returns:
            Nó ou None
        """
        result = await self.db_session.execute(
            select(LineageNode).where(LineageNode.node_id == node_id)
        )
        return result.scalar_one_or_none()
    
    async def get_node_lineage(
        self,
        node_id: str,
        direction: str = "both",  # "upstream", "downstream", "both"
        max_depth: int = 5,
    ) -> LineageGraph:
        """Obtém lineage de um nó.
        
        Args:
            node_id: ID do nó
            direction: Direção da busca
            max_depth: Profundidade máxima
            
        Returns:
            Grafo de lineage
        """
        node = await self.get_node(node_id)
        if not node:
            return LineageGraph()
        
        graph = LineageGraph(root_node=node)
        visited: Set[str] = {node_id}
        
        if direction in ("upstream", "both"):
            await self._traverse_upstream(node_id, graph, visited, max_depth, 0)
        
        if direction in ("downstream", "both"):
            await self._traverse_downstream(node_id, graph, visited, max_depth, 0)
        
        return graph
    
    async def _traverse_upstream(
        self,
        node_id: str,
        graph: LineageGraph,
        visited: Set[str],
        max_depth: int,
        current_depth: int,
    ) -> None:
        """Percorre nós upstream (fontes)."""
        if current_depth >= max_depth:
            return
        
        # Busca arestas que apontam para este nó
        result = await self.db_session.execute(
            select(LineageEdge).where(LineageEdge.target_node == node_id)
        )
        edges = result.scalars().all()
        
        for edge in edges:
            if edge.id not in [e.id for e in graph.edges]:
                graph.edges.append(edge)
            
            if edge.source_node not in visited:
                visited.add(edge.source_node)
                
                # Busca nó origem
                source = await self.get_node(edge.source_node)
                if source:
                    graph.nodes.append(source)
                    
                    # Recursão
                    await self._traverse_upstream(
                        edge.source_node,
                        graph,
                        visited,
                        max_depth,
                        current_depth + 1,
                    )
    
    async def _traverse_downstream(
        self,
        node_id: str,
        graph: LineageGraph,
        visited: Set[str],
        max_depth: int,
        current_depth: int,
    ) -> None:
        """Percorre nós downstream (consumidores)."""
        if current_depth >= max_depth:
            return
        
        # Busca arestas que partem deste nó
        result = await self.db_session.execute(
            select(LineageEdge).where(LineageEdge.source_node == node_id)
        )
        edges = result.scalars().all()
        
        for edge in edges:
            if edge.id not in [e.id for e in graph.edges]:
                graph.edges.append(edge)
            
            if edge.target_node not in visited:
                visited.add(edge.target_node)
                
                # Busca nó destino
                target = await self.get_node(edge.target_node)
                if target:
                    graph.nodes.append(target)
                    
                    # Recursão
                    await self._traverse_downstream(
                        edge.target_node,
                        graph,
                        visited,
                        max_depth,
                        current_depth + 1,
                    )
    
    async def find_path(
        self,
        source_id: str,
        target_id: str,
    ) -> Optional[LineagePath]:
        """Encontra caminho entre dois nós.
        
        Implementa BFS para encontrar caminho mais curto.
        
        Args:
            source_id: Nó origem
            target_id: Nó destino
            
        Returns:
            Caminho ou None
        """
        if source_id == target_id:
            node = await self.get_node(source_id)
            if node:
                return LineagePath(nodes=[node])
            return None
        
        # BFS
        queue: List[Tuple[str, LineagePath]] = [(source_id, LineagePath())]
        visited: Set[str] = set()
        
        while queue:
            current_id, path = queue.pop(0)
            
            if current_id in visited:
                continue
            visited.add(current_id)
            
            # Busca arestas de saída
            result = await self.db_session.execute(
                select(LineageEdge).where(LineageEdge.source_node == current_id)
            )
            edges = result.scalars().all()
            
            for edge in edges:
                # Constrói novo caminho
                new_path = LineagePath(
                    nodes=path.nodes.copy(),
                    edges=path.edges.copy(),
                )
                
                # Adiciona nó atual se não está no caminho
                if not new_path.nodes or new_path.nodes[-1].node_id != current_id:
                    node = await self.get_node(current_id)
                    if node:
                        new_path.nodes.append(node)
                
                new_path.edges.append(edge)
                
                # Verifica se chegou ao destino
                if edge.target_node == target_id:
                    target = await self.get_node(target_id)
                    if target:
                        new_path.nodes.append(target)
                    return new_path
                
                # Adiciona à fila
                queue.append((edge.target_node, new_path))
        
        return None
    
    async def get_impact_analysis(
        self,
        node_id: str,
    ) -> Dict[str, Any]:
        """Análise de impacto de mudança em um nó.
        
        Identifica todos os nós downstream que seriam
        afetados por uma mudança.
        
        Args:
            node_id: ID do nó
            
        Returns:
            Análise de impacto
        """
        node = await self.get_node(node_id)
        if not node:
            return {"error": "Node not found"}
        
        # Obtém lineage downstream
        graph = await self.get_node_lineage(node_id, direction="downstream")
        
        # Agrupa por tipo
        by_type: Dict[str, List[str]] = {}
        for n in graph.nodes:
            by_type.setdefault(n.node_type.value, []).append(n.node_id)
        
        return {
            "node_id": node_id,
            "node_name": node.name,
            "total_affected": len(graph.nodes),
            "affected_by_type": by_type,
            "affected_nodes": [n.node_id for n in graph.nodes],
            "max_depth": self._calculate_max_depth(graph, node_id),
        }
    
    def _calculate_max_depth(self, graph: LineageGraph, start_node_id: str) -> int:
        """Calcula profundidade máxima do grafo a partir de um nó."""
        max_depth = 0
        
        for edge in graph.edges:
            if edge.source_node == start_node_id:
                depth = 1
                current = edge.target_node
                
                while True:
                    next_edges = [e for e in graph.edges if e.source_node == current]
                    if not next_edges:
                        break
                    depth += 1
                    current = next_edges[0].target_node
                
                max_depth = max(max_depth, depth)
        
        return max_depth
    
    async def record_source_to_document(
        self,
        source_id: str,
        document_id: str,
        run_id: Optional[UUID] = None,
    ) -> bool:
        """Registra lineage de source para documento.
        
        Args:
            source_id: ID da fonte
            document_id: ID do documento
            run_id: ID da execução
            
        Returns:
            True se sucesso
        """
        # Cria nó source se não existe
        await self.create_node(
            node_id=f"source:{source_id}",
            node_type=LineageNodeType.SOURCE,
            name=f"Source: {source_id}",
            properties={"source_id": source_id},
        )
        
        # Cria nó documento se não existe
        await self.create_node(
            node_id=f"document:{document_id}",
            node_type=LineageNodeType.DOCUMENT,
            name=f"Document: {document_id}",
            properties={"document_id": document_id},
        )
        
        # Cria aresta
        edge = await self.create_edge(
            source_node=f"source:{source_id}",
            target_node=f"document:{document_id}",
            edge_type=LineageEdgeType.PRODUCED,
            run_id=run_id,
        )
        
        return edge is not None
    
    async def record_transformation(
        self,
        input_nodes: List[str],
        output_node: str,
        transform_name: str,
        run_id: Optional[UUID] = None,
        properties: Optional[Dict] = None,
    ) -> bool:
        """Registra transformação de dados.
        
        Args:
            input_nodes: Nós de entrada
            output_node: Nó de saída
            transform_name: Nome da transformação
            run_id: ID da execução
            properties: Propriedades adicionais
            
        Returns:
            True se sucesso
        """
        # Cria nó de transformação
        transform_id = f"transform:{transform_name}:{datetime.utcnow().timestamp()}"
        await self.create_node(
            node_id=transform_id,
            node_type=LineageNodeType.TRANSFORM,
            name=transform_name,
            properties={
                **(properties or {}),
                "run_id": str(run_id) if run_id else None,
            },
        )
        
        # Cria arestas de entrada
        for input_node in input_nodes:
            await self.create_edge(
                source_node=input_node,
                target_node=transform_id,
                edge_type=LineageEdgeType.INPUT_TO,
                run_id=run_id,
            )
        
        # Cria aresta de saída
        await self.create_edge(
            source_node=transform_id,
            target_node=output_node,
            edge_type=LineageEdgeType.OUTPUT_TO,
            run_id=run_id,
        )
        
        return True
    
    async def get_statistics(self) -> Dict[str, Any]:
        """Retorna estatísticas do grafo de lineage.
        
        Returns:
            Estatísticas
        """
        # Total de nós
        result = await self.db_session.execute(
            select(func.count()).select_from(LineageNode)
        )
        total_nodes = result.scalar()
        
        # Total de arestas
        result = await self.db_session.execute(
            select(func.count()).select_from(LineageEdge)
        )
        total_edges = result.scalar()
        
        # Nós por tipo
        result = await self.db_session.execute(
            select(LineageNode.node_type, func.count())
            .group_by(LineageNode.node_type)
        )
        by_type = {row[0].value: row[1] for row in result.fetchall()}
        
        # Arestas por tipo
        result = await self.db_session.execute(
            select(LineageEdge.edge_type, func.count())
            .group_by(LineageEdge.edge_type)
        )
        by_edge_type = {row[0].value: row[1] for row in result.fetchall()}
        
        # Nós sem conexões (órfãos)
        result = await self.db_session.execute(
            select(LineageNode.node_id)
            .outerjoin(LineageEdge, 
                or_(
                    LineageNode.node_id == LineageEdge.source_node,
                    LineageNode.node_id == LineageEdge.target_node
                )
            )
            .where(LineageEdge.id == None)
        )
        orphan_nodes = [row[0] for row in result.fetchall()]
        
        return {
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "nodes_by_type": by_type,
            "edges_by_type": by_edge_type,
            "orphan_nodes": orphan_nodes,
            "orphan_count": len(orphan_nodes),
            "density": total_edges / (total_nodes * (total_nodes - 1)) if total_nodes > 1 else 0,
        }
    
    async def delete_node(self, node_id: str) -> bool:
        """Remove nó e suas arestas.
        
        Args:
            node_id: ID do nó
            
        Returns:
            True se removido
        """
        try:
            # Remove arestas primeiro
            await self.db_session.execute(
                LineageEdge.__table__.delete().where(
                    or_(
                        LineageEdge.source_node == node_id,
                        LineageEdge.target_node == node_id,
                    )
                )
            )
            
            # Remove nó
            result = await self.db_session.execute(
                LineageNode.__table__.delete().where(
                    LineageNode.node_id == node_id
                )
            )
            
            await self.db_session.commit()
            
            deleted = result.rowcount > 0
            if deleted:
                logger.info(f"Nó {node_id} removido")
            
            return deleted
            
        except Exception as e:
            logger.error(f"Erro ao remover nó {node_id}: {e}")
            await self.db_session.rollback()
            return False


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "LineagePath",
    "LineageGraph",
    "LineageTracker",
]
