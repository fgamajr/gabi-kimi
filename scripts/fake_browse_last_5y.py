#!/usr/bin/env python3
"""Run fake browser traffic against DOU leiturajornal pages for the last N years."""

from __future__ import annotations

import argparse
import os

from crawler.fake_browser import FakeBrowserConfig, run_fake_browse, write_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--sleep-min", type=float, default=0.15)
    parser.add_argument("--sleep-max", type=float, default=0.6)
    parser.add_argument("--max-consecutive-failures", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--report", default="reports/fake_browse_last_5y.json")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    cfg = FakeBrowserConfig(
        years=args.years,
        timeout_seconds=args.timeout,
        sleep_min_seconds=args.sleep_min,
        sleep_max_seconds=args.sleep_max,
        max_consecutive_failures=args.max_consecutive_failures,
        seed=args.seed,
    )

    results, summary = run_fake_browse(cfg)

    report_dir = os.path.dirname(args.report)
    if report_dir:
        os.makedirs(report_dir, exist_ok=True)
    write_report(args.report, results, summary)

    print("\nRun summary")
    for k, v in summary.items():
        print(f"- {k}: {v}")
    print(f"- report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
