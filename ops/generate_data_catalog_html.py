from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row


SOURCES = (
    "dou_documents",
    "tcu_acordao_completo",
    "tcu_jurisprudencia_selecionada",
    "tcu_resposta_consulta",
    "tcu_sumula",
    "tcu_boletim_jurisprudencia",
    "tcu_boletim_pessoal",
    "tcu_boletim_informativo_lc",
    "tcu_normas",
    "tcu_btcu",
    "tcu_publicacoes",
)


def _pg_url() -> str:
    return os.getenv("POSTGRES_URL", "postgresql://gabi:gabi@postgres:5432/gabi")


def _table_exists(conn: psycopg.Connection, schema: str, table: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
            LIMIT 1
            """,
            (schema, table),
        )
        return cur.fetchone() is not None


def _table_columns(conn: psycopg.Connection, schema: str, table: str) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT
                ordinal_position,
                column_name,
                data_type,
                udt_name,
                is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            (schema, table),
        )
        return list(cur.fetchall())


def _sample_rows(conn: psycopg.Connection, schema: str, table: str, limit: int) -> list[dict[str, Any]]:
    cols = [c["column_name"] for c in _table_columns(conn, schema, table)]
    order_candidates = ("updated_at", "dumped_at", "parsed_at", "id", "raw_id")
    order_col = next((c for c in order_candidates if c in cols), None)
    order_sql = f" ORDER BY {order_col} DESC" if order_col else ""
    query = f"SELECT * FROM {schema}.{table}{order_sql} LIMIT %s"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, (limit,))
        rows = [dict(r) for r in cur.fetchall()]
    return rows


def _render_columns(columns: list[dict[str, Any]]) -> str:
    lines = ["<table><thead><tr><th>#</th><th>Campo</th><th>Tipo</th><th>Nullable</th></tr></thead><tbody>"]
    for col in columns:
        dtype = col["data_type"]
        if dtype in {"ARRAY", "USER-DEFINED"}:
            dtype = col["udt_name"]
        lines.append(
            "<tr>"
            f"<td>{col['ordinal_position']}</td>"
            f"<td><code>{html.escape(col['column_name'])}</code></td>"
            f"<td>{html.escape(str(dtype))}</td>"
            f"<td>{html.escape(str(col['is_nullable']))}</td>"
            "</tr>"
        )
    lines.append("</tbody></table>")
    return "\n".join(lines)


def _render_samples(rows: list[dict[str, Any]], limit: int) -> str:
    if not rows:
        return "<p class='muted'>Sem dados.</p>"
    parts = [f"<p class='muted'>{len(rows)} de {limit} exemplos:</p>"]
    for idx, row in enumerate(rows, start=1):
        pretty = html.escape(json.dumps(row, ensure_ascii=False, indent=2, default=str))
        parts.append(
            "<details>"
            f"<summary>Exemplo {idx}</summary>"
            f"<pre>{pretty}</pre>"
            "</details>"
        )
    return "\n".join(parts)


def _resolve_raw_table(conn: psycopg.Connection, source: str) -> str | None:
    candidates = (f"{source}_raw", f"{source}_raw_data")
    for table in candidates:
        if _table_exists(conn, "raw", table):
            return table
    return None


def generate_html(limit: int, output: Path) -> None:
    sections: list[str] = []
    with psycopg.connect(_pg_url()) as conn:
        for source in SOURCES:
            raw_table = _resolve_raw_table(conn, source)
            parsed_table = source if _table_exists(conn, "parsed", source) else None

            raw_block = "<p class='muted'>Tabela raw não encontrada.</p>"
            if raw_table:
                raw_cols = _table_columns(conn, "raw", raw_table)
                raw_rows = _sample_rows(conn, "raw", raw_table, limit)
                raw_block = (
                    f"<h4>raw.{html.escape(raw_table)}</h4>"
                    f"{_render_columns(raw_cols)}"
                    f"{_render_samples(raw_rows, limit)}"
                )

            parsed_block = "<p class='muted'>Tabela parsed não encontrada.</p>"
            if parsed_table:
                parsed_cols = _table_columns(conn, "parsed", parsed_table)
                parsed_rows = _sample_rows(conn, "parsed", parsed_table, limit)
                parsed_block = (
                    f"<h4>parsed.{html.escape(parsed_table)}</h4>"
                    f"{_render_columns(parsed_cols)}"
                    f"{_render_samples(parsed_rows, limit)}"
                )

            sections.append(
                "<section class='card'>"
                f"<h3>{html.escape(source)}</h3>"
                "<div class='grid'>"
                f"<div>{raw_block}</div>"
                f"<div>{parsed_block}</div>"
                "</div>"
                "</section>"
            )

    content = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>GABI - Catálogo Raw/Parsed</title>
  <style>
    :root {{
      --bg: #f7f5ef;
      --card: #ffffff;
      --line: #d9d2c3;
      --ink: #1f2937;
      --muted: #6b7280;
      --accent: #14532d;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: "IBM Plex Sans", "Segoe UI", sans-serif; color: var(--ink); background: var(--bg); }}
    header {{ position: sticky; top: 0; background: #fffdf8; border-bottom: 1px solid var(--line); padding: 16px 24px; z-index: 2; }}
    h1 {{ margin: 0; font-size: 22px; }}
    .meta {{ color: var(--muted); font-size: 13px; margin-top: 4px; }}
    main {{ padding: 20px; display: grid; gap: 14px; }}
    .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 14px; }}
    .card h3 {{ margin: 0 0 10px 0; color: var(--accent); }}
    .grid {{ display: grid; gap: 14px; grid-template-columns: 1fr 1fr; }}
    h4 {{ margin: 0 0 8px 0; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 10px; }}
    th, td {{ border: 1px solid var(--line); padding: 6px; text-align: left; vertical-align: top; }}
    th {{ background: #f2eee2; }}
    pre {{ margin: 8px 0 0 0; padding: 10px; border: 1px solid var(--line); background: #fbfaf6; border-radius: 8px; max-height: 280px; overflow: auto; font-size: 11px; }}
    details {{ margin-bottom: 8px; }}
    summary {{ cursor: pointer; color: #0f172a; font-weight: 600; }}
    .muted {{ color: var(--muted); font-size: 13px; }}
    @media (max-width: 1100px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header>
    <h1>GABI - Visão Raw x Parsed (H1/H2)</h1>
    <div class="meta">Fontes: 11 | Exemplos por tabela: {limit}</div>
  </header>
  <main>
    {''.join(sections)}
  </main>
</body>
</html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera HTML com tabelas, campos e amostras raw/parsed")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", default="ops/data/raw_parsed_catalog.html")
    args = parser.parse_args()
    out = Path(args.output)
    generate_html(limit=args.limit, output=out)
    print(json.dumps({"output": str(out), "limit": args.limit}, ensure_ascii=False))


if __name__ == "__main__":
    main()
