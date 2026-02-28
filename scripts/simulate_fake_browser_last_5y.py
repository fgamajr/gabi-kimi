#!/usr/bin/env python3
"""Simulate fake-browser browsing for DOU leiturajornal without real HTTP requests."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import random
import time

from crawler.memory_budget import MemoryBudgetConfig, MemoryBudgetManager
from crawler.observability import CrawlerLogger
from crawler.user_agent_rotator import create_default_rotator


def iter_last_days(years: int):
    end = date.today()
    start = end - timedelta(days=years * 365)
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def build_url(d: date) -> str:
    return f"https://www.in.gov.br/leiturajornal?data={d.strftime('%d-%m-%Y')}"


def simulate_result(rng: random.Random) -> tuple[bool, str, int]:
    latency_ms = rng.randint(45, 180)
    roll = rng.random()
    if roll < 0.90:
        return True, "ok", latency_ms
    if roll < 0.96:
        return False, "blocked", latency_ms
    if roll < 0.99:
        return False, "timeout", latency_ms
    return False, "error", latency_ms


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--log", default="reports/fake_browser_simulation.log")
    p.add_argument("--sleep-ms", type=int, default=0)
    p.add_argument("--env", default="dev")
    p.add_argument("--memory-limit-mb", type=int, default=1024)
    p.add_argument("--memory-sample-sec", type=float, default=1.0)
    p.add_argument("--memory-stress-mb-per-step", type=int, default=0)
    p.add_argument("--buffer-trim-ratio", type=float, default=0.50)
    p.add_argument("--max-targets", type=int, default=0)
    return p.parse_args()


class SimulatedDomCache:
    def __init__(self) -> None:
        self._items: dict[str, str] = {}

    def add(self, key: str, value: str) -> None:
        self._items[key] = value

    def clear(self) -> None:
        self._items.clear()


class SimulatedDownloadBuffer:
    def __init__(self, trim_ratio: float) -> None:
        self._chunks: list[bytearray] = []
        self._trim_ratio = max(0.0, min(trim_ratio, 1.0))

    def add_megabytes(self, mb: int) -> None:
        if mb <= 0:
            return
        self._chunks.append(bytearray(mb * 1024 * 1024))

    def trim(self) -> None:
        if not self._chunks:
            return
        keep = int(len(self._chunks) * self._trim_ratio)
        if keep <= 0:
            self._chunks.clear()
            return
        self._chunks = self._chunks[-keep:]


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)

    log = CrawlerLogger(svc="fake-browser", env=args.env)
    log.configure(args.log)
    memory = MemoryBudgetManager(
        MemoryBudgetConfig(
            limit_mb=args.memory_limit_mb,
            sample_interval_sec=args.memory_sample_sec,
        ),
        emit_event=lambda evt, fields: log.emit_event(evt, **fields),
    )

    rotator = create_default_rotator()
    ua_ids = {ua: idx for idx, ua in enumerate(rotator.user_agents, start=1)}
    dom_cache = SimulatedDomCache()
    download_buffer = SimulatedDownloadBuffer(trim_ratio=args.buffer_trim_ratio)
    memory.register_cache("dom_cache", dom_cache)
    memory.register_buffer("download_buffer", download_buffer)

    days = list(iter_last_days(args.years))
    if args.max_targets > 0:
        days = days[: args.max_targets]
    run_id = log.generate_run_id()
    started_at = time.monotonic()

    log.run_started(
        run=run_id,
        years=args.years,
        start_date=days[0].isoformat(),
        end_date=days[-1].isoformat(),
        mode="simulated",
    )

    total = 0
    ok = 0
    fail = 0

    for day in days:
        memory.pause_if_needed()
        memory.checkpoint("before_request")

        ua = rotator.next()
        ua_id = ua_ids[ua]
        url = build_url(day)
        day_iso = day.isoformat()

        log.request_planned(
            run=run_id,
            day=day_iso,
            ua_id=ua_id,
            ua_hash=log.ua_hash(ua),
            url=url,
        )

        reachable, status, latency_ms = simulate_result(rng)

        # Simulate parser/extractor memory pressure points.
        dom_cache.add(day_iso, url)
        if args.memory_stress_mb_per_step > 0:
            download_buffer.add_megabytes(args.memory_stress_mb_per_step)

        memory.checkpoint("after_parse")
        log.request_result(
            run=run_id,
            day=day_iso,
            ua_id=ua_id,
            reachable=reachable,
            simulated=True,
            latency_ms=latency_ms,
            status=status,
        )

        total += 1
        if reachable:
            ok += 1
        else:
            fail += 1

        if args.sleep_ms > 0:
            time.sleep(args.sleep_ms / 1000.0)

        memory.checkpoint("after_request")

    duration_ms = int((time.monotonic() - started_at) * 1000)
    success_rate = round(ok / total, 3) if total else 0.0

    log.run_completed(
        run=run_id,
        duration_ms=duration_ms,
        total_targets=total,
        ok=ok,
        fail=fail,
        success_rate=success_rate,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
