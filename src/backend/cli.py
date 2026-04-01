"""GABI feedback CLI.

Usage:
    python -m src.backend.cli feedback-query "consulta" --predicted exploratory --correct legal_reference
    python -m src.backend.cli feedback-answer "consulta" --failure --reason "citou norma inexistente"
    python -m src.backend.cli agent-learn
    python -m src.backend.cli traces [--limit 10]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _ledger_dir() -> Path:
    try:
        from src.backend.core.config import settings

        preferred = Path(settings.RETRIEVAL_AUDIT_LOG_PATH).parent / "answers"
        try:
            preferred.mkdir(parents=True, exist_ok=True)
            return preferred
        except OSError:
            pass
    except Exception:
        pass
    fallback = Path.home() / ".gabi_dou" / "answers"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def cmd_feedback_query(args: argparse.Namespace) -> int:
    from src.backend.answering.classifier import QUERY_TYPES, get_query_classifier

    if args.correct not in QUERY_TYPES:
        print(
            f"Error: --correct must be one of: {', '.join(QUERY_TYPES)}",
            file=sys.stderr,
        )
        return 1
    if args.predicted not in QUERY_TYPES:
        print(
            f"Error: --predicted must be one of: {', '.join(QUERY_TYPES)}",
            file=sys.stderr,
        )
        return 1

    classifier = get_query_classifier()
    learned = classifier.register_feedback(
        query=args.query,
        predicted=args.predicted,
        correct=args.correct,
        confidence=args.confidence,
        source="cli",
    )

    print(f"Feedback recorded: predicted={args.predicted} → correct={args.correct}")
    if learned:
        print(f"Learned {len(learned)} new pattern(s): {list(learned.keys())}")
    return 0


def cmd_feedback_answer(args: argparse.Namespace) -> int:
    ledger = _ledger_dir()
    ledger.mkdir(parents=True, exist_ok=True)

    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query": args.query,
        "success": not args.failure,
        "reason": args.reason,
        "source": "cli",
    }

    feedback_file = ledger / "scoring_feedback.jsonl"
    with feedback_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    status = "failure" if args.failure else "success"
    print(
        f"Answer feedback recorded: {status}"
        + (f" — {args.reason}" if args.reason else "")
    )
    return 0


def cmd_agent_learn(args: argparse.Namespace) -> int:
    from src.backend.answering.classifier import get_query_classifier

    classifier = get_query_classifier()
    if not classifier.enabled:
        classifier.enabled = True

    learned = classifier.learn()
    if not learned:
        print("No new patterns learned (need ≥3 occurrences per token).")
    else:
        print(f"Learned {len(learned)} pattern(s):")
        for token, label in sorted(learned.items()):
            print(f"  {token!r} → {label}")
    return 0


def cmd_agent_learn_scoring(args: argparse.Namespace) -> int:
    from src.backend.answering.classifier import AdaptiveQueryClassifier

    classifier = AdaptiveQueryClassifier(ledger_root=_ledger_dir())
    summary = classifier.learn_scoring()
    by_qt = summary.get("by_query_type", {})
    total_n = sum(v.get("total", 0) for v in by_qt.values())
    if total_n == 0:
        print("Nenhum feedback registrado.")
        return 0
    for qt in sorted(by_qt.keys()):
        inf = by_qt[qt]
        rate = float(inf["success_rate"])
        print(f"{qt}: taxa_de_sucesso={rate:.2%} total_feedbacks={inf['total']}")
    return 0


def cmd_traces(args: argparse.Namespace) -> int:
    from src.backend.answering.ledger import recent_traces

    traces = recent_traces(args.limit)
    if not traces:
        print("No traces found.")
        return 0

    print(f"Last {len(traces)} answers:\n")
    for t in traces:
        qid = t.get("query_id", "?")[:8]
        query = t.get("query", "")[:60]
        qtype = t.get("query_type", "?")
        cits = t.get("citations_extracted", 0)
        latency = t.get("latency_ms", "?")
        print(
            f"  [{qid}…] {query} | type={qtype} | citations={cits} | latency={latency}ms"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gabi", description="GABI feedback CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # feedback-query
    p_fq = sub.add_parser("feedback-query", help="Record query classification feedback")
    p_fq.add_argument("query", help="Query text")
    p_fq.add_argument("--predicted", required=True, help="Predicted query type")
    p_fq.add_argument("--correct", required=True, help="Correct query type")
    p_fq.add_argument(
        "--confidence",
        type=float,
        default=0.5,
        help="Classifier confidence (default: 0.5)",
    )

    # feedback-answer
    p_fa = sub.add_parser("feedback-answer", help="Record answer quality feedback")
    p_fa.add_argument("query", help="Query text")
    p_fa.add_argument(
        "--failure", action="store_true", help="Mark as failure (default: success)"
    )
    p_fa.add_argument("--reason", default="", help="Optional failure reason")

    # agent-learn
    sub.add_parser("agent-learn", help="Process feedback and update learned patterns")

    # agent-learn-scoring
    sub.add_parser(
        "agent-learn-scoring",
        help="Aggregate scoring_feedback.jsonl into scoring_stats.json",
    )

    # traces
    p_tr = sub.add_parser("traces", help="List recent answer traces")
    p_tr.add_argument(
        "--limit", type=int, default=10, help="Max entries to show (default: 10)"
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    handlers = {
        "feedback-query": cmd_feedback_query,
        "feedback-answer": cmd_feedback_answer,
        "agent-learn": cmd_agent_learn,
        "agent-learn-scoring": cmd_agent_learn_scoring,
        "traces": cmd_traces,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
