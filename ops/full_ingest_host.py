#!/usr/bin/env python3
"""Host-native full DOU ingest orchestrator.

Usage:
  python ops/full_ingest_host.py
  python ops/full_ingest_host.py --reset-state
  python ops/full_ingest_host.py --from-month 2011-01 --month-workers 6
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.backend.core.config import settings
from src.backend.data.db import MongoDB
from src.backend.ingest.sync_dou import sync_month


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "ops" / "data" / "dou_catalog_registry.json"
DATA_DIR = REPO_ROOT / "ops" / "data"
STATE_PATH = DATA_DIR / "ingest_state.json"
EVENTS_PATH = DATA_DIR / "ingest_events.jsonl"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_registry_months() -> list[str]:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    months = sorted(registry.get("folder_ids", {}).keys())
    if not months:
        raise RuntimeError(f"No months found in {REGISTRY_PATH}")
    return months


def _initial_state(months: list[str], month_workers: int, zip_parallelism: int) -> dict[str, Any]:
    return {
        "version": 1,
        "started_at": _utc_now(),
        "updated_at": _utc_now(),
        "month_workers": month_workers,
        "zip_parallelism": zip_parallelism,
        "months_total": len(months),
        "months_completed": [],
        "months_failed": {},
        "active_months": {},
        "docs_completed": 0,
        "zips_completed": 0,
        "last_completed_month": None,
    }


def _read_state(months: list[str], month_workers: int, zip_parallelism: int) -> dict[str, Any]:
    if not STATE_PATH.exists():
        return _initial_state(months, month_workers, zip_parallelism)
    with STATE_PATH.open("r", encoding="utf-8") as handle:
        state = json.load(handle)
    state["months_total"] = len(months)
    state.setdefault("months_completed", [])
    state.setdefault("months_failed", {})
    state["active_months"] = {}
    state.setdefault("docs_completed", 0)
    state.setdefault("zips_completed", 0)
    state["month_workers"] = month_workers
    state["zip_parallelism"] = zip_parallelism
    return state


def _write_state(state: dict[str, Any]) -> None:
    state["updated_at"] = _utc_now()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = STATE_PATH.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
    tmp_path.replace(STATE_PATH)


def _append_event(event: dict[str, Any]) -> None:
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def _process_one_month(ym: str, *, zip_parallelism: int) -> dict[str, Any]:
    year_str, month_str = ym.split("-")
    year = int(year_str)
    month = int(month_str)
    start = time.perf_counter()
    summary = sync_month(year, month, extract_xmls=False, parallelism=zip_parallelism)
    elapsed_sec = round(time.perf_counter() - start, 2)
    summary.update({"year_month": ym, "elapsed_sec": elapsed_sec})
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Host-native full DOU ingest runner")
    parser.add_argument("--from-month", help="Inclusive YYYY-MM lower bound")
    parser.add_argument("--to-month", help="Inclusive YYYY-MM upper bound")
    parser.add_argument(
        "--month-workers",
        type=int,
        default=int(os.getenv("DOU_MONTH_PARALLELISM", "6")),
        help="Number of months to process in parallel",
    )
    parser.add_argument(
        "--zip-parallelism",
        type=int,
        default=int(os.getenv("DOU_INGEST_PARALLELISM", str(settings.DOU_INGEST_PARALLELISM))),
        help="Parallel ZIP workers per month",
    )
    parser.add_argument("--reset-state", action="store_true", help="Delete prior ingest state and events")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    months = _load_registry_months()

    if args.from_month:
        months = [month for month in months if month >= args.from_month]
    if args.to_month:
        months = [month for month in months if month <= args.to_month]
    if not months:
        raise RuntimeError("No months selected after applying filters")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if args.reset_state:
        for path in (STATE_PATH, EVENTS_PATH):
            if path.exists():
                path.unlink()

    state_lock = threading.Lock()
    state = _read_state(months, args.month_workers, args.zip_parallelism)
    completed = set(state.get("months_completed", []))
    pending_months = [month for month in months if month not in completed]

    logger.info(
        "Starting host ingest months=%s pending=%s month_workers=%s zip_parallelism=%s mongo=%s",
        len(months),
        len(pending_months),
        args.month_workers,
        args.zip_parallelism,
        settings.MONGO_STRING,
    )
    MongoDB.connect()
    _write_state(state)

    if not pending_months:
        logger.info("Nothing to do; all selected months already completed")
        return

    with ThreadPoolExecutor(max_workers=max(1, args.month_workers)) as pool:
        future_map = {}
        for ym in pending_months:
            with state_lock:
                state["active_months"][ym] = {"started_at": _utc_now(), "status": "running"}
                _write_state(state)
            _append_event({"event": "month_started", "ts": _utc_now(), "year_month": ym})
            future_map[pool.submit(_process_one_month, ym, zip_parallelism=args.zip_parallelism)] = ym

        for future in as_completed(future_map):
            ym = future_map[future]
            try:
                summary = future.result()
            except Exception as exc:
                logger.exception("Month failed: %s", ym)
                with state_lock:
                    state["active_months"].pop(ym, None)
                    state["months_failed"][ym] = {"failed_at": _utc_now(), "error": str(exc)}
                    _write_state(state)
                _append_event({"event": "month_failed", "ts": _utc_now(), "year_month": ym, "error": str(exc)})
                raise

            with state_lock:
                state["active_months"].pop(ym, None)
                if ym not in state["months_completed"]:
                    state["months_completed"].append(ym)
                    state["months_completed"].sort()
                state["months_failed"].pop(ym, None)
                state["docs_completed"] += int(summary.get("doc_count", 0))
                state["zips_completed"] += int(summary.get("zip_count", 0))
                state["last_completed_month"] = ym
                _write_state(state)

            _append_event(
                {
                    "event": "month_completed",
                    "ts": _utc_now(),
                    "year_month": ym,
                    "doc_count": int(summary.get("doc_count", 0)),
                    "zip_count": int(summary.get("zip_count", 0)),
                    "cache_hits": int(summary.get("cache_hits", 0)),
                    "elapsed_sec": float(summary.get("elapsed_sec", 0)),
                }
            )
            logger.info(
                "Month complete %s docs=%s zips=%s cache_hits=%s elapsed=%.2fs",
                ym,
                summary.get("doc_count", 0),
                summary.get("zip_count", 0),
                summary.get("cache_hits", 0),
                summary.get("elapsed_sec", 0.0),
            )

    logger.info("Full host ingest complete")


if __name__ == "__main__":
    main()
