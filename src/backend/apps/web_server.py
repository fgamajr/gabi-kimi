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
import json
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel

from src.backend.apps.mcp_server import (
    SEARCH_CFG,
    search_examples_payload,
    search_payload,
    stats_payload,
    suggest_payload,
    top_searches_payload,
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

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown."""
    app.state.http = httpx.AsyncClient(timeout=60.0)
    yield
    await app.state.http.aclose()


app = FastAPI(title="GABI DOU", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    candidate = Path(local_path)
    if not candidate.is_absolute():
        candidate = _ROOT_DIR / candidate
    return candidate


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
# API — Document
# ---------------------------------------------------------------------------

@app.get("/api/document/{doc_id}")
def api_document(doc_id: str):
    """Get full document by UUID."""
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

        # Normative references
        cur.execute("""
            SELECT reference_type, reference_number, reference_date, reference_text
            FROM dou.normative_reference WHERE document_id = %s::uuid
            ORDER BY reference_type, reference_number
        """, (doc_id,))
        doc["normative_refs"] = [
            {k: _ser(v) for k, v in r.items()}
            for r in _rows(cur)
        ]

        # Procedure references
        cur.execute("""
            SELECT procedure_type, procedure_identifier
            FROM dou.procedure_reference WHERE document_id = %s::uuid
        """, (doc_id,))
        doc["procedure_refs"] = [
            {k: _ser(v) for k, v in r.items()}
            for r in _rows(cur)
        ]

        # Signatures
        cur.execute("""
            SELECT person_name, role_title
            FROM dou.document_signature WHERE document_id = %s::uuid
            ORDER BY sequence_in_document
        """, (doc_id,))
        doc["signatures"] = [
            {k: _ser(v) for k, v in r.items()}
            for r in _rows(cur)
        ]

        # Media list (names only, images served separately)
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
    finally:
        conn.close()

    return doc


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


SYSTEM_PROMPT = (
    "Você é a GABI, assistente do sistema de busca do Diário Oficial da União (DOU). "
    "Responda SEMPRE em português brasileiro, de forma curta e objetiva (máximo 3 parágrafos). "
    "O DOU é o jornal oficial do governo federal do Brasil, publicado diariamente. "
    "Ele contém portarias, decretos, leis, licitações, extratos de contratos, editais, "
    "atos de pessoal, entre outros atos normativos e administrativos. "
    "Você ajuda os usuários a encontrar publicações. "
    "Quando o usuário perguntar algo que pode ser buscado, sugira termos de busca "
    'concretos (ex: use a busca com "portaria ministério da saúde"). '
    "Não invente dados — use apenas o contexto fornecido abaixo.\n\n"
)


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
    # Math expressions (operators present, not just a year)
    ops = len(_re.findall(r'[+\-*/=^]{1}', low))
    if ops >= 2 and not _re.search(r'\b(publicaç|documento|ato|dou|edital|portaria|decreto|ministério)', low):
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


@app.post("/api/chat")
async def api_chat(req: ChatRequest, request: Request):
    """Chat: natural language search interface for DOU publications."""
    msg = req.message.strip()
    low = msg.lower()

    # 1. Greetings
    if _re.search(r'^(oi|olá|ola|hey|bom dia|boa tarde|boa noite|hello|hi)\b', low):
        return {
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

    # 2. What is DOU / help
    if _re.search(r'\b(o que é|oque é|que é o|explica).*(dou|diário oficial|gabi)\b', low):
        return {
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

    # 3. How to search
    if _re.search(r'\b(como|ajuda|help|dica|sintaxe).*(busca|pesquis|procur|encontr|usar)', low):
        return {
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

    # 4. Off-topic rejection
    if _is_off_topic(msg):
        return {
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

    # 5. Try to interpret as a search and return real documents
    result = _chat_search(msg)
    if result:
        return {"reply": result, "model": "gabi"}

    # 6. Fallback: try Qwen API if available
    if QWEN_API_KEY:
        ctx = _chat_context(msg)
        system = SYSTEM_PROMPT + (f"CONTEXTO DA BASE:\n{ctx}" if ctx else "")
        messages = [{"role": "system", "content": system}]
        for h in req.history[-10:]:
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        messages.append({"role": "user", "content": msg})

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
            return {"reply": reply, "model": QWEN_MODEL}
        except Exception:
            pass

    # 7. Final fallback
    return {
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


# ---------------------------------------------------------------------------
# API — Media (serve document images)
# ---------------------------------------------------------------------------


@app.get("/api/media/{doc_id}/{media_name}")
def api_media(doc_id: str, media_name: str):
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
    return FileResponse(SPA_INDEX)


@app.get("/search")
@app.get("/search/{path:path}")
def search_page(path: str = ""):
    return FileResponse(SPA_INDEX)


@app.get("/document/{path:path}")
def document_page(path: str):
    return FileResponse(SPA_INDEX)


@app.get("/doc/{path:path}")
def doc_page(path: str):
    """Serve SPA for document pages."""
    return FileResponse(SPA_INDEX)


@app.get("/dist/{path:path}")
def dist_asset(path: str):
    file_path = WEB_DIR / "dist" / path
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(404, "Asset não encontrado")
    return FileResponse(file_path)

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
