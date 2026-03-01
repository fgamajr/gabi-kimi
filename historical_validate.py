#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from validation.corpus_sampler import CorpusSampler, SamplerConfig
from validation.edition_freezer import StabilizationConfig, freeze_edition
from validation.extractor import ExtractionHarness
from validation.identity_analyzer import analyze_identity, load_identity_config
from validation.completeness_validator import validate_completeness
from validation.semantic_resolver import resolve_semantics
from validation.platform_classifier import classify_samples
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
    s.add_argument("--delay", type=float, default=1.5)

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
    f.add_argument("--delay", type=float, default=1.5)
    f.add_argument("--source", default="dou")

    c = sub.add_parser("classify")
    c.add_argument("--samples", default="samples")
    c.add_argument("--out", default="validation_report")
    c.add_argument("--examples-per-platform", type=int, default=5)

    n = sub.add_parser("enrich")
    n.add_argument("--parsed", required=True, help="Directory with parsed JSON files")
    n.add_argument("--out", default="enriched_report")

    t = sub.add_parser("completeness")
    t.add_argument("--parsed", required=True, help="Directory with enriched/parsed JSON files")
    t.add_argument("--samples", required=True, help="Samples directory containing index.json")
    t.add_argument("--out", default="completeness_report")

    i = sub.add_parser("identity")
    i.add_argument("--parsed", required=True, help="Directory with parsed JSON files (validation_report/parsed)")
    i.add_argument("--identity-config", required=True, help="YAML file with identity block")
    i.add_argument("--out", default="identity_report")
    i.add_argument("--source", default="dou")

    z = sub.add_parser("freeze")
    z.add_argument("--samples", default="samples")
    z.add_argument("--min-page-count", type=int, default=1)
    z.add_argument("--stabilization-interval", type=float, default=3600.0)
    z.add_argument("--min-consecutive-matches", type=int, default=2)
    z.add_argument("--max-checks", type=int, default=6)
    z.add_argument("--historical-days", type=int, default=7)
    z.add_argument("--skip-stabilization", action="store_true")

    return p


def run_sample(args) -> int:
    cfg = SamplerConfig(
        start_year=args.start_year,
        end_year=args.end_year,
        sample_dates=args.dates,
        max_articles=args.max_articles,
        seed=args.seed,
        delay_sec=getattr(args, "delay", 1.5),
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


def run_freeze(args) -> int:
    cfg = StabilizationConfig(
        stabilization_interval=args.stabilization_interval,
        min_consecutive_matches=args.min_consecutive_matches,
        max_checks=args.max_checks,
        historical_days_threshold=args.historical_days,
        min_page_count=args.min_page_count,
        skip_stabilization=args.skip_stabilization,
    )
    manifest = freeze_edition(Path(args.samples), cfg)
    s = manifest.summary
    print(
        f"editions={s['total_editions']} frozen_final={s['frozen_final']} "
        f"temporally_stable={s['temporally_stable']} provisional={s['provisional']} "
        f"listings={s['total_listings_preserved']} articles_hashed={s['total_articles_hashed']}"
    )
    return 0


def main() -> int:
    args = parser().parse_args()
    if args.cmd == "sample":
        run_sample(args)
        return 0
    if args.cmd == "extract":
        return run_extract(args)
    if args.cmd == "classify":
        payload = classify_samples(
            samples_dir=Path(args.samples),
            out_dir=Path(args.out),
            max_examples_per_platform=args.examples_per_platform,
        )
        print(
            f"classified_files={payload['total_files']} "
            f"out={args.out} distribution={payload['platform_distribution']}"
        )
        return 0
    if args.cmd == "enrich":
        summary = resolve_semantics(parsed_dir=Path(args.parsed), out_dir=Path(args.out))
        print(
            f"enriched_files={summary.files_processed} enriched_docs={summary.documents_processed} "
            f"html_missing={summary.html_missing} failures={len(summary.failures)} out={args.out}"
        )
        if summary.failures:
            for f in summary.failures:
                print(f"  {f}")
            return 1
        return 0
    if args.cmd == "completeness":
        result = validate_completeness(
            parsed_dir=Path(args.parsed),
            samples_dir=Path(args.samples),
            out_dir=Path(args.out),
        )
        page_cov = (
            (result.page_matches + result.page_extra) / result.total_html_files * 100
            if result.total_html_files else 0
        )
        print(
            f"pages={result.total_html_files} docs={result.total_json_documents} "
            f"matches={result.page_matches} missing={result.page_missing} "
            f"extra={result.page_extra} page_coverage={page_cov:.1f}% out={args.out}"
        )
        if result.page_missing > 0:
            return 2
        return 0
    if args.cmd == "identity":
        cfg = load_identity_config(args.identity_config, source_id=args.source)
        summary = analyze_identity(parsed_dir=Path(args.parsed), cfg=cfg, out_dir=Path(args.out))
        print(
            f"identity_docs={summary['records']} identity_groups={summary['groups']} "
            f"fallback_pct={summary['fallback_pct']:.2f} out={args.out}"
        )
        return 0
    if args.cmd == "freeze":
        return run_freeze(args)

    # full: sample → freeze(skip_stabilization) → extract
    run_sample(
        argparse.Namespace(
            out=args.samples,
            dates=args.dates,
            max_articles=args.max_articles,
            start_year=args.start_year,
            end_year=args.end_year,
            seed=args.seed,
            delay=args.delay,
        )
    )
    run_freeze(
        argparse.Namespace(
            samples=args.samples,
            min_page_count=1,
            stabilization_interval=3600.0,
            min_consecutive_matches=2,
            max_checks=6,
            historical_days=7,
            skip_stabilization=True,
        )
    )
    return run_extract(
        argparse.Namespace(rules=args.rules, html=args.samples, out=args.out, source=args.source)
    )


if __name__ == "__main__":
    raise SystemExit(main())
