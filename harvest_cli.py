"""CLI entrypoint for deterministic DOU historical harvesting.

Phase 1: date selection only. No network calls.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from harvest.date_selector import select_dates


def cmd_dates(args: argparse.Namespace) -> None:
    """List all dates in the given range."""
    try:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
        dates = select_dates(start, end)
    except (ValueError, TypeError) as exc:
        raise SystemExit(f"error: {exc}")

    output = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "total_dates": len(dates),
        "dates": [d.isoformat() for d in dates],
    }
    try:
        json.dump(output, sys.stdout, indent=2)
        sys.stdout.write("\n")
    except BrokenPipeError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="harvest_cli",
        description="Deterministic DOU historical harvesting",
    )
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    p_dates = sub.add_parser("dates", help="List all dates in range")
    p_dates.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    p_dates.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    p_dates.set_defaults(func=cmd_dates)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        raise SystemExit(1)
    args.func(args)


if __name__ == "__main__":
    main()
