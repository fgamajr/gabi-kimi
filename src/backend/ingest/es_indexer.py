"""Elasticsearch indexer for DOU documents (backfill, incremental sync, stats, verify).

Reads from MongoDB, indexes into Elasticsearch with BM25.

Usage:
  python3 -m src.backend.ingest.es_indexer backfill
  python3 -m src.backend.ingest.es_indexer sync
  python3 -m src.backend.ingest.es_indexer stats
  python3 -m src.backend.ingest.es_indexer verify
"""

from __future__ import annotations

import argparse
import fcntl
from datetime import datetime, timezone
import functools
import json
import os
from pathlib import Path
import sys
import time
import traceback
from typing import Any

import httpx
import pymongo

from src.backend.ingest.es_v2_minimal import mongo_to_es_v2_minimal
from src.backend.ingest.es_v2_search import mongo_to_es_v2_search

_SEARCH_DIR = Path(__file__).resolve().parent.parent / "search"
_DEFAULT_CURSOR_PATH = Path(
    os.getenv(
        "ES_SYNC_CURSOR_PATH",
        str(Path(__file__).resolve().parent.parent / "data" / "es_sync_cursor.json"),
    )
)
_SCHEMA_TO_MAPPING = {
    "v1": _SEARCH_DIR / "es_index_v1.json",
    "v2_minimal": _SEARCH_DIR / "es_index_min_v2.json",
    "v2_search": _SEARCH_DIR / "es_index_v2_search.json",
}
_SCHEMA_TO_INDEX = {
    "v1": "gabi_documents_v1",
    "v2_minimal": "gabi_documents_v2_minimal",
    "v2_search": "gabi_documents_v2_search",
}
_DEFAULT_CURSOR = {
    "updated_at": datetime(1970, 1, 1, tzinfo=timezone.utc).isoformat(timespec="microseconds"),
    "_id": "",
}
_LOCK_PATH = Path(
    os.getenv("ES_SYNC_LOCK_PATH", "/tmp/es_indexer_sync.lock")
)


def _log(msg: str) -> None:
    print(f"[es-indexer] {msg}", flush=True)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@functools.lru_cache(maxsize=1)
def _schema_name() -> str:
    raw = (os.getenv("ES_DOC_SCHEMA") or "v1").strip().lower()
    if raw not in _SCHEMA_TO_MAPPING:
        raise RuntimeError(f"Unsupported ES_DOC_SCHEMA={raw}")
    return raw


def _mapping_path() -> Path:
    override = (os.getenv("ES_MAPPING_PATH") or "").strip()
    if override:
        return Path(override)
    return _SCHEMA_TO_MAPPING[_schema_name()]


def _mongo_client():
    uri = os.getenv("MONGO_STRING", "mongodb://mongo:27017/gabi_dou")
    db_name = os.getenv("DB_NAME", "gabi_dou")
    client = pymongo.MongoClient(uri)
    return client, client[db_name]


def _mongo_collection_name() -> str:
    return os.getenv("MONGO_COLLECTION", "documents")


def _load_cursor(path: Path) -> dict[str, str]:
    if not path.exists():
        return dict(_DEFAULT_CURSOR)
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    updated_at = str(data.get("updated_at") or _DEFAULT_CURSOR["updated_at"])
    doc_id = str(data.get("_id") or _DEFAULT_CURSOR["_id"])
    return {"updated_at": updated_at, "_id": doc_id}


def _parse_cursor_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _save_cursor(path: Path, last_updated_at: datetime, last_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": last_updated_at.astimezone(timezone.utc).isoformat(timespec="microseconds"),
        "_id": last_id,
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=True, indent=2)


def _mongo_to_es(doc: dict[str, Any], schema: str) -> dict[str, Any]:
    """Map a MongoDB document to the ES index schema."""
    if schema == "v2_minimal":
        return mongo_to_es_v2_minimal(doc)
    if schema == "v2_search":
        return mongo_to_es_v2_search(doc)

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


# ---------------------------------------------------------------------------
# DLQ + safe batch conversion (Fix 2)
# ---------------------------------------------------------------------------


def _convert_batch_safe(
    rows: list[dict[str, Any]],
    dlq_collection,
    schema: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Convert a batch of Mongo docs to ES docs, quarantining failures to DLQ.

    Returns (es_docs, valid_rows, skip_count).
    """
    es_docs: list[dict[str, Any]] = []
    valid_rows: list[dict[str, Any]] = []
    skip_count = 0

    for row in rows:
        try:
            es_doc = _mongo_to_es(row, schema=schema)
            es_docs.append(es_doc)
            valid_rows.append(row)
        except Exception as exc:
            skip_count += 1
            doc_id = str(row.get("_id", "unknown"))
            _log(f"DLQ: doc {doc_id} conversion failed: {exc}")
            try:
                dlq_collection.update_one(
                    {"_id": doc_id},
                    {
                        "$set": {
                            "error": str(exc),
                            "traceback": traceback.format_exc(),
                            "failed_at": datetime.now(timezone.utc),
                        },
                        "$setOnInsert": {"_id": doc_id},
                    },
                    upsert=True,
                )
            except Exception as dlq_exc:
                _log(f"DLQ: failed to write dlq entry for {doc_id}: {dlq_exc}")

    return es_docs, valid_rows, skip_count


# ---------------------------------------------------------------------------
# Cursor lock (Fix 4)
# ---------------------------------------------------------------------------


class _CursorLock:
    """File-based exclusive lock to prevent concurrent sync execution."""

    def __init__(self, lock_path: Path = _LOCK_PATH) -> None:
        self._path = lock_path
        self._fd = None

    def acquire(self) -> None:
        self._fd = open(self._path, "w")
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._fd.close()
            self._fd = None
            raise RuntimeError(
                f"Another es_indexer process is already running (lock: {self._path})"
            )
        self._fd.write(str(os.getpid()))
        self._fd.flush()

    def release(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                self._fd.close()
                self._path.unlink(missing_ok=True)
            except Exception:
                pass
            self._fd = None


class ESClient:
    def __init__(self) -> None:
        self.url = os.getenv("ES_URL", "http://elasticsearch:9200").rstrip("/")
        schema = _schema_name()
        self.index = os.getenv("ES_INDEX", _SCHEMA_TO_INDEX[schema])
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
        mapping_path = _mapping_path()
        with mapping_path.open("r", encoding="utf-8") as f:
            mapping = json.load(f)

        if recreate:
            self.client.request(method="DELETE", url=f"{self.url}/{self.index}")

        exists_resp = self.client.request(method="HEAD", url=f"{self.url}/{self.index}")
        if exists_resp.status_code == 404:
            _log(f"creating index {self.index} using mapping {mapping_path.name}")
            self.request("PUT", f"/{self.index}", mapping)
        elif exists_resp.status_code >= 400:
            exists_resp.raise_for_status()

        self.request(
            "GET",
            f"/_cluster/health/{self.index}?wait_for_status=yellow&wait_for_active_shards=1&timeout=120s",
        )

        if self.alias:
            self.request(
                "POST",
                "/_aliases",
                {"actions": [{"add": {"index": self.index, "alias": self.alias}}]},
            )

    def refresh(self) -> None:
        self.request("POST", f"/{self.index}/_refresh")

    def wait_for_healthy(self, max_wait: int = 60) -> bool:
        """Block until ES cluster is yellow/green. Returns True if healthy."""
        waited = 0
        while waited < max_wait:
            try:
                resp = self.client.request(
                    method="GET",
                    url=f"{self.url}/_cluster/health?timeout=5s",
                )
                if resp.status_code == 200:
                    data = resp.json()
                    status = data.get("status", "red")
                    if status in ("yellow", "green"):
                        if waited > 0:
                            _log(f"ES cluster healthy ({status}) after {waited}s")
                        return True
                    _log(f"ES cluster status={status}, waiting...")
            except Exception as exc:
                _log(f"ES health check failed: {exc}")
            time.sleep(10)
            waited += 10
        _log(f"ES cluster not healthy after {max_wait}s")
        return False

    def bulk(self, docs: list[dict[str, Any]], retries: int = 3) -> tuple[int, int]:
        lines: list[str] = []
        for doc in docs:
            doc_id = doc.get("doc_id") or doc.get("logical_doc_id") or doc.get("_id")
            if not doc_id:
                raise RuntimeError("Document is missing an index identifier")
            lines.append(json.dumps({"index": {"_index": self.index, "_id": doc_id}}, ensure_ascii=False))
            lines.append(json.dumps(doc, ensure_ascii=False))
        body = "\n".join(lines) + "\n"

        last_error: str | None = None
        for attempt in range(1, retries + 1):
            try:
                resp = self.client.post(
                    f"{self.url}/_bulk",
                    data=body.encode("utf-8"),
                    headers={"Content-Type": "application/x-ndjson"},
                )
            except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.ConnectTimeout) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < retries:
                    time.sleep(1.5 * attempt)
                    continue
                raise RuntimeError(f"bulk timed out after retries: {last_error}") from exc
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
            retryable_item_failure = False
            for item in items:
                row = item.get("index", {})
                status = int(row.get("status", 500))
                if 200 <= status < 300:
                    ok += 1
                else:
                    failed += 1
                    err = row.get("error")
                    if isinstance(err, dict) and err.get("type") == "unavailable_shards_exception":
                        retryable_item_failure = True
                    if first_error is None:
                        first_error = json.dumps(err, ensure_ascii=True) if err else f"status={status}"
            if failed and retryable_item_failure and attempt < retries:
                last_error = first_error or "unavailable_shards_exception"
                time.sleep(1.5 * attempt)
                continue
            if failed:
                raise RuntimeError(f"bulk indexing failed: failed={failed} ok={ok} first_error={first_error}")
            return ok, failed
        raise RuntimeError(f"bulk failed after retries: {last_error}")


def _fetch_batch(collection, cursor: dict[str, str], batch_size: int) -> list[dict[str, Any]]:
    """Fetch a batch of documents from MongoDB using updated_at + _id pagination."""
    cursor_updated_at = _parse_cursor_timestamp(cursor["updated_at"])
    cursor_id = cursor["_id"]
    query = {
        "$or": [
            {"updated_at": {"$gt": cursor_updated_at}},
            {"updated_at": cursor_updated_at, "_id": {"$gt": cursor_id}},
        ]
    }
    cursor_iter = collection.find(query).sort([("updated_at", 1), ("_id", 1)]).limit(batch_size)
    return list(cursor_iter)


def _counts(collection, es: ESClient) -> tuple[int, int]:
    mongo_count = collection.count_documents({})
    es_count = int(es.request("GET", f"/{es.index}/_count").get("count", 0))
    return mongo_count, es_count


def _run_sync(*, reset_cursor: bool, recreate_index: bool, batch_size: int, cursor_path: Path) -> None:
    lock = _CursorLock()
    lock.acquire()
    try:
        _run_sync_inner(
            reset_cursor=reset_cursor,
            recreate_index=recreate_index,
            batch_size=batch_size,
            cursor_path=cursor_path,
        )
    finally:
        lock.release()


def _run_sync_inner(*, reset_cursor: bool, recreate_index: bool, batch_size: int, cursor_path: Path) -> None:
    es = ESClient()
    es.ensure_index(recreate=recreate_index)

    schema = _schema_name()

    if reset_cursor:
        cursor = dict(_DEFAULT_CURSOR)
    else:
        cursor = _load_cursor(cursor_path)
    _log(f"starting from cursor updated_at={cursor['updated_at']} _id={cursor['_id']}")

    client, db = _mongo_client()
    collection = db[_mongo_collection_name()]
    dlq = db["dlq_es_indexer"]
    collection.create_index([("updated_at", 1), ("_id", 1)])
    total_ok = 0
    total_failed = 0
    total_skipped = 0
    loops = 0
    consecutive_corrupt = 0
    try:
        while True:
            # Backpressure: wait for ES to be healthy before fetching
            if not es.wait_for_healthy(max_wait=60):
                _log("ABORT: ES cluster not healthy")
                break

            loops += 1
            rows = _fetch_batch(collection, cursor, batch_size)
            if not rows:
                break

            es_docs, valid_rows, skip_count = _convert_batch_safe(rows, dlq, schema)
            total_skipped += skip_count

            if not valid_rows:
                consecutive_corrupt += 1
                _log(f"batch={loops} all {len(rows)} docs corrupt (consecutive={consecutive_corrupt})")
                if consecutive_corrupt >= 3:
                    _log("ABORT: 3 consecutive fully-corrupt batches — manual investigation required")
                    break
                # Advance cursor past the corrupt batch
                last = rows[-1]
                last_updated_at = last.get("updated_at") or last.get("indexed_at")
                if isinstance(last_updated_at, datetime):
                    cursor["updated_at"] = last_updated_at.astimezone(timezone.utc).isoformat(timespec="microseconds")
                    cursor["_id"] = str(last["_id"])
                    _save_cursor(cursor_path, last_updated_at, cursor["_id"])
                continue

            consecutive_corrupt = 0
            ok, failed = es.bulk(es_docs)
            total_ok += ok
            total_failed += failed

            last = valid_rows[-1]
            last_updated_at = last.get("updated_at") or last.get("indexed_at")
            if not isinstance(last_updated_at, datetime):
                raise RuntimeError("Mongo row is missing datetime updated_at for cursor pagination")
            cursor["updated_at"] = last_updated_at.astimezone(timezone.utc).isoformat(timespec="microseconds")
            cursor["_id"] = str(last["_id"])
            _save_cursor(cursor_path, last_updated_at, cursor["_id"])

            _log(
                f"batch={loops} fetched={len(rows)} indexed_ok={ok} failed={failed} "
                f"skipped={skip_count} cursor_updated_at={cursor['updated_at']} cursor_id={cursor['_id']}"
            )
    finally:
        client.close()

    client, db = _mongo_client()
    collection = db[_mongo_collection_name()]
    try:
        es.refresh()
        mongo_count, es_count = _counts(collection, es)
    finally:
        client.close()

    _log(
        f"done indexed_ok={total_ok} failed={total_failed} skipped={total_skipped} "
        f"mongo_count={mongo_count} es_count={es_count}"
    )


def cmd_backfill(args: argparse.Namespace) -> None:
    if args.recreate_index and not args.yes_destroy:
        _log("ERROR: --recreate-index requires --yes-destroy to confirm destructive operation")
        sys.exit(1)
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
    collection = db[_mongo_collection_name()]
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


# ---------------------------------------------------------------------------
# Verify command (Fix 6)
# ---------------------------------------------------------------------------

_VERIFY_FIELDS = ("identifica", "pub_date", "art_type", "issuing_organ")


def cmd_verify(args: argparse.Namespace) -> None:
    """Sample random Mongo docs and verify they exist with matching fields in ES."""
    sample_size = args.sample_size
    es = ESClient()
    client, db = _mongo_client()
    collection = db[_mongo_collection_name()]
    schema = _schema_name()

    try:
        # Sample random documents from Mongo
        pipeline = [{"$sample": {"size": sample_size}}]
        sampled = list(collection.aggregate(pipeline))
    finally:
        client.close()

    if not sampled:
        _log("no documents in Mongo to verify")
        return

    checked = 0
    missing_in_es = 0
    field_mismatches = 0
    mismatch_details: list[dict] = []

    for doc in sampled:
        doc_id = str(doc["_id"])
        try:
            es_doc = _mongo_to_es(doc, schema=schema)
        except Exception as exc:
            _log(f"verify: doc {doc_id} conversion failed: {exc}")
            field_mismatches += 1
            continue

        checked += 1
        try:
            resp = es.client.request(
                method="GET",
                url=f"{es.url}/{es.index}/_doc/{doc_id}",
            )
        except Exception:
            missing_in_es += 1
            continue

        if resp.status_code == 404:
            missing_in_es += 1
            continue

        if resp.status_code >= 400:
            missing_in_es += 1
            continue

        es_source = resp.json().get("_source", {})
        for field in _VERIFY_FIELDS:
            es_val = es_source.get(field)
            expected_val = es_doc.get(field)
            if es_val != expected_val:
                field_mismatches += 1
                mismatch_details.append({
                    "doc_id": doc_id,
                    "field": field,
                    "expected": expected_val,
                    "actual": es_val,
                })
                break  # one mismatch per doc is enough

    report = {
        "sampled": len(sampled),
        "checked": checked,
        "missing_in_es": missing_in_es,
        "field_mismatches": field_mismatches,
        "ok": checked - missing_in_es - field_mismatches,
    }
    if mismatch_details:
        report["mismatch_details"] = mismatch_details[:10]  # cap output

    print(json.dumps(report, ensure_ascii=True, indent=2, default=str))

    if missing_in_es > 0 or field_mismatches > 0:
        sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Elasticsearch indexer for GABI DOU (MongoDB → ES)")
    p.add_argument("--cursor", default=str(_DEFAULT_CURSOR_PATH), help="Cursor state file path")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("backfill", help="Full backfill from MongoDB")
    sp.add_argument("--batch-size", type=int, default=1000)
    sp.add_argument("--recreate-index", action="store_true")
    sp.add_argument("--yes-destroy", action="store_true", help="Confirm destructive --recreate-index")
    sp.set_defaults(func=cmd_backfill)

    sp = sub.add_parser("sync", help="Incremental sync from cursor high-water mark")
    sp.add_argument("--batch-size", type=int, default=1000)
    sp.set_defaults(func=cmd_sync)

    sp = sub.add_parser("stats", help="Parity and index statistics")
    sp.set_defaults(func=cmd_stats)

    sp = sub.add_parser("verify", help="Sample-based parity check (Mongo vs ES)")
    sp.add_argument("--sample-size", type=int, default=100, help="Number of random docs to check")
    sp.set_defaults(func=cmd_verify)

    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
