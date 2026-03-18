"""Hybrid search — BM25 + kNN via Elasticsearch RRF (Reciprocal Rank Fusion).

Implements a two-pass cascade for multi-word queries (3+ words):
  Pass 1: Phrase-first — requires the phrase to appear contiguously (slop=2)
          in at least one search field. Only returns true phrase matches.
  Pass 2: If Pass 1 returns fewer than MIN_PHRASE_RESULTS, falls back to
          the original bag-of-words query (all terms anywhere).

Single/two-word queries skip Pass 1 and go straight to bag-of-words.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from src.backend.core.config import settings

logger = logging.getLogger(__name__)

# Minimum phrase-match results before falling back to bag-of-words
MIN_PHRASE_RESULTS = 3

_STOPWORDS_PT = frozenset({
    "a", "e", "o", "da", "de", "do", "das", "dos", "na", "no", "nas", "nos",
    "em", "um", "uma", "para", "por", "com", "que", "se",
})


def _query_word_count(q: str) -> int:
    """Count meaningful words in a query (ignoring Portuguese stopwords)."""
    words = re.findall(r"[a-zA-ZÀ-ÿ]+", q)
    meaningful = [w for w in words if w.lower() not in _STOPWORDS_PT]
    return len(meaningful)


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


def _decay_functions() -> list[dict[str, Any]]:
    return [{
        "gauss": {
            "pub_date": {
                "origin": "now",
                "scale": "365d",
                "offset": "30d",
                "decay": 0.5,
            },
        },
    }]


def build_phrase_query(
    q: str,
    filters: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a phrase-first query for 3+ word queries.

    The phrase (with slop=2) MUST appear in at least one field.
    Exact phrase matches get higher boosts for ranking within results.
    """
    # Must: phrase must appear in at least one field (slop=2 allows minor variations)
    phrase_must: dict[str, Any] = {
        "bool": {
            "should": [
                {"match_phrase": {"identifica": {"query": q, "slop": 2}}},
                {"match_phrase": {"ementa": {"query": q, "slop": 2}}},
                {"match_phrase": {"body_plain": {"query": q, "slop": 2}}},
                {"match_phrase": {"issuing_organ": {"query": q, "slop": 2}}},
            ],
            "minimum_should_match": 1,
        }
    }

    # Should: rank exact matches above slop matches
    should: list[dict] = [
        {"match_phrase": {"identifica": {"query": q, "boost": 10}}},
        {"match_phrase": {"ementa": {"query": q, "boost": 8}}},
        {"match_phrase": {"body_plain": {"query": q, "boost": 3}}},
    ]

    bool_query: dict[str, Any] = {
        "bool": {
            "must": [phrase_must],
            "should": should,
        }
    }
    if filters:
        bool_query["bool"]["filter"] = filters

    return {
        "function_score": {
            "query": bool_query,
            "functions": _decay_functions(),
            "boost_mode": "multiply",
        },
    }


def build_bm25_query(
    q: str,
    filters: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the bag-of-words BM25 query (used for 1-2 word queries and as fallback)."""
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
        # Exact phrase boosts for ranking
        {"match_phrase": {"identifica": {"query": q, "boost": 200}}},
        {"match_phrase": {"ementa": {"query": q, "boost": 150}}},
        {"match_phrase": {"body_plain": {"query": q, "boost": 50}}},
        # Near-phrase (slop=2)
        {"match_phrase": {"identifica": {"query": q, "slop": 2, "boost": 80}}},
        {"match_phrase": {"ementa": {"query": q, "slop": 2, "boost": 60}}},
        {"match_phrase": {"body_plain": {"query": q, "slop": 2, "boost": 20}}},
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
            "functions": _decay_functions(),
            "boost_mode": "multiply",
        },
    }


def _build_payload(
    query_body: dict[str, Any],
    size: int,
    from_: int,
    source_fields: list[str],
    highlight_spec: dict[str, Any],
) -> dict[str, Any]:
    return {
        "from": from_,
        "size": size,
        "track_total_hits": True,
        "query": query_body,
        "sort": [{"_score": {"order": "desc"}}, {"pub_date": {"order": "desc"}}],
        "_source": source_fields,
        "highlight": highlight_spec,
    }


async def _execute_search(
    es_url: str, payload: dict[str, Any], client: httpx.AsyncClient
) -> dict[str, Any]:
    resp = await client.request("POST", es_url, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


async def hybrid_search(
    query: str,
    filters: list[dict[str, Any]],
    size: int,
    source_fields: list[str],
    highlight_spec: dict[str, Any],
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    """Execute search with two-pass cascade for multi-word queries.

    For 3+ word queries:
      1. Try phrase-first query (must match phrase in at least one field)
      2. If < MIN_PHRASE_RESULTS, fall back to bag-of-words
    For 1-2 word queries:
      Straight to bag-of-words (phrase matching doesn't help)
    """
    query_vector = await _get_query_embedding(query, client)
    es_url = f"{settings.ES_URL}/{settings.es_target_index}/_search"
    word_count = _query_word_count(query)

    if query_vector is not None:
        # Hybrid mode: RRF with kNN — use bag-of-words BM25 (phrase filtering
        # happens at the BM25 retriever level within RRF)
        if word_count >= 3:
            bm25_query = build_phrase_query(query, filters)
        else:
            bm25_query = build_bm25_query(query, filters)

        knn_filter = filters if filters else None
        payload: dict[str, Any] = {
            "retriever": {
                "rrf": {
                    "retrievers": [
                        {"standard": {"query": bm25_query}},
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
        result = await _execute_search(es_url, payload, client)

        # Fallback for hybrid mode if phrase query returned too few
        total = result.get("hits", {}).get("total", {}).get("value", 0)
        if word_count >= 3 and total < MIN_PHRASE_RESULTS:
            logger.info("phrase query returned %d results, falling back to bag-of-words", total)
            bm25_query = build_bm25_query(query, filters)
            payload["retriever"]["rrf"]["retrievers"][0] = {"standard": {"query": bm25_query}}
            result = await _execute_search(es_url, payload, client)

        return result

    # BM25-only mode with two-pass cascade
    if word_count >= 3:
        # Pass 1: phrase-first
        phrase_query = build_phrase_query(query, filters)
        payload = _build_payload(phrase_query, size, 0, source_fields, highlight_spec)
        result = await _execute_search(es_url, payload, client)

        total = result.get("hits", {}).get("total", {}).get("value", 0)
        if total >= MIN_PHRASE_RESULTS:
            return result

        # Pass 2: fall back to bag-of-words
        logger.info("phrase query returned %d results, falling back to bag-of-words", total)

    bm25_query = build_bm25_query(query, filters)
    payload = _build_payload(bm25_query, size, 0, source_fields, highlight_spec)
    return await _execute_search(es_url, payload, client)
