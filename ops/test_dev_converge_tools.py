"""Smoke-test the hosted dev-converge tool surface with mock-local agents.

Usage:
  python ops/test_dev_converge_tools.py
  python ops/test_dev_converge_tools.py --output /tmp/dev_converge_results.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dev_converge.mcp_server import (  # noqa: E402
    complete_once,
    get_defaults,
    poll_job,
    start_run_panel,
)
from src.dev_converge.worker import process_next_job  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test hosted dev-converge tools")
    parser.add_argument("--output", default="", help="Optional JSON output path")
    args = parser.parse_args()

    defaults = await get_defaults()
    if "mock-local" not in defaults.get("agent_catalog", {}):
        raise SystemExit("mock-local agent missing from defaults")

    once = await complete_once(
        task="List two reasons deterministic smoke tests are useful.",
        agent_name="mock-local",
    )
    if "output" not in once or "mock-local" not in str(once.get("output")):
        raise SystemExit("complete_once did not return mock-local output")

    queued = start_run_panel(
        task="List two operational risks for deploying a search service.",
        agent_names="mock-local",
        include_transcript=True,
    )
    job_id = queued.get("job_id")
    if not job_id:
        raise SystemExit("start_run_panel did not return a job_id")

    before = poll_job(job_id=job_id, include_result=False)
    if before.get("status") != "queued":
        raise SystemExit(f"expected queued status before worker run, got {before.get('status')}")

    processed = await process_next_job()
    if not processed:
        raise SystemExit("worker did not process queued job")

    after = poll_job(job_id=job_id, include_result=True)
    if after.get("status") != "succeeded":
        raise SystemExit(f"expected succeeded status after worker run, got {after.get('status')}")
    result = after.get("result", {})
    if "result" not in result and "summary" not in result:
        raise SystemExit("poll_job(include_result=True) did not return stored result content")

    payload: dict[str, Any] = {
        "defaults": defaults,
        "complete_once": once,
        "queued_job": queued,
        "job_after_worker": after,
    }
    if args.output:
        Path(args.output).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps({"status": "ok", "job_id": job_id}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
