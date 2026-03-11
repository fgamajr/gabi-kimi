from typing import List, Optional
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field
from src.backend.data.db import MongoDB

# Initialize FastMCP server
mcp = FastMCP("GABI DOU Search")

class SearchResult(BaseModel):
    title: str
    content: str
    score: float
    date: Optional[str] = None
    url: Optional[str] = None

@mcp.tool()
async def search_dou(query: str, limit: int = 5) -> List[SearchResult]:
    """
    Search the Diário Oficial da União (DOU) database using hybrid search (BM25 + Vector).
    
    Args:
        query: The search query string.
        limit: Maximum number of results to return (default: 5).
    """
    db = MongoDB.get_db()
    collection = db["documents"]  # Assuming 'documents' is the collection name

    # MongoDB Atlas Search Aggregation
    pipeline = [
        {
            "$search": {
                "index": "default",  # Ensure this index exists in Atlas
                "text": {
                    "query": query,
                    "path": {"wildcard": "*"}  # Search across all indexed fields
                }
            }
        },
        {
            "$limit": limit
        },
        {
            "$project": {
                "_id": 0,
                "title": 1,
                "content": 1,
                "date": 1,
                "url": 1,
                "score": {"$meta": "searchScore"}
            }
        }
    ]

    try:
        cursor = collection.aggregate(pipeline)
        results = []
        for doc in cursor:
            results.append(SearchResult(
                title=doc.get("title", "No Title"),
                content=doc.get("content", "")[:500] + "...",  # Truncate content for brevity
                score=doc.get("score", 0.0),
                date=doc.get("date"),
                url=doc.get("url")
            ))
        return results
    except Exception as e:
        return [SearchResult(title="Error", content=str(e), score=0.0)]

if __name__ == "__main__":
    mcp.run()
