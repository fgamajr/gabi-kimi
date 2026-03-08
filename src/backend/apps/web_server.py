"""GABI DOU — FastAPI backend for BM25 search + Qwen chat.

Endpoints:
  GET  /api/search?q=...&max=20&page=1&date_from=...&date_to=...&section=...&art_type=...
  GET  /api/suggest?q=...            (autocomplete from BM25 terms)
  GET  /api/top-searches?n=10&period=day|week
  GET  /api/search-examples?n=8
  GET  /api/document/{doc_id}        (full document by UUID)
  GET  /api/stats                    (database + BM25 statistics)
  GET  /api/types                    (distinct art_type values)
  POST /api/chat                     (proxy to DashScope Qwen API)

Usage:
  python3 ops/bin/web_server.py              # dev server on :8000
  python3 ops/bin/web_server.py --port 3000  # custom port
"""
from __future__ import annotations

import os
from io import BytesIO
from html import escape
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any, AsyncIterator
import re
import json

import httpx
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from src.backend.apps.worker_jobs import ensure_worker_jobs_schema, get_job, list_jobs
from src.backend.apps.auth import (
    AuthPrincipal,
    bootstrap_identity_store,
    clear_session_response,
    create_session_response,
    get_auth_config,
    issue_api_token,
    list_roles,
    list_users,
    request_ip,
    revoke_api_token,
    require_admin_access,
    require_protected_access,
    replace_user_roles,
    resolve_request_principal,
    upsert_user,
)
from src.backend.apps.chat_security import ChatSecurity
from src.backend.apps.middleware.security import (
    RateLimiter,
    RateRule,
    build_content_security_policy,
    hostnames_to_origins,
    local_dev_origins,
    log_security_event,
)
from src.backend.apps.middleware.security_middleware import AppSecurityMiddleware

from src.backend.apps.mcp_server import (
    SEARCH_CFG,
    search_examples_payload,
    search_payload,
    stats_payload,
    suggest_payload,
    top_searches_payload,
)
from src.backend.search.norm_queries import NormQuery, detect_legal_norm
from src.backend.storage import (
    delete_object,
    get_object_bytes,
    is_configured as storage_is_configured,
    upload_fileobj,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DSN = os.getenv("PG_DSN") or (
    f"host={os.getenv('PGHOST', 'localhost')} "
    f"port={os.getenv('PGPORT', '5433')} "
    f"dbname={os.getenv('PGDATABASE', 'gabi')} "
    f"user={os.getenv('PGUSER', 'gabi')} "
    f"password={os.getenv('PGPASSWORD', 'gabi')}"
)

DASHSCOPE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-plus")

# Try new frontend first, fallback to old
_ROOT_DIR = Path(__file__).resolve().parents[3]
_FRONTEND_WEB_DIR = _ROOT_DIR / "src" / "frontend" / "web"
_LEGACY_WEB_DIR = _ROOT_DIR / "web"
WEB_DIR = _FRONTEND_WEB_DIR if _FRONTEND_WEB_DIR.exists() else _LEGACY_WEB_DIR
SPA_INDEX = WEB_DIR / "dist" / "index.html" if (WEB_DIR / "dist" / "index.html").exists() else WEB_DIR / "index.html"
DIST_DIR = (WEB_DIR / "dist").resolve()
ASSETS_DIR = (DIST_DIR / "assets").resolve()
MEDIA_ROOT = Path(
    os.getenv("GABI_MEDIA_ROOT", str(_ROOT_DIR / "ops" / "data" / "dou" / "images"))
).resolve()
SERVE_FRONTEND = os.getenv("GABI_SERVE_FRONTEND", "true").strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return []
    normalized = raw.replace("\n", ",").replace(";", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def _allow_local_origins() -> bool:
    if os.getenv("FLY_APP_NAME", "").strip():
        return False
    return os.getenv("GABI_ENV", "development").strip().lower() != "production"


def _allowed_hosts() -> list[str]:
    explicit = _parse_csv_env("GABI_ALLOWED_HOSTS")
    if explicit:
        return explicit
    hosts = ["localhost", "127.0.0.1", "::1"]
    fly_app_name = os.getenv("FLY_APP_NAME", "").strip()
    if fly_app_name:
        hosts.extend([f"{fly_app_name}.fly.dev", f"{fly_app_name}.internal"])
    return hosts


def _allowed_origins(allowed_hosts: list[str]) -> list[str]:
    explicit = _parse_csv_env("GABI_CORS_ORIGINS")
    if explicit:
        return explicit
    origins = hostnames_to_origins(allowed_hosts)
    if _allow_local_origins():
        origins.extend(local_dev_origins())
    return sorted({origin for origin in origins if origin})

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown."""
    bootstrap_identity_store(get_auth_config())
    ensure_worker_jobs_schema()
    app.state.http = httpx.AsyncClient(timeout=60.0)
    app.state.rate_limiter = RateLimiter(redis_url=os.getenv("REDIS_URL", "").strip() or None)
    app.state.chat_security = ChatSecurity(redis_url=os.getenv("REDIS_URL", "").strip() or None)
    await app.state.rate_limiter.startup()
    await app.state.chat_security.startup()
    yield
    await app.state.chat_security.shutdown()
    await app.state.rate_limiter.shutdown()
    await app.state.http.aclose()


app = FastAPI(title="GABI DOU", lifespan=lifespan)
ALLOWED_HOSTS = _allowed_hosts()
ALLOWED_ORIGINS = _allowed_origins(ALLOWED_HOSTS)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=True,
)
app.add_middleware(AppSecurityMiddleware, csp=build_content_security_policy())
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------

def _conn(timeout_ms: int = 30000):
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f"SET statement_timeout = {timeout_ms}")
    cur.close()
    return conn


def _rows(cur) -> list[dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _ser(v: Any) -> Any:
    if isinstance(v, date):
        return v.isoformat()
    return v


def _resolve_local_media_path(local_path: str | None) -> Path | None:
    if not local_path:
        return None
    normalized = str(local_path).strip().replace("\\", "/")
    if not normalized:
        return None

    candidate = Path(normalized)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        relative = normalized
        media_prefix = "ops/data/dou/images/"
        if relative.startswith(media_prefix):
            relative = relative[len(media_prefix):]
        relative = relative.lstrip("./")
        resolved = (MEDIA_ROOT / relative).resolve()

    try:
        resolved.relative_to(MEDIA_ROOT)
    except ValueError:
        log_security_event(
            "media_path_denied",
            requested_path=normalized,
            resolved_path=str(resolved),
            media_root=str(MEDIA_ROOT),
        )
        return None
    return resolved


def _require_frontend_enabled() -> None:
    if SERVE_FRONTEND:
        return
    raise HTTPException(404, "Not found")


def _load_document_payload(doc_id: str) -> dict[str, Any]:
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT d.id, d.id_materia, d.art_type, d.art_type_raw,
                   d.art_category, d.identifica, d.ementa, d.titulo,
                   d.sub_titulo, d.body_plain, d.body_html,
                   d.document_number, d.document_year, d.issuing_organ,
                   d.page_number,
                   COALESCE(array_length(regexp_split_to_array(trim(d.body_plain), E'\\s+'), 1), 0) AS body_word_count,
                   e.publication_date, e.edition_number, e.section, e.is_extra
            FROM dou.document d
            JOIN dou.edition e ON e.id = d.edition_id
            WHERE d.id = %s::uuid
        """, (doc_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Documento não encontrado")
        cols = [desc[0] for desc in cur.description]
        doc = {k: _ser(v) for k, v in zip(cols, row)}

        cur.execute("""
            SELECT reference_type, reference_number, reference_date, reference_text
            FROM dou.normative_reference WHERE document_id = %s::uuid
            ORDER BY reference_type, reference_number
        """, (doc_id,))
        doc["normative_refs"] = [{k: _ser(v) for k, v in r.items()} for r in _rows(cur)]

        cur.execute("""
            SELECT procedure_type, procedure_identifier
            FROM dou.procedure_reference WHERE document_id = %s::uuid
        """, (doc_id,))
        doc["procedure_refs"] = [{k: _ser(v) for k, v in r.items()} for r in _rows(cur)]

        cur.execute("""
            SELECT person_name, role_title
            FROM dou.document_signature WHERE document_id = %s::uuid
            ORDER BY sequence_in_document
        """, (doc_id,))
        doc["signatures"] = [{k: _ser(v) for k, v in r.items()} for r in _rows(cur)]

        cur.execute("""
            SELECT media_name, media_type, file_extension, size_bytes,
                   source_filename, external_url, original_url,
                   availability_status, alt_text, context_hint, fallback_text,
                   local_path, width_px, height_px, ingest_checked_at, retry_count,
                   (data IS NOT NULL) AS has_binary,
                   sequence_in_document
            FROM dou.document_media WHERE document_id = %s::uuid
            ORDER BY sequence_in_document
        """, (doc_id,))
        media_rows = [{k: _ser(v) for k, v in r.items()} for r in _rows(cur)]
        for item in media_rows:
            media_name = str(item.get("media_name", "")).strip()
            effective_status = item.get("availability_status") or "unknown"
            if effective_status == "available" and not item.get("has_binary") and not item.get("local_path"):
                effective_status = "unknown"
            item["position_in_doc"] = item.get("sequence_in_document")
            item["status"] = effective_status
            item["blob_url"] = (
                f"/api/media/{doc_id}/{media_name}"
                if media_name and effective_status == "available"
                else None
            )
        doc["media"] = media_rows
        doc["images"] = media_rows
        cur.close()
        return doc
    finally:
        conn.close()


def _infer_relation_type(text: str | None, fallback: str | None = None) -> str:
    corpus = f"{fallback or ''} {text or ''}".lower()
    if "revog" in corpus:
        return "revoga"
    if "alter" in corpus or "retific" in corpus:
        return "altera"
    if "prorrog" in corpus:
        return "prorroga"
    if "regulament" in corpus:
        return "regulamenta"
    if "complement" in corpus:
        return "complementa"
    return "cita"


def _graph_title_from_search_row(row: dict[str, Any]) -> str:
    return str(row.get("identifica") or row.get("titulo") or row.get("ementa") or row.get("title") or "Sem título")


def _normalize_graph_search_result(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("doc_id") or row.get("id") or ""),
        "title": _graph_title_from_search_row(row),
        "snippet": str(row.get("snippet") or row.get("highlight") or "").strip() or None,
        "pub_date": str(row.get("pub_date") or row.get("publication_date") or ""),
        "section": str(row.get("edition_section") or row.get("section") or ""),
        "page": str(row.get("page_number")) if row.get("page_number") is not None else None,
        "art_type": str(row.get("art_type") or "").strip() or None,
        "issuing_organ": str(row.get("issuing_organ") or "").strip() or None,
        "dou_url": (
            f"https://www.in.gov.br/web/dou/-/{row.get('id_materia')}"
            if row.get("id_materia")
            else None
        ),
    }


def _graph_reference_query(reference_type: str | None, reference_number: str | None, reference_text: str | None) -> str:
    return " ".join(
        part for part in [reference_type, reference_number] if str(part or "").strip()
    ).strip() or str(reference_text or "").strip()


def _resolved_norm_variants(norm_query: NormQuery | None, fallback_number: str | None = None) -> list[str]:
    values: list[str] = []
    if norm_query is not None:
        values.extend(norm_query.number_variants)
        values.append(norm_query.number_digits)
    if fallback_number:
        values.append(str(fallback_number).strip())
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        candidate = str(value or "").strip()
        if candidate and candidate not in seen:
            out.append(candidate)
            seen.add(candidate)
    return out


def _resolve_reference_targets(
    ref: dict[str, Any],
    *,
    exclude_doc_id: str,
    per_seed: int,
) -> list[dict[str, Any]]:
    query = _graph_reference_query(
        str(ref.get("reference_type") or "").strip() or None,
        str(ref.get("reference_number") or "").strip() or None,
        str(ref.get("reference_text") or "").strip() or None,
    )
    norm_query = detect_legal_norm(query, inferred_type=str(ref.get("reference_type") or "").strip() or None)
    exact_rows: list[dict[str, Any]] = []

    if norm_query is not None:
        conn = _conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT d.id AS doc_id, d.id_materia, d.identifica, d.titulo, d.ementa,
                       d.issuing_organ, d.page_number, d.art_type, e.publication_date AS pub_date,
                       e.section AS edition_section
                FROM dou.document d
                JOIN dou.edition e ON e.id = d.edition_id
                WHERE d.id != %s::uuid
                  AND (%s::text IS NULL OR d.art_type = %s)
                  AND d.document_number = ANY(%s)
                  AND (%s::int IS NULL OR d.document_year = %s)
                ORDER BY
                  CASE WHEN %s::int IS NOT NULL AND d.document_year = %s THEN 0 ELSE 1 END,
                  e.publication_date DESC
                LIMIT %s
                """,
                (
                    exclude_doc_id,
                    norm_query.norm_type,
                    norm_query.norm_type,
                    _resolved_norm_variants(norm_query, str(ref.get("reference_number") or "").strip() or None),
                    norm_query.year,
                    norm_query.year,
                    norm_query.year,
                    norm_query.year,
                    per_seed,
                ),
            )
            exact_rows = [_normalize_graph_search_result(item) for item in _rows(cur)]
            cur.close()
        finally:
            conn.close()

    if exact_rows:
        return exact_rows[:per_seed]

    try:
        result = search_payload(query=query, max_results=per_seed, page=1)
        return [
            _normalize_graph_search_result(item)
            for item in result.get("results", [])
            if str(item.get("doc_id") or item.get("id") or "") != exclude_doc_id
        ][:per_seed]
    except Exception:
        return []


def _incoming_normative_branches(
    doc: dict[str, Any],
    *,
    per_seed: int,
) -> list[dict[str, Any]]:
    doc_type = str(doc.get("art_type") or "").strip() or None
    doc_number = str(doc.get("document_number") or "").strip() or None
    doc_year = doc.get("document_year")
    if not doc_type or not doc_number:
        return []

    norm_query = detect_legal_norm(
        " ".join(part for part in [doc_type, doc_number, str(doc_year or "")] if str(part).strip()),
        inferred_type=doc_type,
    )
    variants = _resolved_norm_variants(norm_query, doc_number)
    if not variants:
        return []

    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT d.id AS doc_id, d.id_materia, d.identifica, d.titulo, d.ementa,
                   d.issuing_organ, d.page_number, d.art_type, e.publication_date AS pub_date,
                   e.section AS edition_section, nr.reference_type, nr.reference_number, nr.reference_text
            FROM dou.normative_reference nr
            JOIN dou.document d ON d.id = nr.document_id
            JOIN dou.edition e ON e.id = d.edition_id
            WHERE d.id != %s::uuid
              AND (%s::text IS NULL OR nr.reference_type = %s)
              AND nr.reference_number = ANY(%s)
            ORDER BY e.publication_date DESC
            LIMIT %s
            """,
            (
                str(doc.get("id") or ""),
                doc_type,
                doc_type,
                variants,
                max(6, per_seed * 4),
            ),
        )
        rows = _rows(cur)
        cur.close()
    finally:
        conn.close()

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        relation_type = _infer_relation_type(
            str(row.get("reference_text") or ""),
            str(row.get("reference_type") or ""),
        )
        grouped.setdefault(relation_type, [])
        normalized = _normalize_graph_search_result(row)
        if all(item["id"] != normalized["id"] for item in grouped[relation_type]):
            grouped[relation_type].append(normalized)

    branches: list[dict[str, Any]] = []
    for relation_type, related_docs in grouped.items():
        if not related_docs:
            continue
        verb = {
            "altera": "alteram",
            "revoga": "revogam",
            "prorroga": "prorrogam",
            "regulamenta": "regulamentam",
            "complementa": "complementam",
            "cita": "citam",
        }.get(relation_type, "relacionam-se com")
        branches.append(
            {
                "seed": {
                    "id": f"incoming-{relation_type}",
                    "node_type": "incoming",
                    "relation_type": relation_type,
                    "title": f"Atos que {verb} este ato",
                    "subtitle": "Relações de entrada detectadas no corpus",
                    "query": " ".join(part for part in [doc_type, doc_number] if part),
                },
                "related_documents": related_docs[:per_seed],
            }
        )
    order = {"revoga": 0, "altera": 1, "regulamenta": 2, "complementa": 3, "prorroga": 4, "cita": 5}
    branches.sort(key=lambda branch: order.get(str(branch["seed"].get("relation_type") or ""), 99))
    return branches


def _collapse_text(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def _repair_pdf_text(value: str) -> str:
    text = _collapse_text(value or "")
    if not text:
        return ""

    replacements = {
        "GrÆfico": "Gráfico",
        "Gráfico": "Gráfico",
        "˝ndice": "Índice",
        "■ndice": "Índice",
        "freq�Œncia": "freqüência",
        "freq■Œncia": "freqüência",
        "�bitos": "óbitos",
        "■bitos": "óbitos",
        "p�lo": "pólo",
        "p■lo": "pólo",
        "� composto": "é composto",
        "■ composto": "é composto",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    # Repair OCR-style line-break hyphenation while preserving spaced hyphens.
    text = re.sub(r"(?<=\w)-\s+(?=[a-záàâãéêíóôõúüç])", "", text)
    return text


# ---------------------------------------------------------------------------
# API — Search
# ---------------------------------------------------------------------------

@app.get("/api/search")
def api_search(
    q: str = Query(..., min_length=1),
    max: int = Query(20, ge=1, le=100),
    page: int = Query(1, ge=1),
    date_from: str | None = None,
    date_to: str | None = None,
    section: str | None = None,
    art_type: str | None = None,
    issuing_organ: str | None = None,
):
    """Search with backend adapter (pg/es). q='*' = browse with filters only."""
    try:
        return search_payload(
            query=q,
            max_results=max,
            page=page,
            date_from=date_from,
            date_to=date_to,
            section=section,
            art_type=art_type,
            issuing_organ=issuing_organ,
        )
    except Exception as ex:
        raise HTTPException(503, f"Search backend unavailable ({SEARCH_CFG.backend}): {type(ex).__name__}")


# ---------------------------------------------------------------------------
# API — Suggest (autocomplete)
# ---------------------------------------------------------------------------

@app.get("/api/suggest")
def api_suggest(q: str = Query(..., min_length=2)):
    try:
        return suggest_payload(query=q, limit=10)
    except Exception as ex:
        raise HTTPException(503, f"Suggest backend unavailable ({SEARCH_CFG.backend}): {type(ex).__name__}")


@app.get("/api/autocomplete")
def api_autocomplete(
    q: str = Query(..., min_length=1),
    n: int = Query(10, ge=1, le=20),
):
    """Autocomplete for search textbox (ES/PG base + popularity blending)."""
    try:
        base = suggest_payload(query=q, limit=n)
        rows = base.get("suggestions", [])
        terms: list[str] = []
        seen: set[str] = set()
        for row in rows:
            term = str(row.get("term", "")).strip()
            key = term.casefold()
            if not term or key in seen:
                continue
            seen.add(key)
            terms.append(term)
            if len(terms) >= n:
                break

        # If still short, use top queries as fallback filtered by prefix.
        if len(terms) < n:
            top = top_searches_payload(period="week", n=max(20, n * 3)).get("items", [])
            qnorm = q.casefold().strip()
            for row in top:
                term = str(row.get("term", "")).strip()
                key = term.casefold()
                if not term or key in seen:
                    continue
                if qnorm and not key.startswith(qnorm):
                    continue
                seen.add(key)
                terms.append(term)
                if len(terms) >= n:
                    break

        return {
            "prefix": q,
            "items": terms,
            "backend": SEARCH_CFG.backend,
        }
    except Exception as ex:
        raise HTTPException(503, f"Autocomplete unavailable ({SEARCH_CFG.backend}): {type(ex).__name__}")


@app.get("/api/top-searches")
def api_top_searches(
    n: int = Query(10, ge=1, le=30),
    period: str = Query("day", pattern="^(day|week)$"),
):
    try:
        return top_searches_payload(period=period, n=n)
    except Exception as ex:
        raise HTTPException(503, f"Top searches unavailable: {type(ex).__name__}")


@app.get("/api/search-examples")
def api_search_examples(n: int = Query(8, ge=1, le=20)):
    try:
        return search_examples_payload(n=n)
    except Exception as ex:
        raise HTTPException(503, f"Search examples unavailable: {type(ex).__name__}")


# ---------------------------------------------------------------------------
# API — Auth
# ---------------------------------------------------------------------------

@app.get("/api/auth/session")
def api_auth_session_status(request: Request):
    principal = resolve_request_principal(request, log_failures=False)
    if principal is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "principal": {
            "label": principal.label,
            "source": principal.source,
            "user_id": principal.user_id,
            "roles": list(principal.roles),
            "email": principal.email,
            "status": principal.status,
        },
        "expires_in_sec": get_auth_config().session_ttl_sec,
    }


@app.post("/api/auth/session")
async def api_auth_session_create(request: Request):
    principal = resolve_request_principal(request, allow_session=False)
    assert principal is not None
    limiter = getattr(request.app.state, "rate_limiter", None)
    if isinstance(limiter, RateLimiter):
        await limiter.enforce(
            bucket="auth_bootstrap",
            key=request_ip(request),
            rule=RateRule(limit=10, window_sec=60),
            request=request,
            dimension="ip",
        )
    return create_session_response(request, principal)


@app.delete("/api/auth/session")
def api_auth_session_delete():
    return clear_session_response()


class AdminUserUpsertRequest(BaseModel):
    id: str | None = None
    display_name: str
    email: str | None = None
    status: str = "active"
    is_service_account: bool = False


class AdminUserRolesRequest(BaseModel):
    roles: list[str]


class AdminTokenIssueRequest(BaseModel):
    token_label: str


@app.get("/api/admin/roles")
def api_admin_roles(_auth: AuthPrincipal = Depends(require_admin_access)):
    return {"items": list_roles()}


@app.get("/api/admin/users")
def api_admin_users(_auth: AuthPrincipal = Depends(require_admin_access)):
    return {"items": list_users()}


@app.post("/api/admin/users")
def api_admin_user_upsert(
    payload: AdminUserUpsertRequest,
    _auth: AuthPrincipal = Depends(require_admin_access),
):
    try:
        return upsert_user(
            user_id=payload.id,
            display_name=payload.display_name.strip(),
            email=payload.email.strip() if payload.email else None,
            status=payload.status.strip() or "active",
            is_service_account=payload.is_service_account,
        )
    except ValueError as ex:
        raise HTTPException(404, str(ex))


@app.put("/api/admin/users/{user_id}/roles")
def api_admin_user_roles(
    user_id: str,
    payload: AdminUserRolesRequest,
    _auth: AuthPrincipal = Depends(require_admin_access),
):
    try:
        return replace_user_roles(user_id, payload.roles)
    except ValueError as ex:
        raise HTTPException(404, str(ex))


@app.post("/api/admin/users/{user_id}/tokens")
def api_admin_user_issue_token(
    user_id: str,
    payload: AdminTokenIssueRequest,
    _auth: AuthPrincipal = Depends(require_admin_access),
):
    try:
        label = payload.token_label.strip()
        if not label:
            raise HTTPException(400, "token_label is required")
        return issue_api_token(user_id=user_id, token_label=label)
    except ValueError as ex:
        raise HTTPException(404, str(ex))


@app.delete("/api/admin/tokens/{token_id}")
def api_admin_revoke_token(
    token_id: str,
    _auth: AuthPrincipal = Depends(require_admin_access),
):
    try:
        return revoke_api_token(token_id)
    except ValueError as ex:
        raise HTTPException(404, str(ex))


@app.get("/api/admin/jobs")
def api_admin_jobs_list(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _auth: AuthPrincipal = Depends(require_admin_access),
):
    """List upload jobs (newest first)."""
    return {"items": list_jobs(limit=limit, offset=offset)}


@app.get("/api/admin/jobs/{job_id}")
def api_admin_job_detail(
    job_id: str,
    _auth: AuthPrincipal = Depends(require_admin_access),
):
    """Get one upload job by id."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@app.get("/api/admin/storage-check")
def api_admin_storage_check(_auth: AuthPrincipal = Depends(require_admin_access)):
    """Verify Tigris blob storage: upload a test file and read it back (Phase 1)."""
    if not storage_is_configured():
        raise HTTPException(
            503,
            "Tigris not configured: set AWS_ENDPOINT_URL_S3, AWS_ACCESS_KEY_ID, "
            "AWS_SECRET_ACCESS_KEY, BUCKET_NAME (e.g. fly storage create).",
        )
    test_key = "_storage_check/test.txt"
    payload = b"GABI Tigris check"
    try:
        upload_fileobj(BytesIO(payload), test_key)
        read_back = get_object_bytes(test_key)
        delete_object(test_key)
    except Exception as e:
        raise HTTPException(503, f"Tigris read/write failed: {e}") from e
    if read_back != payload:
        raise HTTPException(503, "Tigris read-back content mismatch")
    return {"ok": True}


# ---------------------------------------------------------------------------
# API — Document
# ---------------------------------------------------------------------------

@app.get("/api/document/{doc_id}")
def api_document(doc_id: str, _auth: AuthPrincipal = Depends(require_protected_access)):
    """Get full document by UUID."""
    return _load_document_payload(doc_id)


@app.get("/api/document/{doc_id}/pdf")
def api_document_pdf(doc_id: str, _auth: AuthPrincipal = Depends(require_protected_access)):
    """Generate a server-side PDF rendition with editorial/two-column layout."""
    doc = _load_document_payload(doc_id)

    try:
        from bs4 import BeautifulSoup, Tag
    except ModuleNotFoundError:  # pragma: no cover - fallback for lean local envs
        BeautifulSoup = None  # type: ignore[assignment]
        Tag = tuple()  # type: ignore[assignment]
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            BaseDocTemplate,
            Frame,
            FrameBreak,
            NextPageTemplate,
            PageBreak,
            PageTemplate,
            Paragraph,
            Spacer,
            Table,
            TableStyle,
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - local env without PDF stack
        raise HTTPException(503, "PDF generation dependencies are not installed") from exc

    buffer = BytesIO()
    pdf = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=str(doc.get("identifica") or doc.get("titulo") or "Documento DOU"),
        author="GABI DOU",
    )
    page_width, page_height = A4
    content_width = page_width - pdf.leftMargin - pdf.rightMargin
    gutter = 10 * mm
    column_width = (content_width - gutter) / 2
    first_header_height = 44 * mm

    first_page_frames = [
        Frame(
            pdf.leftMargin,
            page_height - pdf.topMargin - first_header_height,
            content_width,
            first_header_height,
            id="first-header",
            showBoundary=0,
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        ),
        Frame(
            pdf.leftMargin,
            pdf.bottomMargin,
            column_width,
            page_height - pdf.bottomMargin - pdf.topMargin - first_header_height - 8 * mm,
            id="first-left",
            showBoundary=0,
            leftPadding=0,
            rightPadding=6,
            topPadding=0,
            bottomPadding=0,
        ),
        Frame(
            pdf.leftMargin + column_width + gutter,
            pdf.bottomMargin,
            column_width,
            page_height - pdf.bottomMargin - pdf.topMargin - first_header_height - 8 * mm,
            id="first-right",
            showBoundary=0,
            leftPadding=6,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        ),
    ]

    later_page_frames = [
        Frame(
            pdf.leftMargin,
            pdf.bottomMargin,
            column_width,
            page_height - pdf.bottomMargin - pdf.topMargin,
            id="later-left",
            showBoundary=0,
            leftPadding=0,
            rightPadding=6,
            topPadding=0,
            bottomPadding=0,
        ),
        Frame(
            pdf.leftMargin + column_width + gutter,
            pdf.bottomMargin,
            column_width,
            page_height - pdf.bottomMargin - pdf.topMargin,
            id="later-right",
            showBoundary=0,
            leftPadding=6,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        ),
    ]

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="GabiTitle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=17,
            leading=20,
            textColor=colors.HexColor("#111111"),
            alignment=TA_LEFT,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="GabiMeta",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#4b5563"),
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="GabiBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=12.6,
            textColor=colors.HexColor("#111111"),
            alignment=TA_JUSTIFY,
            firstLineIndent=0,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="GabiSubhead",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10.2,
            leading=12.4,
            textColor=colors.HexColor("#111111"),
            alignment=TA_LEFT,
            spaceBefore=6,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="GabiCentered",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            textColor=colors.HexColor("#111111"),
            alignment=1,
            spaceBefore=4,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="GabiBullet",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=12.4,
            textColor=colors.HexColor("#111111"),
            leftIndent=10,
            firstLineIndent=-6,
            bulletIndent=0,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="GabiFallback",
            parent=styles["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=8.6,
            leading=11,
            textColor=colors.HexColor("#4b5563"),
            alignment=TA_LEFT,
            leftIndent=6,
            borderPadding=6,
            borderWidth=0.6,
            borderColor=colors.HexColor("#cbd5e1"),
            backColor=colors.HexColor("#f8fafc"),
            spaceBefore=4,
            spaceAfter=6,
        )
    )

    story: list[Any] = []
    story.append(Paragraph("Diário Oficial da União", styles["GabiMeta"]))
    story.append(Paragraph(escape(str(doc.get("identifica") or doc.get("titulo") or "Documento")), styles["GabiTitle"]))

    meta_line = " · ".join(
        part for part in [
            f"Seção {str(doc.get('section') or '').replace('do', '').upper()}" if doc.get("section") else None,
            str(doc.get("publication_date") or ""),
            f"Página {doc.get('page_number')}" if doc.get("page_number") is not None else None,
            str(doc.get("issuing_organ") or "").strip() or None,
        ] if part
    )
    if meta_line:
        story.append(Paragraph(escape(meta_line), styles["GabiMeta"]))

    if doc.get("ementa"):
        story.append(Paragraph(escape(_repair_pdf_text(str(doc["ementa"]))), styles["GabiBody"]))
        story.append(Spacer(1, 4))

    story.append(NextPageTemplate("Later"))
    story.append(FrameBreak())

    media_by_position = {
        int(item.get("position_in_doc")): item
        for item in (doc.get("media") or [])
        if item.get("position_in_doc") is not None
    }

    def append_table(tag: Tag) -> None:
        rows: list[list[str]] = []
        for tr in tag.find_all("tr"):
            cols = []
            cells = tr.find_all(["th", "td"])
            for cell in cells:
                cols.append(_repair_pdf_text(cell.get_text(" ", strip=True)))
            if cols:
                rows.append(cols)
        if not rows:
            return
        max_cols = max(len(r) for r in rows)
        normalized_rows = [r + [""] * (max_cols - len(r)) for r in rows]
        col_width = (content_width - gutter) / max_cols
        table = Table(normalized_rows, repeatRows=1 if len(normalized_rows) > 1 else 0, colWidths=[col_width] * max_cols)
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("LEADING", (0, 0), (-1, -1), 10),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#111111")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 6))

    def append_missing_media_fallback(tag: Tag) -> bool:
        img = tag.find("img")
        if not img:
            return False
        seq_raw = img.get("data-image-seq")
        try:
            seq = int(seq_raw)
        except (TypeError, ValueError):
            seq = None
        media = media_by_position.get(seq) if seq is not None else None
        if not media:
            return False

        context_hint = str(media.get("context_hint") or "").strip().lower()
        label = "Imagem"
        if context_hint == "table":
            label = "Tabela"
        elif context_hint == "signature":
            label = "Assinatura"
        elif context_hint == "emblem":
            label = "Brasão/Logotipo"
        elif context_hint == "chart":
            label = "Gráfico"

        fallback_text = _repair_pdf_text(
            str(media.get("fallback_text") or f"{label} disponível apenas no documento original")
        )
        original_url = str(media.get("original_url") or media.get("external_url") or "").strip()
        block = f"<b>{escape(label)} indisponível</b><br/>{escape(fallback_text)}"
        if original_url:
            block += f"<br/><font size='7'>{escape(original_url)}</font>"
        story.append(Paragraph(block, styles["GabiFallback"]))
        return True

    body_html = str(doc.get("body_html") or "").strip()
    if body_html and BeautifulSoup is not None:
        soup = BeautifulSoup(body_html, "html.parser")
        for node in soup.contents:
            if not isinstance(node, Tag):
                continue
            if append_missing_media_fallback(node):
                continue
            if node.name == "table":
                append_table(node)
                continue

            text = _repair_pdf_text(node.get_text(" ", strip=True))
            if not text:
                continue

            classes = set(node.get("class", []))
            text_html = escape(text)

            if "identifica" in classes:
                continue
            if "subtitulo" in classes:
                story.append(Paragraph(text_html, styles["GabiCentered"]))
                continue
            if text.startswith("•"):
                story.append(Paragraph(escape(text.lstrip("• ").strip()), styles["GabiBullet"], bulletText="•"))
                continue
            if len(text) <= 80 and text.upper() == text and any(ch.isalpha() for ch in text):
                story.append(Paragraph(text_html, styles["GabiSubhead"]))
                continue
            if text[:3].lower() in {"a) ", "b) ", "c) "}:
                story.append(Paragraph(text_html, styles["GabiBullet"]))
                continue
            story.append(Paragraph(text_html, styles["GabiBody"]))
    else:
        body_plain = str(doc.get("body_plain") or "").strip()
        paragraphs = [p.strip() for p in body_plain.split("\n\n") if p.strip()]
        if not paragraphs and body_plain:
            paragraphs = [body_plain]

        for paragraph in paragraphs:
            normalized = escape(_repair_pdf_text(paragraph))
            if not normalized:
                continue
            story.append(Paragraph(normalized, styles["GabiBody"]))

    if doc.get("signatures"):
        story.append(Spacer(1, 8))
        story.append(Paragraph("Assinaturas", styles["GabiMeta"]))
        for sig in doc.get("signatures") or []:
            person = escape(_repair_pdf_text(str(sig.get("person_name") or "").strip()))
            role = escape(_repair_pdf_text(str(sig.get("role_title") or "").strip()))
            line = " — ".join([p for p in [person, role] if p])
            if line:
                story.append(Paragraph(line, styles["GabiBody"]))

    def draw_footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawString(pdf.leftMargin, 9 * mm, "GABI · DOU")
        canvas.drawRightString(page_width - pdf.rightMargin, 9 * mm, f"Página {canvas.getPageNumber()}")
        canvas.restoreState()

    pdf.addPageTemplates(
        [
            PageTemplate(id="First", frames=first_page_frames, onPage=draw_footer),
            PageTemplate(id="Later", frames=later_page_frames, onPage=draw_footer),
        ]
    )

    pdf.build(story)
    payload = buffer.getvalue()
    buffer.close()

    filename = f"dou_{doc_id}.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=payload, media_type="application/pdf", headers=headers)


@app.get("/api/document/{doc_id}/graph")
def api_document_graph(
    doc_id: str,
    depth: int = Query(2, ge=1, le=2),
    per_seed: int = Query(3, ge=1, le=5),
    _auth: AuthPrincipal = Depends(require_protected_access),
):
    """Derived document graph from existing references + search backend."""
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT d.id, d.identifica, d.titulo, d.ementa, d.issuing_organ, d.page_number,
                   d.art_type, d.document_number, d.document_year, e.publication_date, e.section
            FROM dou.document d
            JOIN dou.edition e ON e.id = d.edition_id
            WHERE d.id = %s::uuid
            """,
            (doc_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Documento não encontrado")
        cols = [desc[0] for desc in cur.description]
        doc = {k: _ser(v) for k, v in zip(cols, row)}

        cur.execute(
            """
            SELECT reference_type, reference_number, reference_date, reference_text
            FROM dou.normative_reference
            WHERE document_id = %s::uuid
            ORDER BY reference_date NULLS LAST, reference_type, reference_number
            LIMIT 8
            """,
            (doc_id,),
        )
        normative_refs = [{k: _ser(v) for k, v in r.items()} for r in _rows(cur)]

        cur.execute(
            """
            SELECT procedure_type, procedure_identifier
            FROM dou.procedure_reference
            WHERE document_id = %s::uuid
            LIMIT 6
            """,
            (doc_id,),
        )
        procedure_refs = [{k: _ser(v) for k, v in r.items()} for r in _rows(cur)]
        cur.close()
    finally:
        conn.close()

    branches: list[dict[str, Any]] = []

    for idx, ref in enumerate(normative_refs[:4]):
        query = _graph_reference_query(
            str(ref.get("reference_type") or "").strip() or None,
            str(ref.get("reference_number") or "").strip() or None,
            str(ref.get("reference_text") or "").strip() or None,
        )
        if not query:
            continue
        related_docs: list[dict[str, Any]] = _resolve_reference_targets(
            ref,
            exclude_doc_id=doc_id,
            per_seed=per_seed,
        ) if depth >= 2 else []

        branches.append(
            {
                "seed": {
                    "id": f"normative-{idx}",
                    "node_type": "reference",
                    "relation_type": _infer_relation_type(
                        str(ref.get("reference_text") or ""),
                        str(ref.get("reference_type") or ""),
                    ),
                    "title": " ".join(
                        part for part in [ref.get("reference_type"), ref.get("reference_number")] if part
                    ).strip()
                    or "Referência normativa",
                    "subtitle": str(ref.get("reference_text") or "").strip() or str(ref.get("reference_date") or "").strip() or None,
                    "query": query,
                },
                "related_documents": related_docs,
            }
        )

    branches.extend(_incoming_normative_branches(doc, per_seed=per_seed))

    for idx, procedure in enumerate(procedure_refs[:3]):
        query = " ".join(
            part for part in [procedure.get("procedure_type"), procedure.get("procedure_identifier")] if part
        ).strip()
        if not query:
            continue
        related_docs: list[dict[str, Any]] = []
        if depth >= 2:
            try:
                result = search_payload(query=query, max_results=per_seed, page=1)
                related_docs = [
                    _normalize_graph_search_result(item)
                    for item in result.get("results", [])
                    if str(item.get("doc_id") or item.get("id") or "") != doc_id
                ][:per_seed]
            except Exception:
                related_docs = []

        branches.append(
            {
                "seed": {
                    "id": f"procedure-{idx}",
                    "node_type": "procedure",
                    "relation_type": str(procedure.get("procedure_type") or "procedimento"),
                    "title": " · ".join(
                        part for part in [procedure.get("procedure_type"), procedure.get("procedure_identifier")] if part
                    )
                    or "Procedimento relacionado",
                    "subtitle": "Consulta correlata no corpus",
                    "query": query,
                },
                "related_documents": related_docs,
            }
        )

    return {
        "document": {
            "id": str(doc.get("id") or doc_id),
            "title": str(doc.get("identifica") or doc.get("titulo") or doc.get("ementa") or "Sem título"),
            "pub_date": str(doc.get("publication_date") or ""),
            "section": str(doc.get("section") or ""),
            "page": str(doc.get("page_number")) if doc.get("page_number") is not None else None,
            "art_type": str(doc.get("art_type") or "").strip() or None,
            "issuing_organ": str(doc.get("issuing_organ") or "").strip() or None,
        },
        "depth": depth,
        "per_seed": per_seed,
        "branches": branches,
    }


# ---------------------------------------------------------------------------
# API — Stats
# ---------------------------------------------------------------------------

@app.get("/api/stats")
def api_stats():
    """Search + DB stats."""
    conn = _conn()
    try:
        cur = conn.cursor()
        payload = stats_payload()
        search_stats = payload.get("search", {})

        cur.execute("SELECT pg_size_pretty(pg_database_size('gabi'))")
        db_size = cur.fetchone()[0]

        cur.execute("SELECT min(publication_date), max(publication_date) FROM dou.edition")
        dmin, dmax = cur.fetchone()

        cur.execute("""
            SELECT art_type, count(*) as cnt
            FROM dou.document GROUP BY art_type ORDER BY cnt DESC LIMIT 15
        """)
        type_dist = [{"type": t, "count": c} for t, c in cur.fetchall()]

        cur.execute("SELECT count(*) FROM dou.source_zip")
        zip_count = cur.fetchone()[0]

        cur.close()
    finally:
        conn.close()

    return {
        "search_backend": SEARCH_CFG.backend,
        "db_size": db_size,
        "total_docs": search_stats.get("total_docs"),
        "vocabulary_size": search_stats.get("vocabulary_size"),
        "avg_doc_length": search_stats.get("avg_doc_length"),
        "refreshed_at": str(search_stats.get("refreshed_at", "")),
        "search_index": search_stats.get("index"),
        "cluster_status": search_stats.get("cluster_status"),
        "date_min": dmin.isoformat() if dmin else None,
        "date_max": dmax.isoformat() if dmax else None,
        "zip_count": zip_count,
        "type_distribution": type_dist,
    }


@app.get("/api/analytics")
def api_analytics():
    """Operational analytics payload for home and analytics views."""
    conn = _conn()
    try:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                count(*)::bigint AS total_documents,
                (count(DISTINCT issuing_organ) FILTER (WHERE issuing_organ IS NOT NULL AND issuing_organ <> ''))::bigint AS total_organs,
                (count(DISTINCT art_type) FILTER (WHERE art_type IS NOT NULL AND art_type <> ''))::bigint AS total_types
            FROM dou.document
            """
        )
        total_documents, total_organs, total_types = cur.fetchone()

        cur.execute(
            """
            SELECT min(publication_date), max(publication_date)
            FROM dou.edition
            """
        )
        date_min, date_max = cur.fetchone()

        cur.execute(
            """
            SELECT
                date_trunc('month', e.publication_date)::date AS month,
                count(*) FILTER (WHERE e.section = 'do1' AND NOT COALESCE(e.is_extra, false))::bigint AS do1,
                count(*) FILTER (WHERE e.section = 'do2')::bigint AS do2,
                count(*) FILTER (WHERE e.section = 'do3')::bigint AS do3,
                count(*) FILTER (WHERE COALESCE(e.is_extra, false) OR e.section IN ('do1e', 'e'))::bigint AS extra,
                count(*)::bigint AS total
            FROM dou.document d
            JOIN dou.edition e ON e.id = d.edition_id
            GROUP BY 1
            ORDER BY 1 DESC
            LIMIT 18
            """
        )
        monthly_rows = list(reversed(cur.fetchall()))
        section_monthly = [
            {
                "month": row[0].isoformat() if row[0] else None,
                "do1": int(row[1] or 0),
                "do2": int(row[2] or 0),
                "do3": int(row[3] or 0),
                "extra": int(row[4] or 0),
                "total": int(row[5] or 0),
            }
            for row in monthly_rows
        ]

        cur.execute(
            """
            SELECT COALESCE(NULLIF(trim(art_type), ''), 'outros') AS art_type, count(*)::bigint AS cnt
            FROM dou.document
            GROUP BY 1
            ORDER BY cnt DESC
            LIMIT 5
            """
        )
        top_type_rows = cur.fetchall()
        top_types = [str(row[0]) for row in top_type_rows]

        type_points_by_month: dict[str, dict[str, int]] = {}
        if top_types:
            cur.execute(
                """
                SELECT
                    date_trunc('month', e.publication_date)::date AS month,
                    COALESCE(NULLIF(trim(d.art_type), ''), 'outros') AS art_type,
                    count(*)::bigint AS cnt
                FROM dou.document d
                JOIN dou.edition e ON e.id = d.edition_id
                WHERE COALESCE(NULLIF(trim(d.art_type), ''), 'outros') = ANY(%s)
                GROUP BY 1, 2
                ORDER BY 1 ASC
                """,
                (top_types,),
            )
            for month_value, art_type_value, count_value in cur.fetchall():
                month_key = month_value.isoformat() if month_value else ""
                bucket = type_points_by_month.setdefault(month_key, {})
                bucket[str(art_type_value)] = int(count_value or 0)

        top_types_monthly = {
            "months": [item["month"] for item in section_monthly],
            "series": [
                {
                    "key": art_type,
                    "label": art_type.replace("-", " ").title(),
                    "total": int(total or 0),
                    "points": [
                        type_points_by_month.get(str(item["month"]), {}).get(art_type, 0)
                        for item in section_monthly
                    ],
                }
                for art_type, total in top_type_rows
            ],
        }

        cur.execute(
            """
            SELECT issuing_organ, count(*)::bigint AS cnt
            FROM dou.document
            WHERE issuing_organ IS NOT NULL AND issuing_organ <> ''
            GROUP BY issuing_organ
            ORDER BY cnt DESC
            LIMIT 8
            """
        )
        top_organs = [
            {"organ": str(row[0]), "count": int(row[1] or 0)}
            for row in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT
                e.section,
                count(*)::bigint AS cnt
            FROM dou.document d
            JOIN dou.edition e ON e.id = d.edition_id
            GROUP BY e.section
            ORDER BY cnt DESC
            """
        )
        section_totals = [
            {"section": str(row[0] or ""), "count": int(row[1] or 0)}
            for row in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT
                d.id,
                d.identifica,
                d.ementa,
                d.issuing_organ,
                d.art_type,
                e.publication_date,
                e.section,
                d.page_number
            FROM dou.document d
            JOIN dou.edition e ON e.id = d.edition_id
            ORDER BY e.publication_date DESC, d.page_number DESC NULLS LAST, d.id DESC
            LIMIT 4
            """
        )
        latest_documents = []
        for row in cur.fetchall():
            latest_documents.append(
                {
                    "id": str(row[0]),
                    "title": str(row[1] or row[2] or "Sem título"),
                    "snippet": str(row[2] or "").strip() or None,
                    "issuing_organ": str(row[3] or "").strip() or None,
                    "art_type": str(row[4] or "").strip() or None,
                    "pub_date": row[5].isoformat() if row[5] else None,
                    "section": str(row[6] or ""),
                    "page": str(row[7]) if row[7] is not None else None,
                }
            )

        cur.close()
    finally:
        conn.close()

    return {
        "overview": {
            "total_documents": int(total_documents or 0),
            "total_organs": int(total_organs or 0),
            "total_types": int(total_types or 0),
            "date_min": date_min.isoformat() if date_min else None,
            "date_max": date_max.isoformat() if date_max else None,
            "tracked_months": len(section_monthly),
        },
        "section_totals": section_totals,
        "section_monthly": section_monthly,
        "top_types_monthly": top_types_monthly,
        "top_organs": top_organs,
        "latest_documents": latest_documents,
    }


# ---------------------------------------------------------------------------
# API — Types (for filter dropdown)
# ---------------------------------------------------------------------------

@app.get("/api/types")
def api_types():
    """Distinct art_type values with counts."""
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT art_type, count(*) as cnt
            FROM dou.document
            GROUP BY art_type
            ORDER BY cnt DESC
        """)
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return [{"type": t, "count": c} for t, c in rows]


# ---------------------------------------------------------------------------
# API — Chat (natural language search interface)
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] = []


import re as _re


def _chat_context(user_msg: str) -> str:
    """Build a factual context block from live DB queries (instant)."""
    parts: list[str] = []
    conn = _conn(timeout_ms=5000)
    try:
        cur = conn.cursor()
        cur.execute("SELECT cs.total_docs FROM dou.bm25_corpus_stats cs")
        row = cur.fetchone()
        total_docs = row[0] if row else 0

        cur.execute("SELECT min(publication_date), max(publication_date) FROM dou.edition")
        row = cur.fetchone()
        if row and total_docs:
            parts.append(f"A base possui {total_docs:,} documentos, de {row[0]} a {row[1]}.")

        cur.execute(
            "SELECT term, cnt FROM dou.suggest_cache "
            "WHERE cat = 'tipo' ORDER BY cnt DESC LIMIT 8"
        )
        types = [f"{r[0]} ({r[1]:,})" for r in cur.fetchall()]
        if types:
            parts.append("Tipos mais frequentes: " + ", ".join(types) + ".")

        cur.execute(
            "SELECT term, cnt FROM dou.suggest_cache "
            "WHERE cat = 'orgao' AND term ILIKE %s ORDER BY cnt DESC LIMIT 3",
            (f"%{user_msg}%",),
        )
        organs = cur.fetchall()
        if organs:
            parts.append(
                "Órgãos encontrados: "
                + ", ".join(f"{o[0]} ({o[1]:,} docs)" for o in organs)
                + "."
            )
        cur.close()
    except Exception:
        pass
    finally:
        conn.close()
    return "\n".join(parts)


def _normalize_chat_source(row: dict[str, Any]) -> dict[str, Any]:
    section = str(row.get("edition_section") or row.get("section") or "").strip().lower()
    if section in {"1", "do1", "secao1"}:
        section = "do1"
    elif section in {"2", "do2", "secao2"}:
        section = "do2"
    elif section in {"3", "do3", "secao3"}:
        section = "do3"
    elif section in {"e", "extra", "do1e"}:
        section = "do1e"

    title = str(
        row.get("identifica")
        or row.get("titulo")
        or row.get("ementa")
        or row.get("title")
        or "Sem título"
    ).strip()
    snippet = (
        str(row.get("snippet") or row.get("highlight") or row.get("ementa") or "")
        .replace(">>>", "")
        .replace("<<<", "")
        .strip()
    )
    doc_id = str(row.get("doc_id") or row.get("id") or "").strip()
    id_materia = row.get("id_materia")

    return {
        "id": doc_id,
        "title": title,
        "subtitle": str(row.get("ementa") or "").strip() or None,
        "snippet": snippet or None,
        "highlight": str(row.get("highlight") or "").strip() or None,
        "pub_date": str(row.get("pub_date") or row.get("publication_date") or "").strip(),
        "section": section,
        "page": str(row.get("page_number")).strip() if row.get("page_number") is not None else None,
        "art_type": str(row.get("art_type") or "").strip() or None,
        "issuing_organ": str(row.get("issuing_organ") or "").strip() or None,
        "dou_url": f"https://www.in.gov.br/web/dou/-/{id_materia}" if id_materia else None,
    }


def _compact_text(value: str, *, limit: int = 900) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _chat_excerpt_for_query(body_plain: str | None, query: str) -> str:
    text = str(body_plain or "").strip()
    if not text:
        return ""

    paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    if not paragraphs:
        paragraphs = [text]

    keywords = [
        token
        for token in re.findall(r"[\wÀ-ÿ]{4,}", query.lower())
        if token not in {"sobre", "quais", "qual", "como", "esta", "esse", "norma", "decreto", "portaria", "lei"}
    ][:6]

    for paragraph in paragraphs:
        corpus = paragraph.lower()
        if any(token in corpus for token in keywords):
            return _compact_text(paragraph)

    for paragraph in paragraphs:
        if re.search(r"\bart\.\s*\d+", paragraph, re.IGNORECASE):
            return _compact_text(paragraph)

    return _compact_text(paragraphs[0])


def _chat_rag_fallback_reply(message: str, sources: list[dict[str, Any]]) -> str:
    lines = [
        "Recuperei os atos mais relevantes para responder com base no corpus do DOU.",
        "Abra as fontes abaixo para leitura integral ou refine a pergunta com órgão, número da norma ou período.",
        "",
    ]
    for source in sources[:4]:
        bits = [
            str(source.get("art_type") or "").strip(),
            str(source.get("section") or "").upper(),
            str(source.get("pub_date") or "").strip(),
        ]
        meta = " · ".join(bit for bit in bits if bit)
        lines.append(f"• **{source.get('title') or 'Sem título'}**" + (f" — {meta}" if meta else ""))
        if source.get("snippet"):
            lines.append(f"  {source['snippet']}")
    lines.append("")
    lines.append(f"Pergunta original: *{message.strip()}*")
    return "\n".join(lines).strip()


def _chat_extract_organ_terms(message: str) -> list[str]:
    low = message.lower()
    aliases = {
        "anvisa": ["Agência Nacional de Vigilância Sanitária", "ANVISA"],
        "mec": ["Ministério da Educação"],
        "ms": ["Ministério da Saúde"],
        "receita federal": ["Receita Federal", "Ministério da Fazenda"],
        "anatel": ["Agência Nacional de Telecomunicações"],
    }
    terms: list[str] = []
    for alias, expansions in aliases.items():
        if alias in low:
            terms.extend(expansions)

    conn = _conn(timeout_ms=5000)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT term
            FROM dou.suggest_cache
            WHERE cat = 'orgao'
              AND length(term) >= 5
              AND %s ILIKE '%%' || term || '%%'
            ORDER BY length(term) DESC, cnt DESC
            LIMIT 3
            """,
            (message,),
        )
        terms.extend(str(row[0]) for row in cur.fetchall())
        cur.close()
    except Exception:
        pass
    finally:
        conn.close()

    out: list[str] = []
    seen: set[str] = set()
    for term in terms:
        value = str(term or "").strip()
        if value and value.casefold() not in seen:
            seen.add(value.casefold())
            out.append(value)
    return out


def _chat_exact_norm_matches(
    norm_query: NormQuery,
    *,
    organ_terms: list[str] | None = None,
    max_results: int = 4,
) -> list[dict[str, Any]]:
    organ_terms = [term for term in (organ_terms or []) if str(term).strip()]
    conn = _conn(timeout_ms=10000)
    try:
        cur = conn.cursor()
        sql = """
            SELECT d.id AS doc_id, d.id_materia, d.identifica, d.titulo, d.ementa,
                   d.issuing_organ, d.page_number, d.art_type, e.publication_date AS pub_date,
                   e.section AS edition_section
            FROM dou.document d
            JOIN dou.edition e ON e.id = d.edition_id
            WHERE (%s::text IS NULL OR d.art_type = %s)
              AND d.document_number = ANY(%s)
              AND (%s::int IS NULL OR d.document_year = %s)
        """
        params: list[Any] = [
            norm_query.norm_type,
            norm_query.norm_type,
            _resolved_norm_variants(norm_query),
            norm_query.year,
            norm_query.year,
        ]
        if organ_terms:
            sql += """
              AND (
            """
            clauses: list[str] = []
            for term in organ_terms:
                clauses.append(
                    "(d.issuing_organ ILIKE %s OR d.identifica ILIKE %s OR d.ementa ILIKE %s OR d.body_plain ILIKE %s)"
                )
                like = f"%{term}%"
                params.extend([like, like, like, like])
            sql += " OR ".join(clauses) + ")"

        sql += """
            ORDER BY
              CASE WHEN %s::int IS NOT NULL AND d.document_year = %s THEN 0 ELSE 1 END,
              e.publication_date DESC
            LIMIT %s
        """
        params.extend([norm_query.year, norm_query.year, max_results])
        cur.execute(sql, params)
        rows = _rows(cur)
        cur.close()
        return rows
    finally:
        conn.close()


def _chat_corpus_range() -> tuple[str | None, str | None]:
    conn = _conn(timeout_ms=5000)
    try:
        cur = conn.cursor()
        cur.execute("SELECT min(publication_date), max(publication_date) FROM dou.edition")
        row = cur.fetchone()
        cur.close()
        if not row:
            return None, None
        return (
            row[0].isoformat() if row[0] else None,
            row[1].isoformat() if row[1] else None,
        )
    except Exception:
        return None, None
    finally:
        conn.close()


def _chat_exact_norm_miss_reply(
    message: str,
    *,
    norm_query: NormQuery,
    organ_terms: list[str],
    nearby_sources: list[dict[str, Any]],
) -> str:
    date_min, date_max = _chat_corpus_range()
    norm_label = " ".join(
        part
        for part in [
            norm_query.norm_type.title() if norm_query.norm_type else "Norma",
            norm_query.canonical_number,
            f"/{norm_query.year}" if norm_query.year else "",
        ]
        if str(part).strip()
    ).replace(" /", "/")
    organ_label = ", ".join(organ_terms[:2]) if organ_terms else "o órgão solicitado"
    lines = [
        f"Não encontrei um ato exato para **{norm_label}** associado a **{organ_label}** no corpus carregado.",
    ]
    if date_min or date_max:
        lines.append(
            f"O recorte atual da base cobre **{date_min or '?'}** até **{date_max or '?'}**, então a fonte pedida pode estar fora dessa janela."
        )
    if nearby_sources:
        lines.append("")
        lines.append("Encontrei atos próximos pelo mesmo número, mas não vou tratá-los como equivalentes:")
        for source in nearby_sources[:3]:
            meta = " · ".join(
                bit
                for bit in [
                    str(source.get("art_type") or "").strip(),
                    str(source.get("issuing_organ") or "").strip(),
                    str(source.get("pub_date") or "").strip(),
                ]
                if bit
            )
            lines.append(f"• **{source.get('title') or 'Sem título'}**" + (f" — {meta}" if meta else ""))
    lines.append("")
    lines.append(f"Pergunta original: *{message.strip()}*")
    return "\n".join(lines).strip()


def _chat_rag_context(message: str, *, max_results: int = 4) -> dict[str, Any] | None:
    norm_query = detect_legal_norm(message)
    organ_terms = _chat_extract_organ_terms(message)
    relation_terms = [
        term
        for term in ["regulamenta", "revoga", "altera", "complementa", "cita"]
        if term in message.lower()
    ]
    search_query = message
    if norm_query is not None:
        search_query = " ".join(
            part
            for part in [
                norm_query.norm_type or "norma",
                norm_query.number_digits,
                str(norm_query.year) if norm_query.year is not None else "",
                *relation_terms,
            ]
            if str(part or "").strip()
        )
    merged_results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    if norm_query is not None:
        exact_rows = _chat_exact_norm_matches(norm_query, organ_terms=organ_terms, max_results=max_results)
        if not exact_rows and organ_terms:
            nearby_rows = _chat_exact_norm_matches(norm_query, organ_terms=None, max_results=max_results)
            nearby_sources = [_normalize_chat_source(row) for row in nearby_rows]
            return {
                "reply": _chat_exact_norm_miss_reply(
                    message,
                    norm_query=norm_query,
                    organ_terms=organ_terms,
                    nearby_sources=nearby_sources,
                ),
                "sources": nearby_sources,
                "context": "",
                "search_total": len(nearby_sources),
                "search_backend": "exact-norm-guard",
            }
        for row in exact_rows:
            doc_id = str(row.get("doc_id") or "").strip()
            if not doc_id or doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)
            merged_results.append(row)
    try:
        search = search_payload(query=search_query, max_results=max_results, page=1)
    except Exception:
        search = {"results": []}

    raw_results = search.get("results", [])
    if isinstance(raw_results, list):
        for raw in raw_results:
            row = raw if isinstance(raw, dict) else {}
            doc_id = str(row.get("doc_id") or row.get("id") or "").strip()
            if doc_id and doc_id not in seen_ids:
                seen_ids.add(doc_id)
                merged_results.append(row)

    if not merged_results:
        return None

    sources: list[dict[str, Any]] = []
    context_blocks: list[str] = []

    for index, raw in enumerate(merged_results[:max_results], start=1):
        row = raw if isinstance(raw, dict) else {}
        source = _normalize_chat_source(row)
        doc_id = str(source.get("id") or "").strip()
        body_plain = ""
        normative_refs: list[dict[str, Any]] = []

        if doc_id:
            try:
                doc = _load_document_payload(doc_id)
                if isinstance(doc, dict):
                    body_plain = str(doc.get("body_plain") or "").strip()
                    normative_refs = [
                        item for item in doc.get("normative_refs", []) if isinstance(item, dict)
                    ][:4]
                    if not source.get("subtitle"):
                        source["subtitle"] = str(doc.get("ementa") or "").strip() or None
            except HTTPException:
                pass
            except Exception:
                pass

        excerpt = _chat_excerpt_for_query(body_plain, message)
        if excerpt and not source.get("snippet"):
            source["snippet"] = excerpt

        ref_text = ", ".join(
            _compact_text(
                " ".join(
                    part
                    for part in [
                        str(item.get("reference_type") or "").strip(),
                        str(item.get("reference_number") or "").strip(),
                        str(item.get("reference_date") or "").strip(),
                    ]
                    if part
                ),
                limit=80,
            )
            for item in normative_refs[:3]
        )

        meta_bits = [
            str(source.get("art_type") or "").strip(),
            str(source.get("issuing_organ") or "").strip(),
            str(source.get("pub_date") or "").strip(),
            str(source.get("section") or "").upper(),
        ]
        meta = " | ".join(bit for bit in meta_bits if bit)
        block_lines = [f"[DOC {index}] {source.get('title') or 'Sem título'}"]
        if meta:
            block_lines.append(f"Metadados: {meta}")
        if source.get("subtitle"):
            block_lines.append(f"Ementa: {_compact_text(str(source['subtitle']), limit=360)}")
        if excerpt:
            block_lines.append(f"Trecho: {excerpt}")
        if ref_text:
            block_lines.append(f"Referências citadas: {ref_text}")
        context_blocks.append("\n".join(block_lines))
        sources.append(source)

    if not sources:
        return None

    return {
        "reply": _chat_rag_fallback_reply(message, sources),
        "sources": sources,
        "context": "\n\n".join(context_blocks),
        "search_total": int(search.get("total") or 0),
        "search_backend": str(search.get("backend") or "").strip() or None,
    }


SYSTEM_PROMPT = (
    "Você é a GABI, assistente do sistema de busca do Diário Oficial da União (DOU). "
    "Responda SEMPRE em português brasileiro, de forma curta e objetiva (máximo 3 parágrafos). "
    "O DOU é o jornal oficial do governo federal do Brasil, publicado diariamente. "
    "Ele contém portarias, decretos, leis, licitações, extratos de contratos, editais, "
    "atos de pessoal, entre outros atos normativos e administrativos. "
    "Você ajuda os usuários a encontrar publicações. "
    "Quando o usuário perguntar algo que pode ser buscado, sugira termos de busca "
    'concretos (ex: use a busca com "portaria ministério da saúde"). '
    "Quando houver documentos recuperados, responda com base neles, cite o tipo do ato e a data quando isso ajudar, "
    "e admita incerteza se as fontes não bastarem. "
    "Não invente dados — use apenas o contexto fornecido abaixo.\n\n"
)


def _sse_event(event: str, payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {body}\n\n".encode("utf-8")


def _chunk_text(value: str, *, chunk_size: int = 180) -> list[str]:
    text = str(value or "")
    if not text:
        return []
    return [text[idx: idx + chunk_size] for idx in range(0, len(text), chunk_size)]


def _parse_limit(msg: str) -> int:
    """Extract requested number of results from message."""
    low = msg.lower()
    m = _re.search(r'\b(\d{1,2})\s+(?:mais recente|últim|publicaç|resultado|document|portaria|decreto|edital|extrato|aviso|resolução|lei|ato)', low)
    if m:
        return min(int(m.group(1)), 20)
    m = _re.search(r'\b(últim[oa]s?|recentes?|primeiro)\s*(\d{1,2})', low)
    if m:
        return min(int(m.group(2)), 20)
    return 5


def _parse_date_filter(msg: str) -> tuple[str | None, str | None]:
    """Extract date range from message."""
    low = msg.lower()
    # "de 2020" or "em 2020" or "ano 2020"
    m = _re.search(r'\b(de|em|ano|desde)\s+(\d{4})\b', low)
    date_from = f"{m.group(2)}-01-01" if m else None
    m2 = _re.search(r'\b(até|ate|a)\s+(\d{4})\b', low)
    date_to = f"{m2.group(2)}-12-31" if m2 else None
    # If only one year mentioned with "de/em", treat as full year
    if date_from and not date_to:
        year = date_from[:4]
        date_to = f"{year}-12-31"
    return date_from, date_to


def _chat_search(msg: str) -> str | None:
    """Try to interpret the message as a search query and return formatted results."""
    import logging
    log = logging.getLogger("gabi.chat")
    low = msg.lower()

    # Detect art_type FIRST (before organ, to avoid type words matching as organs)
    art_type = None
    type_map = {
        'instrução normativa': 'instrução normativa',
        'portaria': 'portaria', 'portarias': 'portaria',
        'decreto': 'decreto', 'decretos': 'decreto',
        'edital': 'edital', 'editais': 'edital',
        'extrato': 'extrato', 'extratos': 'extrato',
        'aviso': 'aviso', 'avisos': 'aviso',
        'resolução': 'resolução', 'resoluções': 'resolução',
        'resolucao': 'resolução',
        'licitação': 'edital', 'licitacao': 'edital',
        'pregão': 'pregão', 'pregao': 'pregão',
        'lei': 'lei', 'leis': 'lei',
        'retificação': 'retificação',
        'nomeação': 'portaria', 'exoneração': 'portaria',
    }
    type_words_found: set[str] = set()
    for keyword, atype in type_map.items():
        if _re.search(rf'\b{_re.escape(keyword)}\b', low):
            art_type = atype
            type_words_found.add(keyword)
            break

    # Detect person: "mencionando X", "sobre X", or "X" in quotes
    person = None
    m = _re.search(r'(?:mencionando|sobre|nome|assinado por|assinada por)\s+(.+?)(?:\s+(?:de|em|do|da|no|na|desde|até)\s|\s*$)', low)
    if m:
        person = m.group(1).strip().title()
    if not person:
        m = _re.search(r'"([^"]+)"', msg)
        if m:
            person = m.group(1)

    # Detect organ
    organ = None
    conn = _conn(timeout_ms=15000)
    try:
        cur = conn.cursor()
        # Check if any known organ name appears in the message
        cur.execute(
            "SELECT term FROM dou.suggest_cache "
            "WHERE cat = 'orgao' AND length(term) >= 5 "
            "AND %s ILIKE '%%' || term || '%%' "
            "ORDER BY length(term) DESC, cnt DESC LIMIT 1",
            (msg,),
        )
        row = cur.fetchone()
        if row:
            # Make sure the matched organ isn't just a type keyword
            matched_organ = row[0].lower()
            if not any(kw in matched_organ for kw in type_words_found):
                organ = row[0]

        if not organ:
            # Extract capitalized multi-word fragments (potential organ names)
            words = _re.findall(r'[A-ZÀ-Ú][a-zà-ú]+(?:\s+(?:d[aoe]s?\s+)?[A-ZÀ-Ú][a-zà-ú]+)*', msg)
            # Also extract ALL-CAPS acronyms (e.g. ANVISA, IBAMA, INSS)
            acronyms = _re.findall(r'\b[A-ZÀ-Ú]{3,}\b', msg)
            candidates = [(w, 8) for w in words] + [(a, 2) for a in acronyms]
            for w, min_len in candidates:
                if len(w) > min_len and w.lower() not in type_words_found:
                    cur.execute(
                        "SELECT term FROM dou.suggest_cache "
                        "WHERE cat = 'orgao' AND term ~* %s "
                        "ORDER BY cnt DESC LIMIT 1",
                        (rf"\y{_re.escape(w)}\y",),
                    )
                    row = cur.fetchone()
                    if row:
                        organ = row[0]
                        break

        # If no organ, no type, no person — try to detect general search terms
        search_intent = bool(
            organ or art_type or person
            or _re.search(r'\b(publicaç|publicacoe|documento|norma|sobre|busca|busque|mostr|list|recente|últim|ultimo)', low)
        )

        if not search_intent:
            cur.close()
            return None

        # Build query
        limit = _parse_limit(msg)
        date_from, date_to = _parse_date_filter(msg)

        where_parts = ["1=1"]
        params: list = []

        if organ:
            where_parts.append("d.issuing_organ = %s")
            params.append(organ)
        if art_type:
            # Look up exact art_type values from DB to use btree index
            cur.execute(
                "SELECT DISTINCT term FROM dou.suggest_cache "
                "WHERE cat = 'tipo' AND term ILIKE %s",
                (f"%{art_type}%",),
            )
            matching_types = [r[0] for r in cur.fetchall()]
            if matching_types:
                placeholders = ",".join(["%s"] * len(matching_types))
                where_parts.append(f"d.art_type IN ({placeholders})")
                params.extend(matching_types)
            else:
                where_parts.append("d.art_type ILIKE %s")
                params.append(f"%{art_type}%")
        if date_from:
            where_parts.append("e.publication_date >= %s::date")
            params.append(date_from)
        if date_to:
            where_parts.append("e.publication_date <= %s::date")
            params.append(date_to)

        if person:
            where_parts.append(
                "d.body_tsvector @@ websearch_to_tsquery('pg_catalog.portuguese', %s)"
            )
            params.append(person)

        # If we only have search_intent from generic words but no filters, do FTS search
        if len(where_parts) == 1 and not person:
            # Extract meaningful words (skip stop words) and use FTS
            stop = {'as', 'os', 'de', 'do', 'da', 'dos', 'das', 'no', 'na', 'nos', 'nas',
                    'um', 'uma', 'uns', 'umas', 'em', 'por', 'para', 'com', 'que', 'qual',
                    'quais', 'mais', 'menos', 'últimas', 'últimos', 'ultima', 'ultimo',
                    'recentes', 'recente', 'primeiro', 'primeira', 'publicações', 'publicacoes',
                    'documentos', 'documento', 'sobre', 'buscar', 'busque', 'me', 'mostre',
                    'mostra', 'lista', 'liste'}
            meaningful = [w for w in _re.findall(r'\w+', low) if len(w) > 2 and w not in stop]
            if meaningful:
                terms = " ".join(meaningful[:5])
                where_parts.append(
                    "d.body_tsvector @@ websearch_to_tsquery('pg_catalog.portuguese', %s)"
                )
                params.append(terms)

        params.append(limit)

        sql = f"""
            SELECT d.id, d.identifica, d.ementa, d.art_type, d.issuing_organ,
                   e.publication_date, e.section
            FROM dou.document d
            JOIN dou.edition e ON e.id = d.edition_id
            WHERE {' AND '.join(where_parts)}
            ORDER BY e.publication_date DESC
            LIMIT %s
        """
        log.info("chat_search sql=%s params=%s", sql.strip()[:200], params)
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
    except Exception as exc:
        log.exception("chat_search error: %s", exc)
        return None
    finally:
        conn.close()

    if not rows:
        parts = []
        if organ:
            parts.append(f"do **{organ}**")
        if art_type:
            parts.append(f"do tipo **{art_type}**")
        if person:
            parts.append(f"mencionando **{person}**")
        desc = " ".join(parts) if parts else "com esses critérios"
        return f"Não encontrei publicações {desc} na base. Tente com outros termos na aba **Busca**."

    # Format results
    lines: list[str] = []
    desc_parts = []
    if organ:
        desc_parts.append(f"**{organ}**")
    if art_type:
        desc_parts.append(f"tipo **{art_type}**")
    if person:
        desc_parts.append(f"mencionando **{person}**")
    desc = " · ".join(desc_parts) if desc_parts else "publicações"

    lines.append(f"Encontrei {len(rows)} {desc}:\n")

    for r in rows:
        doc_id, identifica, ementa, atype, issuer, pub_date, section = r
        date_str = pub_date.strftime("%d/%m/%Y") if pub_date else "?"
        sec = section.upper() if section else ""
        title = (identifica or ementa or "Sem título")[:120]
        atype_label = (atype or "").upper()
        lines.append(
            f"**{atype_label}** · {sec} · {date_str}\n"
            f"{title}\n"
        )

    lines.append("---\n*Clique em um resultado na aba Busca para ver o documento completo.*")
    return "\n".join(lines)


def _is_off_topic(msg: str) -> bool:
    """Detect messages clearly unrelated to DOU/legal publications."""
    low = msg.lower().strip()
    if detect_legal_norm(msg) is not None:
        return False
    if _re.search(r"\b(publicaç|documento|ato|norma|dou|diário oficial|portaria|decreto|lei|edital|resolução)\b", low):
        return False
    # Math expressions (operators present, not just a year)
    ops = len(_re.findall(r'[+\-*/=^]{1}', low))
    if ops >= 2:
        return True
    # Clearly off-topic
    off_patterns = [
        r'\b(piada|joke|futebol|soccer|receita de|clima|tempo|previsão|horóscopo)\b',
        r'\b(quem ganhou|quem venceu|placar|jogo)\b',
        r'\b(programa|código|python|javascript|html|css)\b.*\b(como|faço|faz)\b',
    ]
    for p in off_patterns:
        if _re.search(p, low):
            return True
    return False


def _should_use_rag(msg: str) -> bool:
    low = msg.lower().strip()
    norm = detect_legal_norm(msg)
    if norm is None and not re.search(r"\b(norma|ato|documento|dou|diário oficial)\b", low):
        return False

    rag_patterns = [
        r"\b(explica|explique|explicar|resuma|resumir|resumo)\b",
        r"\b(o que diz|o que dispõe|o que dispoe|o que estabelece|do que trata)\b",
        r"\b(qual a diferença|quais são|quais sao|quais|qual)\b",
        r"\b(regulamenta|regulamentam|revoga|revogam|altera|alteram|complementa|complementam|cita|citam)\b",
        r"\b(como funciona|como se aplica|impacto|efeito)\b",
    ]
    return any(re.search(pattern, low) for pattern in rag_patterns)


@app.post("/api/chat")
async def api_chat(
    req: ChatRequest,
    request: Request,
    stream: bool = Query(False),
    _auth: AuthPrincipal = Depends(require_protected_access),
):
    """Chat: natural language search interface for DOU publications."""
    msg = req.message.strip()
    low = msg.lower()
    chat_security = getattr(request.app.state, "chat_security", None)
    limiter = getattr(request.app.state, "rate_limiter", None)

    async def finalize(payload: dict[str, Any]) -> dict[str, Any]:
        if isinstance(chat_security, ChatSecurity):
            await chat_security.cache_reply(msg, req.history, payload)
        return payload

    async def stream_payload(payload: dict[str, Any], *, cache_reply: bool) -> StreamingResponse:
        async def iterator() -> AsyncIterator[bytes]:
            effective = await finalize(payload) if cache_reply else payload
            yield _sse_event(
                "meta",
                {
                    "model": str(effective.get("model", "gabi")),
                    "cache": effective.get("cache"),
                    "source_count": len(effective.get("sources", []) or []),
                },
            )
            for chunk in _chunk_text(str(effective.get("reply", ""))):
                yield _sse_event("delta", {"content": chunk})
            yield _sse_event(
                "done",
                {
                    "reply": str(effective.get("reply", "")),
                    "model": str(effective.get("model", "gabi")),
                    "cache": effective.get("cache"),
                    "sources": effective.get("sources", []),
                },
            )

        return StreamingResponse(
            iterator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def stream_qwen(
        messages: list[dict[str, str]],
        *,
        sources: list[dict[str, Any]] | None = None,
        fallback_payload: dict[str, Any] | None = None,
    ) -> StreamingResponse:
        http = request.app.state.http

        async def iterator() -> AsyncIterator[bytes]:
            collected: list[str] = []
            meta_sent = False
            try:
                async with http.stream(
                    "POST",
                    DASHSCOPE_URL,
                    headers={
                        "Authorization": f"Bearer {QWEN_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": QWEN_MODEL,
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 2048,
                        "stream": True,
                    },
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            payload = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        delta = (
                            payload.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if not meta_sent:
                            meta_sent = True
                            yield _sse_event(
                                "meta",
                                {
                                    "model": QWEN_MODEL,
                                    "source_count": len(sources or []),
                                },
                            )
                        if delta:
                            collected.append(str(delta))
                            yield _sse_event("delta", {"content": str(delta)})
            except Exception as exc:
                if fallback_payload is not None:
                    effective = await finalize(
                        {
                            "reply": str(fallback_payload.get("reply", "")),
                            "model": str(fallback_payload.get("model", "gabi-rag")),
                            "sources": fallback_payload.get("sources", sources or []),
                        }
                    )
                    if not meta_sent:
                        yield _sse_event(
                            "meta",
                            {
                                "model": str(effective.get("model", "gabi-rag")),
                                "cache": effective.get("cache"),
                                "source_count": len(effective.get("sources", []) or []),
                            },
                        )
                    for chunk in _chunk_text(str(effective.get("reply", ""))):
                        yield _sse_event("delta", {"content": chunk})
                    yield _sse_event(
                        "done",
                        {
                            "reply": str(effective.get("reply", "")),
                            "model": str(effective.get("model", "gabi-rag")),
                            "cache": effective.get("cache"),
                            "sources": effective.get("sources", []),
                        },
                    )
                    return
                yield _sse_event("error", {"detail": str(exc)})
                return

            payload = await finalize(
                {
                    "reply": "".join(collected),
                    "model": QWEN_MODEL,
                    "sources": sources or [],
                }
            )
            yield _sse_event(
                "done",
                {
                    "reply": payload["reply"],
                    "model": payload["model"],
                    "cache": payload.get("cache"),
                    "sources": payload.get("sources", []),
                },
            )

        return StreamingResponse(
            iterator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    if isinstance(chat_security, ChatSecurity):
        await chat_security.enforce(request, limiter=limiter if isinstance(limiter, RateLimiter) else None)
        cached = await chat_security.get_cached_reply(msg, req.history)
        if cached is not None:
            if stream:
                return await stream_payload(cached, cache_reply=False)
            return cached

    payload: dict[str, Any] | None = None

    if _re.search(r'^(oi|olá|ola|hey|bom dia|boa tarde|boa noite|hello|hi)\b', low):
        payload = {
            "reply": (
                "Olá! Sou a **GABI**, sua assistente para buscas no Diário Oficial da União.\n\n"
                "Posso buscar publicações para você! Experimente:\n"
                '• *"5 últimas portarias do Ministério da Saúde"*\n'
                '• *"editais de licitação de 2024"*\n'
                '• *"publicações mencionando Fernando Lima"*\n\n'
                "Ou pergunte: *O que é o DOU?* · *Como buscar?*"
            ),
            "model": "gabi",
        }
    elif _re.search(r'\b(o que é|oque é|que é o|explica).*(dou|diário oficial|gabi)\b', low):
        payload = {
            "reply": (
                "O **DOU** (Diário Oficial da União) é o jornal oficial do governo federal do Brasil, "
                "publicado diariamente pela Imprensa Nacional.\n\n"
                "Nele são publicados: portarias, decretos, leis, licitações, extratos de contratos, "
                "editais, nomeações/exonerações e outros atos administrativos.\n\n"
                "A GABI busca essas publicações para você. Experimente: "
                '*"últimas 5 portarias do Ministério da Educação"*'
            ),
            "model": "gabi",
        }
    elif _re.search(r'\b(como|ajuda|help|dica|sintaxe).*(busca|pesquis|procur|encontr|usar)', low):
        payload = {
            "reply": (
                "**Como buscar no GABI:**\n\n"
                '🔍 Peça diretamente: *"portarias do Ministério da Saúde de 2023"*\n\n'
                "Ou use a aba **Busca**:\n"
                '• **Aspas** para frase exata: *"decreto presidencial"*\n'
                "• **Filtros** por data, seção, tipo de ato\n"
                "• Operadores: `OR` (um ou outro), `-termo` (excluir)\n"
                "• Clique num **órgão** no autocomplete para filtro instantâneo"
            ),
            "model": "gabi",
        }
    elif _is_off_topic(msg):
        payload = {
            "reply": (
                "Desculpe, só posso ajudar com buscas no **Diário Oficial da União** "
                "(publicações, órgãos, atos normativos).\n\n"
                "Experimente perguntar algo como:\n"
                '• *"últimas portarias do Ministério da Saúde"*\n'
                '• *"editais de licitação de 2024"*\n'
                '• *"publicações mencionando João Silva"*'
            ),
            "model": "gabi",
        }

    use_rag = _should_use_rag(msg)
    rag = _chat_rag_context(msg, max_results=min(_parse_limit(msg), 4)) if use_rag else None
    if payload is not None:
        if stream:
            return await stream_payload(payload, cache_reply=True)
        return await finalize(payload)

    if not use_rag:
        result = _chat_search(msg)
        if result:
            payload = {"reply": result, "model": "gabi"}
            if stream:
                return await stream_payload(payload, cache_reply=True)
            return await finalize(payload)

    if rag is not None and not QWEN_API_KEY:
        payload = {
            "reply": rag["reply"],
            "model": "gabi-rag",
            "sources": rag["sources"],
        }
        if stream:
            return await stream_payload(payload, cache_reply=True)
        return await finalize(payload)

    if QWEN_API_KEY:
        ctx = _chat_context(msg)
        system_parts = [SYSTEM_PROMPT]
        if ctx:
            system_parts.append(f"CONTEXTO DA BASE:\n{ctx}")
        if rag is not None:
            system_parts.append(
                "DOCUMENTOS RECUPERADOS:\n"
                f"{rag['context']}\n\n"
                "Use esses documentos como fonte primária da resposta. "
                "Se a pergunta pedir comparação, regulamentos, alterações ou explicação, "
                "baseie a resposta no que aparece nessas fontes e mencione quando algo não estiver explícito."
            )
        system = "\n\n".join(part for part in system_parts if part)
        messages = [{"role": "system", "content": system}]
        for h in req.history[-10:]:
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        messages.append({"role": "user", "content": msg})

        if stream:
            return await stream_qwen(
                messages,
                sources=list(rag.get("sources", [])) if rag is not None else None,
                fallback_payload=(
                    {
                        "reply": rag["reply"],
                        "model": "gabi-rag",
                        "sources": rag["sources"],
                    }
                    if rag is not None
                    else None
                ),
            )

        http = request.app.state.http
        try:
            resp = await http.post(
                DASHSCOPE_URL,
                headers={
                    "Authorization": f"Bearer {QWEN_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": QWEN_MODEL,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 2048,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            reply = data["choices"][0]["message"]["content"]
            return await finalize(
                {
                    "reply": reply,
                    "model": QWEN_MODEL,
                    "sources": list(rag.get("sources", [])) if rag is not None else [],
                }
            )
        except Exception:
            if rag is not None:
                payload = {
                    "reply": rag["reply"],
                    "model": "gabi-rag",
                    "sources": rag["sources"],
                }
                if stream:
                    return await stream_payload(payload, cache_reply=True)
                return await finalize(payload)

    payload = {
        "reply": (
            "Não entendi sua pergunta. Posso buscar publicações do DOU para você!\n\n"
            "Experimente:\n"
            '• *"portarias do Ministério da Saúde"*\n'
            '• *"editais de licitação de 2024"*\n'
            '• *"publicações mencionando Maria Silva"*\n\n'
            "Ou pergunte: *O que é o DOU?* · *Como buscar?*"
        ),
        "model": "gabi",
    }
    if stream:
        return await stream_payload(payload, cache_reply=True)
    return await finalize(payload)


# ---------------------------------------------------------------------------
# API — Media (serve document images)
# ---------------------------------------------------------------------------


@app.get("/api/media/{doc_id}/{media_name}")
def api_media(
    doc_id: str,
    media_name: str,
    _auth: AuthPrincipal = Depends(require_protected_access),
):
    """Serve media from bytea or local cache only."""
    conn = _conn(timeout_ms=10000)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT data, media_type, local_path, availability_status, ingest_checked_at
            FROM dou.document_media
            WHERE document_id = %s::uuid
              AND (
                    media_name = %s
                 OR source_filename = %s
                 OR media_name = regexp_replace(%s, E'\\.[^\\.]+$', '')
              )
            LIMIT 1
        """, (doc_id, media_name, media_name, media_name))
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    if not row:
        raise HTTPException(404, "Imagem não encontrada")

    data, media_type, local_path, availability_status, ingest_checked_at = row
    if data is None:
        resolved = _resolve_local_media_path(local_path)
        if resolved and resolved.exists():
            return FileResponse(
                resolved,
                media_type=media_type or "image/jpeg",
                headers={"Cache-Control": "public, max-age=86400"},
            )
        if local_path:
            log_security_event(
                "media_cache_lookup_failed",
                doc_id=doc_id,
                media_name=media_name,
                local_path=str(local_path),
            )
        if availability_status == "available" and ingest_checked_at is not None:
            raise HTTPException(500, "Imagem classificada como disponível, mas cache local está ausente")
        raise HTTPException(404, "Imagem não disponível")

    return Response(
        content=bytes(data),
        media_type=media_type or "image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ---------------------------------------------------------------------------
# Static files — serve frontend
# ---------------------------------------------------------------------------

# SPA fallback: serve index.html for non-API routes
@app.get("/")
def index():
    _require_frontend_enabled()
    return FileResponse(SPA_INDEX)


@app.get("/search")
@app.get("/search/{path:path}")
def search_page(path: str = ""):
    _require_frontend_enabled()
    return FileResponse(SPA_INDEX)


@app.get("/analytics")
@app.get("/analytics/{path:path}")
def analytics_page(path: str = ""):
    _require_frontend_enabled()
    return FileResponse(SPA_INDEX)


@app.get("/document/{path:path}")
def document_page(path: str):
    _require_frontend_enabled()
    return FileResponse(SPA_INDEX)


@app.get("/documento/{path:path}")
def documento_page(path: str):
    _require_frontend_enabled()
    return FileResponse(SPA_INDEX)


@app.get("/doc/{path:path}")
def doc_page(path: str):
    """Serve SPA for document pages."""
    _require_frontend_enabled()
    return FileResponse(SPA_INDEX)


@app.get("/dist/{path:path}")
def dist_asset(path: str):
    _require_frontend_enabled()
    requested_path = Path(path)
    if requested_path.is_absolute():
        log_security_event("dist_asset_denied", requested_path=path, reason="absolute_path")
        raise HTTPException(403, "Asset path denied")
    resolved = (DIST_DIR / requested_path).resolve()
    try:
        resolved.relative_to(DIST_DIR)
    except ValueError:
        log_security_event(
            "dist_asset_denied",
            requested_path=path,
            resolved_path=str(resolved),
            reason="path_traversal",
        )
        raise HTTPException(403, "Asset path denied")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(404, "Asset não encontrado")
    return FileResponse(resolved)


@app.get("/assets/{path:path}")
def assets_asset(path: str):
    _require_frontend_enabled()
    requested_path = Path(path)
    if requested_path.is_absolute():
        log_security_event("assets_asset_denied", requested_path=path, reason="absolute_path")
        raise HTTPException(403, "Asset path denied")
    resolved = (ASSETS_DIR / requested_path).resolve()
    try:
        resolved.relative_to(ASSETS_DIR)
    except ValueError:
        log_security_event(
            "assets_asset_denied",
            requested_path=path,
            resolved_path=str(resolved),
            reason="path_traversal",
        )
        raise HTTPException(403, "Asset path denied")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(404, "Asset não encontrado")
    return FileResponse(resolved)

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse
    import uvicorn

    p = argparse.ArgumentParser(description="GABI DOU Web Server")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--reload", action="store_true")
    args = p.parse_args()

    uvicorn.run(
        "src.backend.apps.web_server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
