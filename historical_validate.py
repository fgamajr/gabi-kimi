#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from validation.corpus_sampler import CorpusSampler, SamplerConfig
from validation.extractor import ExtractionHarness
from validation.reporter import write_report
from validation.rules import load_rules


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Historical corpus validation runner")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sample")
    s.add_argument("--out", default="samples")
    s.add_argument("--dates", type=int, default=200)
    s.add_argument("--max-articles", type=int, default=200)
    s.add_argument("--start-year", type=int, default=2010)
    s.add_argument("--end-year", type=int)
    s.add_argument("--seed", type=int, default=42)

    e = sub.add_parser("extract")
    e.add_argument("--rules", required=True)
    e.add_argument("--html", required=True)
    e.add_argument("--out", default="validation_report")
    e.add_argument("--source", default="dou")

    f = sub.add_parser("full")
    f.add_argument("--rules", required=True)
    f.add_argument("--samples", default="samples")
    f.add_argument("--out", default="validation_report")
    f.add_argument("--dates", type=int, default=200)
    f.add_argument("--max-articles", type=int, default=200)
    f.add_argument("--start-year", type=int, default=2010)
    f.add_argument("--end-year", type=int)
    f.add_argument("--seed", type=int, default=42)
    f.add_argument("--source", default="dou")

    return p


def run_sample(args) -> int:
    cfg = SamplerConfig(
        start_year=args.start_year,
        end_year=args.end_year,
        sample_dates=args.dates,
        max_articles=args.max_articles,
        seed=args.seed,
    )
    meta = CorpusSampler(cfg).build(Path(args.out))
    print(f"sampled_dates={meta['dates_sampled']} sampled_articles={meta['articles_selected']} out={args.out}")
    return 0


def run_extract(args) -> int:
    rules = load_rules(args.rules, source_id=args.source)
    run = ExtractionHarness(rules).run_folder(Path(args.html))
    write_report(run, Path(args.out))
    print(f"files={len(run.files)} out={args.out}")
    return 0


def main() -> int:
    args = parser().parse_args()
    if args.cmd == "sample":
        return run_sample(args)
    if args.cmd == "extract":
        return run_extract(args)

    # full
    run_sample(
        argparse.Namespace(
            out=args.samples,
            dates=args.dates,
            max_articles=args.max_articles,
            start_year=args.start_year,
            end_year=args.end_year,
            seed=args.seed,
        )
    )
    return run_extract(
        argparse.Namespace(rules=args.rules, html=args.samples, out=args.out, source=args.source)
    )


if __name__ == "__main__":
    raise SystemExit(main())
