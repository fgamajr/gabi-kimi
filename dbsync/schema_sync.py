"""CLI entrypoint for source-driven PostgreSQL schema reconciliation."""

from __future__ import annotations

import argparse
import os
import sys

from dbsync.differ import diff_schema
from dbsync.executor import ApplyError, apply_operations
from dbsync.introspect import introspect_database
from dbsync.loader import ModelLoadError, load_source_models
from dbsync.planner import PlanningError, build_plan


DEFAULT_DSN = "host=localhost port=5433 dbname=gabi user=gabi password=gabi"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Source-driven PostgreSQL schema sync")
    p.add_argument("command", choices=["plan", "apply", "verify"])
    p.add_argument("--sources", default="sources_v3.yaml")
    p.add_argument("--dsn", default=os.getenv("DBSYNC_DSN", DEFAULT_DSN))
    return p


def _print_plan(diff) -> None:
    print("PLAN")
    if not diff.operations and not diff.manual_actions:
        print("= no changes")
        return
    for op in diff.operations:
        print(op.summary)
    for issue in diff.manual_actions:
        print(issue)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    try:
        models = load_source_models(args.sources)
        desired = build_plan(models)
        existing = introspect_database(args.dsn)
        diff = diff_schema(desired, existing)
    except (ModelLoadError, PlanningError, Exception) as ex:
        print(f"ERROR: {ex}")
        return 2

    if args.command == "plan":
        _print_plan(diff)
        return 1 if diff.manual_actions else 0

    if args.command == "verify":
        _print_plan(diff)
        if diff.manual_actions:
            return 1
        return 0 if not diff.operations else 1

    # apply
    _print_plan(diff)
    if diff.manual_actions:
        return 1

    print("APPLY")
    if not diff.operations:
        print("OK no changes")
        return 0

    try:
        result = apply_operations(args.dsn, diff.operations)
    except ApplyError as ex:
        print(f"FAIL {ex}")
        return 1

    for line in result.applied:
        print(f"OK {line.removeprefix('+ ').strip()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
