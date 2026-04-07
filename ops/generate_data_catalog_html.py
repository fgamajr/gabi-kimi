from __future__ import annotations

import argparse
import html
import json
import os
from collections import Counter
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
            SELECT ordinal_position, column_name, data_type, udt_name, is_nullable
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
        return [dict(r) for r in cur.fetchall()]


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


def _status_badge(status: str) -> str:
    css = {
        "done_full": "ok",
        "done_partial": "warn",
        "done_fallback": "bad",
        "failed": "bad",
        "pending": "pending",
        "running": "pending",
    }.get(status, "plain")
    return f"<span class='badge {css}'>{html.escape(status)}</span>"


def _render_samples(rows: list[dict[str, Any]], limit: int, *, parsed: bool) -> str:
    if not rows:
        return "<p class='muted'>Sem dados.</p>"
    parts = [f"<p class='muted'>{len(rows)} de {limit} exemplos.</p>"]
    for idx, row in enumerate(rows, start=1):
        pretty = html.escape(json.dumps(row, ensure_ascii=False, indent=2, default=str))
        status = str(row.get("enrichment_status") or "")
        mode = str(row.get("enrichment_mode") or "")
        summary_bits = [f"Exemplo {idx}"]
        if row.get("raw_id"):
            summary_bits.append(f"raw_id={row['raw_id']}")
        badge = _status_badge(status) if parsed and status else ""
        if parsed and mode:
            summary_bits.append(f"mode={mode}")
        attrs = f" data-status='{html.escape(status)}'" if parsed and status else ""
        parts.append(
            f"<details class='sample' {attrs}>"
            f"<summary>{' | '.join(summary_bits)} {badge}</summary>"
            f"<pre>{pretty}</pre>"
            "</details>"
        )
    return "\n".join(parts)


def _resolve_raw_table(conn: psycopg.Connection, source: str) -> str | None:
    for table in (f"{source}_raw", f"{source}_raw_data"):
        if _table_exists(conn, "raw", table):
            return table
    return None


def _parsed_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(str(r.get("enrichment_status") or "null") for r in rows)
    modes = Counter(str(r.get("enrichment_mode") or "null") for r in rows)
    tag_spans = sum(1 for r in rows if r.get("tag_spans"))
    structured = sum(1 for r in rows if isinstance(r.get("summary_structured"), dict) and r.get("summary_structured"))
    topics = sum(1 for r in rows if r.get("topics"))
    entities = sum(1 for r in rows if r.get("legal_entities"))
    return {
        "statuses": dict(statuses),
        "modes": dict(modes),
        "tag_spans": tag_spans,
        "summary_structured": structured,
        "topics": topics,
        "legal_entities": entities,
    }


def _render_metrics(metrics: dict[str, Any], sample_size: int) -> str:
    badges = " ".join(_status_badge(k) + f" <span class='metric-num'>{v}</span>" for k, v in metrics["statuses"].items())
    mode_bits = " | ".join(f"{html.escape(k)}={v}" for k, v in metrics["modes"].items())
    return (
        "<div class='metrics'>"
        f"<div>{badges}</div>"
        f"<div class='metric-line'>modes: {mode_bits}</div>"
        f"<div class='metric-line'>sample={sample_size} | summary_structured={metrics['summary_structured']} | "
        f"topics={metrics['topics']} | legal_entities={metrics['legal_entities']} | tag_spans={metrics['tag_spans']}</div>"
        "</div>"
    )


def _source_nav() -> str:
    return "".join(f"<a href='#{source}'>{html.escape(source)}</a>" for source in SOURCES)


def generate_html(limit: int, output: Path, *, mode: str) -> None:
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
                    f"{_render_samples(raw_rows, limit, parsed=False)}"
                )

            parsed_block = "<p class='muted'>Tabela parsed não encontrada.</p>"
            if parsed_table:
                parsed_cols = _table_columns(conn, "parsed", parsed_table)
                parsed_rows = _sample_rows(conn, "parsed", parsed_table, limit)
                parsed_block = (
                    f"<h4>parsed.{html.escape(parsed_table)}</h4>"
                    f"{_render_metrics(_parsed_metrics(parsed_rows), len(parsed_rows))}"
                    f"{_render_columns(parsed_cols)}"
                    f"{_render_samples(parsed_rows, limit, parsed=True)}"
                )

            if mode == "parsed-only":
                sections.append(
                    "<section class='card source-card'>"
                    f"<h3 id='{html.escape(source)}'>{html.escape(source)}</h3>"
                    f"{parsed_block}"
                    "</section>"
                )
                continue

            sections.append(
                "<section class='card source-card'>"
                f"<h3 id='{html.escape(source)}'>{html.escape(source)}</h3>"
                "<div class='tab-row'>"
                f"<button class='tab-btn active' data-target='{html.escape(source)}-parsed'>Parsed</button>"
                f"<button class='tab-btn' data-target='{html.escape(source)}-raw'>Raw</button>"
                "</div>"
                f"<div class='tab-panel active' id='{html.escape(source)}-parsed'>{parsed_block}</div>"
                f"<div class='tab-panel' id='{html.escape(source)}-raw'>{raw_block}</div>"
                "</section>"
            )

    title = "GABI - Parsed Only" if mode == "parsed-only" else "GABI - Raw + Parsed Tabs"
    filter_bar = (
        "<div class='toolbar'>"
        "<button class='filter-btn active' data-filter='all'>Todos</button>"
        "<button class='filter-btn' data-filter='done_full'>done_full</button>"
        "<button class='filter-btn' data-filter='done_partial'>done_partial</button>"
        "<button class='filter-btn' data-filter='done_fallback'>done_fallback</button>"
        "<button class='filter-btn' data-filter='failed'>failed</button>"
        "</div>"
    )
    content = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    :root {{
      --bg: #f6f1e8;
      --card: #fffdf8;
      --line: #ddd2bf;
      --ink: #1f2937;
      --muted: #6b7280;
      --accent: #0f5132;
      --accent-2: #7c2d12;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: "IBM Plex Sans", "Segoe UI", sans-serif; color: var(--ink); background: radial-gradient(circle at top left, #faf7ef, var(--bg)); }}
    header {{ position: sticky; top: 0; z-index: 5; background: rgba(255,253,248,0.96); backdrop-filter: blur(8px); border-bottom: 1px solid var(--line); padding: 16px 24px; }}
    h1 {{ margin: 0; font-size: 24px; }}
    .meta {{ color: var(--muted); font-size: 13px; margin-top: 4px; }}
    .nav {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }}
    .nav a {{ color: var(--accent); text-decoration: none; font-size: 13px; border: 1px solid var(--line); padding: 6px 10px; border-radius: 999px; background: #fff; }}
    .toolbar {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }}
    .filter-btn, .tab-btn {{ border: 1px solid var(--line); background: #fff; color: var(--ink); border-radius: 999px; padding: 7px 12px; cursor: pointer; }}
    .filter-btn.active, .tab-btn.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
    main {{ padding: 20px; display: grid; gap: 16px; }}
    .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 16px; box-shadow: 0 12px 30px rgba(15, 23, 42, 0.04); }}
    .source-card h3 {{ margin: 0 0 12px 0; color: var(--accent); }}
    .tab-row {{ display: flex; gap: 8px; margin-bottom: 12px; }}
    .tab-panel {{ display: none; }}
    .tab-panel.active {{ display: block; }}
    .metrics {{ display: grid; gap: 6px; margin-bottom: 10px; padding: 10px; border: 1px solid var(--line); border-radius: 10px; background: #fbf8f2; }}
    .metric-line {{ color: var(--muted); font-size: 12px; }}
    .metric-num {{ margin-right: 10px; font-size: 12px; color: var(--muted); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 10px; }}
    th, td {{ border: 1px solid var(--line); padding: 6px; text-align: left; vertical-align: top; }}
    th {{ background: #f2eadc; }}
    details {{ margin-bottom: 8px; border: 1px solid var(--line); border-radius: 10px; background: #fff; }}
    summary {{ cursor: pointer; padding: 10px 12px; font-weight: 600; }}
    pre {{ margin: 0; padding: 12px; border-top: 1px solid var(--line); background: #fcfbf7; max-height: 320px; overflow: auto; font-size: 11px; }}
    .badge {{ display: inline-block; margin-left: 8px; padding: 2px 8px; border-radius: 999px; font-size: 11px; border: 1px solid transparent; }}
    .badge.ok {{ background: #dcfce7; color: #166534; border-color: #86efac; }}
    .badge.warn {{ background: #fef3c7; color: #92400e; border-color: #fcd34d; }}
    .badge.bad {{ background: #fee2e2; color: #991b1b; border-color: #fca5a5; }}
    .badge.pending {{ background: #dbeafe; color: #1d4ed8; border-color: #93c5fd; }}
    .badge.plain {{ background: #f3f4f6; color: #374151; border-color: #d1d5db; }}
    .muted {{ color: var(--muted); font-size: 13px; }}
    .sample.hidden {{ display: none; }}
  </style>
</head>
<body>
  <header>
    <h1>{title}</h1>
    <div class="meta">Fontes: {len(SOURCES)} | Exemplos por tabela: {limit}</div>
    <nav class="nav">{_source_nav()}</nav>
    {filter_bar}
  </header>
  <main>
    {''.join(sections)}
  </main>
  <script>
    document.querySelectorAll('.tab-btn').forEach((btn) => {{
      btn.addEventListener('click', () => {{
        const card = btn.closest('.source-card');
        card.querySelectorAll('.tab-btn').forEach((item) => item.classList.remove('active'));
        card.querySelectorAll('.tab-panel').forEach((item) => item.classList.remove('active'));
        btn.classList.add('active');
        const target = card.querySelector('#' + btn.dataset.target);
        if (target) target.classList.add('active');
      }});
    }});
    document.querySelectorAll('.filter-btn').forEach((btn) => {{
      btn.addEventListener('click', () => {{
        document.querySelectorAll('.filter-btn').forEach((item) => item.classList.remove('active'));
        btn.classList.add('active');
        const wanted = btn.dataset.filter;
        document.querySelectorAll('.sample[data-status]').forEach((sample) => {{
          const visible = wanted === 'all' || sample.dataset.status === wanted;
          sample.classList.toggle('hidden', !visible);
        }});
      }});
    }});
  </script>
</body>
</html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera HTML de auditoria raw/parsed")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--mode", choices=("tabs", "parsed-only"), default="tabs")
    parser.add_argument("--output")
    args = parser.parse_args()
    default_output = "ops/data/raw_parsed_catalog_tabs.html" if args.mode == "tabs" else "ops/data/parsed_only_catalog.html"
    out = Path(args.output or default_output)
    generate_html(limit=args.limit, output=out, mode=args.mode)
    print(json.dumps({"output": str(out), "limit": args.limit, "mode": args.mode}, ensure_ascii=False))


if __name__ == "__main__":
    main()
