"""Self-contained MCP server for DOU search with Elasticsearch BM25.

No dependency on adapters.py — filter inference is inlined.

Usage:
  python ops/bin/mcp_es_server.py
  python ops/bin/mcp_es_server.py --transport sse --port 8766
"""

from __future__ import annotations

import os
import re
from typing import Any

import httpx
from dotenv import load_dotenv

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

    def close(self) -> None:
        self._client.close()


ES = ElasticClient()


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
        filters.append({"term": {"art_type.keyword": art_type}})
    if issuing_organ:
        filters.append({"term": {"issuing_organ.keyword": issuing_organ}})
    return filters


def _query_clause(query: str) -> dict[str, Any]:
    q = query.strip()
    if q == "*" or not q:
        return {"match_all": {}}
    return {
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
        }
    }


def _sort_clause(sort: str) -> list[dict[str, Any]]:
    if sort == "date_desc":
        return [{"pub_date": {"order": "desc"}}, {"_score": {"order": "desc"}}]
    if sort == "date_asc":
        return [{"pub_date": {"order": "asc"}}, {"_score": {"order": "desc"}}]
    return [{"_score": {"order": "desc"}}, {"pub_date": {"order": "desc"}}]


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

def es_search(
    query: str,
    page: int = 1,
    page_size: int = 20,
    sort: str = "relevance",
    date_from: str | None = None,
    date_to: str | None = None,
    section: str | None = None,
    art_type: str | None = None,
    issuing_organ: str | None = None,
) -> dict[str, Any]:
    """Search DOU documents with BM25 full-text search, filters, highlights, and pagination.

    Args:
      query: search query in Portuguese, or '*' for browse mode
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
    payload = {
        "from": (page - 1) * page_size,
        "size": page_size,
        "track_total_hits": True,
        "query": {"bool": {"must": [_query_clause(interpreted_query)], "filter": filters}},
        "sort": _sort_clause(sort),
        "_source": [
            "doc_id", "identifica", "ementa", "art_type", "art_category",
            "pub_date", "edition_section", "issuing_organ", "body_plain",
        ],
        "highlight": {
            "pre_tags": [">>>"],
            "post_tags": ["<<<"],
            "fields": {
                "identifica": {"number_of_fragments": 0},
                "ementa": {"number_of_fragments": 1, "fragment_size": 220},
                "body_plain": {"number_of_fragments": 1, "fragment_size": 220},
            },
        },
    }
    data = ES.request("POST", f"/{ES.index}/_search", payload)
    hits = data.get("hits", {}).get("hits", [])
    total = int(data.get("hits", {}).get("total", {}).get("value", 0))

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

    return {
        "query": query,
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
    """Cluster and index health summary."""
    health = ES.request("GET", "/_cluster/health")
    count = ES.request("GET", f"/{ES.index}/_count")
    return {
        "search_backend": "bm25",
        "cluster_name": health.get("cluster_name"),
        "cluster_status": health.get("status"),
        "number_of_nodes": health.get("number_of_nodes"),
        "active_shards": health.get("active_shards"),
        "index": ES.index,
        "index_count": int(count.get("count", 0)),
    }


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------

if FastMCP is not None:
    mcp = FastMCP(
        "GABI Elasticsearch MCP",
        instructions=(
            "Professional search server for Diário Oficial da União (DOU). "
            "Supports BM25 full-text search over ~7M documents (2002-2025). "
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
