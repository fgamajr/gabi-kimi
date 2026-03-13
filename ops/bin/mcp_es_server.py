"""Self-contained MCP server for DOU search with Elasticsearch.

Supports BM25, semantic (kNN), and hybrid (BM25 + kNN) search modes.
No dependency on adapters.py — filter inference is inlined.

Usage:
  python ops/bin/mcp_es_server.py
  python ops/bin/mcp_es_server.py --transport sse --port 8766
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:
    FastMCP = None  # type: ignore[assignment]


load_dotenv()


# ---------------------------------------------------------------------------
# Filter inference (inlined from legacy adapters.py)
# ---------------------------------------------------------------------------

_SECTION_PATTERN = re.compile(r"\bdo([123](?:e)?)\b", re.IGNORECASE)

_ART_TYPE_PATTERNS = [
    (re.compile(r"\baviso(?:s)?\s+de\s+licitac[aã]o\b", re.IGNORECASE), "aviso"),
    (re.compile(r"\bpreg[aã]o(?:es)?\s+eletr[oô]nico(?:s)?\b", re.IGNORECASE), "pregão"),
    (re.compile(r"\bpreg[aã]o(?:es)?\b", re.IGNORECASE), "pregão"),
    (re.compile(r"\bportaria(?:s)?\b", re.IGNORECASE), "portaria"),
    (re.compile(r"\bdecreto(?:s)?\b", re.IGNORECASE), "decreto"),
    (re.compile(r"\bedital(?:is)?\b", re.IGNORECASE), "edital"),
    (re.compile(r"\bextrato(?:s)?\b", re.IGNORECASE), "extrato"),
    (re.compile(r"\bresolu[cç][aã]o(?:es)?\b", re.IGNORECASE), "resolução"),
    (re.compile(r"\bdespacho(?:s)?\b", re.IGNORECASE), "despacho"),
]

_ORGAN_PATTERNS = [
    (re.compile(r"\bminist[eé]rio\s+da\s+sa[uú]de\b", re.IGNORECASE), "Ministério da Saúde"),
    (re.compile(r"\bminist[eé]rio\s+da\s+justi[cç]a\b", re.IGNORECASE), "Ministério da Justiça"),
    (re.compile(r"\bminist[eé]rio\s+da\s+fazenda\b", re.IGNORECASE), "Ministério da Fazenda"),
    (re.compile(r"\bminist[eé]rio\s+da\s+educa[cç][aã]o\b", re.IGNORECASE), "Ministério da Educação"),
    (re.compile(r"\bminist[eé]rio\s+da\s+defesa\b", re.IGNORECASE), "Ministério da Defesa"),
    (
        re.compile(r"\bminist[eé]rio\s+da\s+agricultura(?:,\s*pecu[aá]ria\s+e\s+abastecimento)?\b", re.IGNORECASE),
        "Ministério da Agricultura, Pecuária e Abastecimento",
    ),
    (re.compile(r"\bminist[eé]rio\s+das\s+comunica[cç][oõ]es\b", re.IGNORECASE), "Ministério das Comunicações"),
    (re.compile(r"\bminist[eé]rio\s+de\s+minas\s+e\s+energia\b", re.IGNORECASE), "Ministério de Minas e Energia"),
    (re.compile(r"\bpresid[eê]ncia\s+da\s+rep[uú]blica\b", re.IGNORECASE), "Presidência da República"),
    (re.compile(r"\bpoder\s+judici[aá]rio\b", re.IGNORECASE), "Poder Judiciário"),
]


# ---------------------------------------------------------------------------
# R11: Portuguese legal synonym expansion (query-time)
# ---------------------------------------------------------------------------

_LEGAL_SYNONYMS: dict[str, list[str]] = {
    # Taxation & fiscal
    "tarifa": ["reajuste tarifário", "revisão tarifária"],
    "imposto": ["tributo", "tributação", "contribuição"],
    "imposto seletivo": ["tributação produtos nocivos", "imposto sobre consumo"],
    "tributo": ["imposto", "contribuição", "taxa"],
    "arcabouço fiscal": ["regra fiscal", "marco fiscal", "teto de gastos"],
    # Contracts & procurement
    "termo aditivo": ["aditamento contratual", "prorrogação contrato"],
    "licitação": ["pregão", "concorrência", "tomada de preços"],
    "pregão eletrônico": ["licitação eletrônica", "pregão"],
    "contratação direta": ["inexigibilidade", "dispensa de licitação"],
    # Social programs
    "bolsa família": ["programa bolsa família", "auxílio brasil", "transferência de renda"],
    "auxílio emergencial": ["benefício emergencial", "auxílio covid"],
    # Legislation
    "medida provisória": ["MP", "medida provisória conversão"],
    "decreto": ["decreto regulamentar", "decreto executivo"],
    "regulamentação": ["regulação", "normatização", "normatizar"],
    # Entities
    "LGPD": ["lei geral de proteção de dados", "lei 13709"],
    "ECA": ["estatuto da criança e do adolescente", "lei 8069"],
    "FUNDEB": ["fundo de manutenção educação básica"],
    # Administrative
    "nomeação": ["designação", "investidura"],
    "exoneração": ["dispensa", "vacância"],
    "cessão": ["requisição", "movimentação de pessoal"],
    # Policy domains
    "segurança alimentar": ["combate à fome", "programa alimentar", "soberania alimentar"],
    "meio ambiente": ["ambiental", "licenciamento ambiental", "proteção ambiental"],
    "energia": ["setor elétrico", "energia elétrica"],
}

# Precompute reverse map for fast lookup
_SYNONYM_LOOKUP: dict[str, list[str]] = {}
for _key, _syns in _LEGAL_SYNONYMS.items():
    _SYNONYM_LOOKUP[_key.lower()] = _syns
    for _syn in _syns:
        if _syn.lower() not in _SYNONYM_LOOKUP:
            _SYNONYM_LOOKUP[_syn.lower()] = [_key]


def _expand_synonyms(query: str) -> list[str]:
    """Return synonym expansions for a query (empty list if no matches)."""
    q_lower = query.lower().strip()
    expansions: list[str] = []
    # Try full query match first, then 2-gram and single-word matches
    if q_lower in _SYNONYM_LOOKUP:
        expansions.extend(_SYNONYM_LOOKUP[q_lower])
    else:
        words = q_lower.split()
        # Try bigrams
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i + 1]}"
            if bigram in _SYNONYM_LOOKUP:
                expansions.extend(_SYNONYM_LOOKUP[bigram])
        # Try individual words (only for key domain terms)
        for word in words:
            if word in _SYNONYM_LOOKUP and len(word) > 4:  # skip short common words
                for syn in _SYNONYM_LOOKUP[word]:
                    if syn not in expansions:
                        expansions.append(syn)
    return expansions[:5]  # cap at 5 expansions


def _query_text(query: str) -> str:
    return query.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'").strip()


def _infer_request_filters(
    query: str,
    *,
    section: str | None,
    art_type: str | None,
    issuing_organ: str | None,
) -> tuple[str, str | None, str | None, str | None]:
    q = _query_text(query)
    inferred_section = section
    inferred_art_type = art_type
    inferred_organ = issuing_organ

    if not inferred_section:
        match = _SECTION_PATTERN.search(q)
        if match:
            inferred_section = f"do{match.group(1).lower()}"
            q = _SECTION_PATTERN.sub(" ", q)

    if not inferred_art_type:
        for pattern, value in _ART_TYPE_PATTERNS:
            if pattern.search(q):
                inferred_art_type = value
                break

    if not inferred_organ:
        for pattern, value in _ORGAN_PATTERNS:
            if pattern.search(q):
                inferred_organ = value
                break

    q = re.sub(r"\s+", " ", q).strip()
    return q, inferred_section, inferred_art_type, inferred_organ


def _search_context_payload(
    *,
    original_query: str,
    interpreted_query: str,
    requested_section: str | None,
    requested_art_type: str | None,
    requested_issuing_organ: str | None,
    applied_section: str | None,
    applied_art_type: str | None,
    applied_issuing_organ: str | None,
) -> dict[str, Any]:
    inferred: dict[str, str] = {}
    if not requested_section and applied_section:
        inferred["section"] = applied_section
    if not requested_art_type and applied_art_type:
        inferred["art_type"] = applied_art_type
    if not requested_issuing_organ and applied_issuing_organ:
        inferred["issuing_organ"] = applied_issuing_organ
    return {
        "interpreted_query": interpreted_query,
        "query_normalized": interpreted_query != _query_text(original_query),
        "applied_filters": {
            "section": applied_section,
            "art_type": applied_art_type,
            "issuing_organ": applied_issuing_organ,
        },
        "inferred_filters": inferred,
    }


# ---------------------------------------------------------------------------
# Elasticsearch client
# ---------------------------------------------------------------------------

def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


SYNONYM_EXPANSION = _env_bool("SYNONYM_EXPANSION", True)


class ElasticClient:
    def __init__(self) -> None:
        self.url = os.getenv("ES_URL", "http://localhost:9200").rstrip("/")
        self.index = os.getenv("ES_INDEX", "gabi_documents")
        username = (os.getenv("ES_USERNAME") or "").strip() or None
        password = (os.getenv("ES_PASSWORD") or "").strip() or None
        verify_tls = _env_bool("ES_VERIFY_TLS", True)
        timeout_sec = int(os.getenv("ES_TIMEOUT_SEC", "20"))
        auth = (username, password or "") if username else None
        self._client = httpx.Client(timeout=timeout_sec, verify=verify_tls, auth=auth)

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self._client.request(method=method, url=f"{self.url}{path}", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("Invalid Elasticsearch response")
        return data

    def msearch(self, searches: list[tuple[dict[str, Any], dict[str, Any]]]) -> list[dict[str, Any]]:
        """Execute multiple searches in a single roundtrip via _msearch API."""
        lines = []
        for header, body in searches:
            lines.append(header)
            lines.append(body)
        # _msearch needs NDJSON
        import json
        ndjson = "\n".join(json.dumps(line) for line in lines) + "\n"
        resp = self._client.request(
            method="POST",
            url=f"{self.url}/{self.index}/_msearch",
            content=ndjson,
            headers={"Content-Type": "application/x-ndjson"},
        )
        resp.raise_for_status()
        return resp.json().get("responses", [])

    def close(self) -> None:
        self._client.close()


ES = ElasticClient()

EMBED_URL = os.getenv("EMBED_URL", "http://192.168.15.20:8900").rstrip("/")
EMBED_DIM = int(os.getenv("EMBED_DIM", "384"))
EMBED_TIMEOUT = int(os.getenv("EMBED_TIMEOUT", "10"))


def _get_query_embedding(text: str) -> list[float] | None:
    """Get embedding vector for a search query. Returns None on failure (RESIL-01 fallback)."""
    try:
        resp = httpx.post(
            f"{EMBED_URL}/embed",
            json={"texts": [text], "dimensions": EMBED_DIM},
            timeout=EMBED_TIMEOUT,
        )
        resp.raise_for_status()
        embeddings = resp.json().get("embeddings", [])
        if embeddings:
            return embeddings[0]
    except Exception as exc:
        logger.warning("Embedding server unavailable, falling back to BM25: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def _build_filters(
    *,
    date_from: str | None,
    date_to: str | None,
    section: str | None,
    art_type: str | None,
    issuing_organ: str | None,
) -> list[dict[str, Any]]:
    filters: list[dict[str, Any]] = []
    if date_from or date_to:
        rng: dict[str, Any] = {}
        if date_from:
            rng["gte"] = date_from
        if date_to:
            rng["lte"] = date_to
        filters.append({"range": {"pub_date": rng}})
    if section:
        filters.append({"term": {"edition_section": section}})
    if art_type:
        filters.append({"match": {"art_type": art_type}})
    if issuing_organ:
        filters.append({"term": {"issuing_organ.keyword": issuing_organ}})
    return filters


def _query_clause(query: str) -> dict[str, Any]:
    """Build a BM25 query with exact-phrase boosting and synonym expansion.

    Uses a bool/should with three legs:
    1. simple_query_string (tokenized, fuzzy) — baseline relevance
    2. match_phrase on key fields (huge boost) — exact matches dominate
    3. R11: synonym expansions (small boost) — capture vocabulary gaps
    """
    q = query.strip()
    if q == "*" or not q:
        return {"match_all": {}}

    should_clauses: list[dict[str, Any]] = [
        {"match_phrase": {"identifica": {"query": q, "boost": 20}}},
        {"match_phrase": {"ementa": {"query": q, "boost": 15}}},
        {"match_phrase": {"body_plain": {"query": q, "boost": 5}}},
    ]

    # R11: Add synonym expansion as soft should clauses
    if SYNONYM_EXPANSION:
        for syn in _expand_synonyms(q):
            should_clauses.append({
                "simple_query_string": {
                    "query": syn,
                    "fields": ["identifica^2", "ementa^2", "body_plain"],
                    "default_operator": "and",
                    "boost": 1.5,
                },
            })

    return {
        "bool": {
            "must": [{
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
            }],
            "should": should_clauses,
        },
    }


def _sort_clause(sort: str) -> list[dict[str, Any]]:
    if sort == "date_desc":
        return [{"pub_date": {"order": "desc"}}, {"_score": {"order": "desc"}}]
    if sort == "date_asc":
        return [{"pub_date": {"order": "asc"}}, {"_score": {"order": "desc"}}]
    return [{"_score": {"order": "desc"}}, {"pub_date": {"order": "desc"}}]


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------

# Hybrid weight: 0.0 = pure kNN, 1.0 = pure BM25, 0.5 = equal
HYBRID_ALPHA = float(os.getenv("HYBRID_ALPHA", "0.5"))

# Fusion strategy: "convex" (score interpolation) or "rrf" (Reciprocal Rank Fusion)
HYBRID_FUSION = os.getenv("HYBRID_FUSION", "rrf")

# Coverage-aware gating: fall back to BM25 if embedding % < threshold
HYBRID_COVERAGE_GATE = float(os.getenv("HYBRID_COVERAGE_GATE", "5.0"))

# RRF constant (higher = more emphasis on tail results)
RRF_K = int(os.getenv("RRF_K", "60"))

# Cached embedding coverage (refreshed periodically)
_coverage_cache: dict[str, Any] = {"pct": 0.0, "ts": 0.0}


def _get_embedding_coverage() -> float:
    """Return embedding coverage as percentage, cached for 5 minutes."""
    import time

    now = time.time()
    if now - _coverage_cache["ts"] < 300:
        return _coverage_cache["pct"]
    try:
        total = ES.request("GET", f"/{ES.index}/_count")
        embedded = ES.request("GET", f"/{ES.index}/_count", {"query": {"exists": {"field": "embedding"}}})
        total_n = max(int(total.get("count", 1)), 1)
        embed_n = int(embedded.get("count", 0))
        pct = embed_n / total_n * 100
    except Exception:
        pct = _coverage_cache["pct"]  # keep stale value on error
    _coverage_cache["pct"] = pct
    _coverage_cache["ts"] = now
    return pct


def _format_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert raw ES hits to result dicts."""
    results: list[dict[str, Any]] = []
    for hit in hits:
        src = hit.get("_source", {})
        hl = hit.get("highlight", {})
        snippet = ""
        for k in ("identifica", "ementa", "body_plain"):
            frag = hl.get(k)
            if frag:
                snippet = frag[0]
                break
        if not snippet:
            snippet = (src.get("body_plain") or "")[:220]
        results.append({
            "doc_id": src.get("doc_id") or hit.get("_id"),
            "score": float(hit.get("_score") or 0.0),
            "identifica": src.get("identifica"),
            "ementa": src.get("ementa"),
            "art_type": src.get("art_type"),
            "pub_date": src.get("pub_date"),
            "edition_section": src.get("edition_section"),
            "issuing_organ": src.get("issuing_organ"),
            "snippet": snippet,
        })
    return results


def _min_max_normalize(scores: list[float]) -> list[float]:
    """Normalize scores to [0, 1] range via min-max."""
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    span = hi - lo
    if span == 0:
        return [1.0] * len(scores)
    return [(s - lo) / span for s in scores]


def _extract_hit_info(hit: dict[str, Any], doc_id: str) -> dict[str, Any]:
    """Extract display fields from an ES hit."""
    src = hit.get("_source", {})
    hl = hit.get("highlight", {})
    snippet = ""
    for k in ("identifica", "ementa", "body_plain"):
        frag = hl.get(k)
        if frag:
            snippet = frag[0]
            break
    if not snippet:
        snippet = (src.get("body_plain") or "")[:220]
    return {
        "doc_id": src.get("doc_id") or doc_id,
        "identifica": src.get("identifica"),
        "ementa": src.get("ementa"),
        "art_type": src.get("art_type"),
        "pub_date": src.get("pub_date"),
        "edition_section": src.get("edition_section"),
        "issuing_organ": src.get("issuing_organ"),
        "snippet": snippet,
    }


def _merge_hybrid(
    bm25_hits: list[dict[str, Any]],
    knn_hits: list[dict[str, Any]],
    page: int,
    page_size: int,
    sort: str,
    alpha: float = HYBRID_ALPHA,
    fusion: str = HYBRID_FUSION,
) -> list[dict[str, Any]]:
    """Merge BM25 and kNN hits using configurable fusion strategy.

    Strategies:
      - "convex": alpha * bm25_norm + (1-alpha) * knn_norm (min-max normalized)
      - "rrf": Reciprocal Rank Fusion — rank-based, no normalization needed.
               RRF_score(d) = sum(1 / (k + rank_i(d))) for each retriever.
               Documents in only one retriever still get their rank contribution.
    """
    if fusion == "rrf":
        return _merge_rrf(bm25_hits, knn_hits, page, page_size, sort, alpha)
    return _merge_convex(bm25_hits, knn_hits, page, page_size, sort, alpha)


def _merge_rrf(
    bm25_hits: list[dict[str, Any]],
    knn_hits: list[dict[str, Any]],
    page: int,
    page_size: int,
    sort: str,
    alpha: float,
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion: rank-based merge immune to score scale issues.

    RRF_score(d) = alpha * 1/(k + bm25_rank) + (1-alpha) * 1/(k + knn_rank)
    Missing retriever contribution = 0 (document only in one source).
    """
    k = RRF_K
    doc_map: dict[str, dict[str, Any]] = {}

    # Assign BM25 ranks (1-based)
    for rank, hit in enumerate(bm25_hits, 1):
        doc_id = hit.get("_id", "")
        doc_map[doc_id] = {
            "hit": hit,
            "bm25_rank": rank,
            "knn_rank": 0,  # 0 = not found by this retriever
        }

    # Assign kNN ranks (1-based)
    for rank, hit in enumerate(knn_hits, 1):
        doc_id = hit.get("_id", "")
        if doc_id in doc_map:
            doc_map[doc_id]["knn_rank"] = rank
        else:
            doc_map[doc_id] = {
                "hit": hit,
                "bm25_rank": 0,
                "knn_rank": rank,
            }

    if not doc_map:
        return []

    scored: list[tuple[float, dict[str, Any]]] = []
    for doc_id, doc in doc_map.items():
        bm25_contrib = alpha * (1.0 / (k + doc["bm25_rank"])) if doc["bm25_rank"] > 0 else 0.0
        knn_contrib = (1.0 - alpha) * (1.0 / (k + doc["knn_rank"])) if doc["knn_rank"] > 0 else 0.0
        combined = bm25_contrib + knn_contrib

        info = _extract_hit_info(doc["hit"], doc_id)
        info["score"] = round(combined, 6)
        info["score_bm25"] = round(bm25_contrib, 6)
        info["score_knn"] = round(knn_contrib, 6)
        scored.append((combined, info))

    # Sort
    if sort == "date_desc":
        scored.sort(key=lambda x: (x[1].get("pub_date") or "", x[0]), reverse=True)
    elif sort == "date_asc":
        scored.sort(key=lambda x: (x[1].get("pub_date") or "9999", -x[0]))
    else:
        scored.sort(key=lambda x: x[0], reverse=True)

    start = (page - 1) * page_size
    return [item for _, item in scored[start : start + page_size]]


def _merge_convex(
    bm25_hits: list[dict[str, Any]],
    knn_hits: list[dict[str, Any]],
    page: int,
    page_size: int,
    sort: str,
    alpha: float,
) -> list[dict[str, Any]]:
    """Original convex combination: alpha * bm25_norm + (1-alpha) * knn_norm."""
    doc_map: dict[str, dict[str, Any]] = {}

    for hit in bm25_hits:
        doc_id = hit.get("_id", "")
        doc_map[doc_id] = {
            "hit": hit,
            "bm25_raw": float(hit.get("_score") or 0.0),
            "knn_raw": 0.0,
        }

    for hit in knn_hits:
        doc_id = hit.get("_id", "")
        if doc_id in doc_map:
            doc_map[doc_id]["knn_raw"] = float(hit.get("_score") or 0.0)
        else:
            doc_map[doc_id] = {
                "hit": hit,
                "bm25_raw": 0.0,
                "knn_raw": float(hit.get("_score") or 0.0),
            }

    if not doc_map:
        return []

    bm25_scores = [d["bm25_raw"] for d in doc_map.values()]
    knn_scores = [d["knn_raw"] for d in doc_map.values()]
    bm25_normed = _min_max_normalize(bm25_scores)
    knn_normed = _min_max_normalize(knn_scores)

    scored: list[tuple[float, dict[str, Any]]] = []
    for (doc_id, doc), bm25_n, knn_n in zip(doc_map.items(), bm25_normed, knn_normed):
        combined = alpha * bm25_n + (1 - alpha) * knn_n
        info = _extract_hit_info(doc["hit"], doc_id)
        info["score"] = round(combined, 4)
        info["score_bm25"] = round(bm25_n, 4)
        info["score_knn"] = round(knn_n, 4)
        scored.append((combined, info))

    if sort == "date_desc":
        scored.sort(key=lambda x: (x[1].get("pub_date") or "", x[0]), reverse=True)
    elif sort == "date_asc":
        scored.sort(key=lambda x: (x[1].get("pub_date") or "9999", -x[0]))
    else:
        scored.sort(key=lambda x: x[0], reverse=True)

    start = (page - 1) * page_size
    return [item for _, item in scored[start : start + page_size]]


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

def es_search(
    query: str,
    mode: str = "hybrid",
    page: int = 1,
    page_size: int = 20,
    sort: str = "relevance",
    date_from: str | None = None,
    date_to: str | None = None,
    section: str | None = None,
    art_type: str | None = None,
    issuing_organ: str | None = None,
) -> dict[str, Any]:
    """Search DOU documents with full-text, semantic, or hybrid search.

    Args:
      query: search query in Portuguese, or '*' for browse mode
      mode: hybrid (BM25 + kNN, default) | bm25 (keyword only) | semantic (vector only)
      page: 1-based page number
      page_size: results per page (1-100)
      sort: relevance | date_desc | date_asc
      date_from: YYYY-MM-DD lower bound
      date_to: YYYY-MM-DD upper bound
      section: do1 | do2 | do3
      art_type: exact act type (e.g. decreto, portaria)
      issuing_organ: exact issuing organ name
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    if sort not in {"relevance", "date_desc", "date_asc"}:
        sort = "relevance"
    if mode not in {"hybrid", "bm25", "semantic"}:
        mode = "hybrid"

    requested_section = section
    requested_art_type = art_type
    requested_issuing_organ = issuing_organ
    interpreted_query, section, art_type, issuing_organ = _infer_request_filters(
        query, section=section, art_type=art_type, issuing_organ=issuing_organ,
    )

    filters = _build_filters(
        date_from=date_from, date_to=date_to,
        section=section, art_type=art_type, issuing_organ=issuing_organ,
    )

    # --- Get embedding for semantic/hybrid modes ---
    actual_mode = mode
    query_vector: list[float] | None = None
    is_text_query = interpreted_query.strip() not in ("*", "")
    coverage_gated = False

    # R2: Coverage-aware gating — skip semantic component when coverage is too low
    if mode == "hybrid" and is_text_query and HYBRID_COVERAGE_GATE > 0:
        coverage_pct = _get_embedding_coverage()
        if coverage_pct < HYBRID_COVERAGE_GATE:
            actual_mode = "bm25"
            coverage_gated = True
            logger.info("Coverage gate: %.1f%% < %.1f%% threshold, falling back to BM25", coverage_pct, HYBRID_COVERAGE_GATE)

    if mode in ("hybrid", "semantic") and is_text_query and not coverage_gated:
        query_vector = _get_query_embedding(interpreted_query)
        if query_vector is None:
            # RESIL-01: embedding server down → fall back to BM25
            actual_mode = "bm25"

    if mode == "semantic" and query_vector is None:
        actual_mode = "bm25"  # can't do semantic without vectors

    # --- Build ES payload ---
    # Fetch extra candidates for hybrid merge; CANDIDATE_POOL controls depth
    CANDIDATE_POOL = max(page_size * 3, 60)

    source_fields = [
        "doc_id", "identifica", "ementa", "art_type", "art_category",
        "pub_date", "edition_section", "issuing_organ", "body_plain",
    ]
    highlight_spec = {
        "pre_tags": [">>>"],
        "post_tags": ["<<<"],
        "fields": {
            "identifica": {"number_of_fragments": 0},
            "ementa": {"number_of_fragments": 1, "fragment_size": 220},
            "body_plain": {"number_of_fragments": 1, "fragment_size": 220},
        },
    }

    if actual_mode == "hybrid" and query_vector:
        # --- Two-pass hybrid: BM25 + kNN via msearch, convex combination ---
        bm25_body = {
            "size": CANDIDATE_POOL,
            "track_total_hits": True,
            "query": {"bool": {"must": [_query_clause(interpreted_query)], "filter": filters}},
            "_source": source_fields,
            "highlight": highlight_spec,
        }
        knn_body: dict[str, Any] = {
            "size": CANDIDATE_POOL,
            "knn": {
                "field": "embedding",
                "query_vector": query_vector,
                "k": CANDIDATE_POOL,
                "num_candidates": max(CANDIDATE_POOL * 5, 200),
                "filter": filters or [{"match_all": {}}],
            },
            "_source": source_fields,
        }
        responses = ES.msearch([({}, bm25_body), ({}, knn_body)])
        bm25_data = responses[0] if len(responses) > 0 else {}
        knn_data = responses[1] if len(responses) > 1 else {}

        total = int(bm25_data.get("hits", {}).get("total", {}).get("value", 0))
        bm25_hits = bm25_data.get("hits", {}).get("hits", [])
        knn_hits = knn_data.get("hits", {}).get("hits", [])

        results = _merge_hybrid(bm25_hits, knn_hits, page, page_size, sort, fusion=HYBRID_FUSION)
    elif actual_mode == "semantic" and query_vector:
        # kNN-only
        payload: dict[str, Any] = {
            "size": page_size,
            "knn": {
                "field": "embedding",
                "query_vector": query_vector,
                "k": page_size * 2,
                "num_candidates": max(page_size * 10, 200),
                "filter": filters or [{"match_all": {}}],
            },
            "_source": source_fields,
        }
        data = ES.request("POST", f"/{ES.index}/_search", payload)
        hits = data.get("hits", {}).get("hits", [])
        total = int(data.get("hits", {}).get("total", {}).get("value", 0))
        results = _format_hits(hits)
    else:
        # BM25-only
        payload = {
            "from": (page - 1) * page_size,
            "size": page_size,
            "track_total_hits": True,
            "query": {"bool": {"must": [_query_clause(interpreted_query)], "filter": filters}},
            "sort": _sort_clause(sort),
            "_source": source_fields,
            "highlight": highlight_spec,
        }
        data = ES.request("POST", f"/{ES.index}/_search", payload)
        hits = data.get("hits", {}).get("hits", [])
        total = int(data.get("hits", {}).get("total", {}).get("value", 0))
        results = _format_hits(hits)

    return {
        "query": query,
        "mode": actual_mode,
        "mode_requested": mode,
        "mode_fallback": actual_mode != mode,
        "mode_fallback_reason": "coverage_gate" if coverage_gated else ("embed_unavailable" if actual_mode != mode else None),
        "fusion": HYBRID_FUSION if actual_mode == "hybrid" else None,
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": (page * page_size) < total,
        "sort": sort,
        **_search_context_payload(
            original_query=query,
            interpreted_query=interpreted_query,
            requested_section=requested_section,
            requested_art_type=requested_art_type,
            requested_issuing_organ=requested_issuing_organ,
            applied_section=section,
            applied_art_type=art_type,
            applied_issuing_organ=issuing_organ,
        ),
        "filters": {
            "date_from": date_from, "date_to": date_to,
            "section": section, "art_type": art_type, "issuing_organ": issuing_organ,
        },
        "results": results,
    }


def es_suggest(prefix: str, limit: int = 10) -> dict[str, Any]:
    """Autocomplete suggestions from title, organ and type fields."""
    p = prefix.strip()
    if not p:
        return {"prefix": prefix, "suggestions": []}
    limit = max(1, min(limit, 20))
    payload = {
        "size": max(limit * 4, 40),
        "_source": ["identifica", "issuing_organ", "art_type"],
        "query": {
            "bool": {
                "should": [
                    {"match_phrase_prefix": {"identifica": {"query": p}}},
                    {"match_phrase_prefix": {"issuing_organ": {"query": p}}},
                    {"match_phrase_prefix": {"art_type": {"query": p}}},
                ],
                "minimum_should_match": 1,
            }
        },
    }
    data = ES.request("POST", f"/{ES.index}/_search", payload)
    hits = data.get("hits", {}).get("hits", [])
    bucket: dict[tuple[str, str], int] = {}
    needle = p.lower()
    for hit in hits:
        src = hit.get("_source", {})
        candidates = [
            ("titulo", (src.get("identifica") or "").strip()),
            ("orgao", (src.get("issuing_organ") or "").strip()),
            ("tipo", (src.get("art_type") or "").strip()),
        ]
        for cat, term in candidates:
            if not term:
                continue
            if needle not in term.lower():
                continue
            key = (cat, term)
            bucket[key] = bucket.get(key, 0) + 1

    ranked = sorted(bucket.items(), key=lambda x: x[1], reverse=True)[:limit]
    return {
        "prefix": prefix,
        "suggestions": [{"cat": cat, "term": term, "doc_freq": cnt} for (cat, term), cnt in ranked],
    }


def es_facets(
    query: str = "*",
    date_from: str | None = None,
    date_to: str | None = None,
    section: str | None = None,
    art_type: str | None = None,
    issuing_organ: str | None = None,
    size: int = 10,
) -> dict[str, Any]:
    """Facet aggregations for sections, types, organs, and date histogram."""
    size = max(1, min(size, 30))
    filters = _build_filters(
        date_from=date_from, date_to=date_to,
        section=section, art_type=art_type, issuing_organ=issuing_organ,
    )
    payload = {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": {"must": [_query_clause(query)], "filter": filters}},
        "aggs": {
            "sections": {"terms": {"field": "edition_section", "size": 10}},
            "types": {"terms": {"field": "art_type.keyword", "size": size}},
            "organs": {"terms": {"field": "issuing_organ.keyword", "size": size}},
            "by_month": {"date_histogram": {"field": "pub_date", "calendar_interval": "month"}},
        },
    }
    data = ES.request("POST", f"/{ES.index}/_search", payload)
    aggs = data.get("aggregations", {})
    total = int(data.get("hits", {}).get("total", {}).get("value", 0))

    def _b(name: str) -> list[dict[str, Any]]:
        return [{"key": x.get("key"), "count": x.get("doc_count", 0)} for x in aggs.get(name, {}).get("buckets", [])]

    return {
        "query": query,
        "total": total,
        "facets": {
            "sections": _b("sections"),
            "types": _b("types"),
            "organs": _b("organs"),
            "by_month": _b("by_month"),
        },
    }


def es_document(doc_id: str) -> dict[str, Any]:
    """Fetch a single indexed document by its doc_id."""
    data = ES.request("GET", f"/{ES.index}/_doc/{doc_id}")
    if not data.get("found"):
        return {"found": False, "doc_id": doc_id}
    src = data.get("_source", {})
    return {"found": True, "doc_id": doc_id, "document": src}


def es_health() -> dict[str, Any]:
    """Cluster and index health summary, including embedding server status."""
    health = ES.request("GET", "/_cluster/health")
    count = ES.request("GET", f"/{ES.index}/_count")

    # Check embedding server
    embed_status = "unavailable"
    embed_info: dict[str, Any] = {}
    try:
        resp = httpx.get(f"{EMBED_URL}/health", timeout=5)
        if resp.status_code == 200:
            embed_info = resp.json()
            embed_status = "ok"
    except Exception:
        pass

    # Count docs with embeddings
    embed_count = 0
    try:
        ec = ES.request("GET", f"/{ES.index}/_count", {"query": {"exists": {"field": "embedding"}}})
        embed_count = int(ec.get("count", 0))
    except Exception:
        pass

    return {
        "search_backend": "hybrid" if embed_status == "ok" else "bm25",
        "search_modes": ["bm25", "semantic", "hybrid"] if embed_status == "ok" else ["bm25"],
        "cluster_name": health.get("cluster_name"),
        "cluster_status": health.get("status"),
        "number_of_nodes": health.get("number_of_nodes"),
        "active_shards": health.get("active_shards"),
        "index": ES.index,
        "index_count": int(count.get("count", 0)),
        "embedding_count": embed_count,
        "embedding_pct": round(embed_count / max(int(count.get("count", 1)), 1) * 100, 1),
        "hybrid_fusion": HYBRID_FUSION,
        "hybrid_alpha": HYBRID_ALPHA,
        "coverage_gate_pct": HYBRID_COVERAGE_GATE,
        "coverage_gated": embed_count / max(int(count.get("count", 1)), 1) * 100 < HYBRID_COVERAGE_GATE,
        "embed_server": {"url": EMBED_URL, "status": embed_status, **embed_info},
    }


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------

if FastMCP is not None:
    mcp = FastMCP(
        "GABI Elasticsearch MCP",
        instructions=(
            "Professional search server for Diário Oficial da União (DOU). "
            "Supports hybrid search (BM25 + semantic kNN) over ~16M documents (2002-2026). "
            "Default mode is 'hybrid' which combines keyword and semantic matching. "
            "Use 'bm25' for exact keyword matches, 'semantic' for conceptual similarity. "
            "Use Portuguese terms, apply filters when possible, and prefer precise queries."
        ),
    )
    mcp.tool()(es_search)
    mcp.tool()(es_suggest)
    mcp.tool()(es_facets)
    mcp.tool()(es_document)
    mcp.tool()(es_health)
else:
    mcp = None


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="GABI Elasticsearch MCP Server")
    p.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    p.add_argument("--port", type=int, default=8766)
    args = p.parse_args()

    if mcp is None:
        raise SystemExit("mcp package is not installed.")

    if args.transport == "sse":
        mcp.settings.port = args.port
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
