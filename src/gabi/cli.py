"""CLI utilities for GABI operations."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
import time
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy import desc, select, update
import yaml

from gabi.db import close_db, get_session_no_commit, init_db
from gabi.models.execution import ExecutionManifest, ExecutionStatus
from gabi.models.source import SourceRegistry
from gabi.tasks.sync import _classify_runtime_error, sync_source_task


def _run_sync(
    source_id: str,
    run_id: Optional[str],
    max_docs_per_source: Optional[int] = None,
    disable_embeddings: bool = False,
) -> dict:
    return sync_source_task.run(
        source_id=source_id,
        run_id=run_id,
        max_documents_per_source_override=max_docs_per_source,
        disable_embeddings=disable_embeddings,
    )


def ingest_command(
    source: str,
    run_id: Optional[str],
    max_docs_per_source: Optional[int] = None,
    disable_embeddings: bool = False,
) -> int:
    result = _run_sync(
        source_id=source,
        run_id=run_id,
        max_docs_per_source=max_docs_per_source,
        disable_embeddings=disable_embeddings,
    )
    print(json.dumps(result, default=str, indent=2))
    return 0


def _load_source_ids(sources_file: str) -> list[str]:
    with Path(sources_file).open("r", encoding="utf-8") as stream:
        payload = yaml.safe_load(stream) or {}
    sources = payload.get("sources", {}) or {}
    return list(sources.keys())


def _merge_error_summaries(results: list[dict]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for result in results:
        source_summary = result.get("error_summary", {}) or {}
        for key, value in source_summary.items():
            count = int(value or 0)
            summary[key] = summary.get(key, 0) + count
    return summary


def _build_ingest_all_summary(results: list[dict], total_elapsed_seconds: float) -> dict:
    failed_sources = [r for r in results if str(r.get("status")) != "success" or r.get("errors")]
    successful_sources = len(results) - len(failed_sources)

    failed_external_unreachable = 0
    failed_internal_regression = 0
    for result in failed_sources:
        source_summary = result.get("error_summary", {}) or {}
        if int(source_summary.get("source_unreachable_external", 0)) > 0 or result.get("source_unreachable"):
            failed_external_unreachable += 1
        if int(source_summary.get("internal_pipeline_regression", 0)) > 0:
            failed_internal_regression += 1

    failed_other = len(failed_sources) - failed_external_unreachable - failed_internal_regression
    if failed_other < 0:
        failed_other = 0

    return {
        "total_sources": len(results),
        "successful_sources": successful_sources,
        "failed_sources": len(failed_sources),
        "failed_sources_external_unreachable": failed_external_unreachable,
        "failed_sources_internal_regression": failed_internal_regression,
        "failed_sources_other": failed_other,
        "error_summary": _merge_error_summaries(results),
        "total_elapsed_seconds": round(total_elapsed_seconds, 3),
        "results": results,
    }


def ingest_all_command(
    sources_file: str,
    run_id: Optional[str],
    max_docs_per_source: Optional[int] = None,
    disable_embeddings: bool = False,
) -> int:
    source_ids = _load_source_ids(sources_file)
    results: list[dict] = []
    start = time.time()

    for source_id in source_ids:
        t0 = time.time()
        try:
            result = _run_sync(
                source_id=source_id,
                run_id=run_id,
                max_docs_per_source=max_docs_per_source,
                disable_embeddings=disable_embeddings,
            )
            result["elapsed_wall_seconds"] = round(time.time() - t0, 3)
            results.append(result)
        except Exception as exc:  # noqa: BLE001 - CLI should keep running all sources
            classification = _classify_runtime_error(str(exc), None)
            results.append(
                {
                    "source_id": source_id,
                    "status": "failed",
                    "errors": [{"error": str(exc), "classification": classification}],
                    "error_summary": {classification: 1},
                    "source_unreachable": classification == "source_unreachable_external",
                    "elapsed_wall_seconds": round(time.time() - t0, 3),
                }
            )

    summary = _build_ingest_all_summary(results, total_elapsed_seconds=time.time() - start)
    print(json.dumps(summary, default=str, indent=2))
    return 0


def _source_priority(source_id: str, source_cfg: dict) -> str:
    """Derive ingestion lane from source config.

    Prioritization policy (Stage 1):
    - bulk: explicitly heavy sources (e.g. tcu_acordaos)
    - high: static_url sources (fast/small datasets)
    - normal: all other sources
    """
    if source_id == "tcu_acordaos":
        return "bulk"
    mode = str((source_cfg.get("discovery", {}) or {}).get("mode", "")).lower()
    if mode == "static_url":
        return "high"
    return "normal"


def _queue_for_priority(priority: str) -> str:
    if priority == "high":
        return "gabi.sync.high"
    if priority == "bulk":
        return "gabi.sync.bulk"
    return "gabi.sync.normal"


def ingest_schedule_command(
    sources_file: str,
    run_id: Optional[str],
    max_docs_per_source: Optional[int] = None,
    disable_embeddings: bool = False,
    source: Optional[str] = None,
) -> int:
    with Path(sources_file).open("r", encoding="utf-8") as stream:
        payload = yaml.safe_load(stream) or {}
    sources: dict = payload.get("sources", {}) or {}

    if source:
        if source not in sources:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "error": f"Source '{source}' not found in {sources_file}",
                    },
                    indent=2,
                )
            )
            return 2
        selected_sources = {source: sources[source]}
    else:
        selected_sources = sources

    schedule_id = run_id or str(uuid.uuid4())
    scheduled: list[dict] = []
    started_at = time.time()

    priority_rank = {"high": 0, "normal": 1, "bulk": 2}
    ordered_sources = sorted(
        selected_sources.items(),
        key=lambda item: priority_rank.get(_source_priority(item[0], item[1]), 99),
    )

    for source_id, source_cfg in ordered_sources:
        priority = _source_priority(source_id, source_cfg)
        queue_name = _queue_for_priority(priority)
        result = sync_source_task.apply_async(
            kwargs={
                "source_id": source_id,
                "run_id": str(uuid.uuid4()),
                "max_documents_per_source_override": max_docs_per_source,
                "disable_embeddings": disable_embeddings,
            },
            queue=queue_name,
            retry=False,
        )
        scheduled.append(
            {
                "source_id": source_id,
                "priority": priority,
                "queue": queue_name,
                "celery_task_id": result.id,
            }
        )

    summary = {
        "status": "scheduled",
        "schedule_id": schedule_id,
        "total_scheduled": len(scheduled),
        "max_docs_per_source": max_docs_per_source,
        "disable_embeddings": disable_embeddings,
        "elapsed_seconds": round(time.time() - started_at, 3),
        "scheduled": scheduled,
    }
    print(json.dumps(summary, default=str, indent=2))
    return 0


def reset_stale_manifests_command(stale_minutes: int = 120) -> int:
    async def _reset() -> dict:
        await init_db()
        try:
            threshold = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
            async with get_session_no_commit() as session:
                stmt = (
                    update(ExecutionManifest)
                    .where(ExecutionManifest.completed_at.is_(None))
                    .where(
                        ExecutionManifest.status.in_(
                            [ExecutionStatus.PENDING.value, ExecutionStatus.RUNNING.value]
                        )
                    )
                    .where(ExecutionManifest.started_at < threshold)
                    .values(
                        status=ExecutionStatus.CANCELLED.value,
                        completed_at=datetime.now(timezone.utc),
                        error_message=f"stale_manifest_auto_reset_after_{stale_minutes}m",
                    )
                    .returning(
                        ExecutionManifest.run_id,
                        ExecutionManifest.source_id,
                        ExecutionManifest.status,
                        ExecutionManifest.started_at,
                    )
                )
                rows = (await session.execute(stmt)).all()
                await session.commit()
                return {
                    "status": "ok",
                    "stale_minutes": stale_minutes,
                    "reset_count": len(rows),
                    "reset_items": [
                        {
                            "run_id": str(row.run_id),
                            "source_id": row.source_id,
                            "started_at": row.started_at,
                            "new_status": row.status,
                        }
                        for row in rows
                    ],
                }
        finally:
            await close_db()

    print(json.dumps(asyncio.run(_reset()), default=str, indent=2))
    return 0


def reindex_command(source: str) -> int:
    result = _run_sync(source_id=source, run_id=None)
    print(json.dumps(result, default=str, indent=2))
    return 0


def status_command(source: Optional[str]) -> int:
    async def _status() -> dict:
        await init_db()
        try:
            async with get_session_no_commit() as session:
                source_stmt = select(SourceRegistry)
                if source:
                    source_stmt = source_stmt.where(SourceRegistry.id == source)
                source_rows = (await session.execute(source_stmt)).scalars().all()

                exec_stmt = (
                    select(ExecutionManifest)
                    .order_by(desc(ExecutionManifest.started_at))
                    .limit(20)
                )
                if source:
                    exec_stmt = exec_stmt.where(ExecutionManifest.source_id == source)
                execution_rows = (await session.execute(exec_stmt)).scalars().all()

                return {
                    "sources": [
                        {
                            "id": row.id,
                            "status": str(row.status),
                            "document_count": row.document_count,
                            "last_sync_at": row.last_sync_at,
                            "last_error_message": row.last_error_message,
                        }
                        for row in source_rows
                    ],
                    "executions": [
                        {
                            "run_id": str(row.run_id),
                            "source_id": row.source_id,
                            "status": str(row.status),
                            "started_at": row.started_at,
                            "completed_at": row.completed_at,
                            "error_message": row.error_message,
                        }
                        for row in execution_rows
                    ],
                }
        finally:
            await close_db()

    print(json.dumps(asyncio.run(_status()), default=str, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gabi", description="GABI command line interface")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="Run ingestion pipeline for a source")
    ingest.add_argument("--source", "-s", required=True, help="Source ID to ingest")
    ingest.add_argument("--run-id", default=None, help="Optional run UUID")
    ingest.add_argument(
        "--max-docs-per-source",
        type=int,
        default=None,
        help="Override max docs processed for this run",
    )
    ingest.add_argument(
        "--disable-embeddings",
        action="store_true",
        help="Skip embedding generation during ingestion",
    )

    ingest_all = subparsers.add_parser(
        "ingest-all",
        help="Run ingestion pipeline for all sources in sources.yaml",
    )
    ingest_all.add_argument(
        "--sources-file",
        default="sources.yaml",
        help="Path to sources YAML file",
    )
    ingest_all.add_argument("--run-id", default=None, help="Optional run UUID")
    ingest_all.add_argument(
        "--max-docs-per-source",
        type=int,
        default=None,
        help="Override max docs processed per source",
    )
    ingest_all.add_argument(
        "--disable-embeddings",
        action="store_true",
        help="Skip embedding generation during ingestion",
    )
    ingest_schedule = subparsers.add_parser(
        "ingest-schedule",
        help="Schedule ingestion tasks per source (queue-based, non-blocking)",
    )
    ingest_schedule.add_argument(
        "--sources-file",
        default="sources.yaml",
        help="Path to sources YAML file",
    )
    ingest_schedule.add_argument("--run-id", default=None, help="Optional schedule ID")
    ingest_schedule.add_argument(
        "--source",
        default=None,
        help="Optional single source ID to schedule",
    )
    ingest_schedule.add_argument(
        "--max-docs-per-source",
        type=int,
        default=None,
        help="Override max docs processed per source",
    )
    ingest_schedule.add_argument(
        "--disable-embeddings",
        action="store_true",
        help="Skip embedding generation during ingestion",
    )
    reset_stale_manifests = subparsers.add_parser(
        "reset-stale-manifests",
        help="Mark old pending/running execution manifests as cancelled",
    )
    reset_stale_manifests.add_argument(
        "--stale-minutes",
        type=int,
        default=120,
        help="Age threshold in minutes for stale manifests",
    )

    reindex = subparsers.add_parser("reindex", help="Trigger reindex for a source")
    reindex.add_argument("--source", "-s", required=True, help="Source ID to reindex")

    status = subparsers.add_parser("status", help="Show source and latest execution status")
    status.add_argument("--source", "-s", default=None, help="Optional source filter")

    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "ingest":
        raise SystemExit(
            ingest_command(
                args.source,
                args.run_id,
                max_docs_per_source=args.max_docs_per_source,
                disable_embeddings=args.disable_embeddings,
            )
        )
    if args.command == "ingest-all":
        raise SystemExit(
            ingest_all_command(
                args.sources_file,
                args.run_id,
                max_docs_per_source=args.max_docs_per_source,
                disable_embeddings=args.disable_embeddings,
            )
        )
    if args.command == "ingest-schedule":
        raise SystemExit(
            ingest_schedule_command(
                args.sources_file,
                args.run_id,
                max_docs_per_source=args.max_docs_per_source,
                disable_embeddings=args.disable_embeddings,
                source=args.source,
            )
        )
    if args.command == "reset-stale-manifests":
        raise SystemExit(reset_stale_manifests_command(args.stale_minutes))
    if args.command == "reindex":
        raise SystemExit(reindex_command(args.source))
    if args.command == "status":
        raise SystemExit(status_command(args.source))
    parser.print_help()
    raise SystemExit(1)


if __name__ == "__main__":
    main()
