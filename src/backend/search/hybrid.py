"""Hybrid search — BM25 + kNN via Elasticsearch RRF (Reciprocal Rank Fusion).

Query classification & two-pass cascade:

  1. Person names (detected heuristically): phrase-first with orthographic
     variants (Y↔I, PH↔F, TH↔T, W↔V) and progressive relaxation
     (full name → no suffix → first+last).

  2. Legal references ("Lei 13709"): pinned phrase boost on identifica/ementa.

  3. Multi-word (3+ terms): phrase-first with slop=2, falls back to
     bag-of-words if too few results.

  4. Short queries (1-2 words): straight bag-of-words with phrase boosts.

Falls back to BM25-only if the embedding server is unavailable.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from src.backend.core.config import settings

logger = logging.getLogger(__name__)

# Minimum results before falling back to a more permissive query
MIN_PHRASE_RESULTS = 3

# ---------------------------------------------------------------------------
# Query classification
# ---------------------------------------------------------------------------

_STOPWORDS_PT = frozenset({
    "a", "e", "o", "da", "de", "do", "das", "dos", "na", "no", "nas", "nos",
    "em", "um", "uma", "para", "por", "com", "que", "se",
})

_NAME_PARTICLES = frozenset({"de", "da", "do", "dos", "das", "e"})

_NAME_SUFFIXES = frozenset({
    "junior", "júnior", "jr", "filho", "neto", "sobrinho", "segundo",
    "terceiro", "senior", "sênior",
})

# ~60 top Brazilian first names (lowercase, accent-folded)
_COMMON_FIRST_NAMES = frozenset({
    "fernando", "carlos", "jose", "joao", "antonio", "francisco", "pedro",
    "paulo", "lucas", "marcos", "rafael", "andre", "marcelo", "rodrigo",
    "bruno", "ricardo", "eduardo", "fabio", "sergio", "gustavo", "roberto",
    "daniel", "luis", "luiz", "alexandre", "felipe", "thiago", "tiago",
    "anderson", "leonardo", "renato", "diego", "guilherme", "gabriel",
    "leandro", "claudio", "flavio", "adriano", "maria", "ana", "patricia",
    "fernanda", "juliana", "claudia", "adriana", "luciana", "marcia",
    "cristina", "sandra", "monica", "camila", "vanessa", "aline", "priscila",
    "raquel", "tatiana", "simone", "carla", "renata", "larissa", "beatriz",
    "carolina", "bruna", "amanda", "leticia", "jessica", "roberta", "helena",
    "valeria", "eliane", "solange", "rosangela", "denise", "silvia", "cecilia",
})

_NON_NAME_WORDS = frozenset({
    "lei", "decreto", "portaria", "edital", "resolução", "resolucao", "despacho",
    "instrução", "instrucao", "normativa", "ministerio", "ministério", "secretaria",
    "tribunal", "conselho", "comissão", "comissao", "fundação", "fundacao", "instituto",
    "universidade", "empresa", "sociedade", "ltda", "eireli", "cnpj", "cpf",
    "contrato", "licitação", "licitacao", "pregão", "pregao", "aviso", "extrato",
    "reforma", "tributária", "tributaria", "fiscal", "saúde", "saude", "educação",
    "educacao", "defesa", "agricultura", "artigo", "parágrafo", "paragrafo",
    "concurso", "concursos", "público", "publico", "públicos", "publicos",
    "nomeação", "nomeacao", "nomeações", "nomeacoes", "exoneração", "exoneracao",
    "aposentadoria", "pensão", "pensao", "designação", "designacao",
    "homologação", "homologacao", "ratificação", "ratificacao",
})

_LEGAL_REF_PATTERN = re.compile(
    r"\b(lei(?:\s+complementar)?|decreto(?:\s*-?\s*lei)?|portaria|"
    r"resolu[cç][aã]o|instru[cç][aã]o\s+normativa|medida\s+provis[oó]ria|"
    r"emenda\s+constitucional|s[uú]mula|IN|MP|RDC|RE|ADI|ADPF)"
    r"\s*(?:n[°º.]?\s*)?(\d[\d.]*(?:/\d{2,4})?)\b",
    re.IGNORECASE,
)

_ORTHO_SUBS: list[tuple[str, str]] = [
    ("y", "i"), ("i", "y"),
    ("ph", "f"), ("f", "ph"),
    ("th", "t"),
    ("w", "v"), ("v", "w"),
]


def _normalize_text(s: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFC", s.lower().strip())


def _query_word_count(q: str) -> int:
    words = re.findall(r"[a-zA-ZÀ-ÿ]+", q)
    meaningful = [w for w in words if w.lower() not in _STOPWORDS_PT]
    return len(meaningful)


def _is_person_name(query: str) -> bool:
    """Conservative heuristic: does this query look like a person's name?"""
    q = query.strip()
    if not q or '"' in q:
        return False
    if re.search(r"\d", q):
        return False

    words = q.split()
    if len(words) < 2 or len(words) > 6:
        return False

    normalized = [_normalize_text(w) for w in words]
    if any(w in _NON_NAME_WORDS for w in normalized):
        return False

    meaningful = [w for w in normalized if w not in _NAME_PARTICLES]
    if len(meaningful) < 2:
        return False

    first_is_name = meaningful[0] in _COMMON_FIRST_NAMES
    all_capitalized = all(
        w[0].isupper() or _normalize_text(w) in _NAME_PARTICLES
        for w in words if w
    )

    return first_is_name or all_capitalized


_LAW_NAME_PATTERNS = [
    re.compile(r"^lei\s+(geral|complementar|orgânica|federal|estadual|municipal)", re.IGNORECASE),
    re.compile(r"^(código|estatuto)\s+d[aeo]", re.IGNORECASE),
    re.compile(r"^(lei|decreto|mp|medida\s+provisória)\s*(n[°º.]?\s*)?\d", re.IGNORECASE),
]


def _is_law_name_query(q: str) -> bool:
    """Detect queries seeking a specific law/decree by name."""
    stripped = q.strip()
    return any(p.search(stripped) for p in _LAW_NAME_PATTERNS)


def _has_legal_ref(query: str) -> list[dict[str, str]]:
    """Extract legal references from query (e.g., 'Lei 13709' → [{'type': 'lei', 'number': '13709'}])."""
    refs = []
    for m in _LEGAL_REF_PATTERN.finditer(query):
        refs.append({"type": m.group(1).strip().lower(), "number": m.group(2).strip()})
    return refs


def _normalize_person_query(query: str) -> str:
    """Normalize person name: standardize suffixes, remove particles."""
    q = _normalize_text(query)
    q = re.sub(r"\.(?:\s|$)", " ", q)
    q = re.sub(r"\b(jr|júnior)\b", "junior", q)
    q = re.sub(r"\b(sr|sênior)\b", "senior", q)
    words = q.split()
    canonical = [w for w in words if w not in _NAME_PARTICLES]
    return " ".join(canonical)


def _word_ortho_variants(word: str) -> list[str]:
    variants = {word}
    for src, dst in _ORTHO_SUBS:
        if src in word:
            variants.add(word.replace(src, dst, 1))
    return list(variants)


def _name_spelling_variants(normalized_name: str) -> list[str]:
    """Generate full-name spelling variants (one word varies at a time)."""
    words = normalized_name.split()
    results = {normalized_name}
    for i, word in enumerate(words):
        for variant in _word_ortho_variants(word):
            if variant != word:
                new_name = words[:i] + [variant] + words[i + 1:]
                results.add(" ".join(new_name))
    return list(results)


def _person_name_variants(query: str) -> list[str]:
    """Progressive relaxation: full name → no suffix → first+last."""
    canonical = _normalize_person_query(query)
    words = canonical.split()
    if len(words) < 2:
        return [canonical]

    variants = [canonical]

    # Without suffix (Junior, Filho, etc.)
    norm_suffixes = {_normalize_text(s) for s in _NAME_SUFFIXES}
    if words[-1] in norm_suffixes:
        no_suffix = " ".join(words[:-1])
        if no_suffix != canonical:
            variants.append(no_suffix)

    # First + last name only
    if len(words) >= 3:
        last_idx = -2 if words[-1] in norm_suffixes else -1
        if abs(last_idx) <= len(words):
            first_last = f"{words[0]} {words[last_idx]}"
            if first_last not in variants:
                variants.append(first_last)

    return variants


# ---------------------------------------------------------------------------
# Query builders
# ---------------------------------------------------------------------------

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


def _wrap_function_score(bool_query: dict[str, Any], *, use_decay: bool = True) -> dict[str, Any]:
    if use_decay:
        return {
            "function_score": {
                "query": bool_query,
                "functions": _decay_functions(),
                "boost_mode": "multiply",
            },
        }
    # No decay — pure BM25 relevance (smaller docs with phrase match rank higher)
    return bool_query


def build_person_query(
    q: str,
    filters: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a person-name query: phrase must match in at least one field,
    with orthographic variants (Y↔I, PH↔F, etc.)."""
    normalized = _normalize_person_query(q)
    fields = ["identifica", "ementa", "body_plain"]
    spelling_variants = _name_spelling_variants(normalized)

    # Hard gate: must match ANY spelling variant as phrase with slop=1
    if len(spelling_variants) == 1:
        must_clause: dict[str, Any] = {
            "multi_match": {
                "query": normalized,
                "type": "phrase",
                "fields": fields,
                "slop": 1,
            },
        }
    else:
        variant_clauses = [
            {
                "multi_match": {
                    "query": variant,
                    "type": "phrase",
                    "fields": fields,
                    "slop": 1,
                },
            }
            for variant in spelling_variants
        ]
        must_clause = {
            "bool": {
                "should": variant_clauses,
                "minimum_should_match": 1,
            },
        }

    # Boost exact matches (slop=0) for ranking
    should: list[dict] = [
        {"match_phrase": {"identifica": {"query": normalized, "boost": 50}}},
        {"match_phrase": {"ementa": {"query": normalized, "boost": 40}}},
        {"match_phrase": {"body_plain": {"query": normalized, "boost": 20}}},
    ]

    bool_query: dict[str, Any] = {
        "bool": {
            "must": [must_clause],
            "should": should,
        }
    }
    if filters:
        bool_query["bool"]["filter"] = filters

    # Person names: pure BM25 relevance, no recency decay.
    # Smaller docs where the name appears rank higher naturally.
    return _wrap_function_score(bool_query, use_decay=False)


def build_phrase_query(
    q: str,
    filters: list[dict[str, Any]],
    legal_refs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build a phrase-first query for 3+ word queries.
    The phrase (slop=2) MUST appear in at least one field."""
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

    should: list[dict] = [
        {"match_phrase": {"identifica": {"query": q, "boost": 10}}},
        {"match_phrase": {"ementa": {"query": q, "boost": 8}}},
        {"match_phrase": {"body_plain": {"query": q, "boost": 3}}},
    ]

    # Legal reference pinning
    if legal_refs:
        for ref in legal_refs:
            ref_text = f"{ref['type']} {ref['number']}"
            should.extend([
                {"match_phrase": {"identifica": {"query": ref_text, "boost": 100}}},
                {"match_phrase": {"ementa": {"query": ref_text, "boost": 60}}},
            ])

    bool_query: dict[str, Any] = {
        "bool": {
            "must": [phrase_must],
            "should": should,
        }
    }
    if filters:
        bool_query["bool"]["filter"] = filters

    return _wrap_function_score(bool_query)


def build_bm25_query(
    q: str,
    filters: list[dict[str, Any]],
    legal_refs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build the bag-of-words BM25 query (1-2 word queries and fallback)."""
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
        {"match_phrase": {"identifica": {"query": q, "boost": 200}}},
        {"match_phrase": {"ementa": {"query": q, "boost": 150}}},
        {"match_phrase": {"body_plain": {"query": q, "boost": 50}}},
        {"match_phrase": {"identifica": {"query": q, "slop": 2, "boost": 80}}},
        {"match_phrase": {"ementa": {"query": q, "slop": 2, "boost": 60}}},
        {"match_phrase": {"body_plain": {"query": q, "slop": 2, "boost": 20}}},
    ]

    # Legal reference pinning
    if legal_refs:
        for ref in legal_refs:
            ref_text = f"{ref['type']} {ref['number']}"
            should.extend([
                {"match_phrase": {"identifica": {"query": ref_text, "boost": 100}}},
                {"match_phrase": {"ementa": {"query": ref_text, "boost": 60}}},
            ])

    bool_query: dict[str, Any] = {
        "bool": {
            "must": [text_query],
            "should": should,
        }
    }
    if filters:
        bool_query["bool"]["filter"] = filters

    return _wrap_function_score(bool_query)


def build_canonical_query(
    q: str,
    filters: list[dict[str, Any]],
    legal_refs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build query for canonical document lookup (Lei X, Código Y, etc.)"""
    # Extract the likely art_type from query
    art_type_match = re.match(
        r"^(lei(?:\s+complementar)?|decreto(?:\s*-?\s*lei)?|código|estatuto|medida\s+provisória|emenda\s+constitucional)",
        q.strip(), re.IGNORECASE,
    )
    art_type_term = art_type_match.group(1).strip().lower() if art_type_match else None

    # The full query as phrase MUST appear in at least one field
    phrase_must = {
        "bool": {
            "should": [
                {"match_phrase": {"identifica": {"query": q, "slop": 1}}},
                {"match_phrase": {"ementa": {"query": q, "slop": 2}}},
            ],
            "minimum_should_match": 1,
        }
    }

    # Ranking boosts
    should: list[dict] = [
        {"match_phrase": {"identifica": {"query": q, "boost": 500}}},
        {"match_phrase": {"identifica": {"query": q, "slop": 1, "boost": 200}}},
        {"match_phrase": {"ementa": {"query": q, "boost": 100}}},
        {"match": {"body_plain": {"query": q, "boost": 10}}},
    ]

    # Legal reference pinning
    if legal_refs:
        for ref in legal_refs:
            ref_text = f"{ref['type']} {ref['number']}"
            should.extend([
                {"match_phrase": {"identifica": {"query": ref_text, "boost": 300}}},
                {"match_phrase": {"ementa": {"query": ref_text, "boost": 150}}},
            ])

    bool_query: dict[str, Any] = {
        "bool": {
            "must": [phrase_must],
            "should": should,
        }
    }
    if filters:
        bool_query["bool"]["filter"] = filters

    # Art type boost via function_score
    # art_type is keyword (case-sensitive), so we need all casing variants
    _ART_TYPE_KEYWORD_VARIANTS: dict[str, list[str]] = {
        "lei": ["Lei", "LEI", "Lei Ordinária"],
        "lei complementar": ["Lei Complementar", "LEI COMPLEMENTAR"],
        "decreto": ["Decreto", "DECRETO"],
        "decreto-lei": ["Decreto-Lei", "DECRETO-LEI"],
        "medida provisória": ["Medida Provisória", "MEDIDA PROVISÓRIA"],
        "emenda constitucional": ["Emenda Constitucional", "EMENDA CONSTITUCIONAL"],
        "código": ["Lei", "LEI"],  # Códigos are published as Leis
        "estatuto": ["Lei", "LEI"],
    }
    functions = []
    if art_type_term:
        keywords = _ART_TYPE_KEYWORD_VARIANTS.get(art_type_term, [])
        if keywords:
            functions.append({
                "filter": {"terms": {"art_type": keywords}},
                "weight": 5,
            })

    if functions:
        return {
            "function_score": {
                "query": bool_query,
                "functions": functions,
                "score_mode": "multiply",
                "boost_mode": "multiply",
            }
        }

    # No art_type boost applicable — just return bool_query without decay
    return bool_query


# ---------------------------------------------------------------------------
# Query classification & routing
# ---------------------------------------------------------------------------

def classify_and_build(
    q: str,
    filters: list[dict[str, Any]],
    *,
    is_trending: bool = False,
    intent_override: str | None = None,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Classify query intent and build the appropriate ES query.

    Returns (query_body, strategy_name, intent_metadata).
    """
    from src.backend.search.intent import (
        classify_intent, QueryIntent, IntentResult,
    )
    from src.backend.search.query_builders import (
        build_exact_name_query, build_trending_query, build_subject_query,
    )
    from src.backend.search.trending import get_topic_metadata

    legal_refs = _has_legal_ref(q)

    # Allow intent override
    if intent_override:
        _OVERRIDE_MAP = {
            "exact_name": QueryIntent.EXACT_NAME,
            "canonical": QueryIntent.CANONICAL_LOOKUP,
            "trending": QueryIntent.TRENDING_BROWSE,
            "explore": QueryIntent.SUBJECT_EXPLORE,
            "person": QueryIntent.PERSON_NAME,
        }
        forced = _OVERRIDE_MAP.get(intent_override)
        if forced:
            intent_result = IntentResult(intent=forced, confidence=1.0, metadata={})
        else:
            intent_result = classify_intent(q, is_trending=is_trending)
    else:
        intent_result = classify_intent(q, is_trending=is_trending)

    intent = intent_result.intent
    meta = intent_result.metadata
    intent_data = {
        "detected": intent.value,
        "confidence": intent_result.confidence,
        **{k: v for k, v in meta.items() if k in ("suggestion", "matched_alias")},
    }

    # Route to appropriate builder
    if intent == QueryIntent.EXACT_NAME:
        query_body = build_exact_name_query(meta, q, filters)
        return query_body, "exact_name", intent_data

    if intent == QueryIntent.CANONICAL_LOOKUP:
        # Enhance existing canonical builder with metadata from canonical dict
        entry = meta.get("entry", {})
        formal_ref = entry.get("formal_ref", {})
        boost_organs = entry.get("boost_organs", [])
        related_terms = entry.get("related_terms", [])

        # Build enhanced canonical query using formal reference
        if formal_ref.get("number"):
            # Pin the formal reference with structured fields
            from src.backend.search.query_builders import build_exact_name_query as _build_exact
            formal_number = formal_ref["number"]
            formal_year = formal_ref.get("year")
            formal_type = formal_ref.get("art_type", "lei")
            pin_query = _build_exact(
                {"art_type": formal_type,
                 "number": formal_number,
                 "year": formal_year,
                 "organ": None},
                q, [],
            )
            # Also build the text-based canonical query
            canon_query = build_canonical_query(q, filters, legal_refs)
            canon_base = canon_query.get("function_score", {}).get("query", canon_query)
            # Combine: pin + canonical in a bool/should
            combined = {
                "bool": {
                    "should": [
                        {"bool": {"must": [pin_query], "boost": 12}},
                        {"bool": {"must": [canon_base], "boost": 1}},
                    ],
                    "minimum_should_match": 1,
                }
            }
            formal_phrases = [
                f"{formal_type} {formal_number}",
                f"{formal_type} nº {formal_number}",
            ]
            if formal_year:
                formal_phrases.append(f"{formal_type} {formal_number} de {formal_year}")
            for term in related_terms:
                combined["bool"]["should"].append(
                    {
                        "multi_match": {
                            "query": term,
                            "fields": ["ementa^2", "identifica^2"],
                            "type": "best_fields",
                            "boost": 1.5,
                        }
                    }
                )
            for phrase in formal_phrases:
                combined["bool"]["should"].extend(
                    [
                        {"match_phrase": {"identifica": {"query": phrase, "boost": 6}}},
                        {"match_phrase": {"ementa": {"query": phrase, "boost": 4}}},
                    ]
                )
            if filters:
                combined["bool"]["filter"] = filters
            # Add organ boost + art_type hierarchy via function_score
            functions = []
            for organ in boost_organs:
                functions.append({
                    "filter": {"match_phrase": {"issuing_organ": organ}},
                    "weight": 8,
                })
            functions.append({"filter": {"term": {"art_type_normalized": formal_type}}, "weight": 10})
            for term in related_terms:
                functions.append(
                    {
                        "filter": {
                            "bool": {
                                "should": [
                                    {"match_phrase": {"ementa": term}},
                                    {"match_phrase": {"identifica": term}},
                                ],
                                "minimum_should_match": 1,
                            }
                        },
                        "weight": 2,
                    }
                )

            if functions:
                query_body = {
                    "function_score": {
                        "query": combined,
                        "functions": functions,
                        "score_mode": "sum",
                        "boost_mode": "multiply",
                    }
                }
            else:
                query_body = combined
        else:
            # No formal reference — fall back to existing canonical builder
            query_body = build_canonical_query(q, filters, legal_refs)
        return query_body, "canonical", intent_data

    if intent == QueryIntent.PERSON_NAME:
        query_body = build_person_query(q, filters)
        return query_body, "person", intent_data

    if intent == QueryIntent.TRENDING_BROWSE:
        topic_meta = get_topic_metadata(q)
        if topic_meta:
            intent_data["topic"] = topic_meta["label"]
        query_body = build_trending_query(q, filters, topic_meta)
        return query_body, "trending", intent_data

    if intent == QueryIntent.SUBJECT_EXPLORE:
        query_body = build_subject_query(q, filters, legal_refs)
        return query_body, "subject", intent_data

    # Ultimate fallback
    query_body = build_bm25_query(q, filters, legal_refs)
    return query_body, "bm25", intent_data


# ---------------------------------------------------------------------------
# Search execution
# ---------------------------------------------------------------------------

async def _get_query_embedding(
    query: str, client: httpx.AsyncClient
) -> list[float] | None:
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
        "timeout": "800ms",
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
    from_: int,
    source_fields: list[str],
    highlight_spec: dict[str, Any],
    client: httpx.AsyncClient,
    *,
    is_trending: bool = False,
    intent: str | None = None,
) -> dict[str, Any]:
    """Execute search with intent-based query classification and two-pass cascade.

    Intent classification (priority order):
      1. EXACT_NAME → structured field lookup (art_type + number)
      2. CANONICAL → law by popular name (LGPD, CLT) with regulatory cluster
      3. PERSON → name detection with orthographic variants
      4. TRENDING → heavy recency decay for browsing queries
      5. SUBJECT → thematic exploration with phrase proximity

    Two-pass cascade (for person/phrase/canonical/exact_name):
      Pass 1: strict query
      Pass 2: if < MIN_PHRASE_RESULTS, fall back to bag-of-words
    """
    query_body, strategy, intent_data = classify_and_build(
        query, filters, is_trending=is_trending, intent_override=intent,
    )
    query_vector = await _get_query_embedding(query, client)
    es_url = f"{settings.ES_URL}/{settings.es_target_index}/_search"

    logger.info("search strategy=%s query=%r", strategy, query[:80])

    if query_vector is not None:
        # Hybrid mode with RRF
        knn_filter = filters if filters else None
        payload: dict[str, Any] = {
            "retriever": {
                "rrf": {
                    "retrievers": [
                        {"standard": {"query": query_body}},
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
            "from": from_,
            "size": size,
            "track_total_hits": True,
            "_source": source_fields,
            "highlight": highlight_spec,
        }
        result = await _execute_search(es_url, payload, client)

        # Fallback for strict strategies
        total = result.get("hits", {}).get("total", {}).get("value", 0)
        if strategy in ("person", "phrase", "canonical", "exact_name") and total < MIN_PHRASE_RESULTS:
            logger.info("strategy=%s returned %d, falling back to bm25", strategy, total)
            fallback_query = build_bm25_query(query, filters, _has_legal_ref(query))
            payload["retriever"]["rrf"]["retrievers"][0] = {"standard": {"query": fallback_query}}
            result = await _execute_search(es_url, payload, client)

        result["_intent"] = intent_data
        return result

    # BM25-only mode
    payload = _build_payload(query_body, size, from_, source_fields, highlight_spec)
    result = await _execute_search(es_url, payload, client)

    total = result.get("hits", {}).get("total", {}).get("value", 0)

    # Two-pass: strict → bag-of-words fallback
    if strategy in ("person", "phrase", "canonical", "exact_name") and total < MIN_PHRASE_RESULTS:
        if strategy == "person":
            # Progressive relaxation: try name variants before bag-of-words
            variants = _person_name_variants(query)
            for variant in variants[1:]:
                logger.info("person relaxation: trying variant %r", variant)
                variant_query = build_person_query(variant, filters)
                payload = _build_payload(variant_query, size, from_, source_fields, highlight_spec)
                result = await _execute_search(es_url, payload, client)
                total = result.get("hits", {}).get("total", {}).get("value", 0)
                if total >= MIN_PHRASE_RESULTS:
                    result["_intent"] = intent_data
                    return result

        # Final fallback: bag-of-words
        logger.info("strategy=%s returned %d, falling back to bm25", strategy, total)
        fallback = build_bm25_query(query, filters, _has_legal_ref(query))
        payload = _build_payload(fallback, size, from_, source_fields, highlight_spec)
        result = await _execute_search(es_url, payload, client)

    result["_intent"] = intent_data
    return result
