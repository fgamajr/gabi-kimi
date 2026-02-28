#!/usr/bin/env python3
"""Standalone memory budget simulation to validate level transitions and recovery."""

from __future__ import annotations

import argparse
import time

from crawler.memory_budget import MemoryBudgetConfig, MemoryBudgetManager
from crawler.observability import CrawlerLogger


class ToggleTrimBuffer:
    def __init__(self) -> None:
        self._chunks: list[bytearray] = []
        self.allow_trim = False

    def allocate_mb(self, mb: int) -> None:
        if mb > 0:
            self._chunks.append(bytearray(mb * 1024 * 1024))

    def trim(self) -> None:
        if self.allow_trim:
            self._chunks.clear()


class DummyCache:
    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    def touch(self, key: str) -> None:
        self._d[key] = key

    def clear(self) -> None:
        self._d.clear()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--log", default="reports/memory_budget_simulation.log")
    p.add_argument("--env", default="dev")
    p.add_argument("--limit-mb", type=int, default=200)
    p.add_argument("--allocate-step-mb", type=int, default=40)
    p.add_argument("--max-steps", type=int, default=20)
    return p.parse_args()


def main() -> int:
    args = parse_args()

    log = CrawlerLogger(svc="fake-browser", env=args.env)
    log.configure(args.log)

    mgr = MemoryBudgetManager(
        MemoryBudgetConfig(limit_mb=args.limit_mb, sample_interval_sec=0, pause_sleep_sec=0.05),
        emit_event=lambda evt, fields: log.emit_event(evt, **fields),
    )

    buf = ToggleTrimBuffer()
    cache = DummyCache()
    mgr.register_buffer("simulated_buffer", buf)
    mgr.register_cache("simulated_cache", cache)

    run = log.generate_run_id()
    log.run_started(run=run, years=0, start_date="n/a", end_date="n/a", mode="simulated-memory")

    # Phase 1: allocate until critical enters.
    for i in range(1, args.max_steps + 1):
        cache.touch(f"k{i}")
        buf.allocate_mb(args.allocate_step_mb)
        mgr.checkpoint("memory_sim_alloc")
        if mgr.current_level() == "critical":
            break
        time.sleep(0.01)

    # Phase 2: allow trim and wait for automatic resume.
    buf.allow_trim = True
    for _ in range(60):
        mgr.checkpoint("memory_sim_recover")
        if not mgr.should_pause():
            break
        time.sleep(0.05)

    log.run_completed(
        run=run,
        duration_ms=0,
        total_targets=0,
        ok=0,
        fail=0,
        success_rate=0.0,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
