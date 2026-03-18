"""Intent-based query builders for the GABI DOU search system.

Specialised query builders that produce Elasticsearch query DSL dicts:

  - build_exact_name_query : structured lookup for a specific document by its
    art_type + number + year (e.g. "Portaria MEC 234/2026").

  - build_topic_query : curated high-value topic routing with explicit include /
    exclude terms, art-type preferences and section/organ boosts.

  - build_trending_query : heavy recency ranking for trending / browsing
    queries where the user wants the latest publications on a topic.

  - build_subject_query : thematic exploration with phrase proximity, soft
    recency decay, and legal-reference pinning.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TOPIC_TEXT_FIELDS = ["identifica^6", "ementa^5", "issuing_organ^2", "art_type^1.5"]

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
    # Without dots
    no_dots = number.replace(".", "")
    if no_dots != number:
        variants.add(no_dots)
        if year:
            variants.add(f"{no_dots}/{year}")
    # With dots (e.g., "13709" → "13.709" for Brazilian numbering)
    if "." not in number and len(number) >= 4:
        # Try adding dot as thousands separator: 13709 → 13.709
        dotted = f"{number[:-3]}.{number[-3:]}"
        variants.add(dotted)
        if year:
            variants.add(f"{dotted}/{year}")
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
        "instrucao normativa": "Instrução Normativa",
        "medida provisoria": "Medida Provisória",
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


def _build_type_organ_string(art_type: str, organ: str | None) -> str:
    _SPECIAL_CAPS: dict[str, str] = {
        "instrucao normativa": "Instrução Normativa",
        "medida provisoria": "Medida Provisória",
        "decreto-lei": "Decreto-Lei",
        "lei complementar": "Lei Complementar",
    }
    type_caps = _SPECIAL_CAPS.get(art_type, art_type.title())
    return f"{type_caps} {organ}".strip() if organ else type_caps


def _art_type_variants(art_type: str) -> list[str]:
    variants = {art_type}
    legacy_map: dict[str, list[str]] = {
        "instrucao normativa": ["instrucao", "instrução normativa", "instrução"],
        "resolucao": ["resolução", "resolucao-re", "resolução-re"],
        "decreto-lei": ["decreto lei", "decreto-lei"],
        "medida provisoria": ["medida provisória", "mp"],
    }
    variants.update(legacy_map.get(art_type, []))
    return list(variants)


def _topic_text_clauses(term: str, *, phrase_boost: float, match_boost: float) -> list[dict[str, Any]]:
    clauses: list[dict[str, Any]] = [
        {
            "multi_match": {
                "query": term,
                "fields": _TOPIC_TEXT_FIELDS,
                "type": "best_fields",
                "boost": match_boost,
            }
        }
    ]
    if " " in term:
        clauses.extend(
            [
                {"match_phrase": {"identifica": {"query": term, "boost": phrase_boost * 1.3}}},
                {"match_phrase": {"ementa": {"query": term, "boost": phrase_boost}}},
            ]
        )
    else:
        clauses.extend(
            [
                {"match": {"identifica": {"query": term, "boost": phrase_boost}}},
                {"match": {"ementa": {"query": term, "boost": phrase_boost * 0.7}}},
            ]
        )
    return clauses


def _topic_exclude_clauses(term: str) -> list[dict[str, Any]]:
    if " " in term:
        return [
            {"match_phrase": {"identifica": {"query": term}}},
            {"match_phrase": {"ementa": {"query": term}}},
        ]
    return [
        {
            "multi_match": {
                "query": term,
                "fields": ["identifica^2", "ementa^2"],
                "type": "best_fields",
            }
        }
    ]


def _normalize_topic_term(value: str) -> str:
    lowered = value.lower().strip()
    normalized = unicodedata.normalize("NFD", lowered)
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", normalized)


def _dedupe_topic_terms(values: list[str] | tuple[str, ...]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = _normalize_topic_term(value)
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(value)
    return ordered


def _section_filter_clause(section: str) -> dict[str, Any]:
    return {
        "bool": {
            "should": [
                {"term": {"section": section}},
                {"term": {"edition_section": section}},
            ],
            "minimum_should_match": 1,
        }
    }


# ---------------------------------------------------------------------------
# 1. Curated topic query
# ---------------------------------------------------------------------------

def build_topic_query(
    profile: dict[str, Any],
    original_q: str,
    filters: list[dict[str, Any]],
    *,
    legal_refs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    required_groups = profile.get("required_groups") or []
    should_terms = profile.get("should_terms") or []
    exclude_terms = profile.get("exclude_terms") or []
    required_art_types = profile.get("required_art_types") or []
    preferred_art_types = profile.get("preferred_art_types") or []
    excluded_art_types = profile.get("excluded_art_types") or []
    preferred_sections = profile.get("preferred_sections") or []
    organ_boosts = profile.get("organ_boosts") or []
    recency_scale = profile.get("recency_scale", "45d")
    recency_weight = float(profile.get("recency_weight", 3.5))
    pure_act_type = bool(profile.get("pure_act_type"))
    text_gate_mode = profile.get("text_gate_mode", "expanded")

    must: list[dict[str, Any]] = []
    should: list[dict[str, Any]] = []
    must_not: list[dict[str, Any]] = []

    if pure_act_type and text_gate_mode == "simple":
        for group in required_groups:
            terms = _dedupe_topic_terms(tuple(group))
            if not terms:
                continue
            query = " | ".join(f'"{term}"' if " " in term else term for term in terms)
            must.append(
                {
                    "simple_query_string": {
                        "query": query,
                        "fields": ["identifica^4", "ementa^3"],
                        "default_operator": "or",
                    }
                }
            )
    elif not pure_act_type:
        for group in required_groups:
            group_should: list[dict[str, Any]] = []
            for term in _dedupe_topic_terms(tuple(group)):
                group_should.extend(_topic_text_clauses(term, phrase_boost=10, match_boost=5))
            if group_should:
                must.append({"bool": {"should": group_should, "minimum_should_match": 1}})

    should.extend(
        [
            {
                "multi_match": {
                    "query": original_q,
                    "fields": _TOPIC_TEXT_FIELDS,
                    "type": "best_fields",
                    "boost": 5,
                }
            },
            {"match_phrase": {"identifica": {"query": original_q, "slop": 2, "boost": 8}}},
            {"match_phrase": {"ementa": {"query": original_q, "slop": 3, "boost": 6}}},
        ]
    )

    for term in _dedupe_topic_terms(should_terms):
        should.extend(_topic_text_clauses(term, phrase_boost=4, match_boost=2.2))

    if legal_refs:
        for ref in legal_refs:
            ref_text = f"{ref['type']} {ref['number']}"
            should.extend(
                [
                    {"match_phrase": {"identifica": {"query": ref_text, "boost": 18}}},
                    {"match_phrase": {"ementa": {"query": ref_text, "boost": 10}}},
                ]
            )

    for term in _dedupe_topic_terms(exclude_terms):
        must_not.extend(_topic_exclude_clauses(term))

    for art_type in excluded_art_types:
        must_not.append({"term": {"art_type_normalized": art_type}})

    bool_query: dict[str, Any] = {
        "bool": {
            "should": should,
            "minimum_should_match": 0 if pure_act_type else 1,
        }
    }
    if must:
        bool_query["bool"]["must"] = must
    if must_not:
        bool_query["bool"]["must_not"] = must_not
    if filters:
        bool_query["bool"]["filter"] = filters
    if required_art_types:
        art_type_filter = {"terms": {"art_type_normalized": list(required_art_types)}}
        if "filter" in bool_query["bool"]:
            bool_query["bool"]["filter"].append(art_type_filter)
        else:
            bool_query["bool"]["filter"] = [art_type_filter]

    functions: list[dict[str, Any]] = [
        {
            "gauss": {
                "pub_date": {
                    "origin": "now",
                    "scale": recency_scale,
                    "offset": "1d",
                    "decay": 0.4,
                }
            },
            "weight": recency_weight,
        }
    ]

    for item in preferred_art_types:
        if isinstance(item, dict):
            value = item.get("value")
            weight = float(item.get("weight", 1.0))
        else:
            value, weight = item
        if value:
            functions.append({"filter": {"term": {"art_type_normalized": value}}, "weight": weight})

    for item in preferred_sections:
        if isinstance(item, dict):
            value = item.get("value")
            weight = float(item.get("weight", 1.0))
        else:
            value, weight = item
        if value:
            functions.append({"filter": _section_filter_clause(value), "weight": weight})

    for item in organ_boosts:
        if isinstance(item, dict):
            value = item.get("value")
            weight = float(item.get("weight", 1.0))
        else:
            value, weight = item
        if value:
            functions.append(
                {
                    "filter": {
                        "bool": {
                            "should": [
                                {"match_phrase": {"issuing_organ": value}},
                                {"match": {"issuing_organ": {"query": value}}},
                            ],
                            "minimum_should_match": 1,
                        }
                    },
                    "weight": weight,
                }
            )

    return {
        "function_score": {
            "query": bool_query,
            "functions": functions,
            "score_mode": "sum",
            "boost_mode": "sum",
        }
    }


# ---------------------------------------------------------------------------
# 2. Exact-name query
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
    year_hint = int(number) if not year and number.isdigit() and len(number) == 4 else None

    number_variants = _number_variants(number, year)
    art_type_terms = _art_type_variants(art_type)

    should: list[dict[str, Any]] = []
    organ_should: list[dict[str, Any]] = []

    if organ:
        organ_should = [
            {"match_phrase": {"issuing_organ": {"query": organ, "boost": 12}}},
            {"match": {"issuing_organ": {"query": organ, "boost": 8}}},
        ]

    # Tier 1 (boost 60): Structured lookup — art_type + document_number + year
    structured_must: list[dict[str, Any]] = [
        {"terms": {"art_type_normalized": art_type_terms}},
        {"terms": {"document_number": number_variants}},
    ]
    if year:
        structured_must.append({"term": {"document_year": year}})
    should.append(
        {
            "bool": {
                "must": structured_must,
                "should": organ_should,
                "boost": 60 if year else 45,
            }
        }
    )

    # Tier 2 (boost 35): Structured without year
    if year:
        should.append(
            {
                "bool": {
                    "must": [
                        {"terms": {"art_type_normalized": art_type_terms}},
                        {"terms": {"document_number": number_variants}},
                    ],
                    "should": organ_should,
                    "boost": 35,
                }
            }
        )

    # Tier 2b (boost 24): Ambiguous 4-digit token may really be a year hint
    if year_hint:
        should.append(
            {
                "bool": {
                    "must": [
                        {"terms": {"art_type_normalized": art_type_terms}},
                        {"term": {"document_year": year_hint}},
                    ],
                    "should": organ_should,
                    "boost": 24,
                }
            }
        )

    # Tier 3 (boost 20): Phrase match on identifica
    identifica_query = _build_identifica_string(art_type, organ, number, year)
    should.append({"match_phrase": {"identifica": {"query": identifica_query, "boost": 20}}})

    # Tier 4 (boost 12): Phrase match on identifica without year
    identifica_no_year = _build_identifica_string(art_type, organ, number, None)
    if identifica_no_year != identifica_query:
        should.append({"match_phrase": {"identifica": {"query": identifica_no_year, "boost": 12}}})

    if year_hint:
        type_organ_query = _build_type_organ_string(art_type, organ)
        should.append({"match_phrase": {"identifica": {"query": type_organ_query, "boost": 10}}})
        should.append({"match_phrase": {"ementa": {"query": type_organ_query, "boost": 6}}})

    # Tier 5 (boost 6): Original text as exact-ish phrase, still much stricter than BM25 fallback
    if not year_hint:
        should.append({"match_phrase": {"identifica": {"query": original_q, "slop": 2, "boost": 6}}})
        should.append({"match_phrase": {"ementa": {"query": original_q, "slop": 2, "boost": 3}}})

    bool_query: dict[str, Any] = {"bool": {"should": should, "minimum_should_match": 1}}
    if filters:
        bool_query["bool"]["filter"] = filters

    # No recency decay for exact name lookups
    return bool_query


# ---------------------------------------------------------------------------
# 3. Trending query
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
# 4. Subject query
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
        {"filter": {"term": {"art_type_normalized": "resolucao"}}, "weight": 2},
        {"filter": {"term": {"art_type_normalized": "instrucao normativa"}}, "weight": 1.5},
    ]

    return {
        "function_score": {
            "query": bool_query,
            "functions": functions,
            "score_mode": "multiply",
            "boost_mode": "multiply",
        }
    }
