"""Intent-based query builders for the GABI DOU search system.

Three specialised query builders that produce Elasticsearch query DSL dicts:

  - build_exact_name_query : structured lookup for a specific document by its
    art_type + number + year (e.g. "Portaria MEC 234/2026").

  - build_trending_query : heavy recency ranking for trending / browsing
    queries where the user wants the latest publications on a topic.

  - build_subject_query : thematic exploration with phrase proximity, soft
    recency decay, and legal-reference pinning.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _number_variants(number: str, year: int | None) -> list[str]:
    """Generate document_number variants for keyword lookup.

    The ``document_number`` field is a keyword and its formatting is
    inconsistent across gazette entries, so we produce several plausible
    representations (with/without year suffix, with/without dots).
    """
    variants: set[str] = {number}
    if year:
        variants.add(f"{number}/{year}")
    # Without dots (e.g. "13.709" → "13709")
    no_dots = number.replace(".", "")
    if no_dots != number:
        variants.add(no_dots)
        if year:
            variants.add(f"{no_dots}/{year}")
    return list(variants)


def _build_identifica_string(
    art_type: str,
    organ: str | None,
    number: str,
    year: int | None,
) -> str:
    """Build the most likely *identifica* string for phrase matching.

    The ``identifica`` field stores the document header as it appears in the
    gazette, so we capitalise the art_type appropriately and append the organ
    and number.
    """
    # Map lowercase art_type to its canonical capitalised form
    _SPECIAL_CAPS: dict[str, str] = {
        "instrução normativa": "Instrução Normativa",
        "medida provisória": "Medida Provisória",
        "decreto-lei": "Decreto-Lei",
        "lei complementar": "Lei Complementar",
    }
    type_caps = _SPECIAL_CAPS.get(art_type, art_type.title())

    parts = [type_caps]
    if organ:
        parts.append(organ)
    parts.append(f"Nº {number}")
    # Note: we don't append year/date here since identifica format varies
    return " ".join(parts)


# ---------------------------------------------------------------------------
# 1. Exact-name query
# ---------------------------------------------------------------------------

def build_exact_name_query(
    normalized: dict[str, Any],
    original_q: str,
    filters: list[dict[str, Any]],
) -> dict[str, Any]:
    """Structured lookup for a specific document by art_type + number + year.

    Produces a single ``bool/should`` query with weighted tiers (NOT a
    sequential cascade) so Elasticsearch can score each document against all
    tiers simultaneously.

    Parameters
    ----------
    normalized:
        Dict with keys ``art_type`` (str, lowercase), ``organ`` (str | None),
        ``number`` (str), ``year`` (int | None).
    original_q:
        The user's original query string (used as a BM25 safety net).
    filters:
        Pre-built ES filter clauses (date range, section, etc.).
    """
    art_type: str = normalized.get("art_type", "")
    organ: str | None = normalized.get("organ")
    number: str = normalized.get("number", "")
    year: int | None = normalized.get("year")

    number_variants = _number_variants(number, year)

    should: list[dict[str, Any]] = []

    # Tier 1 (boost 30): Structured lookup — art_type + document_number + year
    structured_must: list[dict[str, Any]] = [
        {"term": {"art_type_normalized": art_type}},
        {"terms": {"document_number": number_variants}},
    ]
    if year:
        structured_must.append({"term": {"document_year": year}})
    should.append({"bool": {"must": structured_must, "boost": 30}})

    # Tier 2 (boost 20): Structured without year
    if year:
        should.append({"bool": {"must": [
            {"term": {"art_type_normalized": art_type}},
            {"terms": {"document_number": number_variants}},
        ], "boost": 20}})

    # Tier 3 (boost 15): Phrase match on identifica
    identifica_query = _build_identifica_string(art_type, organ, number, year)
    should.append({"match_phrase": {"identifica": {"query": identifica_query, "boost": 15}}})

    # Tier 4 (boost 10): Phrase match on identifica without year
    identifica_no_year = _build_identifica_string(art_type, organ, number, None)
    if identifica_no_year != identifica_query:
        should.append({"match_phrase": {"identifica": {"query": identifica_no_year, "boost": 10}}})

    # Tier 5 (boost 5): Organ match if available
    if organ:
        should.append({"match": {"issuing_organ": {"query": organ, "boost": 5}}})

    # Safety net: BM25 on original query
    should.append({"multi_match": {
        "query": original_q,
        "fields": ["identifica^3", "ementa^2", "body_plain"],
        "type": "best_fields",
        "boost": 1,
    }})

    bool_query: dict[str, Any] = {"bool": {"should": should, "minimum_should_match": 1}}
    if filters:
        bool_query["bool"]["filter"] = filters

    # No recency decay for exact name lookups
    return bool_query


# ---------------------------------------------------------------------------
# 2. Trending query
# ---------------------------------------------------------------------------

def build_trending_query(
    q: str,
    filters: list[dict[str, Any]],
    topic_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Heavy recency ranking for trending / browsing queries.

    Uses a steep Gaussian decay on ``pub_date`` so that today's documents
    score ~5x and 30-day-old documents score ~1.5x compared to older ones.
    Optional ``topic_meta`` can supply art-type boosts.

    Parameters
    ----------
    q:
        The user's query string.
    filters:
        Pre-built ES filter clauses.
    topic_meta:
        Optional dict with key ``art_types`` (list of str) providing
        art-type boosts in priority order.
    """
    text_query: dict[str, Any] = {
        "multi_match": {
            "query": q,
            "fields": ["identifica^2", "ementa^2", "body_plain"],
            "type": "best_fields",
        }
    }

    functions: list[dict[str, Any]] = [
        # Heavy recency decay — documents from today score 5x, 30 days ago ~1.5x
        {
            "gauss": {
                "pub_date": {
                    "origin": "now",
                    "scale": "30d",
                    "offset": "1d",
                    "decay": 0.3,
                }
            },
            "weight": 5,
        },
    ]

    # Art type boosts from topic metadata
    if topic_meta and topic_meta.get("art_types"):
        for i, at in enumerate(topic_meta["art_types"]):
            weight = max(3.0 - i * 0.5, 1.5)  # First type gets 3, decreasing
            functions.append({
                "filter": {"term": {"art_type_normalized": at.lower()}},
                "weight": weight,
            })

    bool_query: dict[str, Any] = {"bool": {"must": [text_query]}}
    if filters:
        bool_query["bool"]["filter"] = filters

    return {
        "function_score": {
            "query": bool_query,
            "functions": functions,
            "score_mode": "multiply",
            "boost_mode": "multiply",
        }
    }


# ---------------------------------------------------------------------------
# 3. Subject query
# ---------------------------------------------------------------------------

def build_subject_query(
    q: str,
    filters: list[dict[str, Any]],
    legal_refs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Thematic exploration with phrase proximity and soft recency decay.

    Combines sloppy phrase matches for thematic closeness with broad
    ``most_fields`` matching, optional legal-reference pinning, and a gentle
    six-month Gaussian decay that keeps older but relevant documents visible.

    Parameters
    ----------
    q:
        The user's query string.
    filters:
        Pre-built ES filter clauses.
    legal_refs:
        Optional list of dicts with keys ``type`` and ``number`` extracted
        from the query (e.g. ``[{"type": "lei", "number": "13709"}]``).
    """
    should: list[dict[str, Any]] = [
        # Phrase proximity on ementa — captures thematic closeness
        {"match_phrase": {"ementa": {"query": q, "slop": 3, "boost": 5}}},
        {"match_phrase": {"identifica": {"query": q, "slop": 2, "boost": 3}}},
        # Broad term matching
        {"multi_match": {
            "query": q,
            "fields": ["identifica^3", "ementa^3", "body_plain"],
            "type": "most_fields",
        }},
    ]

    # Legal reference pinning
    if legal_refs:
        for ref in legal_refs:
            ref_text = f"{ref['type']} {ref['number']}"
            should.extend([
                {"match_phrase": {"identifica": {"query": ref_text, "boost": 100}}},
                {"match_phrase": {"ementa": {"query": ref_text, "boost": 60}}},
            ])

    bool_query: dict[str, Any] = {"bool": {"should": should, "minimum_should_match": 1}}
    if filters:
        bool_query["bool"]["filter"] = filters

    functions: list[dict[str, Any]] = [
        # Soft recency — 6 months is still relevant for thematic exploration
        {
            "gauss": {
                "pub_date": {
                    "origin": "now",
                    "scale": "180d",
                    "offset": "7d",
                    "decay": 0.5,
                }
            },
            "weight": 1.5,
        },
        # Canonical document types get boosted
        {"filter": {"term": {"art_type_normalized": "lei"}}, "weight": 3},
        {"filter": {"term": {"art_type_normalized": "decreto"}}, "weight": 2.5},
        {"filter": {"term": {"art_type_normalized": "resolução"}}, "weight": 2},
        {"filter": {"term": {"art_type_normalized": "instrução normativa"}}, "weight": 1.5},
    ]

    return {
        "function_score": {
            "query": bool_query,
            "functions": functions,
            "score_mode": "multiply",
            "boost_mode": "multiply",
        }
    }
