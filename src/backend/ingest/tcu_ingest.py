"""TCU Acórdão ingest pipeline — download CSV, process, store Mongo + ES.

Usage:
  python -m src.backend.ingest.tcu_ingest --year 2026
  python -m src.backend.ingest.tcu_ingest --year 2020 --year 2021
  python -m src.backend.ingest.tcu_ingest --range 1992 2026
  python -m src.backend.ingest.tcu_ingest --range 1992 2026 --recreate-index --yes-destroy
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pymongo

from src.backend.ingest.tcu_processor import csv_row_to_es_doc, iter_csv_rows

_CSV_URL_TEMPLATE = (
    "https://sites.tcu.gov.br/dados-abertos/jurisprudencia"
    "/arquivos/acordao-completo/acordao-completo-{year}.csv"
)

_TCU_INDEX_NAME = "gabi_tcu_acordaos_v1"
_TCU_MAPPING_PATH = (
    Path(__file__).resolve().parent.parent / "search" / "es_tcu_mapping.json"
)
_MONGO_COLLECTION = "tcu_acordaos"


def _log(msg: str) -> None:
    print(f"[tcu-ingest] {msg}", flush=True)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class ESClient:
    def __init__(self) -> None:
        self.url = os.getenv("ES_URL", "http://elasticsearch:9200").rstrip("/")
        self.index = os.getenv("TCU_ES_INDEX", _TCU_INDEX_NAME)
        verify_tls = _env_bool("ES_VERIFY_TLS", True)
        timeout_sec = int(os.getenv("ES_TIMEOUT_SEC", "60"))
        user = (os.getenv("ES_USERNAME") or "").strip()
        pwd = (os.getenv("ES_PASSWORD") or "").strip()
        auth = (user, pwd) if user else None
        self.client = httpx.Client(timeout=timeout_sec, verify=verify_tls, auth=auth)

    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        resp = self.client.request(method=method, url=f"{self.url}{path}", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("Invalid ES response")
        return data

    def ensure_index(self, recreate: bool = False) -> None:
        if recreate:
            try:
                self.client.request(method="DELETE", url=f"{self.url}/{self.index}")
                _log(f"deleted index {self.index}")
            except httpx.HTTPStatusError:
                pass

        exists = self.client.request(method="HEAD", url=f"{self.url}/{self.index}")
        if exists.status_code == 404:
            with _TCU_MAPPING_PATH.open("r", encoding="utf-8") as f:
                mapping = json.load(f)
            _log(f"creating index {self.index}")
            self.request("PUT", f"/{self.index}", mapping)

        self.request(
            "GET",
            f"/_cluster/health/{self.index}?wait_for_status=yellow&timeout=120s",
        )

    def bulk(self, docs: list[dict], retries: int = 3) -> tuple[int, int]:
        lines: list[str] = []
        for doc in docs:
            doc_id = doc.get("doc_id")
            if not doc_id:
                raise RuntimeError("Document missing doc_id")
            lines.append(
                json.dumps(
                    {"index": {"_index": self.index, "_id": doc_id}}, ensure_ascii=False
                )
            )
            lines.append(json.dumps(doc, ensure_ascii=False))
        body = "\n".join(lines) + "\n"

        for attempt in range(1, retries + 1):
            try:
                resp = self.client.post(
                    f"{self.url}/_bulk",
                    data=body.encode("utf-8"),
                    headers={"Content-Type": "application/x-ndjson"},
                )
            except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.ConnectTimeout) as exc:
                if attempt < retries:
                    time.sleep(2 * attempt)
                    continue
                raise RuntimeError(f"bulk timed out: {exc}") from exc

            if resp.status_code in (429, 502, 503, 504):
                time.sleep(2 * attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            ok = sum(
                1 for i in items if 200 <= i.get("index", {}).get("status", 500) < 300
            )
            failed = len(items) - ok
            if failed > 0:
                first_err = next(
                    (
                        i.get("index", {}).get("error")
                        for i in items
                        if i.get("index", {}).get("status", 500) >= 300
                    ),
                    None,
                )
                _log(f"bulk: ok={ok} failed={failed} first_error={first_err}")
            return ok, failed
        raise RuntimeError("bulk failed after retries")

    def refresh(self) -> None:
        self.request("POST", f"/{self.index}/_refresh")

    def count(self) -> int:
        return int(self.request("GET", f"/{self.index}/_count").get("count", 0))


def _mongo_client():
    uri = os.getenv("MONGO_STRING", "mongodb://mongo:27017/gabi_dou")
    db_name = os.getenv("DB_NAME", "gabi_dou")
    client = pymongo.MongoClient(uri)
    return client, client[db_name]


def download_csv(year: int, target_dir: str) -> str:
    """Download TCU CSV for a given year. Returns local file path."""
    url = _CSV_URL_TEMPLATE.format(year=year)
    filename = f"acordao-completo-{year}.csv"
    filepath = os.path.join(target_dir, filename)

    if os.path.exists(filepath):
        size = os.path.getsize(filepath)
        if size > 1000:
            _log(f"using cached {filepath} ({size:,} bytes)")
            return filepath

    _log(f"downloading {url}")
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(resp.content)
    _log(f"downloaded {filepath} ({len(resp.content):,} bytes)")
    return filepath


def ingest_year(
    year: int,
    *,
    es: ESClient,
    mongo_collection,
    dlq_collection,
    batch_size: int = 500,
    cache_dir: str | None = None,
    skip_mongo: bool = False,
) -> dict[str, int]:
    """Ingest a single year's CSV into Mongo + ES."""
    stats = {"total": 0, "indexed": 0, "failed": 0, "skipped": 0, "mongo_upserted": 0}

    # Download
    dl_dir = cache_dir or tempfile.mkdtemp(prefix="tcu_csv_")
    try:
        filepath = download_csv(year, dl_dir)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            _log(f"CSV not found for year {year} (404)")
            return stats
        raise

    csv_filename = os.path.basename(filepath)
    es_batch: list[dict[str, Any]] = []

    for row in iter_csv_rows(filepath):
        stats["total"] += 1

        try:
            es_doc = csv_row_to_es_doc(row, csv_filename)
        except Exception as exc:
            stats["skipped"] += 1
            doc_key = row.get("KEY", "unknown")
            _log(f"DLQ: {doc_key} conversion failed: {exc}")
            try:
                dlq_collection.update_one(
                    {"_id": doc_key},
                    {
                        "$set": {
                            "error": str(exc),
                            "traceback": traceback.format_exc(),
                            "failed_at": datetime.now(timezone.utc),
                            "year": year,
                        }
                    },
                    upsert=True,
                )
            except Exception:
                pass
            continue

        # Mongo upsert
        if not skip_mongo:
            try:
                mongo_collection.update_one(
                    {"_id": es_doc["doc_id"]},
                    {"$set": {**es_doc, "updated_at": datetime.now(timezone.utc)}},
                    upsert=True,
                )
                stats["mongo_upserted"] += 1
            except Exception as exc:
                _log(f"Mongo upsert failed for {es_doc['doc_id']}: {exc}")

        es_batch.append(es_doc)

        if len(es_batch) >= batch_size:
            ok, failed = es.bulk(es_batch)
            stats["indexed"] += ok
            stats["failed"] += failed
            _log(
                f"year={year} processed={stats['total']} indexed={stats['indexed']} "
                f"failed={stats['failed']} skipped={stats['skipped']}"
            )
            es_batch = []

    # Flush remaining
    if es_batch:
        ok, failed = es.bulk(es_batch)
        stats["indexed"] += ok
        stats["failed"] += failed

    _log(
        f"year={year} DONE total={stats['total']} indexed={stats['indexed']} "
        f"failed={stats['failed']} skipped={stats['skipped']} mongo={stats['mongo_upserted']}"
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest TCU Acórdãos from CSV open data"
    )
    parser.add_argument("--year", type=int, action="append", help="Year(s) to ingest")
    parser.add_argument(
        "--range",
        nargs=2,
        type=int,
        metavar=("FROM", "TO"),
        help="Year range (inclusive)",
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--cache-dir", type=str, default=None, help="Directory to cache downloaded CSVs"
    )
    parser.add_argument("--recreate-index", action="store_true")
    parser.add_argument("--yes-destroy", action="store_true")
    parser.add_argument(
        "--skip-mongo", action="store_true", help="Skip MongoDB upsert (ES only)"
    )
    args = parser.parse_args()

    if args.recreate_index and not args.yes_destroy:
        _log("ERROR: --recreate-index requires --yes-destroy")
        sys.exit(1)

    years: list[int] = []
    if args.range:
        years = list(range(args.range[0], args.range[1] + 1))
    elif args.year:
        years = args.year
    else:
        _log("ERROR: specify --year or --range")
        sys.exit(1)

    _log(f"ingesting years: {years}")

    es = ESClient()
    es.ensure_index(recreate=args.recreate_index)

    client = None
    collection = None
    dlq = None
    if not args.skip_mongo:
        client, db = _mongo_client()
        collection = db[_MONGO_COLLECTION]
        dlq = db["dlq_tcu_ingest"]
        collection.create_index([("updated_at", 1), ("_id", 1)])
        collection.create_index("ano_acordao")

    cache_dir = args.cache_dir
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)

    totals = {"total": 0, "indexed": 0, "failed": 0, "skipped": 0, "mongo_upserted": 0}
    t0 = time.time()

    try:
        for year in sorted(years):
            year_stats = ingest_year(
                year,
                es=es,
                mongo_collection=collection,
                dlq_collection=dlq,
                batch_size=args.batch_size,
                cache_dir=cache_dir,
                skip_mongo=args.skip_mongo,
            )
            for k in totals:
                totals[k] += year_stats.get(k, 0)
    finally:
        if client is not None:
            client.close()

    es.refresh()
    elapsed = time.time() - t0
    es_count = es.count()

    _log(
        f"ALL DONE in {elapsed:.0f}s — total={totals['total']} indexed={totals['indexed']} "
        f"failed={totals['failed']} skipped={totals['skipped']} mongo={totals['mongo_upserted']} "
        f"es_count={es_count}"
    )


if __name__ == "__main__":
    main()
