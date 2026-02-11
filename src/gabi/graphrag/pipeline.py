"""Graph Construction Pipeline for GraphRAG.

This module provides the pipeline for constructing and updating the knowledge graph
from processed documents.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

try:
    from neo4j import AsyncGraphDatabase
    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False

from gabi.graphrag.extractor import (
    LegalEntityExtractor,
    ExtractedEntity,
    ExtractedRelation,
)

logger = logging.getLogger(__name__)


@dataclass
class GraphUpdateResult:
    """Result of graph update operation."""
    document_id: str
    nodes_created: int = 0
    nodes_updated: int = 0
    relationships_created: int = 0
    relationships_updated: int = 0
    errors: List[str] = field(default_factory=list)
    duration_ms: float = 0.0


class GraphConstructionPipeline:
    """Pipeline for constructing and updating the knowledge graph."""
    
    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        extractor: Optional[LegalEntityExtractor] = None
    ):
        if not NEO4J_AVAILABLE:
            raise ImportError(
                "Neo4j driver not installed. "
                "Install with: pip install neo4j"
            )
        
        self.driver = AsyncGraphDatabase.driver(
            neo4j_uri, 
            auth=(neo4j_user, neo4j_password)
        )
        self.extractor = extractor or LegalEntityExtractor()
    
    async def process_document(
        self, 
        document: Any,
        chunks: List[Any]
    ) -> GraphUpdateResult:
        """Process a document and update the graph.
        
        This is called from the main ingestion pipeline.
        
        Args:
            document: Document model instance
            chunks: List of document chunks
            
        Returns:
            GraphUpdateResult with statistics
        """
        start_time = datetime.now()
        errors = []
        
        try:
            # Combine chunks into full text
            full_text = "\n\n".join([
                getattr(c, 'chunk_text', str(c)) for c in chunks
            ])
            
            # Extract entities and relations
            extraction = await self.extractor.extract(
                document_text=full_text,
                metadata={
                    'document_id': document.document_id,
                    'source_id': getattr(document, 'source_id', 'unknown'),
                    'title': getattr(document, 'title', None),
                }
            )
            
            # Merge with document metadata
            entities = self._enrich_with_document_metadata(
                extraction['entities'], 
                document
            )
            relations = extraction['relations']
            
            # Update graph
            async with self.driver.session() as session:
                result = await session.execute_write(
                    self._merge_document_subgraph,
                    document_id=document.document_id,
                    pg_id=str(getattr(document, 'id', document.document_id)),
                    entities=entities,
                    relations=relations,
                    doc_metadata={
                        'title': getattr(document, 'title', None),
                        'source_id': getattr(document, 'source_id', 'unknown'),
                        'ingested_at': getattr(document, 'ingested_at', datetime.now()).isoformat(),
                    }
                )
            
            duration = (datetime.now() - start_time).total_seconds() * 1000
            
            return GraphUpdateResult(
                document_id=document.document_id,
                nodes_created=result.get('nodes_created', 0),
                nodes_updated=result.get('nodes_updated', 0),
                relationships_created=result.get('relationships_created', 0),
                relationships_updated=result.get('relationships_updated', 0),
                errors=errors,
                duration_ms=duration
            )
            
        except Exception as e:
            logger.exception(f"Failed to process document {document.document_id}")
            duration = (datetime.now() - start_time).total_seconds() * 1000
            return GraphUpdateResult(
                document_id=document.document_id,
                errors=[str(e)],
                duration_ms=duration
            )
    
    def _enrich_with_document_metadata(
        self, 
        entities: List[Dict[str, Any]],
        document: Any
    ) -> List[Dict[str, Any]]:
        """Enrich extracted entities with document metadata."""
        # Add document as entity if not present
        doc_entity = {
            'id': document.document_id,
            'type': 'Document',
            'name': getattr(document, 'title', None) or document.document_id,
            'properties': {
                'pg_id': str(getattr(document, 'id', document.document_id)),
                'source_id': getattr(document, 'source_id', 'unknown'),
                'fingerprint': getattr(document, 'fingerprint', None),
            },
            'confidence': 1.0
        }
        
        # Add metadata entities
        metadata_entities = []
        doc_metadata = getattr(document, 'doc_metadata', None) or {}
        
        if doc_metadata:
            # Add relator as entity
            if relator := doc_metadata.get('relator'):
                metadata_entities.append({
                    'id': self._normalize_minister_name(relator),
                    'type': 'Ministro',
                    'name': relator,
                    'properties': {},
                    'confidence': 1.0
                })
            
            # Add processo
            if processo := doc_metadata.get('processo'):
                metadata_entities.append({
                    'id': str(processo).replace('/', '-'),
                    'type': 'Processo',
                    'name': f"Processo {processo}",
                    'properties': {'numero': processo},
                    'confidence': 1.0
                })
        
        return [doc_entity] + entities + metadata_entities
    
    def _normalize_minister_name(self, name: str) -> str:
        """Normalize minister name to ID."""
        # Extract last name and first initial
        parts = name.strip().upper().split()
        if len(parts) >= 2:
            return f"{parts[-1]}_{parts[0][0]}"
        return name.upper().replace(' ', '_')
    
    @staticmethod
    async def _merge_document_subgraph(
        tx,
        document_id: str,
        pg_id: str,
        entities: List[Dict[str, Any]],
        relations: List[Dict[str, Any]],
        doc_metadata: Dict[str, Any]
    ) -> Dict[str, int]:
        """Cypher transaction to merge document subgraph."""
        
        stats = {
            'nodes_created': 0,
            'nodes_updated': 0,
            'relationships_created': 0,
            'relationships_updated': 0
        }
        
        # Merge Document node
        await tx.run("""
            MERGE (d:Document {document_id: $doc_id})
            ON CREATE SET 
                d.pg_id = $pg_id,
                d.title = $title,
                d.source_id = $source_id,
                d.created_at = datetime(),
                d.updated_at = datetime()
            ON MATCH SET
                d.title = $title,
                d.source_id = $source_id,
                d.updated_at = datetime()
            RETURN d
        """, {
            'doc_id': document_id,
            'pg_id': pg_id,
            'title': doc_metadata.get('title'),
            'source_id': doc_metadata.get('source_id'),
        })
        
        stats['nodes_created'] += 1
        
        # Merge other entities
        for entity in entities:
            if entity['type'] == 'Document':
                continue  # Already merged
            
            # Use dynamic labels via APOC or parameterized query
            label = entity['type']
            result = await tx.run(f"""
                MERGE (e:{label} {{id: $id}})
                ON CREATE SET 
                    e.name = $name,
                    e.properties = $props,
                    e.created_at = datetime()
                ON MATCH SET
                    e.name = $name,
                    e.properties = COALESCE(e.properties, {{}}) + $props,
                    e.updated_at = datetime()
                RETURN e
            """, {
                'id': entity['id'],
                'name': entity['name'],
                'props': entity.get('properties', {})
            })
            
            # Check if created or merged
            summary = await result.consume()
            if summary.counters.nodes_created > 0:
                stats['nodes_created'] += 1
            else:
                stats['nodes_updated'] += 1
        
        # Merge relationships
        for rel in relations:
            rel_type = rel['relation_type'].upper()
            
            result = await tx.run(f"""
                MATCH (a {{id: $source_id}})
                MATCH (b {{id: $target_id}})
                MERGE (a)-[r:{rel_type}]->(b)
                ON CREATE SET
                    r.properties = $props,
                    r.source_text = $source_text,
                    r.created_at = datetime()
                ON MATCH SET
                    r.properties = COALESCE(r.properties, {{}}) + $props,
                    r.source_text = $source_text,
                    r.updated_at = datetime()
                RETURN r
            """, {
                'source_id': rel['source_id'],
                'target_id': rel['target_id'],
                'props': rel.get('properties', {}),
                'source_text': rel.get('source_text', '')
            })
            
            summary = await result.consume()
            if summary.counters.relationships_created > 0:
                stats['relationships_created'] += 1
            else:
                stats['relationships_updated'] += 1
        
        return stats
    
    async def delete_document(self, document_id: str) -> bool:
        """Remove a document and its relationships from the graph.
        
        Called when document is soft-deleted or hard-deleted.
        
        Args:
            document_id: Document ID to remove
            
        Returns:
            True if document was removed
        """
        async with self.driver.session() as session:
            result = await session.run("""
                MATCH (d:Document {document_id: $doc_id})
                OPTIONAL MATCH (d)-[r]-()
                DELETE r, d
                RETURN count(r) as rels_deleted, count(d) as docs_deleted
            """, {'doc_id': document_id})
            
            record = await result.single()
            return record['docs_deleted'] > 0 if record else False
    
    async def close(self):
        """Close Neo4j driver connection."""
        if hasattr(self, 'driver'):
            await self.driver.close()
    
    async def initialize_schema(self) -> None:
        """Initialize Neo4j schema (indexes and constraints)."""
        async with self.driver.session() as session:
            # Create constraints
            constraints = [
                ("Document", "document_id"),
                ("Ministro", "id"),
                ("Processo", "id"),
                ("Sumula", "id"),
                ("Normativo", "id"),
            ]
            
            for label, property_name in constraints:
                try:
                    await session.run(f"""
                        CREATE CONSTRAINT {label.lower()}_{property_name} 
                        IF NOT EXISTS
                        FOR (n:{label}) REQUIRE n.{property_name} IS UNIQUE
                    """)
                except Exception as e:
                    logger.warning(f"Failed to create constraint for {label}: {e}")
            
            # Create indexes
            indexes = [
                ("Document", "pg_id"),
                ("Document", "source_id"),
            ]
            
            for label, property_name in indexes:
                try:
                    await session.run(f"""
                        CREATE INDEX {label.lower()}_{property_name}_idx 
                        IF NOT EXISTS
                        FOR (n:{label}) ON (n.{property_name})
                    """)
                except Exception as e:
                    logger.warning(f"Failed to create index for {label}.{property_name}: {e}")
