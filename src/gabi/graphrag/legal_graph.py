"""
GraphRAG Implementation for Legal Documents

This module implements GraphRAG by building a knowledge graph where nodes are documents
and entities, and edges represent relationships like citations, references, and connections.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass
from enum import Enum
import re

from sqlmodel import SQLModel, Field, create_engine, Session, select
from sqlalchemy import text
import networkx as nx

from gabi.config import settings
from gabi.db import get_session_no_commit
from gabi.models.document import Document
from gabi.models.chunk import DocumentChunk

logger = logging.getLogger(__name__)


class RelationshipType(str, Enum):
    """Types of relationships between legal documents."""
    CITATES = "cites"
    REFERENCES = "references"
    AMENDS = "amends"
    REVOKES = "revokes"
    DERIVES_FROM = "derives_from"
    SIMILAR_TO = "similar_to"
    DISSENTS_FROM = "dissents_from"
    OVERULES = "overrules"


@dataclass
class Entity:
    """Represents an entity in the knowledge graph."""
    id: str
    type: str  # document, minister, organ, process, etc.
    name: str
    properties: Dict[str, Any]


@dataclass
class Relationship:
    """Represents a relationship between entities."""
    source_id: str
    target_id: str
    type: RelationshipType
    properties: Dict[str, Any]


@dataclass
class GraphQueryResult:
    """Result of a graph query."""
    entities: List[Entity]
    relationships: List[Relationship]
    paths: List[List[str]]  # Paths between entities


class LegalKnowledgeGraph:
    """
    Knowledge Graph for Legal Documents.
    
    Builds and maintains a graph where:
    - Nodes are documents, entities (ministers, organs, processes)
    - Edges are relationships (citations, references, amendments, etc.)
    """
    
    def __init__(self):
        self.graph = nx.MultiDiGraph()
        self.entities: Dict[str, Entity] = {}
        self.relationships: Set[str] = set()  # To prevent duplicates
        
    def add_entity(self, entity: Entity) -> None:
        """Add an entity to the graph."""
        self.entities[entity.id] = entity
        self.graph.add_node(
            entity.id,
            type=entity.type,
            name=entity.name,
            **entity.properties
        )
    
    def add_relationship(self, relationship: Relationship) -> None:
        """Add a relationship to the graph."""
        # Create a unique key for this relationship to prevent duplicates
        rel_key = f"{relationship.source_id}->{relationship.target_id}:{relationship.type}"
        if rel_key in self.relationships:
            return  # Skip duplicate
        
        self.relationships.add(rel_key)
        
        self.graph.add_edge(
            relationship.source_id,
            relationship.target_id,
            key=relationship.type,
            type=relationship.type,
            **relationship.properties
        )
    
    async def build_from_documents(self, source_ids: Optional[List[str]] = None) -> None:
        """
        Build the knowledge graph from documents in the database.
        
        Args:
            source_ids: Optional list of source IDs to limit the graph construction
        """
        logger.info("Building knowledge graph from documents...")
        
        async with get_session_no_commit() as session:
            # Query documents
            query = select(Document)
            if source_ids:
                query = query.where(Document.source_id.in_(source_ids))
            
            result = await session.execute(query)
            documents = result.scalars().all()
            
            # Add document nodes
            for doc in documents:
                entity = Entity(
                    id=doc.document_id,
                    type="document",
                    name=doc.title or f"Document {doc.document_id}",
                    properties={
                        "source_id": doc.source_id,
                        "type": doc.doc_metadata.get("type", "unknown") if doc.doc_metadata else "unknown",
                        "year": doc.doc_metadata.get("year") if doc.doc_metadata else None,
                        "number": doc.doc_metadata.get("number") if doc.doc_metadata else None,
                        "url": doc.url,
                        "status": doc.status
                    }
                )
                self.add_entity(entity)
            
            # Extract relationships from document content
            for doc in documents:
                await self._extract_relationships_from_document(session, doc)
        
        logger.info(f"Knowledge graph built with {len(self.entities)} entities and {len(self.relationships)} relationships")
    
    async def _extract_relationships_from_document(self, session: Session, document: Document) -> None:
        """Extract relationships from a single document."""
        # Get document content
        content = document.content_preview or ""
        
        # Extract document citations (patterns like "Acórdão X/Y", "Súmula Z", etc.)
        citation_patterns = [
            r"Acórdão\s+(\d+/\d+)",  # Acórdão 123/2024
            r"Súmula\s+(\d+)",       # Súmula 247
            r"Instrução\s+Normativa\s+(\d+/\d+)",  # IN 75/2022
            r"Portaria\s+(\d+/\d+)",  # Portaria 123/2024
            r"Resolução\s+(\d+/\d+)", # Resolução 45/2023
        ]
        
        for pattern in citation_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                # Format the document ID based on the pattern
                if "Acórdão" in pattern:
                    target_id = f"TCU-ACORDAO-{match}"
                elif "Súmula" in pattern:
                    target_id = f"TCU-SUMULA-{match}"
                elif "Instrução Normativa" in pattern:
                    target_id = f"TCU-IN-{match}"
                elif "Portaria" in pattern:
                    target_id = f"TCU-PORTARIA-{match}"
                elif "Resolução" in pattern:
                    target_id = f"TCU-RESOLUCAO-{match}"
                else:
                    target_id = f"TCU-DOC-{match}"
                
                # Check if the referenced document exists in our database
                target_doc_exists = await self._document_exists(session, target_id)
                
                if target_doc_exists:
                    # Add relationship: this document cites the other
                    relationship = Relationship(
                        source_id=document.document_id,
                        target_id=target_id,
                        type=RelationshipType.CITATES,
                        properties={
                            "context": f"Cited in {document.title}",
                            "document_type": "citation"
                        }
                    )
                    self.add_relationship(relationship)
    
    async def _document_exists(self, session: Session, document_id: str) -> bool:
        """Check if a document exists in the database."""
        result = await session.execute(
            select(Document).where(Document.document_id == document_id)
        )
        return result.scalar_one_or_none() is not None
    
    async def query_graph(
        self, 
        start_node: str, 
        relationship_types: Optional[List[RelationshipType]] = None,
        max_depth: int = 3,
        limit: int = 50
    ) -> GraphQueryResult:
        """
        Query the knowledge graph starting from a node.
        
        Args:
            start_node: Starting node ID
            relationship_types: Optional list of relationship types to follow
            max_depth: Maximum depth to traverse
            limit: Maximum number of results to return
            
        Returns:
            GraphQueryResult with entities, relationships, and paths
        """
        if start_node not in self.graph:
            return GraphQueryResult(entities=[], relationships=[], paths=[])
        
        # Find connected components within max_depth
        entities_set: Set[str] = set()
        relationships_list: List[Relationship] = []
        paths_list: List[List[str]] = []
        
        # BFS traversal up to max_depth
        queue = [(start_node, 0, [start_node])]  # (node, depth, path)
        visited = {start_node}
        
        while queue:
            current_node, depth, current_path = queue.pop(0)
            entities_set.add(current_node)
            
            if depth >= max_depth:
                continue
            
            # Get neighbors
            for neighbor, edge_dict in self.graph[current_node].items():
                if neighbor in visited and neighbor != start_node:
                    continue
                
                # Check relationship types if specified
                valid_edges = []
                for edge_key, edge_attrs in edge_dict.items():
                    if relationship_types is None or edge_attrs.get('type') in relationship_types:
                        valid_edges.append((edge_key, edge_attrs))
                
                for edge_key, edge_attrs in valid_edges:
                    # Create relationship object
                    relationship = Relationship(
                        source_id=current_node,
                        target_id=neighbor,
                        type=edge_attrs.get('type'),
                        properties={k: v for k, v in edge_attrs.items() if k not in ['type']}
                    )
                    
                    if relationship not in relationships_list:
                        relationships_list.append(relationship)
                    
                    new_path = current_path + [neighbor]
                    paths_list.append(new_path)
                    
                    if neighbor not in visited and len(entities_set) < limit:
                        visited.add(neighbor)
                        queue.append((neighbor, depth + 1, new_path))
                    
                    if len(entities_set) >= limit:
                        break
            
            if len(entities_set) >= limit:
                break
        
        # Create entity objects
        entities = []
        for entity_id in entities_set:
            if entity_id in self.entities:
                entities.append(self.entities[entity_id])
        
        # Limit results
        entities = entities[:limit]
        relationships_list = relationships_list[:limit]
        paths_list = paths_list[:limit]
        
        return GraphQueryResult(
            entities=entities,
            relationships=relationships_list,
            paths=paths_list
        )
    
    def get_neighbors(self, node_id: str, relationship_types: Optional[List[RelationshipType]] = None) -> List[Tuple[str, RelationshipType]]:
        """
        Get neighbors of a node with specific relationship types.
        
        Args:
            node_id: Node ID to get neighbors for
            relationship_types: Optional list of relationship types to filter
            
        Returns:
            List of (neighbor_id, relationship_type) tuples
        """
        if node_id not in self.graph:
            return []
        
        neighbors = []
        for neighbor, edge_dict in self.graph[node_id].items():
            for edge_key, edge_attrs in edge_dict.items():
                rel_type = edge_attrs.get('type')
                if relationship_types is None or rel_type in relationship_types:
                    neighbors.append((neighbor, rel_type))
        
        return neighbors
    
    def get_shortest_path(self, source: str, target: str) -> Optional[List[str]]:
        """
        Find shortest path between two nodes.
        
        Args:
            source: Source node ID
            target: Target node ID
            
        Returns:
            Shortest path as a list of node IDs, or None if no path exists
        """
        try:
            return nx.shortest_path(self.graph, source=source, target=target)
        except nx.NetworkXNoPath:
            return None
        except nx.NodeNotFound:
            return None


# Global instance
_legal_graph: Optional[LegalKnowledgeGraph] = None


async def get_legal_knowledge_graph() -> LegalKnowledgeGraph:
    """Get singleton instance of legal knowledge graph."""
    global _legal_graph
    if _legal_graph is None:
        _legal_graph = LegalKnowledgeGraph()
    return _legal_graph


async def build_legal_graph(source_ids: Optional[List[str]] = None) -> LegalKnowledgeGraph:
    """
    Build the legal knowledge graph from documents.
    
    Args:
        source_ids: Optional list of source IDs to limit the graph construction
        
    Returns:
        Built LegalKnowledgeGraph instance
    """
    graph = await get_legal_knowledge_graph()
    await graph.build_from_documents(source_ids)
    return graph


async def query_legal_graph(
    start_node: str,
    relationship_types: Optional[List[RelationshipType]] = None,
    max_depth: int = 3,
    limit: int = 50
) -> GraphQueryResult:
    """
    Query the legal knowledge graph.
    
    Args:
        start_node: Starting node ID
        relationship_types: Optional list of relationship types to follow
        max_depth: Maximum depth to traverse
        limit: Maximum number of results to return
        
    Returns:
        GraphQueryResult with entities, relationships, and paths
    """
    graph = await get_legal_knowledge_graph()
    return await graph.query_graph(start_node, relationship_types, max_depth, limit)