import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

from src.backend.core.config import settings
from src.backend.data.db import MongoDB
from src.backend.search.hybrid import hybrid_search
from src.backend.search.reranker import rerank
from src.backend.search.trending import FALLBACK_TOPICS, get_cached_trending, update_trending_cache
from src.backend.seo import (
    build_sitemap_index,
    build_sitemap_urls,
    is_template_loaded,
    load_spa_template,
    render_document_html,
    render_fallback_html,
    render_home_html,
    render_search_html,
)

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
    load_spa_template()
    logger.info("GABI API started — ES=%s, index=%s", settings.ES_URL, settings.es_target_index)
    yield
    if _es:
        await _es.aclose()


app = FastAPI(title="GABI DOU API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Validate-if-present bearer token auth.

    - No GABI_API_TOKENS configured → all requests pass (dev mode).
    - Request has no Authorization header → pass through (public frontend).
    - Request has Authorization: Bearer <token> → validate, 401 if invalid.
    """

    async def dispatch(self, request: StarletteRequest, call_next):
        if not settings.api_tokens:
            return await call_next(request)

        # MCP endpoint handles its own auth via MCP_AUTH_TOKEN
        if request.url.path.startswith("/mcp"):
            return await call_next(request)

        auth_header = request.headers.get("authorization")
        if auth_header:
            if not auth_header.startswith("Bearer "):
                return JSONResponse(status_code=401, content={"detail": "Invalid authorization header"})
            token = auth_header[7:]
            if token not in settings.api_tokens:
                return JSONResponse(status_code=401, content={"detail": "Invalid API token"})
            request.state.token_label = settings.api_tokens[token]

        return await call_next(request)


app.add_middleware(TokenAuthMiddleware)

# ---------------------------------------------------------------------------
# MCP SSE endpoint (mounted at /mcp/)
# ---------------------------------------------------------------------------

try:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "ops" / "bin"))
    from mcp_es_server import get_mcp_sse_app

    _mcp_app = get_mcp_sse_app()
    if _mcp_app:
        app.mount("/mcp", _mcp_app)
        logger.info("MCP SSE endpoint mounted at /mcp/")
except Exception as exc:
    logger.warning("MCP SSE endpoint not available: %s", exc)

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
    upper = es_val.upper()
    return _SECTION_ES_TO_FE.get(upper, upper.replace("DO", "").lower() or es_val)


_SECTION_NAMES = {"1": "Seção 1", "2": "Seção 2", "3": "Seção 3", "e": "Extra"}
_mongo_db = MongoDB.get_db()


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


def _art_type_label(value: str) -> str:
    label = value.replace("-", " ")
    return " ".join(part.capitalize() for part in label.split())


def _normalize_match_text(value: str | None) -> str:
    if not value:
        return ""
    import unicodedata

    normalized = unicodedata.normalize("NFD", value.lower().strip())
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", normalized)


def _days_since(pub_date: str | None) -> int:
    if not pub_date:
        return 999
    try:
        parsed = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.fromisoformat(f"{pub_date}T00:00:00+00:00")
        except ValueError:
            return 999
    return max((datetime.now(timezone.utc).date() - parsed.date()).days, 0)


def _recent_highlight_score(hit: dict[str, Any]) -> tuple[float, list[str]]:
    src = hit.get("_source", {})
    title = src.get("identifica") or ""
    subtitle = src.get("ementa") or ""
    organ = src.get("issuing_organ") or ""
    text = " ".join(part for part in [title, subtitle, organ] if part)
    norm_text = _normalize_match_text(text)
    art_type_normalized = _normalize_match_text(src.get("art_type_normalized") or src.get("art_type") or "")
    section = _section_to_frontend(src.get("section") or src.get("edition_section"))
    days_old = _days_since(src.get("pub_date"))

    score = max(18 - days_old, 0) * 0.8
    reasons: list[str] = []

    if days_old <= 3:
        score += 6
        reasons.append("muito recente")
    elif days_old <= 7:
        score += 3

    if section == "1":
        score += 4
        reasons.append("seção 1")
    elif section == "3":
        score -= 4
    elif section == "2":
        score -= 2

    for act_type, boost in _RECENT_ART_TYPE_BOOSTS.items():
        if act_type in art_type_normalized:
            score += boost
            if len(reasons) < 3:
                reasons.append(act_type)
            break

    for term, boost in _RECENT_RELEVANT_TERMS.items():
        if term in norm_text:
            score += boost
            if len(reasons) < 3:
                reasons.append(term)

    for term, penalty in _RECENT_NOISE_TERMS.items():
        if term in norm_text:
            score += penalty

    if any(pattern in _normalize_match_text(organ) for pattern in _RECENT_ORGAN_BOOST_PATTERNS):
        score += 2.5
        if len(reasons) < 3:
            reasons.append("órgão relevante")

    if len(title.split()) <= 4 and "nº" not in _normalize_match_text(title):
        score -= 2

    return score, reasons[:3]


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
    "pub_date", "section", "edition_number", "page_number",
    "issuing_organ", "organization_path", "body_plain",
]

_LATEST_SOURCE_FIELDS = [
    "doc_id", "identifica", "ementa", "art_type", "art_type_normalized", "pub_date",
    "section", "edition_section", "page_number", "issuing_organ",
]

_RECENT_ART_TYPE_BOOSTS = {
    "edital": 7.0,
    "resolucao": 6.0,
    "instrucao normativa": 6.0,
    "instrução normativa": 6.0,
    "decreto": 5.5,
    "lei": 5.0,
    "medida provisoria": 5.0,
    "medida provisória": 5.0,
    "aviso": 3.0,
    "portaria": 1.5,
}

_RECENT_ORGAN_BOOST_PATTERNS = (
    "presidencia",
    "presidência",
    "ministerio",
    "ministério",
    "autoridade nacional de protecao de dados",
    "anpd",
    "banco central",
    "anvisa",
    "cvm",
    "mec",
    "saude",
    "saúde",
    "fazenda",
    "tcu",
)

_RECENT_RELEVANT_TERMS = {
    "concurso": 6.0,
    "edital": 5.5,
    "consulta publica": 6.0,
    "consulta pública": 6.0,
    "chamamento publico": 5.5,
    "chamamento público": 5.5,
    "regulamenta": 4.5,
    "altera": 3.5,
    "aprova": 3.0,
    "licitacao": 4.5,
    "licitação": 4.5,
    "pregao": 4.0,
    "pregão": 4.0,
    "credenciamento": 2.0,
    "anpd": 5.0,
    "lgpd": 5.0,
}

_RECENT_NOISE_TERMS = {
    "nomeacao": -8.0,
    "nomeação": -8.0,
    "nomeacoes": -8.0,
    "nomeações": -8.0,
    "exoneracao": -8.0,
    "exoneração": -8.0,
    "designacao": -7.0,
    "designação": -7.0,
    "dispensa": -5.0,
    "aposentadoria": -6.0,
    "pensao": -6.0,
    "pensão": -6.0,
    "ferias": -7.0,
    "férias": -7.0,
    "licenca": -6.0,
    "licença": -6.0,
    "substituicao": -6.0,
    "substituição": -6.0,
    "portaria de pessoal": -9.0,
    "servidor": -3.0,
    "extrato": -6.0,
    "apostila": -6.0,
    "cessao": -6.0,
    "cessão": -6.0,
}


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

    # Top-level organ from organization_path (e.g. "Ministério da Defesa")
    org_path = src.get("organization_path") or []
    top_organ = org_path[0] if org_path else None

    return {
        "id": src.get("doc_id") or hit.get("_id"),
        "title": src.get("identifica") or "",
        "subtitle": src.get("ementa") or "",
        "snippet": re.sub(r">>>|<<<", "", raw_snippet),
        "highlight": _hl_to_html(raw_snippet) if snippet_parts else None,
        "pub_date": src.get("pub_date") or "",
        "section": _section_to_frontend(src.get("section")),
        "page": src.get("page_number"),
        "art_type": src.get("art_type"),
        "issuing_organ": src.get("issuing_organ"),
        "top_organ": top_organ,
        "dou_url": None,
    }


def _build_filters(
    date_from: str | None,
    date_to: str | None,
    section: str | None,
    art_type: str | None,
    issuing_organ: str | None,
    topic: str | None = None,
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
            # Match both uppercase (DO1) and lowercase (do1) variants
            variants = [es_sec, es_sec.lower()]
            filters.append(
                {
                    "bool": {
                        "should": [
                            {"terms": {"section": variants}},
                            {"terms": {"edition_section": variants}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )
    if art_type:
        filters.append({"term": {"art_type_normalized": art_type.lower()}})
    if issuing_organ:
        filters.append({"match_phrase": {"issuing_organ": issuing_organ}})
    if topic:
        filters.append({"term": {"topics": topic}})
    return filters


# ---------------------------------------------------------------------------
# TCU index support
# ---------------------------------------------------------------------------

_TCU_INDEX = "gabi_tcu_acordaos_v1"
_OPENAI_EMBED_MODEL = "text-embedding-3-small"
_OPENAI_EMBED_DIMS = 384


async def _get_openai_query_embedding(query: str) -> list[float] | None:
    """Get query embedding via OpenAI API. Returns None if unavailable."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key or not settings.VECTOR_SEARCH_ENABLED:
        return None
    try:
        assert _es is not None
        resp = await _es.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": _OPENAI_EMBED_MODEL, "input": [query], "dimensions": _OPENAI_EMBED_DIMS},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["data"][0]["embedding"]
    except Exception:
        logger.warning("OpenAI embedding failed, falling back to BM25-only", exc_info=True)
        return None


def _tcu_hit_to_result(hit: dict) -> dict:
    src = hit.get("_source", {})
    hl = hit.get("highlight", {})

    snippet_parts: list[str] = []
    for k in ("sumario", "titulo", "acordao_texto", "search_all"):
        frags = hl.get(k)
        if frags:
            snippet_parts.extend(frags)
            if len(snippet_parts) >= 2:
                break
    raw_snippet = " … ".join(snippet_parts) if snippet_parts else (
        src.get("sumario") or src.get("acordao_texto") or ""
    )[:280]

    return {
        "id": src.get("doc_id") or hit.get("_id"),
        "title": src.get("titulo") or "",
        "subtitle": src.get("sumario") or "",
        "snippet": re.sub(r">>>|<<<", "", raw_snippet),
        "highlight": _hl_to_html(raw_snippet) if snippet_parts else None,
        "pub_date": src.get("data_sessao") or "",
        "section": src.get("colegiado") or "",
        "page": None,
        "art_type": src.get("tipo") or "Acórdão TCU",
        "issuing_organ": "Tribunal de Contas da União",
        "top_organ": "Tribunal de Contas da União",
        "dou_url": None,
        "source_type": "tcu_acordao",
        "relator": src.get("relator"),
        "tipo_processo": src.get("tipo_processo"),
        "colegiado": src.get("colegiado"),
        "dispositivo_resumo": src.get("dispositivo_resumo"),
    }


async def _tcu_search(
    *,
    q: str,
    page: int,
    max_results: int,
    offset: int,
    date_from: str | None,
    date_to: str | None,
    source: str,
) -> dict:
    """Search TCU index directly via ES."""
    if source == "all":
        index = f"{settings.es_target_index},{_TCU_INDEX}"
    else:
        index = _TCU_INDEX

    filters: list[dict] = []
    if date_from or date_to:
        rng: dict[str, str] = {}
        if date_from:
            rng["gte"] = date_from
        if date_to:
            rng["lte"] = date_to
        if source == "all":
            filters.append({"bool": {"should": [
                {"range": {"pub_date": rng}},
                {"range": {"data_sessao": rng}},
            ], "minimum_should_match": 1}})
        else:
            filters.append({"range": {"data_sessao": rng}})

    if source == "tcu":
        fields = [
            "titulo^5", "sumario^4", "assunto^3",
            "relator^2", "entidade^2", "acordao_texto", "search_all",
        ]
    else:
        fields = [
            "titulo^5", "identifica^5", "sumario^4", "ementa^4",
            "assunto^3", "issuing_organ^2", "relator^2",
            "acordao_texto", "body_plain", "search_all",
        ]

    bm25_query: dict = {
        "bool": {
            "must": [{
                "simple_query_string": {
                    "query": q,
                    "fields": fields,
                    "default_operator": "and",
                },
            }],
            "filter": filters,
        },
    }

    highlight_spec: dict = {
        "pre_tags": [">>>"], "post_tags": ["<<<"],
        "max_analyzed_offset": 500000,
        "fields": {
            "titulo": {"number_of_fragments": 0},
            "sumario": {"number_of_fragments": 1, "fragment_size": 280},
            "acordao_texto": {"number_of_fragments": 2, "fragment_size": 200},
            "identifica": {"number_of_fragments": 0},
            "ementa": {"number_of_fragments": 1, "fragment_size": 280},
            "body_plain": {"number_of_fragments": 2, "fragment_size": 200},
        },
    }

    # Try hybrid search with kNN if embeddings available
    query_vector = await _get_openai_query_embedding(q)
    if query_vector is not None and source == "tcu":
        knn_filter = filters if filters else None
        payload = {
            "retriever": {
                "rrf": {
                    "retrievers": [
                        {"standard": {"query": bm25_query}},
                        {
                            "knn": {
                                "field": "embedding",
                                "query_vector": query_vector,
                                "k": min(max_results, 50),
                                "num_candidates": min(max_results * 2, 200),
                                **({"filter": {"bool": {"filter": knn_filter}}} if knn_filter else {}),
                            }
                        },
                    ],
                    "rank_window_size": min(max_results * 2, 200),
                    "rank_constant": 60,
                }
            },
            "from": offset,
            "size": max_results,
            "track_total_hits": True,
            "highlight": highlight_spec,
        }
    else:
        payload = {
            "from": offset,
            "size": max_results,
            "track_total_hits": True,
            "query": bm25_query,
            "highlight": highlight_spec,
            "sort": [{"_score": {"order": "desc"}}],
        }

    try:
        data = await es_request("POST", f"/{index}/_search", json=payload)
    except httpx.HTTPStatusError as e:
        logger.error("TCU search error: %s", e.response.text[:200])
        return {"results": [], "total": 0, "page": page, "max": max_results, "query": q, "took_ms": 0}

    hits = data.get("hits", {}).get("hits", [])
    total = int(data.get("hits", {}).get("total", {}).get("value", 0))
    took = data.get("took", 0)

    results = []
    for hit in hits:
        src = hit.get("_source", {})
        if src.get("source_type") == "tcu_acordao":
            results.append(_tcu_hit_to_result(hit))
        else:
            results.append(_hit_to_result(hit))

    return {
        "results": results,
        "total": total,
        "page": page,
        "max": max_results,
        "query": q,
        "took_ms": took,
        "source": source,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/root")
async def api_root():
    return {"message": "GABI DOU API is running"}


@app.get("/api/health")
async def health():
    try:
        cluster = await es_request("GET", "/_cluster/health")
    except Exception as exc:
        logger.warning("health check failed to reach ES: %s", exc)
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "elasticsearch": False,
                "index": settings.es_target_index,
                "reranker_enabled": settings.RERANKER_ENABLED,
            },
        )

    return {
        "status": "ok",
        "elasticsearch": True,
        "es_cluster_status": cluster.get("status"),
        "index": settings.es_target_index,
        "reranker_enabled": settings.RERANKER_ENABLED,
    }


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
    intent: Optional[str] = None,
    is_trending: bool = False,
    topic: Optional[str] = None,
    source: Optional[str] = None,
):
    offset = (page - 1) * max

    # TCU search: direct ES query to TCU index
    if source in ("tcu", "all"):
        return await _tcu_search(q=q, page=page, max_results=max, offset=offset,
                                 date_from=date_from, date_to=date_to, source=source)

    filters = _build_filters(date_from, date_to, section, art_type, issuing_organ, topic)

    use_hybrid = settings.VECTOR_SEARCH_ENABLED
    use_reranker = settings.RERANKER_ENABLED

    # When reranking, fetch more candidates from ES for the reranker to sort
    es_size = settings.RERANKER_TOP_K if use_reranker else max
    es_from = 0 if use_reranker else offset

    try:
        data = await hybrid_search(
            query=q,
            filters=filters,
            size=es_size,
            from_=es_from,
            source_fields=_SOURCE_FIELDS,
            highlight_spec=_HIGHLIGHT_SPEC,
            client=_es,
            is_trending=is_trending,
            intent=intent,
        )
    except httpx.HTTPStatusError as e:
        logger.error("ES search error: %s", e.response.text[:200])
        return {"results": [], "total": 0, "page": page, "max": max, "query": q, "took_ms": 0}

    hits = data.get("hits", {}).get("hits", [])
    total = int(data.get("hits", {}).get("total", {}).get("value", 0))
    took = data.get("took", 0)
    intent_data = data.get("_intent")

    if use_reranker and hits:
        hits = await rerank(q, hits, top_k=settings.RERANKER_TOP_K, client=_es)
        page_hits = hits[offset : offset + max]
        results = [_hit_to_result(h) for h in page_hits]
    else:
        results = [_hit_to_result(h) for h in hits]

    response = {
        "results": results,
        "total": total,
        "page": page,
        "max": max,
        "query": q,
        "took_ms": took,
    }
    if intent_data:
        response["intent"] = intent_data
        if intent_data.get("suggestion"):
            response["suggestion"] = intent_data["suggestion"]
    return response


@app.get("/api/autocomplete")
async def autocomplete(
    q: str = Query(..., min_length=1),
    n: int = Query(8, ge=1, le=20),
):
    p = q.strip()
    if not p:
        return []
    p = p.strip("\"'`´“”‘’").strip()
    if len(p) < 2:
        return []

    payload = {
        "size": n * 4,
        "_source": ["identifica", "issuing_organ", "art_type", "art_type_normalized"],
        "query": {
            "bool": {
                "should": [
                    {"match_phrase_prefix": {"identifica": {"query": p}}},
                    {"match_phrase_prefix": {"issuing_organ": {"query": p}}},
                    {"prefix": {"art_type_normalized": {"value": p.lower()}}},
                ],
                "minimum_should_match": 1,
            }
        },
    }

    try:
        data = await es_request("POST", f"/{settings.es_target_index}/_search", json=payload)
    except httpx.HTTPStatusError as e:
        logger.warning("ES autocomplete error for query %r: %s", p, e.response.text[:300])
        return []

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


async def _fetch_document_source(doc_id: str) -> dict[str, Any] | None:
    """Fetch raw ES source for a document. Returns None if not found."""
    try:
        data = await es_request("GET", f"/{settings.es_target_index}/_doc/{doc_id}")
        return data.get("_source", {})
    except httpx.HTTPStatusError:
        return None


async def _fetch_tcu_document_source(doc_id: str) -> dict[str, Any] | None:
    """Fetch raw ES source for a TCU document."""
    try:
        data = await es_request("GET", f"/{_TCU_INDEX}/_doc/{doc_id}")
        return data.get("_source", {})
    except httpx.HTTPStatusError:
        return None


@app.get("/api/document/{doc_id}")
async def document(doc_id: str):
    # Auto-detect TCU documents by prefix
    if doc_id.startswith("ACORDAO-COMPLETO-"):
        src = await _fetch_tcu_document_source(doc_id)
        if src is None:
            return Response(status_code=404, content='{"detail":"Document not found"}',
                            media_type="application/json")
        return {
            "id": doc_id,
            "source_type": "tcu_acordao",
            "title": src.get("titulo") or "",
            "subtitle": src.get("sumario") or "",
            "body_html": None,
            "body_plain": src.get("acordao_texto") or "",
            "pub_date": src.get("data_sessao") or "",
            "section": src.get("colegiado") or "",
            "section_name": src.get("colegiado"),
            "page": None,
            "edition": None,
            "art_type": src.get("tipo") or "Acórdão TCU",
            "art_type_name": src.get("tipo"),
            "issuing_organ": "Tribunal de Contas da União",
            "dou_url": None,
            "media": [],
            # TCU-specific fields
            "relator": src.get("relator"),
            "colegiado": src.get("colegiado"),
            "tipo_processo": src.get("tipo_processo"),
            "numero_processo": src.get("numero_processo"),
            "numero_acordao": src.get("numero_acordao"),
            "ano_acordao": src.get("ano_acordao"),
            "acordao_id": src.get("acordao_id"),
            "relatorio": src.get("relatorio") or "",
            "voto": src.get("voto") or "",
            "dispositivo_tipo": src.get("dispositivo_tipo"),
            "dispositivo_resumo": src.get("dispositivo_resumo"),
            "entidade": src.get("entidade"),
            "interessados": src.get("interessados"),
            "assunto": src.get("assunto"),
            "source_url": src.get("source_url"),
        }

    src = await _fetch_document_source(doc_id)
    if src is None:
        return Response(status_code=404, content='{"detail":"Document not found"}',
                        media_type="application/json")

    section = _section_to_frontend(src.get("edition_section") or src.get("section"))

    return {
        "id": doc_id,
        "source_type": "dou",
        "title": src.get("identifica") or "",
        "subtitle": src.get("ementa") or "",
        "body_html": None,
        "body_plain": src.get("body_plain") or "",
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
        "assinatura": src.get("primary_signer"),
        "primary_signer": src.get("primary_signer"),
        "signers_all": src.get("signers_all_flat") or [],
    }


@app.get("/api/document/{doc_id}/pdf")
async def document_pdf(doc_id: str):
    is_tcu = doc_id.startswith("ACORDAO-COMPLETO-")

    if is_tcu:
        src = await _fetch_tcu_document_source(doc_id)
    else:
        src = await _fetch_document_source(doc_id)

    if src is None:
        return Response(status_code=404, content='{"detail":"Document not found"}',
                        media_type="application/json")

    from src.backend.pdf.template import render_pdf_html
    from src.backend.pdf.generator import generate_pdf

    if is_tcu:
        # Build TCU-specific PDF data
        body_parts = []
        if src.get("sumario"):
            body_parts.append(f"SUMÁRIO\n\n{src['sumario']}")
        if src.get("acordao_texto"):
            body_parts.append(f"ACÓRDÃO\n\n{src['acordao_texto']}")
        if src.get("relatorio"):
            body_parts.append(f"RELATÓRIO\n\n{src['relatorio']}")
        if src.get("voto"):
            body_parts.append(f"VOTO\n\n{src['voto']}")

        doc_data = {
            "identifica": src.get("titulo"),
            "ementa": src.get("sumario"),
            "body_plain": "\n\n".join(body_parts),
            "issuing_organ": "Tribunal de Contas da União",
            "art_type": src.get("tipo") or "Acórdão TCU",
            "pub_date": src.get("data_sessao"),
            "section": src.get("colegiado"),
            "page_number": None,
            "edition_number": None,
            "primary_signer": src.get("relator"),
            "signers_all_flat": None,
        }
        title_slug = (src.get("titulo") or doc_id)[:60].replace(" ", "_")
        filename = f"TCU_{title_slug}.pdf"
    else:
        section = _section_to_frontend(src.get("edition_section") or src.get("section"))
        doc_data = {
            "identifica": src.get("identifica"),
            "ementa": src.get("ementa"),
            "body_plain": src.get("body_plain"),
            "issuing_organ": src.get("issuing_organ"),
            "art_type": src.get("art_type"),
            "pub_date": src.get("pub_date"),
            "section": section,
            "page_number": src.get("page_number"),
            "edition_number": src.get("edition_number"),
            "primary_signer": src.get("primary_signer"),
            "signers_all_flat": src.get("signers_all_flat"),
        }
        title_slug = (src.get("identifica") or doc_id)[:60].replace(" ", "_")
        filename = f"DOU_{title_slug}.pdf"

    html_content = render_pdf_html(doc_data)
    pdf_bytes = generate_pdf(html_content)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@app.get("/api/stats")
async def stats():
    count_data = await es_request("GET", f"/{settings.es_target_index}/_count")
    total = count_data.get("count", 0)

    agg_payload = {
        "size": 0,
        "aggs": {
            "min_date": {"min": {"field": "pub_date"}},
            "max_date": {"max": {"field": "pub_date"}},
            "sections": {"terms": {"field": "section", "size": 10}},
        },
    }
    agg_data = await es_request("POST", f"/{settings.es_target_index}/_search", json=agg_payload)
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
            "types": {"terms": {"field": "art_type_normalized", "size": 200}},
        },
    }
    data = await es_request("POST", f"/{settings.es_target_index}/_search", json=payload)
    buckets = data.get("aggregations", {}).get("types", {}).get("buckets", [])

    return [
        {"value": b["key"], "label": _art_type_label(b["key"]), "count": b["doc_count"]}
        for b in buckets
    ]


@app.get("/api/trending")
async def trending():
    cached = get_cached_trending(_mongo_db)
    if cached:
        return cached

    try:
        with httpx.Client() as client:
            topics = update_trending_cache(client, _mongo_db, top_n=8)
        if topics:
            return topics
    except Exception:
        logger.exception("failed to compute trending topics on cache miss")

    return FALLBACK_TOPICS


@app.get("/api/recent-highlights")
async def recent_highlights(limit: int = Query(8, ge=1, le=20)):
    payload = {
        "size": 1200,
        "track_total_hits": False,
        "sort": [{"pub_date": {"order": "desc"}}],
        "_source": _LATEST_SOURCE_FIELDS,
        "query": {
            "bool": {
                "filter": [
                    {"range": {"pub_date": {"gte": "now-60d/d"}}},
                ]
            }
        },
    }
    data = await es_request("POST", f"/{settings.es_target_index}/_search", json=payload)
    hits = data.get("hits", {}).get("hits", [])

    ranked: list[tuple[float, list[str], dict[str, Any]]] = []
    for hit in hits:
        score, reasons = _recent_highlight_score(hit)
        if score < 3:
            continue
        ranked.append((score, reasons, hit))

    ranked.sort(
        key=lambda item: (
            item[0],
            item[2].get("_source", {}).get("pub_date") or "",
        ),
        reverse=True,
    )

    results: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    per_art_type: dict[str, int] = {}

    for score, reasons, hit in ranked:
        src = hit.get("_source", {})
        title_key = _normalize_match_text(src.get("identifica"))
        art_type_key = _normalize_match_text(src.get("art_type_normalized") or src.get("art_type"))

        if title_key in seen_titles:
            continue
        if art_type_key and per_art_type.get(art_type_key, 0) >= 3:
            continue

        item = _hit_to_result(hit)
        item["relevance_score"] = round(score, 1)
        item["reasons"] = reasons
        results.append(item)
        seen_titles.add(title_key)
        if art_type_key:
            per_art_type[art_type_key] = per_art_type.get(art_type_key, 0) + 1
        if len(results) >= limit:
            break

    if not results:
        return await latest_publications(limit)

    return results


@app.get("/api/latest-publications")
async def latest_publications(limit: int = Query(8, ge=1, le=20)):
    payload = {
        "size": limit,
        "track_total_hits": False,
        "sort": [{"pub_date": {"order": "desc"}}],
        "_source": _LATEST_SOURCE_FIELDS,
        "query": {"match_all": {}},
    }
    data = await es_request("POST", f"/{settings.es_target_index}/_search", json=payload)
    hits = data.get("hits", {}).get("hits", [])
    return [_hit_to_result(hit) for hit in hits]


@app.get("/api/top-searches")
async def top_searches():
    return await trending()


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


@app.get("/api/suggested-topics")
async def suggested_topics():
    import json as _json
    path = Path(__file__).resolve().parent / "data" / "suggested_topics.json"
    try:
        return _json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


@app.get("/api/editorial-highlights")
async def editorial_highlights():
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
    doc = _mongo_db["editorial_highlights"].find_one({"_id": "latest"})
    if not doc:
        return {"date": today, "categories": {}}
    doc.pop("_id", None)
    doc.pop("generated_at", None)
    return {"date": doc.get("generated_for", today), **doc}


@app.get("/api/media/{doc_id:path}/{name}")
async def media(doc_id: str, name: str):
    return Response(status_code=404, content='{"detail":"Media not available"}',
                    media_type="application/json")


# ---------------------------------------------------------------------------
# SEO: HTML shell routes (dynamic meta tags for crawlers)
# ---------------------------------------------------------------------------

_sitemap_cache: dict[str, tuple[str, float]] = {}
_SITEMAP_CACHE_TTL = 86400  # 24h

HTML_MEDIA = "text/html; charset=utf-8"


@app.get("/sitemap-index.xml")
async def sitemap_index():
    import time

    cache_key = "index"
    cached = _sitemap_cache.get(cache_key)
    if cached and (time.time() - cached[1]) < _SITEMAP_CACHE_TTL:
        return Response(content=cached[0], media_type="application/xml")

    agg_payload = {
        "size": 0,
        "aggs": {
            "min_date": {"min": {"field": "pub_date"}},
            "max_date": {"max": {"field": "pub_date"}},
        },
    }
    data = await es_request("POST", f"/{settings.es_target_index}/_search", json=agg_payload)
    aggs = data.get("aggregations", {})
    min_date = aggs.get("min_date", {}).get("value_as_string", "2002-01-01")
    max_date = aggs.get("max_date", {}).get("value_as_string", "2026-01-01")

    xml = build_sitemap_index(min_date, max_date)
    _sitemap_cache[cache_key] = (xml, time.time())
    return Response(content=xml, media_type="application/xml")


@app.get("/sitemap-{year}-{month}.xml")
async def sitemap_month(year: int, month: int):
    import time

    cache_key = f"{year}-{month:02d}"
    cached = _sitemap_cache.get(cache_key)
    if cached and (time.time() - cached[1]) < _SITEMAP_CACHE_TTL:
        return Response(content=cached[0], media_type="application/xml")

    # Build date range for this month
    date_from = f"{year}-{month:02d}-01"
    if month == 12:
        date_to = f"{year + 1}-01-01"
    else:
        date_to = f"{year}-{month + 1:02d}-01"

    # Scroll through all docs in this month using search_after
    all_docs: list[tuple[str, str]] = []
    search_after = None

    while True:
        payload: dict[str, Any] = {
            "size": 10000,
            "track_total_hits": False,
            "_source": ["doc_id", "pub_date"],
            "sort": [{"doc_id": "asc"}],
            "query": {
                "bool": {
                    "filter": [
                        {"range": {"pub_date": {"gte": date_from, "lt": date_to}}},
                    ]
                }
            },
        }
        if search_after:
            payload["search_after"] = search_after

        data = await es_request("POST", f"/{settings.es_target_index}/_search", json=payload)
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            break

        for hit in hits:
            src = hit.get("_source", {})
            doc_id = src.get("doc_id") or hit.get("_id", "")
            pub_date = src.get("pub_date") or ""
            all_docs.append((doc_id, pub_date))

        search_after = hits[-1].get("sort")
        if not search_after or len(hits) < 10000:
            break

        # Safety: max 50K URLs per sitemap
        if len(all_docs) >= 50000:
            break

    xml = build_sitemap_urls(all_docs)
    _sitemap_cache[cache_key] = (xml, time.time())
    return Response(content=xml, media_type="application/xml")


@app.get("/document/{doc_id}")
async def document_html(doc_id: str):
    if not is_template_loaded():
        return Response(content="Template not loaded", status_code=503)

    src = await _fetch_document_source(doc_id)
    if src is None:
        return Response(
            content=render_fallback_html(),
            media_type=HTML_MEDIA,
            status_code=404,
        )
    return Response(content=render_document_html(src, doc_id), media_type=HTML_MEDIA)


@app.get("/search")
async def search_html(q: str = Query("", min_length=0)):
    if not is_template_loaded():
        return Response(content="Template not loaded", status_code=503)
    if q.strip():
        return Response(content=render_search_html(q), media_type=HTML_MEDIA)
    return Response(content=render_fallback_html(), media_type=HTML_MEDIA)


@app.get("/")
async def home_html():
    if not is_template_loaded():
        return Response(content="Template not loaded", status_code=503)
    return Response(content=render_home_html(), media_type=HTML_MEDIA)


@app.get("/{path:path}")
async def catch_all_html(path: str):
    if not is_template_loaded():
        return Response(content="Template not loaded", status_code=503)
    return Response(content=render_fallback_html(), media_type=HTML_MEDIA)
