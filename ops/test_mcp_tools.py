"""Current MCP smoke suite for GABI's search server.

Exercises the live MCP tool surface with async-aware execution and
contract checks for query_id / took_ms / error fields.

Usage:
  python ops/test_mcp_tools.py
  python ops/test_mcp_tools.py --output ops/test_mcp_results.json
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
import time
import traceback
from typing import Any

sys.path.insert(0, ".")

from ops.bin.mcp_es_server import (
    es_audit_query,
    es_compare_periods,
    es_cross_reference,
    es_document,
    es_evidence_bundle,
    es_health,
    es_organ_profile,
    es_parent_expand,
    es_search,
    es_significant_terms,
    es_suggest,
)


def _assert_envelope(
    result: dict[str, Any], *, allow_error: bool = True
) -> dict[str, Any]:
    missing = [key for key in ("query_id", "took_ms", "error") if key not in result]
    if missing:
        raise AssertionError(f"missing envelope fields: {missing}")
    if not allow_error and result.get("error"):
        raise AssertionError(f"unexpected error: {result['error']}")
    return result


async def _call(fn, *args, **kwargs) -> Any:
    value = fn(*args, **kwargs)
    if inspect.isawaitable(value):
        return await value
    return value


async def _run_case(name: str, fn, *args, **kwargs) -> dict[str, Any]:
    started_at = time.perf_counter()
    try:
        result = await _call(fn, *args, **kwargs)
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
        return {
            "name": name,
            "status": "ok",
            "elapsed_ms": elapsed_ms,
            "result": result,
        }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
        return {
            "name": name,
            "status": "error",
            "elapsed_ms": elapsed_ms,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }


async def _search_validation_error() -> dict[str, Any]:
    result = await es_search(
        query="nepotismo",
        date_from="2025-12-31",
        date_to="2025-01-01",
    )
    _assert_envelope(result)
    if not result.get("error"):
        raise AssertionError("expected validation error from es_search")
    return result


async def _search_btcu_canonical() -> dict[str, Any]:
    result = await es_search(
        query="portaria",
        source="btcu",
        page=1,
        page_size=3,
        caderno="Administrativo",
    )
    _assert_envelope(result)
    if result.get("source") not in (None, "btcu"):
        raise AssertionError("btcu source was not preserved")
    return result


async def _search_publicacoes_canonical() -> dict[str, Any]:
    result = await es_search(
        query="auditoria",
        source="publicacoes",
        page=1,
        page_size=3,
        pub_type="sumarios-executivos",
    )
    _assert_envelope(result)
    return result


async def _search_rewrite_btcu() -> dict[str, Any]:
    result = await es_search(
        query="quando TCU proibiu nepotismo",
        source="btcu",
        page=1,
        page_size=3,
        rewrite=True,
    )
    _assert_envelope(result)
    if "rewrite" not in result:
        raise AssertionError("rewrite metadata missing from btcu canonical search")
    return result


async def _evidence_bundle_smoke() -> dict[str, Any]:
    result = await es_evidence_bundle(query="licitação emergencial", k=3)
    _assert_envelope(result)
    return result


async def _parent_expand_empty() -> dict[str, Any]:
    result = await es_parent_expand(chunk_ids=[])
    _assert_envelope(result)
    if result.get("results") != []:
        raise AssertionError("expected empty result for empty parent expand")
    return result


def _audit_lookup_miss() -> dict[str, Any]:
    result = es_audit_query(query_id="missing-query-id")
    _assert_envelope(result)
    if result.get("found") not in (False, 0):
        raise AssertionError("expected missing audit lookup")
    return result


def _sigterms_validation_error() -> dict[str, Any]:
    result = es_significant_terms(query="*")
    _assert_envelope(result)
    if not result.get("error"):
        raise AssertionError("expected validation error from es_significant_terms")
    return result


def _crossref_validation_error() -> dict[str, Any]:
    result = es_cross_reference(reference="")
    _assert_envelope(result)
    if not result.get("error"):
        raise AssertionError("expected validation error from es_cross_reference")
    return result


def _organ_validation_error() -> dict[str, Any]:
    result = es_organ_profile(organ="")
    _assert_envelope(result)
    if not result.get("error"):
        raise AssertionError("expected validation error from es_organ_profile")
    return result


def _compare_validation_error() -> dict[str, Any]:
    result = es_compare_periods(query="decreto")
    _assert_envelope(result)
    if not result.get("error"):
        raise AssertionError("expected validation error from es_compare_periods")
    return result


async def _document_not_found() -> dict[str, Any]:
    result = await es_document(doc_id="nonexistent_doc_12345")
    _assert_envelope(result, allow_error=False)
    if result.get("found") is not False:
        raise AssertionError("expected missing document")
    return result


async def _suggest_empty() -> dict[str, Any]:
    result = await es_suggest(prefix="")
    _assert_envelope(result, allow_error=False)
    return result


def _health_smoke() -> dict[str, Any]:
    result = es_health()
    _assert_envelope(result, allow_error=False)
    return result


def build_test_suite() -> list[tuple[str, Any]]:
    return [
        ("health:smoke", _health_smoke),
        ("suggest:empty", _suggest_empty),
        ("document:not_found", _document_not_found),
        ("search:validation_error", _search_validation_error),
        ("search:btcu:canonical", _search_btcu_canonical),
        ("search:publicacoes:canonical", _search_publicacoes_canonical),
        ("search:btcu:rewrite", _search_rewrite_btcu),
        ("sigterms:validation_error", _sigterms_validation_error),
        ("crossref:validation_error", _crossref_validation_error),
        ("organ:validation_error", _organ_validation_error),
        ("compare:validation_error", _compare_validation_error),
        ("evidence_bundle:smoke", _evidence_bundle_smoke),
        ("parent_expand:empty", _parent_expand_empty),
        ("audit_query:miss", _audit_lookup_miss),
    ]


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run MCP smoke tests")
    parser.add_argument("--output", default=None, help="Optional JSON report path")
    args = parser.parse_args()

    results: list[dict[str, Any]] = []
    for name, fn in build_test_suite():
        results.append(await _run_case(name, fn))

    summary = {
        "total": len(results),
        "ok": sum(1 for row in results if row["status"] == "ok"),
        "error": sum(1 for row in results if row["status"] == "error"),
    }
    report = {"summary": summary, "results": results}

    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=True, indent=2)

    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 1 if summary["error"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
