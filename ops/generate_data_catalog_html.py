from __future__ import annotations

import argparse
import html
import json
import os
import re
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


def _sample_rows(
    conn: psycopg.Connection,
    schema: str,
    table: str,
    limit: int,
    *,
    raw_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    cols = [c["column_name"] for c in _table_columns(conn, schema, table)]
    order_candidates = ("updated_at", "dumped_at", "parsed_at", "id", "raw_id")
    order_col = next((c for c in order_candidates if c in cols), None)
    if raw_ids:
        id_col = "raw_id" if "raw_id" in cols else "id"
        limit_sql = " LIMIT %s" if limit > 0 else ""
        query = (
            f"SELECT * FROM {schema}.{table} "
            f"WHERE {id_col} = ANY(%s) "
            f"ORDER BY array_position(%s::text[], {id_col})"
            f"{limit_sql}"
        )
        params: list[Any] = [raw_ids, raw_ids]
        if limit > 0:
            params.append(limit)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            return [dict(r) for r in cur.fetchall()]
    order_sql = f" ORDER BY {order_col} DESC" if order_col else ""
    limit_sql = " LIMIT %s" if limit > 0 else ""
    query = f"SELECT * FROM {schema}.{table}{order_sql}{limit_sql}"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, (limit,)) if limit > 0 else cur.execute(query)
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


def _clean_preview_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _snippet(value: Any, *, limit: int = 220) -> str:
    cleaned = _clean_preview_text(value)
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit].rstrip()}..."


def _render_preview_line(label: str, value: Any) -> str:
    snippet = _snippet(value)
    if not snippet:
        return ""
    return (
        "<div class='preview-line'>"
        f"<strong>{html.escape(label)}:</strong> {html.escape(snippet)}"
        "</div>"
    )


def _semantic_delta_labels(parsed_row: dict[str, Any] | None, semantic_row: dict[str, Any]) -> list[str]:
    if not parsed_row:
        return []
    deltas: list[str] = []
    if _clean_preview_text(parsed_row.get("summary_short")) != _clean_preview_text(semantic_row.get("semantic_summary_short")):
        deltas.append("summary")
    parsed_topics = ",".join(parsed_row.get("topics") or [])
    semantic_topics = ",".join(semantic_row.get("semantic_topics") or [])
    if _clean_preview_text(parsed_topics) != _clean_preview_text(semantic_topics):
        deltas.append("topics")
    parsed_structured = json.dumps(parsed_row.get("summary_structured") or {}, ensure_ascii=False, sort_keys=True)
    semantic_structured = json.dumps(semantic_row.get("semantic_summary_structured") or {}, ensure_ascii=False, sort_keys=True)
    if _clean_preview_text(parsed_structured) != _clean_preview_text(semantic_structured):
        deltas.append("structured")
    return deltas


def _render_sample_preview(
    row: dict[str, Any],
    *,
    kind: str,
    related_row: dict[str, Any] | None = None,
) -> str:
    lines: list[str] = []
    if kind == "raw":
        title = next(
            (
                row.get(field)
                for field in ("titulo", "title", "identifica", "ementa", "subject")
                if row.get(field)
            ),
            None,
        )
        preview = next(
            (
                row.get(field)
                for field in ("raw_text", "texto", "content", "body", "html", "body_plain", "text")
                if row.get(field)
            ),
            None,
        )
        if title:
            lines.append(_render_preview_line("título", title))
        lines.append(_render_preview_line("bruto", preview or "campo de bruto não exposto nesta row"))
    elif kind == "parsed":
        lines.append(_render_preview_line("summary_short", row.get("summary_short")))
        lines.append(_render_preview_line("topics", ", ".join(row.get("topics") or [])))
        lines.append(_render_preview_line("summary_structured", row.get("summary_structured")))
    elif kind == "semantic":
        lines.append(_render_preview_line("semantic_summary_short", row.get("semantic_summary_short")))
        lines.append(_render_preview_line("semantic_topics", ", ".join(row.get("semantic_topics") or [])))
        lines.append(_render_preview_line("quality_flags", ", ".join(row.get("quality_flags") or [])))
        if related_row:
            lines.append(_render_preview_line("H2 summary_short", related_row.get("summary_short")))
            lines.append(_render_preview_line("H2 topics", ", ".join(related_row.get("topics") or [])))
    lines = [line for line in lines if line]
    if not lines:
        return ""
    return "<div class='preview-box'>" + "".join(lines) + "</div>"


def _sample_meta_bits(row: dict[str, Any]) -> list[str]:
    bits: list[str] = []
    cohort_type = str(row.get("audit_cohort_type") or "")
    if cohort_type:
        bits.append(f"cohort={cohort_type}")
    verdict = str(row.get("audit_final_verdict") or "")
    if verdict:
        bits.append(f"verdict={verdict}")
    judge_status = str(row.get("audit_judge_status") or "")
    if judge_status:
        bits.append(f"judge_status={judge_status}")
    judge_mode = str(row.get("audit_judge_mode") or "")
    if judge_mode:
        bits.append(f"judge_mode={judge_mode}")
    if row.get("audit_process_cached") is not None:
        bits.append(f"process_cache={'yes' if row['audit_process_cached'] else 'no'}")
    return bits


def _render_samples(
    rows: list[dict[str, Any]],
    limit: int,
    *,
    parsed: bool,
    kind: str,
    related_rows: dict[str, dict[str, Any]] | None = None,
) -> str:
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
        summary_bits.extend(_sample_meta_bits(row))
        if kind == "semantic":
            semantic_mode = str(row.get("semantic_mode") or "")
            if semantic_mode:
                summary_bits.append(f"semantic_mode={semantic_mode}")
            if row.get("prompt_version"):
                summary_bits.append(f"prompt={row['prompt_version']}")
            delta_bits = _semantic_delta_labels((related_rows or {}).get(str(row.get("raw_id") or "")), row)
            if delta_bits:
                summary_bits.append(f"delta={'+'.join(delta_bits)}")
        attrs = f" data-status='{html.escape(status)}'" if parsed and status else ""
        preview = _render_sample_preview(
            row,
            kind=kind,
            related_row=(related_rows or {}).get(str(row.get("raw_id") or "")),
        )
        parts.append(
            f"<details class='sample' {attrs}>"
            f"<summary>{' | '.join(summary_bits)} {badge}</summary>"
            f"{preview}"
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
    useful_spans = sum(
        1
        for r in rows
        if any(str(span.get("tag") or "") != "assinatura" for span in (r.get("tag_spans") or []))
    )
    signature_spans = sum(
        sum(1 for span in (r.get("tag_spans") or []) if str(span.get("tag") or "") == "assinatura")
        for r in rows
    )
    structured = sum(1 for r in rows if isinstance(r.get("summary_structured"), dict) and r.get("summary_structured"))
    topics = sum(1 for r in rows if r.get("topics"))
    entities = sum(1 for r in rows if r.get("legal_entities"))
    confidence_values = [
        float((r.get("confidence_fields") or {}).get("overall"))
        for r in rows
        if isinstance(r.get("confidence_fields"), dict) and (r.get("confidence_fields") or {}).get("overall") is not None
    ]
    return {
        "statuses": dict(statuses),
        "modes": dict(modes),
        "tag_spans": tag_spans,
        "useful_spans": useful_spans,
        "signature_spans": signature_spans,
        "summary_structured": structured,
        "topics": topics,
        "legal_entities": entities,
        "avg_confidence": round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else None,
    }


def _semantic_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(str(r.get("semantic_status") or "null") for r in rows)
    modes = Counter(str(r.get("semantic_mode") or "null") for r in rows)
    prompt_versions = Counter(str(r.get("prompt_version")) for r in rows if r.get("prompt_version"))
    structured = sum(1 for r in rows if isinstance(r.get("semantic_summary_structured"), dict) and r.get("semantic_summary_structured"))
    topics = sum(1 for r in rows if r.get("semantic_topics"))
    fallback_rows = sum(1 for r in rows if "fallback" in str(r.get("semantic_mode") or ""))
    extraction = [
        float(r.get("extraction_confidence_overall"))
        for r in rows
        if r.get("extraction_confidence_overall") is not None
    ]
    interpretation = [
        float(r.get("interpretation_confidence_overall"))
        for r in rows
        if r.get("interpretation_confidence_overall") is not None
    ]
    return {
        "statuses": dict(statuses),
        "modes": dict(modes),
        "summary_structured": structured,
        "topics": topics,
        "fallback_rows": fallback_rows,
        "avg_extraction": round(sum(extraction) / len(extraction), 3) if extraction else None,
        "avg_interpretation": round(sum(interpretation) / len(interpretation), 3) if interpretation else None,
        "prompt_versions": dict(prompt_versions),
    }


def _render_metrics(metrics: dict[str, Any], sample_size: int) -> str:
    badges = " ".join(_status_badge(k) + f" <span class='metric-num'>{v}</span>" for k, v in metrics["statuses"].items())
    mode_bits = " | ".join(f"{html.escape(k)}={v}" for k, v in metrics["modes"].items())
    return (
        "<div class='metrics'>"
        f"<div>{badges}</div>"
        f"<div class='metric-line'>modes: {mode_bits}</div>"
        f"<div class='metric-line'>sample={sample_size} | summary_structured={metrics['summary_structured']} | "
        f"topics={metrics['topics']} | legal_entities={metrics['legal_entities']} | tag_spans={metrics['tag_spans']} | "
        f"useful_span_docs={metrics['useful_spans']} | assinatura_spans={metrics['signature_spans']} | "
        f"avg_confidence={metrics['avg_confidence']}</div>"
        "</div>"
    )


def _render_semantic_metrics(metrics: dict[str, Any], sample_size: int, routing_status: str | None) -> str:
    badges = " ".join(_status_badge(k) + f" <span class='metric-num'>{v}</span>" for k, v in metrics["statuses"].items())
    mode_bits = " | ".join(f"{html.escape(k)}={v}" for k, v in metrics["modes"].items())
    prompt_bits = " | ".join(f"{html.escape(k)}={v}" for k, v in metrics["prompt_versions"].items()) or "none"
    routing = routing_status or "unknown"
    return (
        "<div class='metrics'>"
        f"<div>{badges}</div>"
        f"<div class='metric-line'>routing={html.escape(routing)} | modes: {mode_bits}</div>"
        f"<div class='metric-line'>sample={sample_size} | summary_structured={metrics['summary_structured']} | "
        f"topics={metrics['topics']} | fallback_rows={metrics['fallback_rows']} | "
        f"avg_extraction={metrics['avg_extraction']} | avg_interpretation={metrics['avg_interpretation']}</div>"
        f"<div class='metric-line'>prompt_versions: {prompt_bits}</div>"
        "</div>"
    )


def _load_routing_status(conn: psycopg.Connection, source: str) -> str | None:
    if not _table_exists(conn, "h3_governance", "h3_routing"):
        return None
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM h3_governance.h3_routing WHERE source_type = %s", (source,))
        row = cur.fetchone()
    return str(row[0]) if row else None


def _source_nav() -> str:
    return "".join(f"<a href='#{source}'>{html.escape(source)}</a>" for source in SOURCES)


def _round_raw_ids(conn: psycopg.Connection, round_id: str, source: str) -> list[str]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT raw_id
            FROM audit.cohort
            WHERE round_id = %s AND source_type = %s
            ORDER BY cohort_type ASC, raw_id ASC
            """,
            (round_id, source),
        )
        return [str(row["raw_id"]) for row in cur.fetchall()]


def _round_meta(conn: psycopg.Connection, round_id: str, source: str) -> dict[str, dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT
                c.raw_id,
                c.cohort_type,
                ac.final_verdict,
                js.status AS judge_status,
                js.judge_mode,
                EXISTS (
                    SELECT 1
                    FROM audit.process_cache pc
                    WHERE pc.source_type = c.source_type AND pc.raw_id = c.raw_id
                ) AS process_cached
            FROM audit.cohort c
            LEFT JOIN LATERAL (
                SELECT final_verdict
                FROM audit.approval_cache ac
                WHERE ac.source_type = c.source_type AND ac.raw_id = c.raw_id
                ORDER BY approved_at DESC
                LIMIT 1
            ) ac ON TRUE
            LEFT JOIN audit.judge_status js
              ON js.round_id = c.round_id
             AND js.source_type = c.source_type
             AND js.raw_id = c.raw_id
            WHERE c.round_id = %s AND c.source_type = %s
            ORDER BY c.raw_id ASC
            """,
            (round_id, source),
        )
        rows = cur.fetchall()
    return {
        str(row["raw_id"]): {
            "audit_cohort_type": row["cohort_type"],
            "audit_final_verdict": row["final_verdict"],
            "audit_judge_status": row["judge_status"],
            "audit_judge_mode": row["judge_mode"],
            "audit_process_cached": bool(row["process_cached"]),
        }
        for row in rows
    }


def generate_html(limit: int, output: Path, *, mode: str, round_id: str | None = None) -> None:
    sections: list[str] = []
    with psycopg.connect(_pg_url()) as conn:
        for source in SOURCES:
            scoped_raw_ids = _round_raw_ids(conn, round_id, source) if round_id else []
            if round_id and not scoped_raw_ids:
                continue
            meta_by_raw_id = _round_meta(conn, round_id, source) if round_id else {}
            raw_table = _resolve_raw_table(conn, source)
            parsed_table = source if _table_exists(conn, "parsed", source) else None

            raw_block = "<p class='muted'>Tabela raw não encontrada.</p>"
            if raw_table:
                raw_cols = _table_columns(conn, "raw", raw_table)
                raw_rows = _sample_rows(conn, "raw", raw_table, limit, raw_ids=scoped_raw_ids or None)
                for row in raw_rows:
                    row.update(meta_by_raw_id.get(str(row.get("id")), {}))
                raw_block = (
                    f"<h4>raw.{html.escape(raw_table)}</h4>"
                    f"{_render_columns(raw_cols)}"
                    f"{_render_samples(raw_rows, limit, parsed=False, kind='raw')}"
                )

            parsed_block = "<p class='muted'>Tabela parsed não encontrada.</p>"
            parsed_rows: list[dict[str, Any]] = []
            if parsed_table:
                parsed_cols = _table_columns(conn, "parsed", parsed_table)
                parsed_rows = _sample_rows(conn, "parsed", parsed_table, limit, raw_ids=scoped_raw_ids or None)
                for row in parsed_rows:
                    row.update(meta_by_raw_id.get(str(row.get("raw_id")), {}))
                parsed_block = (
                    f"<h4>parsed.{html.escape(parsed_table)}</h4>"
                    f"{_render_metrics(_parsed_metrics(parsed_rows), len(parsed_rows))}"
                    f"{_render_columns(parsed_cols)}"
                    f"{_render_samples(parsed_rows, limit, parsed=True, kind='parsed')}"
                )

            semantic_table = source if _table_exists(conn, "parsed_semantic", source) else None
            semantic_block = "<p class='muted'>Tabela parsed_semantic não encontrada.</p>"
            if semantic_table:
                semantic_cols = _table_columns(conn, "parsed_semantic", semantic_table)
                semantic_rows = _sample_rows(conn, "parsed_semantic", semantic_table, limit, raw_ids=scoped_raw_ids or None)
                for row in semantic_rows:
                    row.update(meta_by_raw_id.get(str(row.get("raw_id")), {}))
                parsed_index = {
                    str(row.get("raw_id")): row
                    for row in parsed_rows
                    if row.get("raw_id") is not None
                }
                semantic_block = (
                    f"<h4>parsed_semantic.{html.escape(semantic_table)}</h4>"
                    f"{_render_semantic_metrics(_semantic_metrics(semantic_rows), len(semantic_rows), _load_routing_status(conn, source))}"
                    f"{_render_columns(semantic_cols)}"
                    f"{_render_samples(semantic_rows, limit, parsed=False, kind='semantic', related_rows=parsed_index)}"
                )

            if mode == "parsed-only":
                sections.append(
                    "<section class='card source-card'>"
                    f"<h3 id='{html.escape(source)}'>{html.escape(source)}</h3>"
                    f"{parsed_block}"
                    f"{semantic_block}"
                    "</section>"
                )
                continue

            sections.append(
                "<section class='card source-card'>"
                f"<h3 id='{html.escape(source)}'>{html.escape(source)}</h3>"
                "<div class='tab-row'>"
                f"<button class='tab-btn active' data-target='{html.escape(source)}-parsed'>Parsed</button>"
                f"<button class='tab-btn' data-target='{html.escape(source)}-semantic'>H3</button>"
                f"<button class='tab-btn' data-target='{html.escape(source)}-raw'>Raw</button>"
                "</div>"
                f"<div class='tab-panel active' id='{html.escape(source)}-parsed'>{parsed_block}</div>"
                f"<div class='tab-panel' id='{html.escape(source)}-semantic'>{semantic_block}</div>"
                f"<div class='tab-panel' id='{html.escape(source)}-raw'>{raw_block}</div>"
                "</section>"
            )

    title = "GABI - Parsed Only" if mode == "parsed-only" else "GABI - Raw + Parsed Tabs"
    if round_id:
        title = f"{title} - {round_id}"
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
    .preview-box {{ padding: 10px 12px; border-top: 1px solid var(--line); background: #fffaf0; display: grid; gap: 6px; }}
    .preview-line {{ font-size: 12px; color: var(--ink); }}
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
    <div class="meta">Fontes: {len(sections)} | Exemplos por tabela: {'all round ids' if limit <= 0 else limit}</div>
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
    parser.add_argument("--round-id", default="")
    args = parser.parse_args()
    default_output = "ops/data/raw_parsed_catalog_tabs.html" if args.mode == "tabs" else "ops/data/parsed_only_catalog.html"
    out = Path(args.output or default_output)
    generate_html(limit=args.limit, output=out, mode=args.mode, round_id=args.round_id or None)
    print(
        json.dumps(
            {"output": str(out), "limit": args.limit, "mode": args.mode, "round_id": args.round_id or None},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
