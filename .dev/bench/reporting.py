from __future__ import annotations

from datetime import UTC, date, datetime
import json
from decimal import Decimal
from pathlib import Path
from typing import Any


def create_run_dir(base_dir: str = ".dev/bench/runs", run_label: str | None = None) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = f"-{run_label}" if run_label else ""
    path = Path(base_dir) / f"{timestamp}{suffix}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n"
    )


def write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def build_markdown_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# Hybrid Search Benchmark",
        "",
        f"- Cases: {summary['case_count']}",
        f"- Backends: {', '.join(summary['backends'])}",
        f"- Run dir: `{summary['run_dir']}`",
        "",
        "## Aggregate Metrics",
        "",
        "| Backend | Cases | P@1 | P@3 | P@5 | Hits@10 | MRR | Avg Relevance |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for backend, metrics in summary["aggregates"].items():
        lines.append(
            f"| {backend} | {int(metrics['cases'])} | {metrics['p_at_1']:.4f} | "
            f"{metrics['p_at_3']:.4f} | {metrics['p_at_5']:.4f} | {metrics['hits_at_10']:.4f} | "
            f"{metrics['mrr']:.4f} | {metrics['avg_relevance']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## Categories",
            "",
            "| Backend | Category | Cases | P@1 | P@3 | Hits@10 | MRR |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for backend, categories in summary["by_category"].items():
        for category, metrics in sorted(categories.items()):
            lines.append(
                f"| {backend} | {category} | {int(metrics['cases'])} | {metrics['p_at_1']:.4f} | "
                f"{metrics['p_at_3']:.4f} | {metrics['hits_at_10']:.4f} | {metrics['mrr']:.4f} |"
            )
    return "\n".join(lines) + "\n"


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)
