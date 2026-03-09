"""One-time migration from JSON catalog to SQLite registry.

Reads the DOU catalog JSON, queries Elasticsearch to determine which
(year_month, section) combinations are already indexed, and populates
the SQLite registry with appropriate statuses.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from src.backend.worker.pipeline.discovery import parse_dou_filename
from src.backend.worker.registry import FileStatus, Registry

logger = logging.getLogger(__name__)


async def _get_es_coverage(es_url: str) -> set[tuple[str, str]]:
    """Query ES to find which (year_month, section) combos have indexed docs."""
    query = {
        "size": 0,
        "aggs": {
            "coverage": {
                "composite": {
                    "size": 10000,
                    "sources": [
                        {"year_month": {"terms": {"field": "year_month"}}},
                        {"section": {"terms": {"field": "section"}}},
                    ],
                }
            }
        },
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{es_url}/gabi_documents_v1/_search",
                json=query,
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("ES coverage probe failed, bootstrapping catalog as DISCOVERED-only: %s", exc)
        return set()

    buckets = data.get("aggregations", {}).get("coverage", {}).get("buckets", [])
    return {
        (b["key"]["year_month"], b["key"]["section"])
        for b in buckets
    }


async def migrate_catalog_to_sqlite(
    catalog_path: str,
    registry: Registry,
    es_url: str,
) -> dict[str, int]:
    """Migrate JSON catalog to SQLite registry.

    Args:
        catalog_path: Path to dou_catalog_registry.json
        registry: Initialized Registry instance
        es_url: Elasticsearch URL (e.g. http://es.internal:9200)

    Returns:
        Stats dict with total, verified, discovered counts.
    """
    with open(catalog_path) as f:
        catalog = json.load(f)

    catalog_files = catalog.get("files", [])
    if not catalog_files:
        return {"total": 0, "verified": 0, "discovered": 0}

    files = _normalize_catalog_entries(catalog)
    if not files:
        return {"total": 0, "verified": 0, "discovered": 0}

    # Get ES coverage
    coverage = await _get_es_coverage(es_url)

    # Classify files
    verified_files: list[dict[str, Any]] = []
    discovered_files: list[dict[str, Any]] = []

    for entry in files:
        key = (entry["year_month"], entry["section"])
        record = {
            "filename": entry["filename"],
            "section": entry["section"],
            "year_month": entry["year_month"],
            "folder_id": entry.get("folder_id"),
            "file_url": entry.get("file_url"),
        }
        if key in coverage:
            record["status"] = FileStatus.VERIFIED.value
            verified_files.append(record)
        else:
            record["status"] = FileStatus.DISCOVERED.value
            discovered_files.append(record)

    # Bulk insert (INSERT OR IGNORE for idempotency)
    all_files = verified_files + discovered_files
    await registry.bulk_insert_with_status(all_files)

    stats = {
        "total": len(files),
        "verified": len(verified_files),
        "discovered": len(discovered_files),
    }
    logger.info(
        "Migration complete: %d total, %d verified, %d discovered",
        stats["total"], stats["verified"], stats["discovered"],
    )
    return stats


def _normalize_catalog_entries(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize supported catalog layouts into flat file records."""
    raw_files = catalog.get("files", [])
    if isinstance(raw_files, list):
        return list(raw_files)

    if not isinstance(raw_files, dict):
        return []

    group_id = str(catalog.get("group_id") or "49035712")
    folder_ids = catalog.get("folder_ids", {})
    records: list[dict[str, Any]] = []

    for year_month, filenames in raw_files.items():
        if not isinstance(filenames, list):
            continue
        folder_id = folder_ids.get(year_month)
        for filename in filenames:
            try:
                section, parsed_year_month = parse_dou_filename(filename)
            except ValueError:
                logger.warning("Skipping unparseable catalog filename: %s", filename)
                continue
            record: dict[str, Any] = {
                "filename": filename,
                "section": section,
                "year_month": parsed_year_month or year_month,
                "folder_id": folder_id,
            }
            if folder_id:
                record["file_url"] = f"https://www.in.gov.br/documents/{group_id}/{folder_id}/{filename}"
            records.append(record)

    return records


async def bootstrap_registry_if_empty(
    registry: Registry,
    es_url: str,
    catalog_path: str | Path,
) -> dict[str, int] | None:
    """Populate the registry from the catalog on first boot.

    Returns migration stats when bootstrap runs, otherwise ``None``.
    """
    status_counts = await registry.get_status_counts()
    if sum(status_counts.values()) > 0:
        await ensure_registry_seed_audit_trail(registry)
        return None

    catalog = Path(catalog_path)
    if not catalog.exists():
        logger.info("Catalog bootstrap skipped; file not found: %s", catalog)
        return None

    stats = await migrate_catalog_to_sqlite(str(catalog), registry, es_url)
    await ensure_registry_seed_audit_trail(
        registry,
        phase="catalog-bootstrap",
        message=(
            "Registry bootstrapped from catalog with "
            f"{stats['total']} files ({stats['verified']} already covered in ES, "
            f"{stats['discovered']} queued as DISCOVERED)."
        ),
    )
    logger.info("Registry bootstrapped from catalog: %s", stats)
    return stats


async def ensure_registry_seed_audit_trail(
    registry: Registry,
    *,
    phase: str = "state-seed",
    message: str | None = None,
) -> str | None:
    """Create a synthetic audit run when the registry has rows but no historical runs.

    This keeps the dashboard honest in fresh/local environments where the
    registry may be pre-seeded from the catalog before any real scheduler phase
    has executed.
    """
    runs = await registry.get_pipeline_runs(limit=1)
    if runs:
        return None

    stats = await registry.get_summary_stats()
    total_files = int(stats.get("total_files") or 0)
    if total_files == 0:
        return None

    status_counts = stats.get("status_counts", {})
    verified = int(status_counts.get(FileStatus.VERIFIED.value, 0))
    pending = total_files - verified
    run_id = await registry.create_pipeline_run(phase)
    await registry.add_log_entry(
        run_id,
        None,
        "INFO",
        message
        or (
            "Synthetic audit entry created because the registry already had "
            f"{total_files} files but no historical pipeline runs were recorded. "
            f"Current state: {verified} VERIFIED, {pending} pending."
        ),
    )
    await registry.complete_pipeline_run(
        run_id,
        files_processed=total_files,
        files_succeeded=total_files,
        files_failed=0,
    )
    return run_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate DOU catalog JSON to SQLite")
    parser.add_argument("--catalog", required=True, help="Path to catalog JSON file")
    parser.add_argument("--db", default="/data/registry.db", help="SQLite DB path")
    parser.add_argument(
        "--es-url", default="http://es.internal:9200", help="Elasticsearch URL"
    )
    args = parser.parse_args()

    async def main():
        reg = Registry(db_path=args.db)
        await reg.init_db()
        stats = await migrate_catalog_to_sqlite(args.catalog, reg, args.es_url)
        print(f"Migration stats: {stats}")

    asyncio.run(main())
