from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from cases import build_cases
from grader import aggregate_scores, grade_case
from normalization import BenchmarkHydrator, normalized_query, response_meta
from reporting import build_markdown_summary, create_run_dir, write_json, write_markdown

import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backend.search.adapters import (  # noqa: E402
    PGSearchAdapter,
    SearchConfig,
    create_search_adapter,
    load_search_config,
)

try:
    from judge import judge_results
except ImportError:
    judge_results = None  # type: ignore[assignment]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run hybrid search benchmark cases")
    parser.add_argument("--backends", default="hybrid,pg", help="Comma-separated backends: hybrid,es,pg")
    parser.add_argument("--limit", type=int, default=0, help="Optional limit for case count")
    parser.add_argument("--top-k", type=int, default=10, help="How many results to grade per case")
    parser.add_argument("--page-size", type=int, default=10, help="Search page size")
    parser.add_argument("--category", action="append", default=[], help="Filter to one or more categories")
    parser.add_argument("--llm-judge-agent", default="", help="Optional judge agent from .dev/mcp")
    parser.add_argument("--judge-sample", type=int, default=0, help="Judge only the first N cases per backend")
    parser.add_argument("--run-label", default="", help="Optional run label suffix")
    return parser.parse_args()


def main() -> None:
    load_dotenv(ROOT / ".env")
    args = parse_args()
    backends = [item.strip() for item in args.backends.split(",") if item.strip()]
    cases = build_cases()
    if args.category:
        allowed = set(args.category)
        cases = [case for case in cases if case["category"] in allowed]
    if args.limit > 0:
        cases = cases[: args.limit]

    run_dir = create_run_dir(run_label=args.run_label or None)
    base_cfg = load_search_config()
    adapters = {backend: _adapter_for_backend(base_cfg, backend) for backend in backends}
    hydrator = BenchmarkHydrator(base_cfg.pg_dsn)

    results_by_backend: dict[str, list[dict[str, Any]]] = {backend: [] for backend in backends}
    category_rollup: dict[str, dict[str, list[dict[str, Any]]]] = {
        backend: defaultdict(list) for backend in backends
    }

    judge_budget = {backend: args.judge_sample for backend in backends}

    for case in cases:
        for backend, adapter in adapters.items():
            query = normalized_query(case, backend)
            response = adapter.search(
                query=query,
                page_size=args.page_size,
                page=1,
                **case["filters"],
            )
            rows = hydrator.hydrate(response.get("results") or [])
            grade = grade_case(case, rows, top_k=args.top_k)
            record: dict[str, Any] = {
                "case": case,
                "backend": backend,
                "response_meta": response_meta(
                    response,
                    backend=backend,
                    original_query=str(case["query"]),
                    executed_query=query,
                ),
                "results": rows,
                "grade": grade,
            }
            if args.llm_judge_agent and judge_results and judge_budget[backend] > 0:
                record["llm_judge"] = judge_results(
                    judge_agent=args.llm_judge_agent,
                    case=case,
                    backend=backend,
                    results=rows,
                    top_k=min(5, args.top_k),
                )
                judge_budget[backend] -= 1
            results_by_backend[backend].append(record)
            category_rollup[backend][case["category"]].append(grade)

    aggregates = {
        backend: aggregate_scores([item["grade"] for item in items])
        for backend, items in results_by_backend.items()
    }
    by_category = {
        backend: {
            category: aggregate_scores(grades)
            for category, grades in categories.items()
        }
        for backend, categories in category_rollup.items()
    }

    summary = {
        "case_count": len(cases),
        "backends": backends,
        "run_dir": str(run_dir),
        "aggregates": aggregates,
        "by_category": by_category,
    }

    write_json(run_dir / "summary.json", summary)
    write_markdown(run_dir / "summary.md", build_markdown_summary(summary))
    write_json(run_dir / "cases.json", cases)
    for backend, items in results_by_backend.items():
        write_json(run_dir / f"{backend}.json", items)

    print(f"benchmark cases={len(cases)} backends={','.join(backends)} run_dir={run_dir}")
    for backend in backends:
        metrics = aggregates[backend]
        print(
            f"{backend}: p@1={metrics['p_at_1']:.4f} p@3={metrics['p_at_3']:.4f} "
            f"hits@10={metrics['hits_at_10']:.4f} mrr={metrics['mrr']:.4f}"
        )


def _adapter_for_backend(base_cfg: SearchConfig, backend: str):
    if backend == "pg":
        return PGSearchAdapter(base_cfg.pg_dsn)
    cfg = SearchConfig(
        backend=backend,
        pg_dsn=base_cfg.pg_dsn,
        es_url=base_cfg.es_url,
        es_index=base_cfg.es_index,
        es_chunks_index=base_cfg.es_chunks_index,
        es_username=base_cfg.es_username,
        es_password=base_cfg.es_password,
        es_verify_tls=base_cfg.es_verify_tls,
        es_timeout_sec=base_cfg.es_timeout_sec,
        hybrid_lexical_k=base_cfg.hybrid_lexical_k,
        hybrid_vector_k=base_cfg.hybrid_vector_k,
        hybrid_num_candidates=base_cfg.hybrid_num_candidates,
        hybrid_rrf_k=base_cfg.hybrid_rrf_k,
        rerank_provider=base_cfg.rerank_provider,
        rerank_top_n=base_cfg.rerank_top_n,
    )
    return create_search_adapter(cfg)


if __name__ == "__main__":
    main()
