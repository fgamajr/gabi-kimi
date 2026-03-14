"""Elasticsearch indexer for DOU documents (backfill, incremental sync, stats).

Reads from MongoDB, indexes into Elasticsearch with BM25.

Usage:
  python3 -m src.backend.ingest.es_indexer backfill
  python3 -m src.backend.ingest.es_indexer sync
  python3 -m src.backend.ingest.es_indexer stats
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any

import httpx
import pymongo
from bson import ObjectId


_MAPPING_PATH = Path(__file__).resolve().parent.parent / "search" / "es_index_v1.json"
_DEFAULT_CURSOR_PATH = Path(__file__).resolve().parent.parent / "data" / "es_sync_cursor.json"


def _log(msg: str) -> None:
    print(f"[es-indexer] {msg}", flush=True)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _mongo_client():
    uri = os.getenv("MONGO_STRING", "mongodb://localhost:27017/gabi_dou")
    db_name = os.getenv("DB_NAME", "gabi_dou")
    client = pymongo.MongoClient(uri)
    return client, client[db_name]


def _load_cursor(path: Path) -> dict[str, str]:
    if not path.exists():
        return {"_id": "000000000000000000000000"}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return {"_id": str(data.get("_id", "000000000000000000000000"))}


def _save_cursor(path: Path, last_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_id": last_id,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=True, indent=2)


def _mongo_to_es(doc: dict[str, Any]) -> dict[str, Any]:
    """Map a MongoDB document to the ES index schema."""
    structured = doc.get("structured") or {}
    pub_date = doc.get("pub_date")
    if isinstance(pub_date, datetime):
        pub_date_str = pub_date.strftime("%Y-%m-%d")
    elif pub_date:
        pub_date_str = str(pub_date)[:10]
    else:
        pub_date_str = None

    page = doc.get("page")
    edition = doc.get("edition")

    return {
        "doc_id": str(doc["_id"]),
        "identifica": doc.get("identifica"),
        "ementa": doc.get("ementa"),
        "body_plain": doc.get("texto"),
        "art_type": doc.get("art_type"),
        "art_category": doc.get("art_category"),
        "issuing_organ": doc.get("orgao"),
        "edition_section": doc.get("section"),
        "pub_date": pub_date_str,
        "document_number": structured.get("act_number"),
        "document_year": structured.get("act_year"),
        "page_number": str(page) if page is not None else None,
        "edition_number": str(edition) if edition is not None else None,
        "source_zip": doc.get("source_zip"),
    }


class ESClient:
    def __init__(self) -> None:
        self.url = os.getenv("ES_URL", "http://localhost:9200").rstrip("/")
        self.index = os.getenv("ES_INDEX", "gabi_documents")
        self.alias = (os.getenv("ES_ALIAS") or "").strip() or None
        self.verify_tls = _env_bool("ES_VERIFY_TLS", True)
        self.timeout_sec = int(os.getenv("ES_TIMEOUT_SEC", "30"))
        user = (os.getenv("ES_USERNAME") or "").strip()
        pwd = (os.getenv("ES_PASSWORD") or "").strip()
        self.auth = (user, pwd) if user else None
        self.client = httpx.Client(timeout=self.timeout_sec, verify=self.verify_tls, auth=self.auth)

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self.client.request(method=method, url=f"{self.url}{path}", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("Invalid Elasticsearch response")
        return data

    def ensure_index(self, recreate: bool = False) -> None:
        with _MAPPING_PATH.open("r", encoding="utf-8") as f:
            mapping = json.load(f)

        if recreate:
            self.client.request(method="DELETE", url=f"{self.url}/{self.index}")

        exists_resp = self.client.request(method="HEAD", url=f"{self.url}/{self.index}")
        if exists_resp.status_code == 404:
            _log(f"creating index {self.index}")
            self.request("PUT", f"/{self.index}", mapping)
        elif exists_resp.status_code >= 400:
            exists_resp.raise_for_status()

        if self.alias:
            self.request(
                "POST",
                "/_aliases",
                {"actions": [{"add": {"index": self.index, "alias": self.alias}}]},
            )

    def bulk(self, docs: list[dict[str, Any]], retries: int = 3) -> tuple[int, int]:
        lines: list[str] = []
        for doc in docs:
            doc_id = doc["doc_id"]
            lines.append(json.dumps({"index": {"_index": self.index, "_id": doc_id}}, ensure_ascii=False))
            lines.append(json.dumps(doc, ensure_ascii=False))
        body = "\n".join(lines) + "\n"

        last_error: str | None = None
        for attempt in range(1, retries + 1):
            resp = self.client.post(
                f"{self.url}/_bulk",
                data=body.encode("utf-8"),
                headers={"Content-Type": "application/x-ndjson"},
            )
            if resp.status_code in (429, 502, 503, 504):
                last_error = f"http {resp.status_code}"
                time.sleep(1.5 * attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise RuntimeError("Invalid bulk response")
            items = data.get("items", [])
            ok = 0
            failed = 0
            first_error: str | None = None
            for item in items:
                row = item.get("index", {})
                status = int(row.get("status", 500))
                if 200 <= status < 300:
                    ok += 1
                else:
                    failed += 1
                    if first_error is None:
                        err = row.get("error")
                        first_error = json.dumps(err, ensure_ascii=True) if err else f"status={status}"
            if failed:
                raise RuntimeError(f"bulk indexing failed: failed={failed} ok={ok} first_error={first_error}")
            return ok, failed
        raise RuntimeError(f"bulk failed after retries: {last_error}")


def _fetch_batch(collection, cursor_id: str, batch_size: int) -> list[dict[str, Any]]:
    """Fetch a batch of documents from MongoDB using cursor pagination."""
    query = {"_id": {"$gt": cursor_id}}
    cursor = collection.find(query).sort("_id", 1).limit(batch_size)
    return list(cursor)


def _counts(collection, es: ESClient) -> tuple[int, int]:
    mongo_count = collection.count_documents({})
    es_count = int(es.request("GET", f"/{es.index}/_count").get("count", 0))
    return mongo_count, es_count


def _run_sync(*, reset_cursor: bool, recreate_index: bool, batch_size: int, cursor_path: Path) -> None:
    es = ESClient()
    es.ensure_index(recreate=recreate_index)

    if reset_cursor:
        cursor = {"_id": "000000000000000000000000"}
    else:
        cursor = _load_cursor(cursor_path)
    _log(f"starting from cursor _id={cursor['_id']}")

    client, db = _mongo_client()
    collection = db["documents"]
    total_ok = 0
    total_failed = 0
    loops = 0
    try:
        while True:
            loops += 1
            rows = _fetch_batch(collection, cursor["_id"], batch_size)
            if not rows:
                break
            es_docs = [_mongo_to_es(row) for row in rows]
            ok, failed = es.bulk(es_docs)
            total_ok += ok
            total_failed += failed

            last = rows[-1]
            cursor["_id"] = str(last["_id"])
            _save_cursor(cursor_path, cursor["_id"])

            _log(
                f"batch={loops} fetched={len(rows)} indexed_ok={ok} failed={failed} "
                f"cursor={cursor['_id']}"
            )
    finally:
        client.close()

    client, db = _mongo_client()
    collection = db["documents"]
    try:
        mongo_count, es_count = _counts(collection, es)
    finally:
        client.close()

    _log(f"done indexed_ok={total_ok} failed={total_failed} mongo_count={mongo_count} es_count={es_count}")


def cmd_backfill(args: argparse.Namespace) -> None:
    _run_sync(
        reset_cursor=True,
        recreate_index=args.recreate_index,
        batch_size=args.batch_size,
        cursor_path=Path(args.cursor),
    )


def cmd_sync(args: argparse.Namespace) -> None:
    _run_sync(
        reset_cursor=False,
        recreate_index=False,
        batch_size=args.batch_size,
        cursor_path=Path(args.cursor),
    )


def cmd_stats(args: argparse.Namespace) -> None:
    cursor_path = Path(args.cursor)
    es = ESClient()
    client, db = _mongo_client()
    collection = db["documents"]
    try:
        mongo_count, es_count = _counts(collection, es)
    finally:
        client.close()

    health = es.request("GET", "/_cluster/health")
    idx_stats = es.request("GET", f"/{es.index}/_stats/docs,store")
    cursor = _load_cursor(cursor_path)

    print(
        json.dumps(
            {
                "backend": "es",
                "index": es.index,
                "cluster_status": health.get("status"),
                "mongo_count": mongo_count,
                "es_count": es_count,
                "count_delta": mongo_count - es_count,
                "cursor": cursor,
                "index_stats": idx_stats.get("indices", {}).get(es.index, {}),
            },
            ensure_ascii=True,
            indent=2,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Elasticsearch indexer for GABI DOU (MongoDB → ES)")
    p.add_argument("--cursor", default=str(_DEFAULT_CURSOR_PATH), help="Cursor state file path")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("backfill", help="Full backfill from MongoDB")
    sp.add_argument("--batch-size", type=int, default=2000)
    sp.add_argument("--recreate-index", action="store_true")
    sp.set_defaults(func=cmd_backfill)

    sp = sub.add_parser("sync", help="Incremental sync from cursor high-water mark")
    sp.add_argument("--batch-size", type=int, default=2000)
    sp.set_defaults(func=cmd_sync)

    sp = sub.add_parser("stats", help="Parity and index statistics")
    sp.set_defaults(func=cmd_stats)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
