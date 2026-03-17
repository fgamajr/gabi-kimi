"""Async reranker client — calls the host-native reranker server.

Extracts identifica + ementa from ES hits, sends to reranker, maps scores
back to original hits. Falls back to original order on any error.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.backend.core.config import settings

logger = logging.getLogger(__name__)


async def rerank(
    query: str,
    hits: list[dict[str, Any]],
    top_k: int | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Rerank ES hits via the external reranker server.

    Returns reranked hits on success, or the original hits unchanged on error.
    """
    if not hits:
        return hits

    top_k = top_k or settings.RERANKER_TOP_K

    # Build document texts from identifica + ementa (concise, not body)
    documents: list[str] = []
    for hit in hits:
        src = hit.get("_source", {})
        parts = []
        if src.get("identifica"):
            parts.append(src["identifica"])
        if src.get("ementa"):
            parts.append(src["ementa"])
        documents.append(" ".join(parts) if parts else hit.get("_id", ""))

    try:
        http = client or httpx.AsyncClient()
        try:
            resp = await http.post(
                f"{settings.RERANKER_URL}/v1/rerank",
                json={
                    "query": query,
                    "documents": documents,
                    "top_n": top_k,
                },
                timeout=settings.RERANKER_TIMEOUT,
            )
            resp.raise_for_status()
        finally:
            if client is None:
                await http.aclose()

        data = resp.json()
        results = data.get("results", [])

        # Map reranker scores back to original hits
        reranked: list[dict[str, Any]] = []
        for r in results:
            idx = r["index"]
            if 0 <= idx < len(hits):
                hit = hits[idx].copy()
                hit["_rerank_score"] = r["relevance_score"]
                reranked.append(hit)

        logger.info(
            "rerank ok: %d → %d hits, elapsed=%sms",
            len(hits),
            len(reranked),
            data.get("elapsed_ms", "?"),
        )
        return reranked

    except Exception:
        logger.warning("reranker fallback: returning original hits", exc_info=True)
        return hits
