"""API endpoints for GraphRAG functionality.

This module provides FastAPI endpoints for graph-aware search and exploration.
"""

from typing import Optional, List, Any
from fastapi import APIRouter, Depends, Query, HTTPException

from gabi.graphrag.search import GraphRAGSearchService
from gabi.schemas.search import SearchRequest

router = APIRouter(prefix="/graph", tags=["graph"])


# Dependency to get graph search service
def get_graph_search_service() -> GraphRAGSearchService:
    """Get GraphRAG search service instance.
    
    This should be replaced with actual dependency injection
    based on the application's dependency setup.
    """
    from gabi.config import settings
    from gabi.services.search_service import SearchService
    
    # This is a placeholder - actual implementation should use
    # properly configured clients
    raise NotImplementedError(
        "Graph search service dependency not configured. "
        "Implement get_graph_search_service in dependencies."
    )


@router.post("/search")
async def search_graph(
    request: SearchRequest,
    graph_depth: int = Query(2, ge=1, le=5, description="Graph traversal depth"),
    include_citations: bool = Query(True, description="Include citation network"),
    include_conflicts: bool = Query(True, description="Include conflicting precedents"),
    include_normative_chain: bool = Query(False, description="Include normative chain"),
    graph_service: GraphRAGSearchService = Depends(get_graph_search_service),
):
    """Execute graph-aware search.
    
    Returns documents enhanced with:
    - Citation chains (documents cited by and citing each result)
    - Related documents (found through graph proximity)
    - Conflicting precedents (documents that diverge)
    - Normative chains (for normative documents)
    
    Example:
        ```json
        {
            "query": "licitação direta",
            "sources": ["tcu_acordaos"],
            "limit": 10
        }
        ```
    """
    try:
        return await graph_service.search(
            query=request.query,
            limit=request.limit,
            graph_depth=graph_depth,
            include_citations=include_citations,
            include_conflicts=include_conflicts,
            include_normative_chain=include_normative_chain,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/{doc_id}/citations")
async def get_document_citations(
    doc_id: str,
    direction: str = Query("both", enum=["incoming", "outgoing", "both"]),
    graph_service: GraphRAGSearchService = Depends(get_graph_search_service),
):
    """Get citation network for a document.
    
    Args:
        doc_id: Document ID
        direction: Filter by citation direction
        
    Returns:
        Citation information for the document
    """
    try:
        citations = await graph_service.get_citations(doc_id, direction)
        return {"document_id": doc_id, "citations": citations}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/{doc_id}/precedent-chain")
async def get_precedent_chain(
    doc_id: str,
    direction: str = Query("both", enum=["forward", "backward", "both"]),
    max_depth: int = Query(5, ge=1, le=10),
    graph_service: GraphRAGSearchService = Depends(get_graph_search_service),
):
    """Get precedent chain for a document.
    
    Traces the chain of precedents related to a document through
    citation and fundamentação relationships.
    
    Args:
        doc_id: Document ID
        direction: Search direction
            - forward: Documents citing this document
            - backward: Documents cited by this document
            - both: Both directions
        max_depth: Maximum traversal depth
        
    Returns:
        Precedent chains
    """
    try:
        chain = await graph_service.find_precedent_chain(
            doc_id, 
            direction=direction,
            max_depth=max_depth
        )
        return {
            "document_id": doc_id,
            "direction": direction,
            "chains": chain
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/normativos/{norm_id}/evolution")
async def get_normative_evolution(
    norm_id: str,
    graph_service: GraphRAGSearchService = Depends(get_graph_search_service),
):
    """Trace the evolution of a normative document.
    
    Shows:
    - Documents this normative revokes
    - Documents this normative modifies
    - Documents that revoke this normative
    - Documents that modify this normative
    
    Args:
        norm_id: Normative document ID (e.g., "IN-0075-2022")
        
    Returns:
        Evolution information
    """
    try:
        evolution = await graph_service.find_normative_evolution(norm_id)
        return {"normative_id": norm_id, "evolution": evolution}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ministros/{ministro_id}/jurisprudence")
async def get_minister_jurisprudence(
    ministro_id: str,
    limit: int = Query(20, ge=1, le=100),
    # graph_service: GraphRAGSearchService = Depends(get_graph_search_service),
):
    """Get jurisprudence by minister.
    
    Args:
        ministro_id: Minister ID (normalized name)
        limit: Maximum number of results
        
    Returns:
        Documents related to the minister
    """
    # This would require extending the search service
    # with minister-specific queries
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/explore/related")
async def explore_related(
    doc_id: str,
    depth: int = Query(2, ge=1, le=4),
    limit: int = Query(10, ge=1, le=50),
    graph_service: GraphRAGSearchService = Depends(get_graph_search_service),
):
    """Explore documents related to a given document.
    
    Finds documents that are graph-proximate to the given document
    through citation, fundamentação, or thematic relationships.
    
    Args:
        doc_id: Starting document ID
        depth: Graph traversal depth
        limit: Maximum number of related documents
        
    Returns:
        Related documents with connection strength
    """
    try:
        context = await graph_service._get_graph_context(
            document_id=doc_id,
            depth=depth,
            include_citations=True,
            include_conflicts=True,
            include_normative_chain=False,
        )
        
        related = context.get('related', [])[:limit]
        return {
            "document_id": doc_id,
            "related_documents": related
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def graph_health():
    """Check graph database health."""
    try:
        from gabi.config import settings
        from neo4j import AsyncGraphDatabase
        
        driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password.get_secret_value())
        )
        
        async with driver.session() as session:
            result = await session.run("RETURN 1 as test")
            record = await result.single()
            await driver.close()
            
            if record and record['test'] == 1:
                return {"status": "healthy"}
            else:
                return {"status": "unhealthy", "error": "Unexpected response"}
                
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
