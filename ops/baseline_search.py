#!/usr/bin/env python3
"""Search baseline runner for /api/search.

Usage examples:
  python3 ops/baseline_search.py
  python3 ops/baseline_search.py --base-url http://localhost:8001 --runs 3
  python3 ops/baseline_search.py --queries-file ops/baselines/queries_v1.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://localhost:8001"
DEFAULT_QUERIES_FILE = Path("ops/baselines/queries_v1.json")
DEFAULT_OUTPUT_DIR = Path("ops/baselines")


@dataclass
class Sample:
    query: str
    run: int
    status_code: int
    latency_ms: float
    total: int | None
    took_ms: int | None
    results_count: int | None
    ok: bool
    error: str | None


def _git_short_commit() -> str:
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        )
        return output.decode("utf-8").strip() or "nogit"
    except Exception:
        return "nogit"


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 3)
    return round(float(statistics.quantiles(values, n=100, method="inclusive")[int(q * 100) - 1]), 3)


def _bucket(value: int | None) -> str:
    if value is None:
        return "unknown"
    if value == 0:
        return "0"
    if value <= 3:
        return "1-3"
    if value <= 10:
        return "4-10"
    if value <= 50:
        return "11-50"
    if value <= 200:
        return "51-200"
    return "201+"


def _request_search(base_url: str, query: str, timeout_s: float) -> tuple[int, dict[str, Any]]:
    params = urlencode({"q": query, "page": 1, "max": 10})
    url = f"{base_url.rstrip('/')}/api/search?{params}"
    req = Request(url, method="GET")
    with urlopen(req, timeout=timeout_s) as response:
        status = int(getattr(response, "status", 200))
        payload = json.loads(response.read().decode("utf-8"))
        return status, payload


def _load_queries(path: Path) -> tuple[str, list[str]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    query_set_id = str(raw.get("query_set_id") or path.stem)
    queries = [str(item).strip() for item in raw.get("queries", []) if str(item).strip()]
    if not queries:
        raise ValueError(f"No queries found in {path}")
    return query_set_id, queries


def _summarize(samples: list[Sample]) -> dict[str, Any]:
    latencies = [s.latency_ms for s in samples]
    ok_samples = [s for s in samples if s.ok]
    total_count = len(samples)
    errors = [s for s in samples if not s.ok]
    empty_ok = [s for s in ok_samples if (s.results_count or 0) == 0]

    results_hist: dict[str, int] = {}
    total_hist: dict[str, int] = {}
    for s in ok_samples:
        r_key = _bucket(s.results_count)
        t_key = _bucket(s.total)
        results_hist[r_key] = results_hist.get(r_key, 0) + 1
        total_hist[t_key] = total_hist.get(t_key, 0) + 1

    return {
        "sample_count": total_count,
        "ok_count": len(ok_samples),
        "error_count": len(errors),
        "latency_ms_p50": _quantile(latencies, 0.50),
        "latency_ms_p95": _quantile(latencies, 0.95),
        "error_rate": round((len(errors) / total_count) if total_count else 0.0, 6),
        "empty_rate": round((len(empty_ok) / len(ok_samples)) if ok_samples else 0.0, 6),
        "results_count_histogram": results_hist,
        "total_histogram": total_hist,
    }


def _per_query(samples: list[Sample], queries: list[str]) -> list[dict[str, Any]]:
    grouped: list[dict[str, Any]] = []
    for query in queries:
        q_samples = [s for s in samples if s.query == query]
        q_summary = _summarize(q_samples)
        avg_took = [s.took_ms for s in q_samples if s.took_ms is not None]
        grouped.append(
            {
                "query": query,
                "runs": len(q_samples),
                "summary": {
                    **q_summary,
                    "avg_took_ms": round(sum(avg_took) / len(avg_took), 3) if avg_took else None,
                },
            }
        )
    return grouped


def _default_output_path(output_arg: str | None) -> Path:
    if output_arg:
        return Path(output_arg)
    date_stamp = datetime.now(UTC).strftime("%Y%m%d")
    commit = _git_short_commit()
    return DEFAULT_OUTPUT_DIR / f"baseline_{date_stamp}_{commit}.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run /api/search baseline and write JSON output.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base backend URL (default: http://localhost:8001)")
    parser.add_argument("--queries-file", default=str(DEFAULT_QUERIES_FILE), help="Path to query set JSON")
    parser.add_argument("--runs", type=int, default=2, help="Repetitions per query (default: 2)")
    parser.add_argument("--output", default=None, help="Output JSON path (default: ops/baselines/baseline_YYYYMMDD_<commit>.json)")
    parser.add_argument("--timeout", type=float, default=10.0, help="Request timeout in seconds (default: 10)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    queries_path = Path(args.queries_file)
    if args.runs < 1:
        print("--runs must be >= 1", file=sys.stderr)
        return 2
    if args.timeout <= 0:
        print("--timeout must be > 0", file=sys.stderr)
        return 2
    if not queries_path.exists():
        print(f"queries file not found: {queries_path}", file=sys.stderr)
        return 2

    query_set_id, queries = _load_queries(queries_path)
    samples: list[Sample] = []

    for query in queries:
        for run_idx in range(1, args.runs + 1):
            t0 = time.perf_counter()
            try:
                status, payload = _request_search(args.base_url, query, args.timeout)
                latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
                results = payload.get("results") if isinstance(payload, dict) else None
                samples.append(
                    Sample(
                        query=query,
                        run=run_idx,
                        status_code=status,
                        latency_ms=latency_ms,
                        total=int(payload.get("total", 0)) if isinstance(payload, dict) else None,
                        took_ms=int(payload.get("took_ms", 0)) if isinstance(payload, dict) else None,
                        results_count=len(results) if isinstance(results, list) else None,
                        ok=(200 <= status < 300),
                        error=None if 200 <= status < 300 else f"http_status_{status}",
                    )
                )
            except Exception as exc:
                latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
                samples.append(
                    Sample(
                        query=query,
                        run=run_idx,
                        status_code=0,
                        latency_ms=latency_ms,
                        total=None,
                        took_ms=None,
                        results_count=None,
                        ok=False,
                        error=str(exc),
                    )
                )

    output_path = _default_output_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "commit": _git_short_commit(),
        "env": "local",
        "api_base": args.base_url,
        "query_set_id": query_set_id,
        "runs": args.runs,
        "summary": _summarize(samples),
        "per_query": _per_query(samples, queries),
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    has_errors = payload["summary"]["error_count"] > 0
    print(f"wrote baseline: {output_path}")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 1 if has_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
