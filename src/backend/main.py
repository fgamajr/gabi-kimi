import logging
import re
from contextlib import asynccontextmanager
from typing import Any, Optional

import httpx
from fastapi import FastAPI, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from src.backend.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ES async client (created once at startup)
# ---------------------------------------------------------------------------

_es: httpx.AsyncClient | None = None


def _es_url(path: str) -> str:
    return f"{settings.ES_URL}{path}"


async def es_request(method: str, path: str, json: dict | None = None) -> dict:
    assert _es is not None
    resp = await _es.request(method, _es_url(path), json=json, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _es
    _es = httpx.AsyncClient()
    logger.info("GABI API started — ES=%s, index=%s", settings.ES_URL, settings.ES_INDEX)
    yield
    if _es:
        await _es.aclose()


app = FastAPI(title="GABI DOU API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://localhost:5173",
        "http://[::]:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SECTION_ES_TO_FE = {"DO1": "1", "DO2": "2", "DO3": "3", "DOE": "e", "DO1a": "e"}
_SECTION_FE_TO_ES = {v: k for k, v in _SECTION_ES_TO_FE.items()}
# Extra editions can have various prefixes
_SECTION_FE_TO_ES["e"] = "DOE"


def _section_to_frontend(es_val: str | None) -> str:
    if not es_val:
        return ""
    return _SECTION_ES_TO_FE.get(es_val, es_val.replace("DO", "").lower() or es_val)


_SECTION_NAMES = {"1": "Seção 1", "2": "Seção 2", "3": "Seção 3", "e": "Extra"}


def _section_to_es(fe_val: str) -> str | None:
    return _SECTION_FE_TO_ES.get(fe_val)


def _hl_to_html(text: str) -> str:
    """Convert ES highlight markers >>>…<<< to <mark>…</mark>, escaping other HTML."""
    import html
    # Temporarily replace our markers, escape everything, then restore markers
    text = text.replace(">>>", "\x00MARK_OPEN\x00").replace("<<<", "\x00MARK_CLOSE\x00")
    text = html.escape(text)
    text = text.replace("\x00MARK_OPEN\x00", "<mark>").replace("\x00MARK_CLOSE\x00", "</mark>")
    return text


_HIGHLIGHT_SPEC: dict[str, Any] = {
    "pre_tags": [">>>"],
    "post_tags": ["<<<"],
    "max_analyzed_offset": 500000,
    "fields": {
        "identifica": {"number_of_fragments": 0},
        "ementa": {"number_of_fragments": 1, "fragment_size": 280},
        "body_plain": {"number_of_fragments": 2, "fragment_size": 200},
    },
}

_SOURCE_FIELDS = [
    "doc_id", "identifica", "ementa", "art_type", "art_category",
    "pub_date", "edition_section", "edition_number", "page_number",
    "issuing_organ", "body_plain",
]


def _hit_to_result(hit: dict) -> dict:
    src = hit.get("_source", {})
    hl = hit.get("highlight", {})

    # Build snippet from highlights
    snippet_parts: list[str] = []
    for k in ("ementa", "identifica", "body_plain"):
        frags = hl.get(k)
        if frags:
            snippet_parts.extend(frags)
            if len(snippet_parts) >= 2:
                break
    raw_snippet = " … ".join(snippet_parts) if snippet_parts else (
        src.get("ementa") or src.get("body_plain") or ""
    )[:280]

    return {
        "id": src.get("doc_id") or hit.get("_id"),
        "title": src.get("identifica") or "",
        "subtitle": src.get("ementa") or "",
        "snippet": re.sub(r">>>|<<<", "", raw_snippet),
        "highlight": _hl_to_html(raw_snippet) if snippet_parts else None,
        "pub_date": src.get("pub_date") or "",
        "section": _section_to_frontend(src.get("edition_section")),
        "page": src.get("page_number"),
        "art_type": src.get("art_type"),
        "issuing_organ": src.get("issuing_organ"),
        "dou_url": None,
    }


def _build_filters(
    date_from: str | None,
    date_to: str | None,
    section: str | None,
    art_type: str | None,
    issuing_organ: str | None,
) -> list[dict]:
    filters: list[dict] = []
    if date_from or date_to:
        r: dict[str, str] = {}
        date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        if date_from and date_re.match(date_from):
            r["gte"] = date_from
        if date_to and date_re.match(date_to):
            r["lte"] = date_to
        if r:
            filters.append({"range": {"pub_date": r}})
    if section:
        es_sec = _section_to_es(section)
        if es_sec:
            filters.append({"term": {"edition_section": es_sec}})
    if art_type:
        filters.append({"term": {"art_type.keyword": art_type}})
    if issuing_organ:
        filters.append({"match_phrase": {"issuing_organ": issuing_organ}})
    return filters


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {"message": "GABI DOU API is running"}


@app.get("/api/search")
async def search(
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    max: int = Query(20, ge=1, le=100),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    section: Optional[str] = None,
    art_type: Optional[str] = None,
    issuing_organ: Optional[str] = None,
):
    es_from = (page - 1) * max
    filters = _build_filters(date_from, date_to, section, art_type, issuing_organ)

    query: dict[str, Any] = {
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
            "must": [query],
            "should": should,
        }
    }
    if filters:
        bool_query["bool"]["filter"] = filters

    # Recency decay
    final_query: dict[str, Any] = {
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

    payload: dict[str, Any] = {
        "from": es_from,
        "size": max,
        "track_total_hits": True,
        "query": final_query,
        "sort": [{"_score": {"order": "desc"}}, {"pub_date": {"order": "desc"}}],
        "_source": _SOURCE_FIELDS,
        "highlight": _HIGHLIGHT_SPEC,
    }

    try:
        data = await es_request("POST", f"/{settings.ES_INDEX}/_search", json=payload)
    except httpx.HTTPStatusError as e:
        logger.error("ES search error: %s", e.response.text[:200])
        return {"results": [], "total": 0, "page": page, "max": max, "query": q, "took_ms": 0}

    hits = data.get("hits", {}).get("hits", [])
    total = int(data.get("hits", {}).get("total", {}).get("value", 0))
    took = data.get("took", 0)

    return {
        "results": [_hit_to_result(h) for h in hits],
        "total": total,
        "page": page,
        "max": max,
        "query": q,
        "took_ms": took,
    }


@app.get("/api/autocomplete")
async def autocomplete(
    q: str = Query(..., min_length=1),
    n: int = Query(8, ge=1, le=20),
):
    p = q.strip()
    if not p:
        return []

    payload = {
        "size": n * 4,
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

    data = await es_request("POST", f"/{settings.ES_INDEX}/_search", json=payload)
    hits = data.get("hits", {}).get("hits", [])

    seen: set[str] = set()
    results: list[dict] = []
    needle = p.lower()

    for hit in hits:
        src = hit.get("_source", {})
        candidates = [
            ("titulo", (src.get("identifica") or "").strip()),
            ("orgao", (src.get("issuing_organ") or "").strip()),
            ("tipo", (src.get("art_type") or "").strip()),
        ]
        for cat, term in candidates:
            if not term or needle not in term.lower():
                continue
            key = term.lower()
            if key not in seen:
                seen.add(key)
                results.append({"suggestion": term, "type": cat})
                if len(results) >= n:
                    break
        if len(results) >= n:
            break

    return results


@app.get("/api/document/{doc_id}")
async def document(doc_id: str):
    # Fetch full document from ES (all fields)
    try:
        data = await es_request("GET", f"/{settings.ES_INDEX}/_doc/{doc_id}")
        src = data.get("_source", {})
    except httpx.HTTPStatusError:
        return Response(status_code=404, content='{"detail":"Document not found"}',
                        media_type="application/json")

    section = _section_to_frontend(src.get("edition_section"))
    body_plain = src.get("body_plain") or ""

    return {
        "id": doc_id,
        "title": src.get("identifica") or "",
        "subtitle": src.get("ementa") or "",
        "body_html": None,
        "body_plain": body_plain,
        "pub_date": src.get("pub_date") or "",
        "section": section,
        "section_name": _SECTION_NAMES.get(section),
        "page": src.get("page_number"),
        "edition": src.get("edition_number"),
        "art_type": src.get("art_type"),
        "art_type_name": src.get("art_type"),
        "issuing_organ": src.get("issuing_organ"),
        "dou_url": None,
        "media": [],
        "identifica": src.get("identifica"),
        "ementa": src.get("ementa"),
        "assinatura": None,
    }


@app.get("/api/stats")
async def stats():
    count_data = await es_request("GET", f"/{settings.ES_INDEX}/_count")
    total = count_data.get("count", 0)

    agg_payload = {
        "size": 0,
        "aggs": {
            "min_date": {"min": {"field": "pub_date"}},
            "max_date": {"max": {"field": "pub_date"}},
            "sections": {"terms": {"field": "edition_section", "size": 10}},
        },
    }
    agg_data = await es_request("POST", f"/{settings.ES_INDEX}/_search", json=agg_payload)
    aggs = agg_data.get("aggregations", {})

    min_date = aggs.get("min_date", {}).get("value_as_string", "")
    max_date = aggs.get("max_date", {}).get("value_as_string", "")
    sections_count = len(aggs.get("sections", {}).get("buckets", []))

    return {
        "total_documents": total,
        "total_sections": sections_count,
        "date_range": {"min": min_date[:10] if min_date else "", "max": max_date[:10] if max_date else ""},
        "last_updated": max_date[:10] if max_date else None,
    }


@app.get("/api/types")
async def types():
    payload = {
        "size": 0,
        "aggs": {
            "types": {"terms": {"field": "art_type.keyword", "size": 200}},
        },
    }
    data = await es_request("POST", f"/{settings.ES_INDEX}/_search", json=payload)
    buckets = data.get("aggregations", {}).get("types", {}).get("buckets", [])

    return [
        {"value": b["key"], "label": b["key"], "count": b["doc_count"]}
        for b in buckets
    ]


@app.get("/api/top-searches")
async def top_searches():
    return [
        {"query": "concurso público", "count": 4820},
        {"query": "nomeação", "count": 3915},
        {"query": "portaria", "count": 3750},
        {"query": "licitação", "count": 2890},
        {"query": "LGPD", "count": 2410},
        {"query": "aposentadoria", "count": 2105},
        {"query": "pregão eletrônico", "count": 1890},
        {"query": "decreto", "count": 1760},
        {"query": "exoneração", "count": 1550},
        {"query": "resolução", "count": 1320},
    ]


@app.get("/api/search-examples")
async def search_examples():
    return [
        {"query": "Lei 14133 licitações", "description": "Nova Lei de Licitações"},
        {"query": "concurso público federal 2024", "description": "Concursos abertos"},
        {"query": '"Lei Geral de Proteção de Dados"', "description": "LGPD — busca exata"},
        {"query": "nomeação cargo comissionado", "description": "Nomeações DAS/FCPE"},
        {"query": "pregão eletrônico registro preços", "description": "Pregões SRP"},
        {"query": "aposentadoria servidor público", "description": "Aposentadorias"},
    ]


@app.get("/api/media/{doc_id:path}/{name}")
async def media(doc_id: str, name: str):
    return Response(status_code=404, content='{"detail":"Media not available"}',
                    media_type="application/json")
