"""Async reranker client — calls the configured reranker provider.

Extracts identifica + ementa from ES hits, sends to reranker, maps scores
back to original hits. Falls back to original order on any error.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.backend.core.config import settings

logger = logging.getLogger(__name__)


def _reranker_provider() -> str:
    return settings.RERANKER_PROVIDER.strip().lower() or "http"


def _rerank_endpoint() -> str:
    base = settings.RERANKER_URL.rstrip("/")
    if base.endswith("/v1/rerank"):
        return base
    return f"{base}/v1/rerank"


def _build_rerank_text(hit: dict[str, Any]) -> str:
    src = hit.get("_source", {})
    parts: list[str] = []
    for field in ("identifica", "titulo", "assunto"):
        if src.get(field):
            parts.append(str(src[field]))
    for field in ("ementa", "sumario", "dispositivo_resumo"):
        if src.get(field):
            parts.append(str(src[field]))
    if not parts:
        for field in (
            "rerank_text",
            "text",
            "body_plain",
            "acordao_texto",
            "texto_norma",
            "search_all",
        ):
            if src.get(field):
                parts.append(str(src[field]))
                break

    text = " ".join(parts) if parts else str(hit.get("_id", ""))
    return " ".join(text.split())[: settings.RERANKER_MAX_DOC_CHARS]


async def _post_rerank_request(
    *,
    query: str,
    documents: list[str],
    top_k: int,
    client: httpx.AsyncClient | None,
) -> dict[str, Any]:
    provider = _reranker_provider()
    http = client or httpx.AsyncClient()

    try:
        if provider == "cohere":
            api_key = settings.COHERE_API_KEY.strip()
            if not api_key:
                raise RuntimeError("COHERE_API_KEY not configured")

            resp = await http.post(
                settings.RERANKER_COHERE_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "content-type": "application/json",
                    "X-Client-Name": "gabi-kimi",
                },
                json={
                    "model": settings.RERANKER_COHERE_MODEL,
                    "query": query,
                    "documents": documents,
                    "top_n": top_k,
                },
                timeout=settings.RERANKER_TIMEOUT,
            )
        else:
            resp = await http.post(
                _rerank_endpoint(),
                json={
                    "query": query,
                    "documents": documents,
                    "top_n": top_k,
                },
                timeout=settings.RERANKER_TIMEOUT,
            )
        resp.raise_for_status()
        return resp.json()
    finally:
        if client is None:
            await http.aclose()


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

    deduped_hits: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for hit in hits:
        hit_id = str(hit.get("_id") or hit.get("_source", {}).get("doc_id") or "")
        if hit_id and hit_id in seen_ids:
            continue
        if hit_id:
            seen_ids.add(hit_id)
        deduped_hits.append(hit)

    limited_hits = deduped_hits[: settings.RERANKER_MAX_DOCS]
    top_k = min(top_k or settings.RERANKER_TOP_K, len(limited_hits))
    documents = [_build_rerank_text(hit) for hit in limited_hits]

    try:
        data = await _post_rerank_request(
            query=query,
            documents=documents,
            top_k=top_k,
            client=client,
        )
        results = data.get("results", [])

        # Map reranker scores back to original hits
        reranked: list[dict[str, Any]] = []
        used_indexes: set[int] = set()
        for r in results:
            idx = r["index"]
            if 0 <= idx < len(limited_hits):
                used_indexes.add(idx)
                hit = limited_hits[idx].copy()
                hit["_rerank_score"] = r["relevance_score"]
                reranked.append(hit)

        for idx, hit in enumerate(limited_hits):
            if idx not in used_indexes:
                reranked.append(hit)

        reranked.extend(deduped_hits[len(limited_hits) :])

        logger.info(
            "rerank ok provider=%s: %d → %d hits, elapsed=%sms",
            _reranker_provider(),
            len(limited_hits),
            len(reranked),
            data.get("elapsed_ms", "?"),
        )
        return reranked

    except Exception:
        logger.warning("reranker fallback: returning original hits", exc_info=True)
        return hits
