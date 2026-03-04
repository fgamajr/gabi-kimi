"""MCP Server for GABI DOU BM25 Search.

Exposes PostgreSQL Okapi BM25 search over DOU publications (Diário Oficial da
União) as MCP tools, enabling AI agents to query 1M+ Brazilian legal documents.

Usage:
  # stdio transport (for local MCP clients like Claude Desktop, VS Code)
  python3 mcp_server.py

  # SSE transport (for remote/web clients)
  python3 mcp_server.py --transport sse --port 8765

MCP Tools:
  - dou_search:          BM25 full-text search across all DOU documents
  - dou_search_filtered: BM25 search with date/section/type filters
  - dou_stats:           Database and BM25 index statistics
  - dou_document:        Retrieve a specific document by ID
"""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

import psycopg2
import psycopg2.extras
from mcp.server.fastmcp import FastMCP

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

mcp = FastMCP(
    "GABI DOU Search",
    instructions=(
        "Search engine for Brazilian Federal Official Gazette (DOU) publications. "
        "Contains 1M+ legal documents (portarias, decretos, licitações, extratos, etc.) "
        "from 2002-2026 with Okapi BM25 ranking. "
        "Queries should be in Portuguese."
    ),
)

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
        lines.append(f"**Tipo:** {r.get('art_type', '?')} | "
                      f"**Seção:** {r.get('edition_section', '?')} | "
                      f"**Data:** {r.get('pub_date', '?')}")
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
# MCP Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def dou_search(query: str, max_results: int = 10) -> str:
    """Search DOU publications using Okapi BM25 ranking.

    Use Portuguese terms for best results. Searches across document title
    (identifica), summary (ementa), and full body text.

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
    max_results = min(max(1, max_results), 50)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT doc_id, score, identifica, ementa, art_type, "
            "pub_date, edition_section, snippet "
            "FROM dou.bm25_search(%s, %s)",
            (query, max_results),
        )
        rows = _rows_to_dicts(cur)
        cur.close()
    finally:
        conn.close()

    header = f"**BM25 Search:** \"{query}\" — {len(rows)} resultado(s)\n\n"
    return header + _format_results(rows)


@mcp.tool()
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
    max_results = min(max(1, max_results), 50)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT doc_id, score, identifica, ementa, art_type, "
            "pub_date, edition_section, snippet "
            "FROM dou.bm25_search_filtered(%s, %s, %s, %s, %s, %s)",
            (query, max_results, date_from, date_to, section, art_type),
        )
        rows = _rows_to_dicts(cur)
        cur.close()
    finally:
        conn.close()

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

    header = f"**BM25 Search:** \"{query}\"{filter_str} — {len(rows)} resultado(s)\n\n"
    return header + _format_results(rows)


@mcp.tool()
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
        cur.execute("""
            SELECT d.id, d.id_materia, d.art_type, d.art_type_raw,
                   d.art_category, d.identifica, d.ementa, d.titulo,
                   d.sub_titulo, d.body_plain, d.document_number,
                   d.document_year, d.issuing_organ, d.page_number,
                   d.body_word_count, d.is_multipart, d.multipart_index,
                   e.publication_date, e.edition_number, e.section, e.is_extra
            FROM dou.document d
            JOIN dou.edition e ON e.id = d.edition_id
            WHERE d.id = %s::uuid
        """, (doc_id,))
        row = cur.fetchone()
        if not row:
            return f"Documento não encontrado: {doc_id}"
        cols = [desc[0] for desc in cur.description]
        doc = dict(zip(cols, row))

        # Normative references
        cur.execute("""
            SELECT reference_type, reference_number, reference_date, reference_text
            FROM dou.normative_reference
            WHERE document_id = %s::uuid
            ORDER BY reference_type, reference_number
        """, (doc_id,))
        norm_refs = _rows_to_dicts(cur) if cur.description else []

        # Procedure references
        cur.execute("""
            SELECT procedure_type, procedure_identifier
            FROM dou.procedure_reference
            WHERE document_id = %s::uuid
        """, (doc_id,))
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
        lines.append(f"**Número:** {doc['document_number']}"
                      + (f"/{doc['document_year']}" if doc.get("document_year") else ""))
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
            lines.append(f"- {r.get('reference_type', '')} "
                          f"{r.get('reference_number', '')} "
                          f"({r.get('reference_date', '?')}) — {r.get('reference_text', '')[:100]}")

    if proc_refs:
        lines.append("\n## Referências Processuais")
        for r in proc_refs[:20]:
            lines.append(f"- {r.get('procedure_type', '')} {r.get('procedure_identifier', '')}")

    lines.append(f"\n---\n**ID:** `{doc_id}` | "
                  f"**id_materia:** {doc.get('id_materia')} | "
                  f"**Palavras:** {doc.get('body_word_count', '?')}")

    return "\n".join(lines)


@mcp.tool()
def dou_stats() -> str:
    """Get statistics about the DOU database and BM25 search index.

    Returns document counts, database size, BM25 vocabulary size, and
    top terms. Use this to understand the scope and scale of the data.
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()

        # BM25 stats
        cur.execute("SELECT * FROM dou.v_bm25_stats")
        cols = [d[0] for d in cur.description]
        bm25 = dict(zip(cols, cur.fetchone())) if cur.description else {}

        # DB size
        cur.execute("SELECT pg_size_pretty(pg_database_size('gabi'))")
        db_size = cur.fetchone()[0]

        # Doc count by type (top 10)
        cur.execute("""
            SELECT art_type, count(*) as cnt
            FROM dou.document
            GROUP BY art_type ORDER BY cnt DESC LIMIT 10
        """)
        type_dist = cur.fetchall()

        # Date range
        cur.execute("""
            SELECT min(publication_date), max(publication_date)
            FROM dou.edition
        """)
        date_range = cur.fetchone()

        # Top BM25 terms
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
        f"**Total de documentos:** {bm25.get('total_docs', '?'):,}" if isinstance(bm25.get('total_docs'), int) else f"**Total de documentos:** {bm25.get('total_docs', '?')}",
        f"**Período:** {date_range[0]} a {date_range[1]}" if date_range else "",
        f"**Vocabulário BM25:** {bm25.get('vocabulary_size', '?'):,} lexemas" if isinstance(bm25.get('vocabulary_size'), int) else "",
        f"**Comprimento médio doc:** {bm25.get('avg_doc_length', 0):.0f} palavras",
        f"**Última atualização BM25:** {bm25.get('refreshed_at', '?')}",
        "",
        "## Distribuição por tipo",
    ]
    for art_type, cnt in type_dist:
        lines.append(f"- **{art_type}:** {cnt:,}")

    lines.append("\n## Top termos BM25")
    for lex, df in top_terms:
        lines.append(f"- **{lex}:** {df:,} documentos")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="GABI DOU MCP Server")
    p.add_argument("--transport", choices=["stdio", "sse"], default="stdio",
                    help="MCP transport (default: stdio)")
    p.add_argument("--port", type=int, default=8765,
                    help="Port for SSE transport (default: 8765)")
    args = p.parse_args()

    if args.transport == "sse":
        mcp.run(transport="sse", sse_params={"port": args.port})
    else:
        mcp.run(transport="stdio")
