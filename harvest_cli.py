"""CLI entrypoint for deterministic DOU historical harvesting.

Phase 1: listing page freezer. Downloads and stores raw HTML.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from harvest.date_selector import select_dates
from harvest.freezer import freeze_range


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


def cmd_freeze(args: argparse.Namespace) -> None:
    """Freeze DOU listing pages for a date range."""
    try:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
    except ValueError as exc:
        raise SystemExit(f"error: {exc}")
    if start > end:
        raise SystemExit("error: start date must be before or equal to end date")

    output_dir = Path(args.output)
    # Check existing path components for symlinks before any mkdir
    check = Path(output_dir.anchor) if output_dir.is_absolute() else Path.cwd()
    for part in output_dir.parts[1:] if output_dir.is_absolute() else output_dir.parts:
        check = check / part
        if check.is_symlink():
            raise SystemExit(f"error: output path contains symlinks: {check}")
        if not check.exists():
            break
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SystemExit(f"error: cannot create output directory: {exc}")
    # Post-creation recheck: reject if output_dir is now a symlink (TOCTOU mitigation)
    if output_dir.is_symlink():
        raise SystemExit(f"error: output path is a symlink: {output_dir}")
    resolved = output_dir.resolve(strict=True)
    if not resolved.is_dir():
        raise SystemExit(f"error: output path is not a directory: {output_dir}")
    # Verify resolved path components have no symlinks
    rc = Path(resolved.anchor)
    for part in resolved.parts[1:]:
        rc = rc / part
        if rc.is_symlink():
            raise SystemExit(f"error: resolved path contains symlinks: {rc}")

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(message)s",
        level=level,
        stream=sys.stderr,
        force=True,
    )

    delay = getattr(args, "delay", 1.5)
    retries = getattr(args, "retries", 3)
    workers = getattr(args, "workers", 1)
    no_resume = getattr(args, "no_resume", False)

    dates_processed = 0
    total_ok = 0
    total_err = 0
    try:
        for m in freeze_range(start, end, resolved,
                              delay=delay, retries=retries,
                              workers=workers, resume=not no_resume):
            dates_processed += 1
            for s in (m.get("sections") or []):
                if s.get("error") is not None:
                    total_err += 1
                elif s.get("sha256") is not None:
                    total_ok += 1
    except Exception as exc:
        logging.exception("freeze failed: %s", exc)
        raise SystemExit(1)

    # Summary to stdout
    summary = {
        "dates_processed": dates_processed,
        "output_dir": str(resolved),
        "sections_failed": total_err,
        "sections_ok": total_ok,
    }
    try:
        json.dump(summary, sys.stdout, indent=2, sort_keys=True)
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

    p_freeze = sub.add_parser("freeze", help="Freeze DOU listing pages")
    p_freeze.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    p_freeze.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    p_freeze.add_argument("--output", required=True, help="Output directory")
    p_freeze.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    p_freeze.add_argument("--delay", type=float, default=1.5,
                          help="Seconds between requests (default: 1.5)")
    p_freeze.add_argument("--retries", type=int, default=3,
                          help="Max retries per download (default: 3)")
    p_freeze.add_argument("--workers", type=int, default=1,
                          help="Parallel download threads (default: 1)")
    p_freeze.add_argument("--no-resume", action="store_true",
                          help="Re-freeze all dates (ignore existing manifests)")
    p_freeze.set_defaults(func=cmd_freeze)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        raise SystemExit(1)
    args.func(args)


if __name__ == "__main__":
    main()
