"""GraphRAG Search Service.

This module provides graph-aware search capabilities that enhance
traditional search with relationship information from the knowledge graph.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from datetime import datetime
import logging

try:
    from neo4j import AsyncGraphDatabase
    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False

if TYPE_CHECKING:
    from gabi.services.search_service import SearchService

logger = logging.getLogger(__name__)


@dataclass
class GraphSearchResult:
    """Result from graph-aware search."""
    document_id: str
    title: str
    score: float
    graph_score: float
    citation_chain: List[Dict[str, Any]] = field(default_factory=list)
    related_documents: List[Dict[str, Any]] = field(default_factory=list)
    conflicting_precedents: List[Dict[str, Any]] = field(default_factory=list)
    normative_chain: Optional[Dict[str, Any]] = None


class GraphRAGSearchService:
    """Graph-aware search service for legal documents."""
    
    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        base_search_service: "SearchService",
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
        self.base_search = base_search_service
    
    async def search(
        self,
        query: str,
        limit: int = 10,
        graph_depth: int = 2,
        include_citations: bool = True,
        include_conflicts: bool = True,
        include_normative_chain: bool = False,
    ) -> Dict[str, Any]:
        """Execute graph-aware search.
        
        Args:
            query: Search query
            limit: Max results to return
            graph_depth: How many hops to traverse
            include_citations: Include citation network
            include_conflicts: Include conflicting precedents
            include_normative_chain: Include normative relationships
            
        Returns:
            Dictionary with enriched search results
        """
        # Phase 1: Base semantic search
        base_results = await self.base_search.search_api(query, limit=limit * 2)
        
        # Phase 2: Enhance with graph context
        enriched_results = []
        
        for hit in base_results.hits[:limit * 2]:
            try:
                graph_context = await self._get_graph_context(
                    document_id=hit.document_id,
                    depth=graph_depth,
                    include_citations=include_citations,
                    include_conflicts=include_conflicts,
                    include_normative_chain=include_normative_chain,
                )
                
                # Calculate graph-boosted score
                graph_score = self._calculate_graph_score(hit, graph_context)
                
                enriched_results.append(GraphSearchResult(
                    document_id=hit.document_id,
                    title=hit.title or "",
                    score=hit.score,
                    graph_score=graph_score,
                    citation_chain=graph_context.get('citations', []),
                    related_documents=graph_context.get('related', []),
                    conflicting_precedents=graph_context.get('conflicts', []),
                    normative_chain=graph_context.get('normative_chain'),
                ))
            except Exception as e:
                logger.warning(f"Failed to get graph context for {hit.document_id}: {e}")
                # Fall back to base result
                enriched_results.append(GraphSearchResult(
                    document_id=hit.document_id,
                    title=hit.title or "",
                    score=hit.score,
                    graph_score=hit.score,
                ))
        
        # Re-rank by combined score
        enriched_results.sort(key=lambda x: x.graph_score, reverse=True)
        
        return {
            'query': query,
            'total': len(enriched_results),
            'hits': enriched_results[:limit],
        }
    
    async def _get_graph_context(
        self,
        document_id: str,
        depth: int,
        include_citations: bool,
        include_conflicts: bool,
        include_normative_chain: bool,
    ) -> Dict[str, Any]:
        """Get graph context for a document."""
        context = {}
        
        async with self.driver.session() as session:
            # Citations (both directions)
            if include_citations:
                try:
                    citations_result = await session.run("""
                        MATCH (d:Document {document_id: $doc_id})
                        OPTIONAL MATCH (d)-[r:CITA]->(cited:Document)
                        OPTIONAL MATCH (citing:Document)-[r2:CITA]->(d)
                        RETURN {
                            cited: collect(DISTINCT {
                                doc_id: cited.document_id,
                                title: cited.title,
                                context: r.context,
                                confidence: r.confidence
                            })[0..10],
                            cited_by: collect(DISTINCT {
                                doc_id: citing.document_id,
                                title: citing.title,
                                context: r2.context,
                                confidence: r2.confidence
                            })[0..10]
                        } as citations
                    """, {'doc_id': document_id})
                    
                    record = await citations_result.single()
                    context['citations'] = record['citations'] if record else {}
                except Exception as e:
                    logger.debug(f"Citation query failed: {e}")
                    context['citations'] = {}
            
            # Conflicting precedents
            if include_conflicts:
                try:
                    conflicts_result = await session.run("""
                        MATCH (d:Document {document_id: $doc_id})
                        OPTIONAL MATCH (d)-[:DIVERGE]->(conflict:Document)
                        OPTIONAL MATCH (divergent:Document)-[:DIVERGE]->(d)
                        RETURN collect(DISTINCT {
                            doc_id: coalesce(conflict.document_id, divergent.document_id),
                            title: coalesce(conflict.title, divergent.title),
                            direction: CASE WHEN conflict IS NOT NULL THEN 'outgoing' ELSE 'incoming' END
                        })[0..5] as conflicts
                    """, {'doc_id': document_id})
                    
                    record = await conflicts_result.single()
                    context['conflicts'] = record['conflicts'] if record else []
                except Exception as e:
                    logger.debug(f"Conflicts query failed: {e}")
                    context['conflicts'] = []
            
            # Normative chain
            if include_normative_chain:
                try:
                    normative_result = await session.run("""
                        MATCH (d:Document {document_id: $doc_id})
                        OPTIONAL MATCH chain = (d)-[:REVOGA|MODIFICA*1..5]->(target)
                        WITH d, chain, target
                        ORDER BY length(chain) DESC
                        LIMIT 1
                        RETURN {
                            chain: [node in nodes(chain) | node.document_id],
                            relationships: [rel in relationships(chain) | type(rel)]
                        } as normative_chain
                    """, {'doc_id': document_id})
                    
                    record = await normative_result.single()
                    context['normative_chain'] = record['normative_chain'] if record else None
                except Exception as e:
                    logger.debug(f"Normative chain query failed: {e}")
                    context['normative_chain'] = None
            
            # Related documents (semantic + graph proximity)
            try:
                related_result = await session.run("""
                    MATCH (d:Document {document_id: $doc_id})
                    MATCH (d)-[:CITA|FUNDAMENTA|TRATA_DE*1..2]-(related:Document)
                    WHERE related.document_id <> d.document_id
                    WITH related, count(*) as connection_strength
                    ORDER BY connection_strength DESC
                    LIMIT 5
                    RETURN collect({
                        doc_id: related.document_id,
                        title: related.title,
                        strength: connection_strength
                    }) as related
                """, {'doc_id': document_id})
                
                record = await related_result.single()
                context['related'] = record['related'] if record else []
            except Exception as e:
                logger.debug(f"Related documents query failed: {e}")
                context['related'] = []
        
        return context
    
    def _calculate_graph_score(
        self, 
        base_hit: Any, 
        graph_context: Dict[str, Any]
    ) -> float:
        """Calculate graph-boosted relevance score."""
        base_score = getattr(base_hit, 'score', 0.0)
        
        # Boost factors
        citation_boost = 0.0
        authority_boost = 0.0
        
        # Boost by citation count
        citations = graph_context.get('citations', {})
        cited_by_count = len(citations.get('cited_by', []))
        citation_boost = min(cited_by_count * 0.05, 0.5)  # Max 0.5 boost
        
        # Boost by authority (documents cited by high-authority documents)
        for citing in citations.get('cited_by', [])[:10]:
            authority_boost += 0.02
        authority_boost = min(authority_boost, 0.3)
        
        # Penalize documents with many conflicts
        conflicts = graph_context.get('conflicts', [])
        conflict_penalty = len(conflicts) * 0.05
        
        return base_score + citation_boost + authority_boost - conflict_penalty
    
    async def find_precedent_chain(
        self,
        document_id: str,
        direction: str = 'both',
        max_depth: int = 5
    ) -> List[Dict[str, Any]]:
        """Find chain of precedents related to a document.
        
        Args:
            document_id: Starting document
            direction: Search direction ('forward', 'backward', 'both')
            max_depth: Maximum traversal depth
            
        Returns:
            List of precedent chains
        """
        async with self.driver.session() as session:
            if direction == 'backward':
                # Documents this one cites
                result = await session.run(f"""
                    MATCH path = (d:Document {{document_id: $doc_id}})
                              -[:CITA|FUNDAMENTA*1..{max_depth}]->(prec:Document)
                    RETURN [node in nodes(path) | {{
                        doc_id: node.document_id,
                        title: node.title
                    }}] as chain
                    ORDER BY length(path) ASC
                    LIMIT 10
                """, {'doc_id': document_id})
            
            elif direction == 'forward':
                # Documents citing this one
                result = await session.run(f"""
                    MATCH path = (prec:Document)
                              -[:CITA|FUNDAMENTA*1..{max_depth}]->
                              (d:Document {{document_id: $doc_id}})
                    RETURN [node in nodes(path) | {{
                        doc_id: node.document_id,
                        title: node.title
                    }}] as chain
                    ORDER BY length(path) ASC
                    LIMIT 10
                """, {'doc_id': document_id})
            
            else:  # both
                result = await session.run(f"""
                    MATCH path = (a:Document)-[:CITA|FUNDAMENTA*1..{max_depth}]-(b:Document)
                    WHERE a.document_id = $doc_id OR b.document_id = $doc_id
                    RETURN [node in nodes(path) | {{
                        doc_id: node.document_id,
                        title: node.title
                    }}] as chain
                    ORDER BY length(path) ASC
                    LIMIT 10
                """, {'doc_id': document_id})
            
            chains = []
            async for record in result:
                chains.append(record['chain'])
            
            return chains
    
    async def find_normative_evolution(
        self,
        normative_id: str
    ) -> Dict[str, Any]:
        """Trace the evolution of a normative document."""
        async with self.driver.session() as session:
            # Find what this normative revokes/modifies
            result = await session.run("""
                MATCH (n:Normativo {numero: $norm_id})
                OPTIONAL MATCH (n)-[:REVOGA]->(revoked:Normativo)
                OPTIONAL MATCH (n)-[:MODIFICA]->(modified:Normativo)
                OPTIONAL MATCH (revoked_by:Normativo)-[:REVOGA]->(n)
                OPTIONAL MATCH (modified_by:Normativo)-[:MODIFICA]->(n)
                RETURN {
                    revokes: collect(DISTINCT revoked.numero),
                    modifies: collect(DISTINCT modified.numero),
                    revoked_by: collect(DISTINCT revoked_by.numero),
                    modified_by: collect(DISTINCT modified_by.numero),
                    current_status: CASE 
                        WHEN size(collect(revoked_by)) > 0 THEN 'revoked'
                        WHEN size(collect(modified_by)) > 0 THEN 'modified'
                        ELSE 'active'
                    END
                } as evolution
            """, {'norm_id': normative_id})
            
            record = await result.single()
            return record['evolution'] if record else {}
    
    async def get_citations(
        self,
        document_id: str,
        direction: str = 'both'
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get citations for a document.
        
        Args:
            document_id: Document ID
            direction: 'incoming', 'outgoing', or 'both'
            
        Returns:
            Dictionary with citation information
        """
        async with self.driver.session() as session:
            if direction == 'outgoing':
                result = await session.run("""
                    MATCH (d:Document {document_id: $doc_id})-[r:CITA]->(cited:Document)
                    RETURN collect({
                        doc_id: cited.document_id,
                        title: cited.title,
                        context: r.properties.context,
                        confidence: r.properties.confidence
                    }) as citations
                """, {'doc_id': document_id})
                record = await result.single()
                return {'outgoing': record['citations'] if record else []}
            
            elif direction == 'incoming':
                result = await session.run("""
                    MATCH (citing:Document)-[r:CITA]->(d:Document {document_id: $doc_id})
                    RETURN collect({
                        doc_id: citing.document_id,
                        title: citing.title,
                        context: r.properties.context,
                        confidence: r.properties.confidence
                    }) as citations
                """, {'doc_id': document_id})
                record = await result.single()
                return {'incoming': record['citations'] if record else []}
            
            else:  # both
                result = await session.run("""
                    MATCH (d:Document {document_id: $doc_id})
                    OPTIONAL MATCH (d)-[r1:CITA]->(cited:Document)
                    OPTIONAL MATCH (citing:Document)-[r2:CITA]->(d)
                    RETURN {
                        outgoing: collect(DISTINCT {
                            doc_id: cited.document_id,
                            title: cited.title
                        }),
                        incoming: collect(DISTINCT {
                            doc_id: citing.document_id,
                            title: citing.title
                        })
                    } as citations
                """, {'doc_id': document_id})
                record = await result.single()
                return record['citations'] if record else {'outgoing': [], 'incoming': []}
    
    async def close(self):
        """Close Neo4j driver connection."""
        if hasattr(self, 'driver'):
            await self.driver.close()
