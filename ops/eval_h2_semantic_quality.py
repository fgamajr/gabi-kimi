from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from src.backend.parsing.h2_llm import build_h2_prompt, call_local_llm
from src.backend.parsing.h2_quality import evaluate_h2_output
from src.backend.parsing.h2_vocab import tags_for_source


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _build_text(row: dict[str, Any]) -> str:
    raw = row.get("raw_fields") or {}
    return (
        row.get("raw_text")
        or raw.get("texto")
        or raw.get("content_html")
        or raw.get("body_plain")
        or raw.get("TEXTONORMA")
        or ""
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate H2 semantic output quality on sampled docs")
    parser.add_argument("--input", required=True, help="JSONL sample input")
    parser.add_argument("--source", default="dou_documents")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--model", default="qwen3")
    parser.add_argument("--output", default="ops/data/h2_eval_report.json")
    parser.add_argument("--min-avg-score", type=float, default=0.75)
    parser.add_argument("--min-pass-rate", type=float, default=0.90)
    parser.add_argument("--fail-score-threshold", type=float, default=0.60)
    parser.add_argument("--max-span-error-rate", type=float, default=0.02)
    parser.add_argument("--max-low-coverage-rate", type=float, default=0.10)
    args = parser.parse_args()

    source = args.source
    allowed = tags_for_source(source)
    if not allowed:
        raise SystemExit(f"No allowed tags configured for source={source}")

    rows = _iter_jsonl(Path(args.input))[: args.limit]
    reports: list[dict[str, Any]] = []
    for row in rows:
        text = _build_text(row)
        if not text.strip():
            continue
        prompt = build_h2_prompt(text=text, allowed_tags=allowed, source_type=source)
        try:
            output = call_local_llm(prompt=prompt, model=args.model)
            report = evaluate_h2_output(text=text, allowed_tags=allowed, output=output)
            reports.append(
                {
                    "raw_id": row.get("raw_id"),
                    "score": report.score,
                    "issues": list(report.issues),
                    "coverage_ratio": report.coverage_ratio,
                    "valid_schema": report.valid_schema,
                    "valid_spans": report.valid_spans,
                }
            )
        except Exception as exc:
            reports.append({"raw_id": row.get("raw_id"), "score": 0.0, "issues": [f"llm_error:{exc}"]})

    total = len(reports)
    avg = sum(item["score"] for item in reports) / total if total else 0.0
    failed = sum(1 for item in reports if item["score"] < args.fail_score_threshold)
    span_errors = sum(1 for item in reports if any(str(x).startswith("span_error:") for x in item.get("issues", [])))
    low_coverage = sum(1 for item in reports if any(str(x).startswith("low_coverage:") for x in item.get("issues", [])))
    pass_rate = round(((total - failed) / total), 4) if total else 0.0
    span_error_rate = round((span_errors / total), 4) if total else 0.0
    low_coverage_rate = round((low_coverage / total), 4) if total else 0.0
    summary = {
        "source": source,
        "model": args.model,
        "total_evaluated": total,
        "avg_score": round(avg, 4),
        "failed_below_threshold": failed,
        "fail_score_threshold": args.fail_score_threshold,
        "pass_rate": pass_rate,
        "span_error_rate": span_error_rate,
        "low_coverage_rate": low_coverage_rate,
        "gate_thresholds": {
            "min_avg_score": args.min_avg_score,
            "min_pass_rate": args.min_pass_rate,
            "max_span_error_rate": args.max_span_error_rate,
            "max_low_coverage_rate": args.max_low_coverage_rate,
        },
        "reports": reports,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    gate_passed = (
        summary["avg_score"] >= args.min_avg_score
        and summary["pass_rate"] >= args.min_pass_rate
        and summary["span_error_rate"] <= args.max_span_error_rate
        and summary["low_coverage_rate"] <= args.max_low_coverage_rate
    )
    summary["gate_passed"] = gate_passed
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(out),
                "total": total,
                "avg_score": summary["avg_score"],
                "pass_rate": summary["pass_rate"],
                "gate_passed": gate_passed,
            },
            ensure_ascii=False,
        )
    )
    if not gate_passed:
        sys.exit(2)


if __name__ == "__main__":
    main()
