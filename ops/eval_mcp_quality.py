"""Curated MCP quality evaluation for GABI.

Runs a benchmark pack against the live MCP tool functions, scores each case
with lightweight heuristics, and writes both JSON and Markdown reports.

Usage:
  python ops/eval_mcp_quality.py
  python ops/eval_mcp_quality.py --limit 5
  python ops/eval_mcp_quality.py --case lgpd
  python ops/eval_mcp_quality.py --strict-optional
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
import time
import traceback
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - docker image includes python-dotenv
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:
        return False

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.bin.mcp_es_server import (  # noqa: E402
    es_audit_query,
    es_btcu_search,
    es_cross_reference,
    es_evidence_bundle,
    es_facets,
    es_health,
    es_parent_expand,
    es_publicacoes_search,
    es_search,
    es_suggest,
    es_tcu_semantic_search,
    es_trending,
)

load_dotenv(ROOT / ".env")

CASES_PATH = Path(__file__).with_name("eval_mcp_cases.json")
RESULTS_PATH = Path(__file__).with_name("eval_mcp_quality_results.json")
REPORT_PATH = Path(__file__).with_name("eval_mcp_quality_report.md")

TOOL_MAP: dict[str, Any] = {
    "es_audit_query": es_audit_query,
    "es_btcu_search": es_btcu_search,
    "es_cross_reference": es_cross_reference,
    "es_evidence_bundle": es_evidence_bundle,
    "es_facets": es_facets,
    "es_health": es_health,
    "es_parent_expand": es_parent_expand,
    "es_publicacoes_search": es_publicacoes_search,
    "es_search": es_search,
    "es_suggest": es_suggest,
    "es_tcu_semantic_search": es_tcu_semantic_search,
    "es_trending": es_trending,
}

TEXT_FIELDS = (
    "identifica",
    "title",
    "titulo",
    "assunto",
    "section_title",
    "description",
    "excerpt",
    "snippet",
    "literal_excerpt",
    "ementa",
    "chunk_text",
    "source_type",
    "doc_id",
)

OPTIONAL_SKIP_MARKERS = (
    "index ",
    "not available",
    "404 not found",
    "no such index",
    "embedding service unavailable",
    "client error '404",
    "could not find session",
)


def load_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def _get_path(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return None
            current = current[index]
        else:
            return None
    return current


def _flatten_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_flatten_strings(item))
        return out
    if isinstance(value, dict):
        out = []
        for item in value.values():
            out.extend(_flatten_strings(item))
        return out
    return [str(value)]


def _result_items(result: dict[str, Any]) -> list[Any]:
    if isinstance(result.get("results"), list):
        return result["results"]
    if isinstance(result.get("suggestions"), list):
        return result["suggestions"]
    return []


def _result_count(result: dict[str, Any]) -> int:
    if isinstance(result.get("results"), list):
        return len(result["results"])
    if isinstance(result.get("suggestions"), list):
        return len(result["suggestions"])
    return 0


def _row_text(row: Any) -> str:
    if isinstance(row, str):
        return row
    if not isinstance(row, dict):
        return str(row)
    parts = [str(row.get(field) or "") for field in TEXT_FIELDS]
    return " ".join(part for part in parts if part)


def _text_blob(case: dict[str, Any], result: dict[str, Any]) -> str:
    checks = case.get("checks", {})
    top_n = int(checks.get("scan_top_n", 3))
    text_path = checks.get("text_path")
    if text_path:
        return " ".join(_flatten_strings(_get_path(result, text_path)))
    items = _result_items(result)[:top_n]
    return " ".join(_row_text(item) for item in items)


def _compact_preview(result: dict[str, Any]) -> dict[str, Any]:
    preview: dict[str, Any] = {
        "query_id": result.get("query_id"),
        "error": result.get("error"),
        "warning": result.get("warning"),
    }
    for field in ("total", "dou_count", "tcu_count", "total_publications", "took_ms"):
        if field in result:
            preview[field] = result.get(field)

    items = _result_items(result)
    if items:
        first = items[0]
        if isinstance(first, dict):
            preview["first_result"] = {
                key: first.get(key)
                for key in (
                    "doc_id",
                    "identifica",
                    "title",
                    "titulo",
                    "assunto",
                    "pub_date",
                    "data_publicacao",
                    "score",
                )
                if first.get(key) is not None
            }
        else:
            preview["first_result"] = first
    return preview


def _is_optional_skip(case: dict[str, Any], result: dict[str, Any] | None, exc: BaseException | None) -> bool:
    if not case.get("optional"):
        return False
    message_parts: list[str] = []
    if exc is not None:
        message_parts.append(str(exc))
    if result:
        message_parts.extend(
            str(result.get(key) or "") for key in ("error", "warning")
        )
    haystack = _normalize_text(" ".join(message_parts))
    return any(marker in haystack for marker in OPTIONAL_SKIP_MARKERS)


def _check_scalar_min(result: dict[str, Any], path: str, expected: float) -> str | None:
    value = _get_path(result, path)
    if not isinstance(value, (int, float)) or value < expected:
        return f"{path} expected >= {expected}, got {value!r}"
    return None


def _check_list_min(result: dict[str, Any], path: str, expected: int) -> str | None:
    value = _get_path(result, path)
    if not isinstance(value, list) or len(value) < expected:
        size = len(value) if isinstance(value, list) else None
        return f"{path} expected at least {expected} items, got {size!r}"
    return None


def _evaluate_case(case: dict[str, Any], result: dict[str, Any]) -> list[str]:
    checks = case.get("checks", {})
    failures: list[str] = []

    if checks.get("require_query_id") and not result.get("query_id"):
        failures.append("missing query_id")
    if checks.get("error_absent") and result.get("error"):
        failures.append(f"unexpected error: {result.get('error')}")

    if "min_total" in checks:
        failure = _check_scalar_min(result, "total", checks["min_total"])
        if failure:
            failures.append(failure)

    if "min_items" in checks and _result_count(result) < int(checks["min_items"]):
        failures.append(
            f"expected at least {checks['min_items']} result items, got {_result_count(result)}"
        )

    if "min_suggestions" in checks:
        count = len(result.get("suggestions", [])) if isinstance(result.get("suggestions"), list) else 0
        if count < int(checks["min_suggestions"]):
            failures.append(f"expected at least {checks['min_suggestions']} suggestions, got {count}")

    for path, expected in checks.get("scalar_paths_min", {}).items():
        failure = _check_scalar_min(result, path, expected)
        if failure:
            failures.append(failure)

    for path, expected in checks.get("list_paths_min", {}).items():
        failure = _check_list_min(result, path, expected)
        if failure:
            failures.append(failure)

    if checks.get("top_contains_any"):
        haystack = _normalize_text(_text_blob(case, result))
        needles = [_normalize_text(value) for value in checks["top_contains_any"]]
        if not any(needle and needle in haystack for needle in needles):
            failures.append(
                "top results did not contain any expected terms: "
                + ", ".join(checks["top_contains_any"])
            )

    return failures


async def _call_tool(tool_name: str, kwargs: dict[str, Any]) -> Any:
    fn = TOOL_MAP[tool_name]
    value = fn(**kwargs)
    if inspect.isawaitable(value):
        return await value
    return value


async def run_case(case: dict[str, Any], strict_optional: bool) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = await _call_tool(case["tool"], case.get("kwargs", {}))
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        if not strict_optional and _is_optional_skip(case, None, exc):
            return {
                "id": case["id"],
                "label": case.get("label", case["id"]),
                "tool": case["tool"],
                "status": "skipped",
                "elapsed_ms": elapsed_ms,
                "reason": str(exc),
            }
        return {
            "id": case["id"],
            "label": case.get("label", case["id"]),
            "tool": case["tool"],
            "status": "failed",
            "elapsed_ms": elapsed_ms,
            "failures": [f"exception: {type(exc).__name__}: {exc}"],
            "traceback": traceback.format_exc(),
        }

    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    if not isinstance(result, dict):
        return {
            "id": case["id"],
            "label": case.get("label", case["id"]),
            "tool": case["tool"],
            "status": "failed",
            "elapsed_ms": elapsed_ms,
            "failures": [f"tool returned non-dict result: {type(result).__name__}"],
        }

    if not strict_optional and _is_optional_skip(case, result, None):
        return {
            "id": case["id"],
            "label": case.get("label", case["id"]),
            "tool": case["tool"],
            "status": "skipped",
            "elapsed_ms": elapsed_ms,
            "reason": result.get("error") or result.get("warning"),
            "result_preview": _compact_preview(result),
        }

    failures = _evaluate_case(case, result)
    return {
        "id": case["id"],
        "label": case.get("label", case["id"]),
        "tool": case["tool"],
        "status": "passed" if not failures else "failed",
        "elapsed_ms": elapsed_ms,
        "failures": failures,
        "result_preview": _compact_preview(result),
        "query_id": result.get("query_id"),
        "result": result,
        "followups": case.get("followups", []),
    }


def _first_chunk_ids(result: dict[str, Any], limit: int = 2) -> list[str]:
    items = result.get("results", [])
    chunk_ids: list[str] = []
    if not isinstance(items, list):
        return chunk_ids
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("source_type") != "dou_chunk":
            continue
        chunk_id = str(item.get("chunk_id") or "").strip()
        if chunk_id:
            chunk_ids.append(chunk_id)
        if len(chunk_ids) >= limit:
            break
    return chunk_ids


async def _followup_audit(row: dict[str, Any], strict_optional: bool) -> dict[str, Any]:
    query_id = row.get("query_id")
    if not query_id:
        return {
            "id": f"{row['id']}:audit_roundtrip",
            "tool": "es_audit_query",
            "status": "failed",
            "failures": ["missing query_id for audit roundtrip"],
        }

    started = time.perf_counter()
    result = es_audit_query(query_id=query_id)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    if not strict_optional and _is_optional_skip({"optional": True}, result, None):
        return {
            "id": f"{row['id']}:audit_roundtrip",
            "tool": "es_audit_query",
            "status": "skipped",
            "elapsed_ms": elapsed_ms,
            "reason": result.get("error") or result.get("warning"),
            "result_preview": _compact_preview(result),
        }

    failures = []
    if not result.get("found"):
        failures.append("audit record not found for query_id")
    return {
        "id": f"{row['id']}:audit_roundtrip",
        "tool": "es_audit_query",
        "status": "passed" if not failures else "failed",
        "elapsed_ms": elapsed_ms,
        "failures": failures,
        "result_preview": _compact_preview(result),
    }


async def _followup_parent_expand(row: dict[str, Any], strict_optional: bool) -> dict[str, Any]:
    result = row.get("result") or {}
    chunk_ids = _first_chunk_ids(result)
    if not chunk_ids:
        return {
            "id": f"{row['id']}:parent_expand",
            "tool": "es_parent_expand",
            "status": "skipped" if not strict_optional else "failed",
            "reason": "no DOU chunk ids available in evidence bundle",
        }

    started = time.perf_counter()
    expanded = await _call_tool("es_parent_expand", {"chunk_ids": chunk_ids})
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    if not isinstance(expanded, dict):
        return {
            "id": f"{row['id']}:parent_expand",
            "tool": "es_parent_expand",
            "status": "failed",
            "elapsed_ms": elapsed_ms,
            "failures": ["non-dict result from es_parent_expand"],
        }

    failures = []
    results = expanded.get("results", [])
    if not isinstance(results, list) or not results:
        failures.append("no parent expansions returned")
    elif not any(str(item.get("expanded_context") or "").strip() for item in results if isinstance(item, dict)):
        failures.append("expanded_context missing from all parent expansions")

    return {
        "id": f"{row['id']}:parent_expand",
        "tool": "es_parent_expand",
        "status": "passed" if not failures else "failed",
        "elapsed_ms": elapsed_ms,
        "failures": failures,
        "result_preview": _compact_preview(expanded),
    }


def _top_doc_ids(result: dict[str, Any], limit: int = 3) -> list[str]:
    ids: list[str] = []
    for item in result.get("results", [])[:limit]:
        if not isinstance(item, dict):
            continue
        doc_id = str(item.get("doc_id") or item.get("chunk_id") or "").strip()
        if doc_id:
            ids.append(doc_id)
    return ids


async def _followup_wrapper_parity(row: dict[str, Any], strict_optional: bool) -> dict[str, Any]:
    if row["tool"] not in {"es_btcu_search", "es_publicacoes_search"}:
        return {
            "id": f"{row['id']}:wrapper_parity",
            "tool": "wrapper_parity",
            "status": "skipped",
            "reason": "wrapper parity only applies to btcu/publicacoes wrappers",
        }

    original_kwargs = {}
    if row["tool"] == "es_btcu_search":
        original_kwargs = {
            "query": row["result"].get("query"),
            "source": "btcu",
            "page_size": row["result"].get("page_size", 3),
            "page": row["result"].get("page", 1),
        }
        if row["result"].get("caderno"):
            original_kwargs["caderno"] = row["result"]["caderno"]
        if row["result"].get("section_type"):
            original_kwargs["section_type"] = row["result"]["section_type"]
    else:
        original_kwargs = {
            "query": row["result"].get("query"),
            "source": "publicacoes",
            "page_size": row["result"].get("page_size", 3),
            "page": row["result"].get("page", 1),
        }
        if row["result"].get("pub_type"):
            original_kwargs["pub_type"] = row["result"]["pub_type"]

    if not original_kwargs.get("query"):
        return {
            "id": f"{row['id']}:wrapper_parity",
            "tool": "es_search",
            "status": "failed",
            "failures": ["wrapper result did not preserve query for parity check"],
        }

    started = time.perf_counter()
    canonical = await _call_tool("es_search", original_kwargs)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    if not isinstance(canonical, dict):
        return {
            "id": f"{row['id']}:wrapper_parity",
            "tool": "es_search",
            "status": "failed",
            "elapsed_ms": elapsed_ms,
            "failures": ["canonical es_search returned non-dict result"],
        }

    if not strict_optional and _is_optional_skip({"optional": True}, canonical, None):
        return {
            "id": f"{row['id']}:wrapper_parity",
            "tool": "es_search",
            "status": "skipped",
            "elapsed_ms": elapsed_ms,
            "reason": canonical.get("error") or canonical.get("warning"),
            "result_preview": _compact_preview(canonical),
        }

    failures = []
    wrapper_result = row.get("result", {})
    if canonical.get("total") != wrapper_result.get("total"):
        failures.append(
            f"total mismatch wrapper={wrapper_result.get('total')} canonical={canonical.get('total')}"
        )

    wrapper_ids = _top_doc_ids(wrapper_result)
    canonical_ids = _top_doc_ids(canonical)
    if wrapper_ids and canonical_ids and wrapper_ids[0] != canonical_ids[0]:
        failures.append(f"top doc mismatch wrapper={wrapper_ids[0]} canonical={canonical_ids[0]}")

    return {
        "id": f"{row['id']}:wrapper_parity",
        "tool": "es_search",
        "status": "passed" if not failures else "failed",
        "elapsed_ms": elapsed_ms,
        "failures": failures,
        "result_preview": {
            "wrapper_top_ids": wrapper_ids,
            "canonical_top_ids": canonical_ids,
            "wrapper_total": wrapper_result.get("total"),
            "canonical_total": canonical.get("total"),
        },
    }


async def run_followups(rows: list[dict[str, Any]], strict_optional: bool) -> list[dict[str, Any]]:
    followup_rows: list[dict[str, Any]] = []
    for row in rows:
        if row.get("status") != "passed":
            continue
        for followup in row.get("followups", []):
            if followup == "audit_roundtrip":
                followup_rows.append(await _followup_audit(row, strict_optional))
            elif followup == "parent_expand":
                followup_rows.append(await _followup_parent_expand(row, strict_optional))
            elif followup == "wrapper_parity":
                followup_rows.append(await _followup_wrapper_parity(row, strict_optional))
    return followup_rows


def _tool_breakdown(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    breakdown: dict[str, dict[str, int]] = {}
    for row in rows:
        tool = row.get("tool", "unknown")
        bucket = breakdown.setdefault(tool, {"passed": 0, "failed": 0, "skipped": 0})
        bucket[row.get("status", "failed")] = bucket.get(row.get("status", "failed"), 0) + 1
    return breakdown


def build_report(report: dict[str, Any]) -> str:
    generated_at = report["summary"]["generated_at"]
    lines = [
        "# MCP Quality Evaluation Report",
        "",
        f"**Generated**: {generated_at}",
        f"**Cases**: {report['summary']['cases_total']}",
        f"**Passed**: {report['summary']['passed']}",
        f"**Failed**: {report['summary']['failed']}",
        f"**Skipped**: {report['summary']['skipped']}",
        f"**Average elapsed**: {report['summary']['avg_elapsed_ms']} ms",
        "",
        "## Tool Breakdown",
        "",
        "| Tool | Passed | Failed | Skipped |",
        "|------|--------|--------|---------|",
    ]

    for tool, bucket in sorted(report["tool_breakdown"].items()):
        lines.append(
            f"| {tool} | {bucket.get('passed', 0)} | {bucket.get('failed', 0)} | {bucket.get('skipped', 0)} |"
        )

    if report["summary"]["failed"]:
        lines.extend(["", "## Failures", ""])
        for row in report["rows"]:
            if row.get("status") != "failed":
                continue
            lines.append(f"### {row['id']} — {row.get('label', row['id'])}")
            lines.append("")
            for failure in row.get("failures", []):
                lines.append(f"- {failure}")
            preview = row.get("result_preview")
            if preview:
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps(preview, ensure_ascii=False, indent=2))
                lines.append("```")

    lines.extend(["", "## Case Results", ""])
    lines.extend(
        [
            "| Status | Case | Tool | Elapsed (ms) | Preview |",
            "|--------|------|------|--------------|---------|",
        ]
    )
    for row in report["rows"]:
        preview = row.get("result_preview") or {}
        short_preview = json.dumps(preview, ensure_ascii=False)[:120].replace("|", "/")
        lines.append(
            f"| {row.get('status')} | {row.get('id')} | {row.get('tool')} | {row.get('elapsed_ms', '')} | {short_preview} |"
        )

    return "\n".join(lines) + "\n"


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run curated MCP quality evaluation")
    parser.add_argument("--cases", default=str(CASES_PATH), help="Path to case pack JSON")
    parser.add_argument("--case", default="", help="Run only cases whose id contains this substring")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of cases after filtering")
    parser.add_argument("--strict-optional", action="store_true", help="Fail optional cases instead of skipping missing sources/services")
    parser.add_argument("--json-out", default=str(RESULTS_PATH), help="Path to JSON report")
    parser.add_argument("--report-out", default=str(REPORT_PATH), help="Path to Markdown report")
    args = parser.parse_args()

    cases = load_cases(Path(args.cases))
    if args.case:
        needle = _normalize_text(args.case)
        cases = [case for case in cases if needle in _normalize_text(case["id"])]
    if args.limit > 0:
        cases = cases[: args.limit]

    rows: list[dict[str, Any]] = []
    for case in cases:
        rows.append(await run_case(case, args.strict_optional))

    rows.extend(await run_followups(rows, args.strict_optional))

    status_counts = Counter(row.get("status", "failed") for row in rows)
    elapsed = [float(row.get("elapsed_ms", 0.0)) for row in rows if row.get("elapsed_ms") is not None]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases_total": len(rows),
        "passed": status_counts.get("passed", 0),
        "failed": status_counts.get("failed", 0),
        "skipped": status_counts.get("skipped", 0),
        "avg_elapsed_ms": round(sum(elapsed) / max(len(elapsed), 1), 1),
    }

    report = {
        "summary": summary,
        "tool_breakdown": _tool_breakdown(rows),
        "rows": rows,
    }

    json_path = Path(args.json_out)
    json_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")

    markdown_path = Path(args.report_out)
    markdown_path.write_text(build_report(report), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Wrote JSON report to {json_path}")
    print(f"Wrote Markdown report to {markdown_path}")

    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
