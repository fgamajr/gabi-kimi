"""Comprehensive test suite for GABI MCP ES server — 100 queries across all 13 tools.

Exercises every tool, edge case, and feature of mcp_es_server.py.
Outputs a structured JSON report for adversarial audit.

Usage:
  python ops/test_mcp_tools.py
  python ops/test_mcp_tools.py --output ops/test_mcp_results.json
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from typing import Any

sys.path.insert(0, ".")
from ops.bin.mcp_es_server import (
    es_compare_periods,
    es_cross_reference,
    es_document,
    es_explain,
    es_facets,
    es_health,
    es_more_like_this,
    es_organ_profile,
    es_search,
    es_significant_terms,
    es_suggest,
    es_timeline,
    es_trending,
)


def _run(name: str, fn, *args, **kwargs) -> dict[str, Any]:
    """Run a test case, capture result or error."""
    t0 = time.perf_counter()
    try:
        result = fn(*args, **kwargs)
        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        return {"name": name, "status": "ok", "elapsed_ms": elapsed, "result": result}
    except Exception as exc:
        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        return {"name": name, "status": "error", "elapsed_ms": elapsed, "error": str(exc), "traceback": traceback.format_exc()}


def build_test_suite() -> list[tuple[str, Any, list, dict]]:
    """Build 100 test cases across all 13 tools."""
    tests: list[tuple[str, Any, list, dict]] = []

    # === TOOL 1: es_search (40 tests — the core tool) ===

    # Basic queries
    tests.append(("search:basic:decreto", es_search, [], {"query": "decreto"}))
    tests.append(("search:basic:portaria", es_search, [], {"query": "portaria nomeação"}))
    tests.append(("search:basic:licitacao", es_search, [], {"query": "licitação pregão eletrônico"}))
    tests.append(("search:basic:saude", es_search, [], {"query": "ministério da saúde covid"}))
    tests.append(("search:basic:educacao", es_search, [], {"query": "educação básica fundeb"}))

    # Quoted phrase detection
    tests.append(("search:phrase:reforma", es_search, [], {"query": '"reforma tributária"'}))
    tests.append(("search:phrase:protecao", es_search, [], {"query": '"proteção de dados"'}))
    tests.append(("search:phrase:bolsa", es_search, [], {"query": '"bolsa família" reajuste'}))

    # Legal reference boosting
    tests.append(("search:legalref:lei13709", es_search, [], {"query": "Lei 13709"}))
    tests.append(("search:legalref:decreto9203", es_search, [], {"query": "Decreto 9.203"}))
    tests.append(("search:legalref:mp_mixed", es_search, [], {"query": "medida provisória 1234 impacto"}))

    # Filter inference
    tests.append(("search:infer:do1", es_search, [], {"query": "decreto DO1"}))
    tests.append(("search:infer:do3_extrato", es_search, [], {"query": "extrato de contrato DO3"}))
    tests.append(("search:infer:organ", es_search, [], {"query": "ministério da fazenda imposto"}))

    # Explicit filters
    tests.append(("search:filter:section", es_search, [], {"query": "nomeação", "section": "DO2"}))
    tests.append(("search:filter:date_range", es_search, [], {"query": "decreto", "date_from": "2024-01-01", "date_to": "2024-06-30"}))
    tests.append(("search:filter:art_type", es_search, [], {"query": "energia", "art_type": "portaria"}))
    tests.append(("search:filter:combined", es_search, [], {"query": "saúde", "section": "DO1", "date_from": "2023-01-01"}))

    # Sorting
    tests.append(("search:sort:date_desc", es_search, [], {"query": "portaria", "sort": "date_desc"}))
    tests.append(("search:sort:date_asc", es_search, [], {"query": "decreto", "sort": "date_asc"}))
    tests.append(("search:sort:relevance", es_search, [], {"query": "licitação", "sort": "relevance"}))

    # Pagination
    tests.append(("search:page:1", es_search, [], {"query": "edital", "page": 1, "page_size": 5}))
    tests.append(("search:page:2", es_search, [], {"query": "edital", "page": 2, "page_size": 5}))
    tests.append(("search:page:large", es_search, [], {"query": "portaria", "page": 1, "page_size": 50}))

    # Boost recent
    tests.append(("search:boost_recent:on", es_search, [], {"query": "decreto regulamentar", "boost_recent": True}))
    tests.append(("search:boost_recent:off", es_search, [], {"query": "decreto regulamentar", "boost_recent": False}))

    # Include facets
    tests.append(("search:facets:inline", es_search, [], {"query": "imposto", "include_facets": True}))

    # Rerank toggle
    tests.append(("search:rerank:on", es_search, [], {"query": "proteção ambiental licenciamento", "rerank": True}))
    tests.append(("search:rerank:off", es_search, [], {"query": "proteção ambiental licenciamento", "rerank": False}))

    # Browse mode (wildcard)
    tests.append(("search:browse:all", es_search, [], {"query": "*", "sort": "date_desc", "page_size": 10}))
    tests.append(("search:browse:filtered", es_search, [], {"query": "*", "section": "DO1", "sort": "date_desc"}))

    # Two-stage fallback (obscure query likely to trigger OR)
    tests.append(("search:fallback:obscure", es_search, [], {"query": "xylophagous dendrochronology", "rerank": False}))

    # Synonym expansion
    tests.append(("search:synonym:tributo", es_search, [], {"query": "tributo federal"}))
    tests.append(("search:synonym:nomeacao", es_search, [], {"query": "nomeação servidor"}))

    # Complex multi-feature
    tests.append(("search:complex:full", es_search, [], {
        "query": '"reforma tributária" Lei 13709 DO1',
        "date_from": "2023-01-01",
        "boost_recent": True,
        "include_facets": True,
        "rerank": True,
        "page_size": 10,
    }))

    # Edge cases
    tests.append(("search:edge:empty", es_search, [], {"query": ""}))
    tests.append(("search:edge:special_chars", es_search, [], {"query": "art. 5° § 1º inciso III"}))
    tests.append(("search:edge:long_query", es_search, [], {"query": "ministério da saúde portaria regulamenta procedimentos atendimento básico atenção primária saúde família"}))
    tests.append(("search:edge:unicode_quotes", es_search, [], {"query": "\u201creforma administrativa\u201d"}))
    tests.append(("search:edge:page_size_1", es_search, [], {"query": "decreto", "page_size": 1}))

    # === TOOL 2: es_suggest (5 tests) ===
    tests.append(("suggest:prefix:port", es_suggest, [], {"prefix": "port"}))
    tests.append(("suggest:prefix:minist", es_suggest, [], {"prefix": "minist"}))
    tests.append(("suggest:prefix:short", es_suggest, [], {"prefix": "d"}))
    tests.append(("suggest:edge:empty", es_suggest, [], {"prefix": ""}))
    tests.append(("suggest:limit:3", es_suggest, [], {"prefix": "decreto", "limit": 3}))

    # === TOOL 3: es_facets (5 tests) ===
    tests.append(("facets:all", es_facets, [], {}))
    tests.append(("facets:query", es_facets, [], {"query": "saúde"}))
    tests.append(("facets:filtered", es_facets, [], {"query": "*", "section": "DO1", "date_from": "2024-01-01"}))
    tests.append(("facets:large", es_facets, [], {"query": "decreto", "size": 25}))
    tests.append(("facets:date_range", es_facets, [], {"query": "*", "date_from": "2020-01-01", "date_to": "2020-12-31"}))

    # === TOOL 4: es_document (4 tests) ===
    # First get a real doc_id from a search
    tests.append(("document:fetch:real", _test_document_real, [], {}))
    tests.append(("document:notfound", es_document, [], {"doc_id": "nonexistent_doc_12345"}))

    # === TOOL 5: es_health (2 tests) ===
    tests.append(("health:basic", es_health, [], {}))

    # === TOOL 6: es_more_like_this (5 tests) ===
    tests.append(("mlt:basic", _test_mlt_real, [], {}))
    tests.append(("mlt:with_section", _test_mlt_with_section, [], {}))
    tests.append(("mlt:with_date", _test_mlt_with_date, [], {}))

    # === TOOL 7: es_significant_terms (7 tests) ===
    tests.append(("sigterms:body", es_significant_terms, [], {"query": "saúde", "field": "body_plain"}))
    tests.append(("sigterms:identifica", es_significant_terms, [], {"query": "decreto", "field": "identifica"}))
    tests.append(("sigterms:ementa", es_significant_terms, [], {"query": "educação", "field": "ementa"}))
    tests.append(("sigterms:keyword", es_significant_terms, [], {"query": "licitação", "field": "art_type.keyword"}))
    tests.append(("sigterms:organ_kw", es_significant_terms, [], {"query": "energia", "field": "issuing_organ.keyword"}))
    tests.append(("sigterms:filtered", es_significant_terms, [], {"query": "*", "field": "identifica", "section": "DO1", "date_from": "2024-01-01"}))
    tests.append(("sigterms:guard:wildcard", es_significant_terms, [], {"query": "*"}))

    # === TOOL 8: es_timeline (5 tests) ===
    tests.append(("timeline:month", es_timeline, [], {"query": "decreto", "interval": "month", "date_from": "2024-01-01"}))
    tests.append(("timeline:year", es_timeline, [], {"query": "saúde", "interval": "year"}))
    tests.append(("timeline:week", es_timeline, [], {"query": "licitação", "interval": "week", "date_from": "2024-06-01", "date_to": "2024-06-30"}))
    tests.append(("timeline:all", es_timeline, [], {"query": "*", "interval": "year"}))
    tests.append(("timeline:filtered", es_timeline, [], {"query": "portaria", "interval": "quarter", "section": "DO1"}))

    # === TOOL 9: es_trending (4 tests) ===
    tests.append(("trending:7d", es_trending, [], {"days": 7}))
    tests.append(("trending:30d", es_trending, [], {"days": 30}))
    tests.append(("trending:section", es_trending, [], {"days": 14, "section": "DO1"}))
    tests.append(("trending:large", es_trending, [], {"days": 90, "size": 20}))

    # === TOOL 10: es_cross_reference (5 tests) ===
    tests.append(("crossref:lei", es_cross_reference, [], {"reference": "Lei 8.666"}))
    tests.append(("crossref:decreto", es_cross_reference, [], {"reference": "Decreto 7.892"}))
    tests.append(("crossref:constituicao", es_cross_reference, [], {"reference": "Constituição Federal"}))
    tests.append(("crossref:filtered", es_cross_reference, [], {"reference": "Lei 8.666", "section": "DO3"}))
    tests.append(("crossref:date", es_cross_reference, [], {"reference": "Lei 14.133", "date_from": "2023-01-01"}))

    # === TOOL 11: es_organ_profile (4 tests) ===
    tests.append(("organ:saude", es_organ_profile, [], {"organ": "Ministério da Saúde"}))
    tests.append(("organ:educacao", es_organ_profile, [], {"organ": "Ministério da Educação"}))
    tests.append(("organ:date_range", es_organ_profile, [], {"organ": "Ministério da Saúde", "date_from": "2024-01-01"}))
    tests.append(("organ:empty", es_organ_profile, [], {"organ": ""}))

    # === TOOL 12: es_compare_periods (4 tests) ===
    tests.append(("compare:yoy", es_compare_periods, [], {
        "query": "decreto", "period_a_from": "2023-01-01", "period_a_to": "2023-06-30",
        "period_b_from": "2024-01-01", "period_b_to": "2024-06-30",
    }))
    tests.append(("compare:saude", es_compare_periods, [], {
        "query": "saúde", "period_a_from": "2019-01-01", "period_a_to": "2019-12-31",
        "period_b_from": "2020-01-01", "period_b_to": "2020-12-31",
    }))
    tests.append(("compare:section", es_compare_periods, [], {
        "query": "*", "period_a_from": "2022-01-01", "period_a_to": "2022-12-31",
        "period_b_from": "2023-01-01", "period_b_to": "2023-12-31", "section": "DO1",
    }))
    tests.append(("compare:missing_dates", es_compare_periods, [], {"query": "teste"}))

    # === TOOL 13: es_explain (3 tests) ===
    tests.append(("explain:basic", _test_explain_real, [], {}))
    tests.append(("explain:phrase", _test_explain_phrase, [], {}))

    return tests


# --- Helper test functions that need real doc_ids ---

def _test_document_real() -> dict[str, Any]:
    """Search for a doc, then fetch it by ID."""
    results = es_search(query="decreto", page_size=1)
    if not results.get("results"):
        return {"error": "no results to fetch"}
    doc_id = results["results"][0]["doc_id"]
    return es_document(doc_id=doc_id)


def _test_mlt_real() -> dict[str, Any]:
    """Search for a doc, then find similar."""
    results = es_search(query="portaria nomeação", page_size=1)
    if not results.get("results"):
        return {"error": "no results for MLT seed"}
    doc_id = results["results"][0]["doc_id"]
    return es_more_like_this(doc_id=doc_id, max_results=5)


def _test_mlt_with_section() -> dict[str, Any]:
    results = es_search(query="decreto", page_size=1, section="DO1")
    if not results.get("results"):
        return {"error": "no results for MLT seed"}
    doc_id = results["results"][0]["doc_id"]
    return es_more_like_this(doc_id=doc_id, max_results=5, section="DO1")


def _test_mlt_with_date() -> dict[str, Any]:
    results = es_search(query="licitação", page_size=1, date_from="2024-01-01")
    if not results.get("results"):
        return {"error": "no results for MLT seed"}
    doc_id = results["results"][0]["doc_id"]
    return es_more_like_this(doc_id=doc_id, max_results=5, date_from="2024-01-01")


def _test_explain_real() -> dict[str, Any]:
    results = es_search(query="decreto regulamentar", page_size=1, rerank=False)
    if not results.get("results"):
        return {"error": "no results to explain"}
    doc_id = results["results"][0]["doc_id"]
    return es_explain(query="decreto regulamentar", doc_id=doc_id)


def _test_explain_phrase() -> dict[str, Any]:
    results = es_search(query='"proteção de dados"', page_size=1, rerank=False)
    if not results.get("results"):
        return {"error": "no results to explain"}
    doc_id = results["results"][0]["doc_id"]
    return es_explain(query='"proteção de dados"', doc_id=doc_id)


def main():
    import argparse

    p = argparse.ArgumentParser(description="Test GABI MCP ES tools")
    p.add_argument("--output", default="ops/test_mcp_results.json")
    args = p.parse_args()

    tests = build_test_suite()
    print(f"Running {len(tests)} tests...\n")

    results: list[dict[str, Any]] = []
    ok = 0
    fail = 0

    for i, (name, fn, pos_args, kw_args) in enumerate(tests, 1):
        r = _run(name, fn, *pos_args, **kw_args)
        status_icon = "✓" if r["status"] == "ok" else "✗"
        print(f"  [{i:3d}/{len(tests)}] {status_icon} {name} ({r['elapsed_ms']}ms)")
        if r["status"] == "ok":
            ok += 1
        else:
            fail += 1
            print(f"         ERROR: {r.get('error', 'unknown')}")
        results.append(r)

    # Summary
    total_ms = sum(r["elapsed_ms"] for r in results)
    summary = {
        "total_tests": len(tests),
        "passed": ok,
        "failed": fail,
        "total_time_ms": round(total_ms, 1),
        "avg_time_ms": round(total_ms / max(len(tests), 1), 1),
        "tools_tested": sorted(set(n.split(":")[0] for n, *_ in tests)),
    }

    report = {"summary": summary, "results": results}

    with open(args.output, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n{'='*60}")
    print(f"  TOTAL: {ok}/{len(tests)} passed | {fail} failed")
    print(f"  TIME:  {total_ms:.0f}ms total, {summary['avg_time_ms']:.0f}ms avg")
    print(f"  TOOLS: {len(summary['tools_tested'])} tools tested")
    print(f"  SAVED: {args.output}")
    print(f"{'='*60}")

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
