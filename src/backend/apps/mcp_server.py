"""MCP Server for GABI DOU search.

Exposes configured search backends over DOU publications (Diário Oficial da
União) as MCP tools, including PostgreSQL BM25, Elasticsearch, and hybrid
retrieval (BM25 + vector + RRF).

Usage:
  # stdio transport (for local MCP clients like Claude Desktop, VS Code)
  python3 ops/bin/mcp_server.py

  # SSE transport (for remote/web clients)
  python3 ops/bin/mcp_server.py --transport sse --port 8765

MCP Tools:
  - dou_search:          Search across all DOU documents
  - dou_search_filtered: Search with date/section/type filters
  - dou_stats:           Database and search index statistics
  - dou_document:        Retrieve a specific document by ID
"""

from __future__ import annotations

import math
import os
from datetime import date
from typing import Any

import httpx
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:
    FastMCP = None  # type: ignore[assignment]

from src.backend.search.adapters import create_search_adapter, load_search_config
from src.backend.search.redis_signals import (
    get_cached_search,
    get_cached_suggest,
    normalize_query,
    record_query,
    redis_available,
    set_cached_search,
    set_cached_suggest,
    top_prefix_matches,
    top_searches,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DSN = (
    f"host={os.getenv('PGHOST', 'localhost')} "
    f"port={os.getenv('PGPORT', '5433')} "
    f"dbname={os.getenv('PGDATABASE', 'gabi')} "
    f"user={os.getenv('PGUSER', 'gabi')} "
    f"password={os.getenv('PGPASSWORD', 'gabi')}"
)

if FastMCP is not None:
    mcp = FastMCP(
        "GABI DOU Search",
        instructions=(
            "Search engine for Brazilian Federal Official Gazette (DOU) publications. "
            "Contains 1M+ legal documents (portarias, decretos, licitações, extratos, etc.) "
            "from 2002-2026 with configurable search backend (PG BM25 or Elasticsearch). "
            "Queries should be in Portuguese."
        ),
    )
else:
    mcp = None
SEARCH_CFG = load_search_config()
SEARCH_ADAPTER = create_search_adapter(SEARCH_CFG)
CURATED_EXAMPLES = [
    "portaria ministério da saúde",
    "decreto presidencial 2002",
    "edital de licitação do3",
    "extrato de contrato ministério da educação",
    "resolução anvisa medicamento",
    "nomeação ministro",
    "pregão eletrônico",
    "instrução normativa receita federal",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_conn():
    return psycopg2.connect(DSN)


def _rows_to_dicts(cur) -> list[dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _serialize(obj: Any) -> Any:
    """Make objects JSON-serializable."""
    if isinstance(obj, (date,)):
        return obj.isoformat()
    if isinstance(obj, memoryview):
        return "<binary>"
    return obj


def _format_results(rows: list[dict]) -> str:
    """Format search results as readable text for the AI."""
    if not rows:
        return "Nenhum resultado encontrado."

    parts = []
    for i, r in enumerate(rows, 1):
        lines = [f"### Resultado {i} — BM25 score: {r['score']:.4f}"]
        lines.append(
            f"**Tipo:** {r.get('art_type', '?')} | "
            f"**Seção:** {r.get('edition_section', '?')} | "
            f"**Data:** {r.get('pub_date', '?')}"
        )
        if r.get("identifica"):
            lines.append(f"**Título:** {r['identifica'][:300]}")
        if r.get("ementa"):
            lines.append(f"**Ementa:** {r['ementa'][:500]}")
        if r.get("snippet"):
            snip = r["snippet"].replace(">>>", "**").replace("<<<", "**")
            lines.append(f"**Trecho:** ...{snip}...")
        lines.append(f"**ID:** `{r['doc_id']}`")
        parts.append("\n".join(lines))

    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Shared payload API (used by MCP tools and web server)
# ---------------------------------------------------------------------------


def search_payload(
    query: str,
    max_results: int = 10,
    page: int = 1,
    date_from: str | None = None,
    date_to: str | None = None,
    section: str | None = None,
    art_type: str | None = None,
    issuing_organ: str | None = None,
) -> dict[str, Any]:
    """Structured search payload using configured backend."""
    max_results = min(max(1, max_results), 50)
    cache_params = {
        "backend": SEARCH_CFG.backend,
        "query": normalize_query(query),
        "max_results": max_results,
        "page": max(1, page),
        "date_from": date_from or "",
        "date_to": date_to or "",
        "section": section or "",
        "art_type": art_type or "",
        "issuing_organ": issuing_organ or "",
    }
    cached = get_cached_search(cache_params)
    if cached is not None:
        record_query(query)
        return cached

    result = SEARCH_ADAPTER.search(
        query=query,
        page_size=max_results,
        page=max(1, page),
        date_from=date_from,
        date_to=date_to,
        section=section,
        art_type=art_type,
        issuing_organ=issuing_organ,
    )
    set_cached_search(cache_params, result)
    record_query(query)
    return result


def suggest_payload(query: str, limit: int = 10) -> dict[str, Any]:
    """Structured suggest payload with ES base + Redis popularity boosts."""
    limit = max(1, min(limit, 20))
    cached = get_cached_suggest(query)
    if cached is not None:
        return {"prefix": query, "suggestions": cached[:limit]}

    base = SEARCH_ADAPTER.suggest(query=query, limit=max(limit * 2, 12))
    base_rows = base.get("suggestions", [])
    prefix_rows = top_prefix_matches(query, n=max(limit * 2, 12))
    prefix_norm = normalize_query(query)

    rank: dict[str, dict[str, Any]] = {}
    for idx, s in enumerate(base_rows):
        term = str(s.get("term", "")).strip()
        if not term:
            continue
        key = normalize_query(term)
        if not key:
            continue
        rank[key] = {
            "term": term,
            "doc_freq": int(s.get("doc_freq", 0) or 0),
            "cat": s.get("cat", "titulo"),
            "score": max(0.0, 100.0 - idx * 3.0),
        }

    for p in prefix_rows:
        term = str(p.get("term", "")).strip()
        if not term:
            continue
        key = normalize_query(term)
        if not key:
            continue
        boost = 50.0 + (math.log1p(float(p.get("count", 0) or 0)) * 12.0)
        if key in rank:
            rank[key]["score"] += boost
            rank[key]["doc_freq"] = max(int(rank[key].get("doc_freq", 0)), int(p.get("count", 0) or 0))
        else:
            rank[key] = {
                "term": term,
                "doc_freq": int(p.get("count", 0) or 0),
                "cat": "top",
                "score": boost,
            }

    if not rank and prefix_norm:
        for ex in CURATED_EXAMPLES:
            if normalize_query(ex).startswith(prefix_norm):
                key = normalize_query(ex)
                rank[key] = {"term": ex, "doc_freq": 0, "cat": "example", "score": 20.0}

    rows = sorted(rank.values(), key=lambda x: (x["score"], x["doc_freq"]), reverse=True)[:limit]
    set_cached_suggest(query, rows)
    return {"prefix": query, "suggestions": rows}


def top_searches_payload(period: str = "day", n: int = 10) -> dict[str, Any]:
    period = "week" if period == "week" else "day"
    items = top_searches(period=period, n=n)
    return {"period": period, "items": items, "available": redis_available()}


def search_examples_payload(n: int = 8) -> dict[str, Any]:
    n = max(1, min(n, 20))
    items: list[dict[str, str]] = []
    seen: set[str] = set()

    for row in top_searches(period="week", n=max(n * 2, 12)):
        term = str(row.get("term", "")).strip()
        if not term:
            continue
        key = normalize_query(term)
        if key in seen:
            continue
        seen.add(key)
        items.append({"term": term, "source": "trending"})
        if len(items) >= n:
            return {"items": items}

    for term in CURATED_EXAMPLES:
        key = normalize_query(term)
        if key in seen:
            continue
        seen.add(key)
        items.append({"term": term, "source": "curated"})
        if len(items) >= n:
            break

    return {"items": items}


def stats_payload() -> dict[str, Any]:
    """Structured DB/search stats payload."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        out: dict[str, Any] = {"search_backend": SEARCH_CFG.backend}
        if SEARCH_CFG.backend == "pg":
            cur.execute("SELECT * FROM dou.v_bm25_stats")
            cols = [d[0] for d in cur.description]
            out["search"] = dict(zip(cols, cur.fetchone())) if cur.description else {}
        else:
            auth = (SEARCH_CFG.es_username, SEARCH_CFG.es_password) if SEARCH_CFG.es_username else None
            with httpx.Client(timeout=8, verify=SEARCH_CFG.es_verify_tls, auth=auth) as client:
                health = client.get(f"{SEARCH_CFG.es_url}/_cluster/health")
                health.raise_for_status()
                health_data = health.json()
                count = client.get(f"{SEARCH_CFG.es_url}/{SEARCH_CFG.es_index}/_count")
                count.raise_for_status()
                count_data = count.json()
            out["search"] = {
                "total_docs": int(count_data.get("count", 0)),
                "cluster_status": health_data.get("status"),
                "index": SEARCH_CFG.es_index,
            }
        cur.execute("SELECT pg_size_pretty(pg_database_size('gabi'))")
        out["db_size"] = cur.fetchone()[0]
        cur.execute("SELECT min(publication_date), max(publication_date) FROM dou.edition")
        dmin, dmax = cur.fetchone()
        out["date_min"] = dmin.isoformat() if dmin else None
        out["date_max"] = dmax.isoformat() if dmax else None
        cur.execute("SELECT count(*) FROM dou.source_zip")
        out["zip_count"] = cur.fetchone()[0]
        cur.close()
    finally:
        conn.close()
    return out


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


def dou_search(query: str, max_results: int = 10) -> str:
    """Search DOU publications using the configured backend.

    Use Portuguese terms for best results. Depending on configuration this may
    run BM25, Elasticsearch lexical search, or hybrid retrieval.

    Examples:
      - "portaria ministério da saúde"
      - "licitação pregão eletrônico"
      - "decreto presidente república"
      - "concurso público servidor federal"
      - "resolução ANVISA medicamento"

    Args:
        query: Search query in Portuguese
        max_results: Maximum number of results (1-50, default 10)
    """
    try:
        data = search_payload(query=query, max_results=max_results)
        rows = data["results"]
    except Exception as ex:
        return f"Erro no backend de busca ({SEARCH_CFG.backend}): {type(ex).__name__}"

    header = f'**Search[{SEARCH_CFG.backend}]:** "{query}" — {len(rows)} resultado(s)\n\n'
    return header + _format_results(rows)


def dou_search_filtered(
    query: str,
    max_results: int = 10,
    date_from: str | None = None,
    date_to: str | None = None,
    section: str | None = None,
    art_type: str | None = None,
) -> str:
    """Search DOU publications with filters.

    Same as dou_search but with optional filters for date range, section, and
    document type. Use this when the user wants results from a specific period,
    section, or type of legal act.

    Sections: do1 (atos normativos), do2 (atos de pessoal), do3 (licitações/contratos)
    Art types: portaria, decreto, resolução, instrução normativa, aviso, extrato, edital, etc.

    Args:
        query: Search query in Portuguese
        max_results: Maximum number of results (1-50, default 10)
        date_from: Start date filter (YYYY-MM-DD), e.g. "2024-01-01"
        date_to: End date filter (YYYY-MM-DD), e.g. "2024-12-31"
        section: DOU section filter: "do1", "do2", or "do3"
        art_type: Document type filter: "portaria", "decreto", "resolução", etc.
    """
    try:
        data = search_payload(
            query=query,
            max_results=max_results,
            page=1,
            date_from=date_from,
            date_to=date_to,
            section=section,
            art_type=art_type,
        )
        rows = data["results"]
    except Exception as ex:
        return f"Erro no backend de busca ({SEARCH_CFG.backend}): {type(ex).__name__}"

    filters = []
    if date_from:
        filters.append(f"de {date_from}")
    if date_to:
        filters.append(f"até {date_to}")
    if section:
        filters.append(f"seção={section}")
    if art_type:
        filters.append(f"tipo={art_type}")
    filter_str = f" [{', '.join(filters)}]" if filters else ""

    header = f'**Search[{SEARCH_CFG.backend}]:** "{query}"{filter_str} — {len(rows)} resultado(s)\n\n'
    return header + _format_results(rows)


def dou_document(doc_id: str) -> str:
    """Retrieve full content of a specific DOU document by its UUID.

    Use this after getting a doc_id from search results to read the complete
    document text, metadata, and associated references.

    Args:
        doc_id: Document UUID from search results
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()

        # Document + edition metadata
        cur.execute(
            """
            SELECT d.id, d.id_materia, d.art_type, d.art_type_raw,
                   d.art_category, d.identifica, d.ementa, d.titulo,
                   d.sub_titulo, d.body_plain, d.document_number,
                   d.document_year, d.issuing_organ, d.page_number,
                   COALESCE(array_length(regexp_split_to_array(trim(d.body_plain), E'\\s+'), 1), 0) AS body_word_count,
                   d.is_multipart, d.multipart_index,
                   e.publication_date, e.edition_number, e.section, e.is_extra
            FROM dou.document d
            JOIN dou.edition e ON e.id = d.edition_id
            WHERE d.id = %s::uuid
        """,
            (doc_id,),
        )
        row = cur.fetchone()
        if not row:
            return f"Documento não encontrado: {doc_id}"
        cols = [desc[0] for desc in cur.description]
        doc = dict(zip(cols, row))

        # Normative references
        cur.execute(
            """
            SELECT reference_type, reference_number, reference_date, reference_text
            FROM dou.normative_reference
            WHERE document_id = %s::uuid
            ORDER BY reference_type, reference_number
        """,
            (doc_id,),
        )
        norm_refs = _rows_to_dicts(cur) if cur.description else []

        # Procedure references
        cur.execute(
            """
            SELECT procedure_type, procedure_identifier
            FROM dou.procedure_reference
            WHERE document_id = %s::uuid
        """,
            (doc_id,),
        )
        proc_refs = _rows_to_dicts(cur) if cur.description else []

        cur.close()
    finally:
        conn.close()

    # Format output
    lines = [
        f"# {doc.get('identifica') or doc.get('art_type_raw', 'Documento')}",
        "",
        f"**Tipo:** {doc['art_type']} | "
        f"**Seção:** {doc['section']} | "
        f"**Data:** {doc['publication_date']} | "
        f"**Edição:** {doc['edition_number']}",
    ]
    if doc.get("issuing_organ"):
        lines.append(f"**Órgão:** {doc['issuing_organ']}")
    if doc.get("document_number"):
        lines.append(
            f"**Número:** {doc['document_number']}" + (f"/{doc['document_year']}" if doc.get("document_year") else "")
        )
    if doc.get("art_category"):
        lines.append(f"**Categoria:** {doc['art_category']}")
    if doc.get("ementa"):
        lines.append(f"\n**Ementa:** {doc['ementa']}")

    # Body text (truncate at 8000 chars for context window)
    body = doc.get("body_plain", "")
    if len(body) > 8000:
        body = body[:8000] + "\n\n[... texto truncado ...]"
    lines.append(f"\n---\n\n{body}")

    # References
    if norm_refs:
        lines.append("\n## Referências Normativas")
        for r in norm_refs[:20]:
            lines.append(
                f"- {r.get('reference_type', '')} "
                f"{r.get('reference_number', '')} "
                f"({r.get('reference_date', '?')}) — {r.get('reference_text', '')[:100]}"
            )

    if proc_refs:
        lines.append("\n## Referências Processuais")
        for r in proc_refs[:20]:
            lines.append(f"- {r.get('procedure_type', '')} {r.get('procedure_identifier', '')}")

    lines.append(
        f"\n---\n**ID:** `{doc_id}` | "
        f"**id_materia:** {doc.get('id_materia')} | "
        f"**Palavras:** {doc.get('body_word_count', '?')}"
    )

    return "\n".join(lines)


def dou_stats() -> str:
    """Get statistics about the DOU database and BM25 search index.

    Returns document counts, database size, BM25 vocabulary size, and
    top terms. Use this to understand the scope and scale of the data.
    """
    stats = stats_payload()
    search_stats = stats.get("search", {})
    db_size = stats.get("db_size")
    date_range = (stats.get("date_min"), stats.get("date_max"))
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT art_type, count(*) as cnt
            FROM dou.document
            GROUP BY art_type ORDER BY cnt DESC LIMIT 10
        """)
        type_dist = cur.fetchall()
        top_terms = []
        if SEARCH_CFG.backend == "pg":
            cur.execute("""
                SELECT lexeme, doc_freq FROM dou.bm25_term_stats
                ORDER BY doc_freq DESC LIMIT 10
            """)
            top_terms = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    lines = [
        "# GABI DOU — Estatísticas",
        "",
        f"**Banco de dados:** {db_size}",
        f"**Backend de busca:** {SEARCH_CFG.backend}",
        f"**Total de documentos:** {search_stats.get('total_docs', '?'):,}"
        if isinstance(search_stats.get("total_docs"), int)
        else f"**Total de documentos:** {search_stats.get('total_docs', '?')}",
        f"**Período:** {date_range[0]} a {date_range[1]}" if date_range else "",
        f"**Vocabulário BM25:** {search_stats.get('vocabulary_size', '?'):,} lexemas"
        if isinstance(search_stats.get("vocabulary_size"), int)
        else "",
        f"**Comprimento médio doc:** {search_stats.get('avg_doc_length', 0):.0f} palavras" if search_stats else "",
        f"**Última atualização BM25:** {search_stats.get('refreshed_at', '?')}" if search_stats else "",
        "",
        "## Distribuição por tipo",
    ]
    for art_type, cnt in type_dist:
        lines.append(f"- **{art_type}:** {cnt:,}")

    if top_terms:
        lines.append("\n## Top termos BM25")
        for lex, df in top_terms:
            lines.append(f"- **{lex}:** {df:,} documentos")

    return "\n".join(lines)


if mcp is not None:
    mcp.tool()(dou_search)
    mcp.tool()(dou_search_filtered)
    mcp.tool()(dou_document)
    mcp.tool()(dou_stats)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="GABI DOU MCP Server")
    p.add_argument("--transport", choices=["stdio", "sse"], default="stdio", help="MCP transport (default: stdio)")
    p.add_argument("--port", type=int, default=8765, help="Port for SSE transport (default: 8765)")
    args = p.parse_args()

    if mcp is None:
        raise SystemExit("mcp package is not installed. Install dependencies for MCP server runtime.")

    if args.transport == "sse":
        mcp.settings.port = args.port
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
