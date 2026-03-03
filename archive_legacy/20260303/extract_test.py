#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from validation.extractor import ExtractionHarness
from validation.reporter import write_report
from validation.rules import load_rules


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Extraction test harness (no DB)")
    p.add_argument("--rules", required=True, help="rules YAML file")
    p.add_argument("--html", required=True, help="folder with raw HTML files")
    p.add_argument("--out", required=True, help="report output folder")
    p.add_argument("--source", default="dou", help="source id under sources.*")
    return p


def main() -> int:
    args = parser().parse_args()
    rules = load_rules(args.rules, source_id=args.source)

    harness = ExtractionHarness(rules)
    run = harness.run_folder(Path(args.html))
    write_report(run, Path(args.out))

    print(f"files={len(run.files)} out={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
