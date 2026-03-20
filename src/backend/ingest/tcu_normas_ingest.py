"""Ingest TCU Normas (Portarias, Resoluções, INs) into gabi_tcu_normas_v1.

Usage:
  python -m src.backend.ingest.tcu_normas_ingest --ingest
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pymongo

from src.backend.ingest.tcu_normas_processor import NORMA_URL, iter_csv_rows, norma_to_es_doc

_NORMAS_INDEX = "gabi_tcu_normas_v1"
_NORMAS_MAPPING_PATH = Path(__file__).resolve().parent.parent / "search" / "es_tcu_normas_mapping.json"
_MONGO_COLLECTION = "tcu_normas"


def _log(msg: str) -> None:
    print(f"[tcu-normas] {msg}", flush=True)


def _es_url() -> str:
    return os.getenv("ES_URL", "http://elasticsearch:9200").rstrip("/")


def _mongo_client():
    uri = os.getenv("MONGO_STRING", "mongodb://mongo:27017/gabi_dou")
    db_name = os.getenv("DB_NAME", "gabi_dou")
    client = pymongo.MongoClient(uri)
    return client, client[db_name]


def _ensure_index(es_client: httpx.Client) -> None:
    """Create normas index if it doesn't exist."""
    index = os.getenv("TCU_NORMAS_INDEX", _NORMAS_INDEX)
    url = _es_url()
    resp = es_client.head(f"{url}/{index}")
    if resp.status_code == 404:
        with _NORMAS_MAPPING_PATH.open("r", encoding="utf-8") as f:
            mapping = json.load(f)
        _log(f"creating index {index}")
        resp = es_client.put(f"{url}/{index}", json=mapping)
        resp.raise_for_status()
    es_client.get(f"{url}/_cluster/health/{index}?wait_for_status=yellow&timeout=60s")


def _download_csv(url: str, cache_dir: str) -> str:
    filename = url.split("/")[-1]
    filepath = os.path.join(cache_dir, filename)
    _log(f"downloading {url}")
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(resp.content)
    _log(f"downloaded {filepath} ({len(resp.content):,} bytes)")
    return filepath


def _es_bulk(docs: list[dict], es_client: httpx.Client) -> tuple[int, int]:
    index = os.getenv("TCU_NORMAS_INDEX", _NORMAS_INDEX)
    lines: list[str] = []
    for doc in docs:
        doc_id = doc.get("doc_id")
        lines.append(json.dumps({"index": {"_index": index, "_id": doc_id}}, ensure_ascii=False))
        lines.append(json.dumps(doc, ensure_ascii=False))
    body = "\n".join(lines) + "\n"
    resp = es_client.post(
        f"{_es_url()}/_bulk",
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/x-ndjson"},
        timeout=60,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    ok = sum(1 for i in items if 200 <= i.get("index", {}).get("status", 500) < 300)
    return ok, len(items) - ok


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest TCU Normas")
    parser.add_argument("--ingest", action="store_true")
    parser.add_argument("--cache-dir", default=None)
    args = parser.parse_args()

    if not args.ingest:
        _log("ERROR: specify --ingest")
        sys.exit(1)

    cache_dir = args.cache_dir or tempfile.mkdtemp(prefix="tcu_normas_")
    os.makedirs(cache_dir, exist_ok=True)

    es_client = httpx.Client(timeout=60)
    _ensure_index(es_client)

    mongo_client, db = _mongo_client()
    collection = db[_MONGO_COLLECTION]

    filepath = _download_csv(NORMA_URL, cache_dir)
    csv_filename = os.path.basename(filepath)

    t0 = time.time()
    stats = {"total": 0, "indexed": 0, "failed": 0, "skipped": 0}
    batch: list[dict] = []

    for row in iter_csv_rows(filepath):
        stats["total"] += 1
        try:
            doc = norma_to_es_doc(row, csv_filename)
        except Exception as exc:
            stats["skipped"] += 1
            _log(f"skip: {row.get('KEY', '?')}: {exc}")
            continue

        try:
            collection.update_one(
                {"_id": doc["doc_id"]},
                {"$set": {**doc, "updated_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
        except Exception as exc:
            _log(f"mongo error: {doc['doc_id']}: {exc}")

        batch.append(doc)
        if len(batch) >= 500:
            ok, failed = _es_bulk(batch, es_client)
            stats["indexed"] += ok
            stats["failed"] += failed
            _log(f"progress: {stats['total']} processed, {stats['indexed']} indexed")
            batch = []

    if batch:
        ok, failed = _es_bulk(batch, es_client)
        stats["indexed"] += ok
        stats["failed"] += failed

    es_client.close()
    mongo_client.close()

    elapsed = time.time() - t0
    _log(f"DONE in {elapsed:.0f}s — total={stats['total']} indexed={stats['indexed']} failed={stats['failed']} skipped={stats['skipped']}")


if __name__ == "__main__":
    main()
