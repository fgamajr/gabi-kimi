#!/usr/bin/env python3
"""MCP server exposing the local repo index for codebase search."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from repo root without installing
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp.server.fastmcp import FastMCP

from src.backend.repo_index.config import settings
from src.backend.repo_index.retrieval.service import RetrievalService
from src.backend.repo_index.storage.db import get_connection

mcp = FastMCP("gabi-repo")


@mcp.tool()
def repo_query(
    query: str,
    top_k: int = 8,
    mode: str = "auto",
) -> str:
    """Search the indexed codebase.

    Args:
        query: Natural-language or keyword query (e.g. "reranker pipeline", "hybrid_search function").
        top_k: Number of results to return (default 8, max 20).
        mode: "lexical" | "semantic" | "hybrid" (default hybrid; falls back to lexical when no embeddings).

    Returns a JSON array of matching code chunks with path, lines, and content.
    """
    import json

    top_k = min(max(1, top_k), 20)
    svc = RetrievalService()
    hits, meta = svc.search(
        query,
        top_k=top_k,
        mode=mode if mode in {"lexical", "semantic", "hybrid"} else "hybrid",
    )
    results = [
        {
            "rank": i + 1,
            "path": h.path,
            "lines": f"{h.start_line}-{h.end_line}",
            "symbol": h.symbol,
            "score": h.score,
            "content": h.content[:1200],
        }
        for i, h in enumerate(hits)
    ]
    return json.dumps(results, ensure_ascii=False, indent=2)


@mcp.tool()
def repo_stats() -> str:
    """Return health and statistics of the local repo index."""
    import json

    db_path = settings.db_path
    if not db_path.exists():
        return json.dumps({"status": "missing", "db_path": str(db_path)})

    conn = get_connection()
    try:
        total_docs = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        total_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        top_paths = conn.execute(
            "SELECT path, COUNT(*) AS n FROM chunks GROUP BY path ORDER BY n DESC LIMIT 5"
        ).fetchall()
    finally:
        conn.close()

    return json.dumps(
        {
            "status": "ok",
            "db_path": str(db_path),
            "documents": total_docs,
            "chunks": total_chunks,
            "top_indexed_files": [{"path": r[0], "chunks": r[1]} for r in top_paths],
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def repo_file(path: str, max_chars: int = 8000) -> str:
    """Retrieve the indexed content of a specific file from the repo index.

    Args:
        path: Relative path from repo root (e.g. "src/backend/search/hybrid.py").
        max_chars: Maximum characters to return (default 8000).
    """
    import json

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT start_line, end_line, text FROM chunks WHERE path = ? ORDER BY start_line",
            (path,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return json.dumps({"error": f"No indexed chunks for path: {path}"})

    assembled = "\n".join(r[2] for r in rows)
    truncated = len(assembled) > max_chars
    return json.dumps(
        {
            "path": path,
            "chunks": len(rows),
            "lines": f"{rows[0][0]}-{rows[-1][1]}",
            "content": assembled[:max_chars],
            "truncated": truncated,
        },
        ensure_ascii=False,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="gabi-repo MCP server")
    parser.add_argument("--transport", default="stdio", choices=["stdio"])
    parser.parse_args()
    mcp.run(transport="stdio")
