"""CLI for manually scoring RAG answers.

Usage:
    python -m src.backend.answering.feedback --query_id <id> --score correct
    python -m src.backend.answering.feedback --query_id <id> --score incorrect --reason "..."
    python -m src.backend.answering.feedback --list
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from src.backend.answering.ledger import _LEDGER_DIR, get_trace, recent_traces


def _feedback_path() -> Path:
    return _LEDGER_DIR / "scoring_feedback.jsonl"


def iter_scoring_feedback(
    *,
    feedback_path: Path | None = None,
) -> Iterator[dict[str, Any]]:
    path = feedback_path or _feedback_path()
    if not path.exists():
        return
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def record_feedback(
    query_id: str,
    score: str,
    reason: str = "",
) -> None:
    if score not in ("correct", "incorrect", "partial"):
        raise ValueError(f"score must be correct/incorrect/partial, got: {score!r}")

    trace = get_trace(query_id)
    if trace is None:
        print(f"Error: trace not found for query_id={query_id}", file=sys.stderr)
        sys.exit(1)

    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query_id": query_id,
        "query": trace.get("query", ""),
        "query_type": trace.get("query_type", ""),
        "score": score,
        "reason": reason,
        "model": trace.get("model", ""),
        "citations_extracted": trace.get("citations_extracted", 0),
        "hallucinated_removed": trace.get("hallucinated_citations_removed", 0),
    }

    _LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    with _feedback_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Feedback recorded: {score} for query_id={query_id}")


def list_recent(limit: int = 10) -> None:
    traces = recent_traces(limit)
    if not traces:
        print("No traces found.")
        return
    print(f"Last {len(traces)} answers:\n")
    for t in traces:
        print(
            f"  [{t['query_id'][:8]}...] {t['query'][:60]} "
            f"| type={t['query_type']} | citations={t['citations_extracted']} "
            f"| latency={t.get('latency_ms', '?')}ms"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Score RAG answers")
    parser.add_argument("--query_id", help="query_id to score")
    parser.add_argument(
        "--score",
        choices=["correct", "incorrect", "partial"],
        help="Answer quality score",
    )
    parser.add_argument("--reason", default="", help="Optional reason")
    parser.add_argument("--list", action="store_true", help="List recent answers")
    parser.add_argument(
        "--limit", type=int, default=10, help="Number of entries to list"
    )

    args = parser.parse_args()

    if args.list:
        list_recent(args.limit)
        return 0

    if not args.query_id or not args.score:
        parser.print_help()
        return 1

    record_feedback(args.query_id, args.score, args.reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
