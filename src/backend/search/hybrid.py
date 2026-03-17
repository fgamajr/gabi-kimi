"""Hybrid search — BM25 + kNN via Elasticsearch RRF (Reciprocal Rank Fusion).

Builds and executes a combined retriever query. Falls back to BM25-only
if the embedding server is unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.backend.core.config import settings

logger = logging.getLogger(__name__)


async def _get_query_embedding(
    query: str, client: httpx.AsyncClient
) -> list[float] | None:
    """Get query embedding from the host embedding server. Returns None on failure."""
    try:
        resp = await client.post(
            f"{settings.EMBED_SERVER_URL}/embed",
            json={"texts": [query], "dimensions": 384},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings = data.get("embeddings", [])
        if embeddings:
            return embeddings[0]
    except Exception:
        logger.warning("embed server unavailable, falling back to BM25-only", exc_info=True)
    return None


def build_bm25_query(
    q: str,
    filters: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the BM25 query with field boosts, phrase matching, and date decay."""
    text_query: dict[str, Any] = {
        "simple_query_string": {
            "query": q,
            "fields": [
                "identifica^5",
                "ementa^4",
                "issuing_organ^2",
                "art_type^2",
                "art_category",
                "body_plain",
            ],
            "default_operator": "and",
            "fuzzy_max_expansions": 20,
        },
    }
    should: list[dict] = [
        {"match_phrase": {"identifica": {"query": q, "boost": 20}}},
        {"match_phrase": {"ementa": {"query": q, "boost": 15}}},
        {"match_phrase": {"body_plain": {"query": q, "boost": 5}}},
    ]

    bool_query: dict[str, Any] = {
        "bool": {
            "must": [text_query],
            "should": should,
        }
    }
    if filters:
        bool_query["bool"]["filter"] = filters

    return {
        "function_score": {
            "query": bool_query,
            "functions": [{
                "gauss": {
                    "pub_date": {
                        "origin": "now",
                        "scale": "365d",
                        "offset": "30d",
                        "decay": 0.5,
                    },
                },
            }],
            "boost_mode": "multiply",
        },
    }


async def hybrid_search(
    query: str,
    filters: list[dict[str, Any]],
    size: int,
    source_fields: list[str],
    highlight_spec: dict[str, Any],
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    """Execute hybrid BM25 + kNN search via ES RRF.

    Falls back to BM25-only if the embedding server is unreachable.
    """
    bm25_query = build_bm25_query(query, filters)
    query_vector = await _get_query_embedding(query, client)

    es_url = f"{settings.ES_URL}/{settings.es_target_index}/_search"

    if query_vector is not None:
        # Hybrid: use ES Retriever API with RRF
        # Build kNN filter from the same filters used for BM25
        knn_filter = filters if filters else None

        payload: dict[str, Any] = {
            "retriever": {
                "rrf": {
                    "retrievers": [
                        {
                            "standard": {
                                "query": bm25_query,
                            }
                        },
                        {
                            "knn": {
                                "field": "embedding",
                                "query_vector": query_vector,
                                "k": min(size, 50),
                                "num_candidates": min(size * 2, 200),
                                **({"filter": {"bool": {"filter": knn_filter}}} if knn_filter else {}),
                            }
                        },
                    ],
                    "rank_window_size": min(size * 2, 200),
                    "rank_constant": 60,
                }
            },
            "size": size,
            "track_total_hits": True,
            "_source": source_fields,
            "highlight": highlight_spec,
        }
    else:
        # BM25-only fallback
        payload = {
            "size": size,
            "track_total_hits": True,
            "query": bm25_query,
            "sort": [{"_score": {"order": "desc"}}, {"pub_date": {"order": "desc"}}],
            "_source": source_fields,
            "highlight": highlight_spec,
        }

    resp = await client.request("POST", es_url, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()
