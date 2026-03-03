#!/usr/bin/env python3
"""Run YAML-driven crawl engine in mock runtime mode."""

from __future__ import annotations

import argparse

from crawler.crawl_engine import CrawlEngine
from crawler.dsl_loader import load_crawl_spec
from crawler.observability import CrawlerLogger


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="examples/mock_crawl.yaml")
    p.add_argument("--env", default="dev")
    p.add_argument("--log", default="reports/mock_crawl.log")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    logger = CrawlerLogger(svc="mock-crawl", env=args.env)
    logger.configure(args.log)

    spec = load_crawl_spec(args.config)
    engine = CrawlEngine(logger=logger)
    state = engine.execute(spec)

    # machine-friendly summary line
    print(f"total_documents={len(state.documents)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
