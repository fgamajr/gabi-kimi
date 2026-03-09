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
from typing import Any

import httpx

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
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{es_url}/gabi_documents_v1/_search",
            json=query,
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()

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
        Stats dict with total, ingested, discovered counts.
    """
    with open(catalog_path) as f:
        catalog = json.load(f)

    files = catalog.get("files", [])
    if not files:
        return {"total": 0, "ingested": 0, "discovered": 0}

    # Get ES coverage
    coverage = await _get_es_coverage(es_url)

    # Classify files
    ingested_files: list[dict[str, Any]] = []
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
            record["status"] = FileStatus.INGESTED.value
            ingested_files.append(record)
        else:
            record["status"] = FileStatus.DISCOVERED.value
            discovered_files.append(record)

    # Bulk insert (INSERT OR IGNORE for idempotency)
    all_files = ingested_files + discovered_files
    await registry.bulk_insert_with_status(all_files)

    stats = {
        "total": len(files),
        "ingested": len(ingested_files),
        "discovered": len(discovered_files),
    }
    logger.info(
        "Migration complete: %d total, %d ingested, %d discovered",
        stats["total"], stats["ingested"], stats["discovered"],
    )
    return stats


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
