"""Reindex V3 utilities for DOU parent/chunk rollout.

Usage:
  python -m src.backend.ingest.reindex_v3 mapping-diff
  python -m src.backend.ingest.reindex_v3 parent-backfill
  python -m src.backend.ingest.reindex_v3 parent-sync
  python -m src.backend.ingest.reindex_v3 parent-repair-cursor
  python -m src.backend.ingest.reindex_v3 parent-stats
  python -m src.backend.ingest.reindex_v3 parent-cutover
  python -m src.backend.ingest.reindex_v3 chunk-backfill
  python -m src.backend.ingest.reindex_v3 chunk-sync
  python -m src.backend.ingest.reindex_v3 chunk-pilot
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import sys
import time
import traceback
from typing import Any

import httpx
import pymongo

from src.backend.core.config import settings
from src.backend.ingest.dou_chunker import DouChunker
from src.backend.ingest.es_parent_v2 import mongo_to_es_parent_v2

_SEARCH_DIR = Path(__file__).resolve().parent.parent / "search"
_DEFAULT_PARENT_MAPPING_PATH = _SEARCH_DIR / "es_parent_v2.json"
_DEFAULT_CHUNK_MAPPING_PATH = _SEARCH_DIR / "es_dou_chunks_v1.json"
_COMPARE_FIELD_KEYS = (
    "type",
    "analyzer",
    "format",
    "ignore_above",
    "dims",
    "index",
    "similarity",
)
_DEFAULT_PARENT_INDEX = "gabi_documents_v2"
_DEFAULT_CHUNK_INDEX = settings.ES_CHUNKS_INDEX
_DEFAULT_PARENT_CURSOR = {
    "updated_at": datetime(1970, 1, 1, tzinfo=timezone.utc).isoformat(
        timespec="microseconds"
    ),
    "_id": "",
}
_DEFAULT_CHUNK_CURSOR = dict(_DEFAULT_PARENT_CURSOR)
_DEFAULT_PARENT_CURSOR_PATH = Path(
    os.getenv(
        "ES_PARENT_V2_CURSOR_PATH",
        "/data/gabi_dou/es_parent_v2_cursor.json",
    )
)
_DEFAULT_CHUNK_CURSOR_PATH = Path(
    os.getenv(
        "ES_DOU_CHUNKS_CURSOR_PATH",
        "/data/gabi_dou/es_dou_chunks_cursor.json",
    )
)
_DEFAULT_PARENT_LOCK_PATH = Path(
    os.getenv("ES_PARENT_V2_LOCK_PATH", "/tmp/reindex_v3_parent.lock")
)
_DEFAULT_CHUNK_LOCK_PATH = Path(
    os.getenv("ES_DOU_CHUNKS_LOCK_PATH", "/tmp/reindex_v3_chunks.lock")
)
_PARENT_VERIFY_FIELDS = (
    "identifica",
    "pub_date",
    "art_type",
    "issuing_organ",
    "schema_version",
    "topic_primary",
)
_CHUNK_LEDGER_COLLECTION = "reindex_v3_chunk_pruning_ledger"


def _log(msg: str) -> None:
    print(f"[reindex-v3] {msg}", flush=True)


def _es_url() -> str:
    return os.getenv("ES_URL", settings.ES_URL).rstrip("/")


def _expected_mapping_path(path_arg: str | None) -> Path:
    if path_arg:
        return Path(path_arg)
    override = (os.getenv("ES_MAPPING_PATH") or "").strip()
    if override:
        return Path(override)
    return _DEFAULT_PARENT_MAPPING_PATH


def _parent_index_name(index_arg: str | None) -> str:
    if index_arg:
        return index_arg.strip()
    return (os.getenv("ES_PARENT_V2_INDEX") or _DEFAULT_PARENT_INDEX).strip()


def _chunk_index_name(index_arg: str | None) -> str:
    if index_arg:
        return index_arg.strip()
    return (os.getenv("ES_CHUNKS_INDEX") or _DEFAULT_CHUNK_INDEX).strip()


def _mongo_client() -> tuple[pymongo.MongoClient, pymongo.database.Database]:
    client = pymongo.MongoClient(os.getenv("MONGO_STRING", settings.MONGO_STRING))
    return client, client[os.getenv("DB_NAME", settings.DB_NAME)]


def _mongo_collection_name() -> str:
    return os.getenv("MONGO_COLLECTION", "documents")


def _http_client() -> httpx.Client:
    verify_tls = (os.getenv("ES_VERIFY_TLS") or "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    timeout_sec = int(os.getenv("ES_TIMEOUT_SEC", "30"))
    user = (os.getenv("ES_USERNAME") or "").strip()
    pwd = (os.getenv("ES_PASSWORD") or "").strip()
    auth = (user, pwd) if user else None
    return httpx.Client(timeout=timeout_sec, verify=verify_tls, auth=auth)


def _read_expected_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected mapping JSON object in {path}")
    return data


def _resolve_live_mapping(
    http: httpx.Client, target: str
) -> tuple[list[str], dict[str, Any]]:
    url = _es_url()
    alias_resp = http.get(f"{url}/_alias/{target}")
    if alias_resp.status_code == 200:
        alias_data = alias_resp.json()
        if not isinstance(alias_data, dict) or not alias_data:
            raise RuntimeError(f"Alias {target} returned no indices")
        live_indices = sorted(alias_data.keys())
        mapping_resp = http.get(f"{url}/{target}/_mapping")
        mapping_resp.raise_for_status()
        mapping_data = mapping_resp.json()
        return live_indices, mapping_data

    if alias_resp.status_code != 404:
        alias_resp.raise_for_status()

    mapping_resp = http.get(f"{url}/{target}/_mapping")
    mapping_resp.raise_for_status()
    mapping_data = mapping_resp.json()
    if not isinstance(mapping_data, dict) or not mapping_data:
        raise RuntimeError(f"Target {target} returned no mapping")
    return [target], mapping_data


def _first_mapping_entry(mapping_data: dict[str, Any]) -> dict[str, Any]:
    first_key = next(iter(mapping_data))
    first_entry = mapping_data[first_key]
    if not isinstance(first_entry, dict):
        raise RuntimeError("Invalid live mapping entry")
    return first_entry


def _properties(mapping_doc: dict[str, Any]) -> dict[str, Any]:
    mappings = mapping_doc.get("mappings", {})
    if not isinstance(mappings, dict):
        return {}
    properties = mappings.get("properties", {})
    if not isinstance(properties, dict):
        return {}
    return properties


def _field_signature(field_mapping: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _normalize_scalar(field_mapping.get(key))
        for key in _COMPARE_FIELD_KEYS
        if key in field_mapping
    }


def _normalize_scalar(value: Any) -> Any:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "false":
            return False
        if lowered == "true":
            return True
    return value


def _diff_field_properties(
    expected_props: dict[str, Any], live_props: dict[str, Any]
) -> dict[str, Any]:
    expected_fields = set(expected_props.keys())
    live_fields = set(live_props.keys())

    missing_in_live = sorted(expected_fields - live_fields)
    extra_in_live = sorted(live_fields - expected_fields)

    type_mismatches: list[dict[str, Any]] = []
    attribute_mismatches: list[dict[str, Any]] = []

    for field_name in sorted(expected_fields & live_fields):
        expected_field = expected_props.get(field_name, {})
        live_field = live_props.get(field_name, {})
        if not isinstance(expected_field, dict) or not isinstance(live_field, dict):
            continue

        expected_type = expected_field.get("type")
        live_type = live_field.get("type")
        if expected_type != live_type:
            type_mismatches.append(
                {
                    "field": field_name,
                    "expected_type": expected_type,
                    "live_type": live_type,
                }
            )

        expected_sig = _field_signature(expected_field)
        live_sig = _field_signature(live_field)
        if expected_sig != live_sig:
            diffs: dict[str, Any] = {}
            for key in _COMPARE_FIELD_KEYS:
                if expected_field.get(key) != live_field.get(key):
                    diffs[key] = {
                        "expected": expected_field.get(key),
                        "live": live_field.get(key),
                    }
            if diffs:
                attribute_mismatches.append({"field": field_name, "differences": diffs})

    return {
        "missing_in_live": missing_in_live,
        "extra_in_live": extra_in_live,
        "type_mismatches": type_mismatches,
        "attribute_mismatches": attribute_mismatches,
    }


def build_mapping_diff(expected_mapping_path: Path, live_target: str) -> dict[str, Any]:
    expected_mapping = _read_expected_mapping(expected_mapping_path)
    expected_doc = {
        "mappings": expected_mapping.get("mappings", {}),
        "settings": expected_mapping.get("settings", {}),
    }
    expected_props = _properties(expected_doc)

    with _http_client() as http:
        live_indices, live_mapping_data = _resolve_live_mapping(http, live_target)

    live_doc = _first_mapping_entry(live_mapping_data)
    live_props = _properties(live_doc)
    diff = _diff_field_properties(expected_props, live_props)

    expected_dynamic = _normalize_scalar(
        expected_doc.get("mappings", {}).get("dynamic")
    )
    live_dynamic = _normalize_scalar(live_doc.get("mappings", {}).get("dynamic"))
    root_differences: dict[str, Any] = {}
    if expected_dynamic != live_dynamic:
        root_differences["dynamic"] = {
            "expected": expected_dynamic,
            "live": live_dynamic,
        }

    return {
        "live_target": live_target,
        "live_indices": live_indices,
        "expected_mapping_path": str(expected_mapping_path),
        "expected_field_count": len(expected_props),
        "live_field_count": len(live_props),
        "root_differences": root_differences,
        **diff,
        "summary": {
            "missing_in_live_count": len(diff["missing_in_live"]),
            "extra_in_live_count": len(diff["extra_in_live"]),
            "type_mismatch_count": len(diff["type_mismatches"]),
            "attribute_mismatch_count": len(diff["attribute_mismatches"]),
        },
    }


def _load_cursor(path: Path) -> dict[str, str]:
    if not path.exists():
        return dict(_DEFAULT_PARENT_CURSOR)
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    updated_at = str(data.get("updated_at") or _DEFAULT_PARENT_CURSOR["updated_at"])
    doc_id = str(data.get("_id") or _DEFAULT_PARENT_CURSOR["_id"])
    return {"updated_at": updated_at, "_id": doc_id}


def _parse_cursor_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _save_cursor(path: Path, last_updated_at: datetime, last_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": last_updated_at.astimezone(timezone.utc).isoformat(
            timespec="microseconds"
        ),
        "_id": last_id,
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2)


def _fetch_batch(
    collection, cursor: dict[str, str], batch_size: int
) -> list[dict[str, Any]]:
    cursor_updated_at = _parse_cursor_timestamp(cursor["updated_at"])
    cursor_id = cursor["_id"]
    query = {
        "$or": [
            {"updated_at": {"$gt": cursor_updated_at}},
            {"updated_at": cursor_updated_at, "_id": {"$gt": cursor_id}},
        ]
    }
    cursor_iter = (
        collection.find(query).sort([("updated_at", 1), ("_id", 1)]).limit(batch_size)
    )
    return list(cursor_iter)


def _counts(collection, es_client: "IndexClient") -> tuple[int, int]:
    mongo_count = collection.count_documents({})
    es_count = int(
        es_client.request("GET", f"/{es_client.index}/_count").get("count", 0)
    )
    return mongo_count, es_count


def _read_cursor_raw(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _repair_cursor_from_index(index_name: str) -> dict[str, str]:
    es_client = IndexClient(index_name)
    try:
        response = es_client.request(
            "POST",
            f"/{index_name}/_search",
            {
                "size": 1,
                "_source": ["doc_id", "updated_at"],
                "sort": [
                    {"updated_at": {"order": "desc", "unmapped_type": "date"}},
                    {"doc_id": {"order": "desc", "unmapped_type": "keyword"}},
                ],
                "query": {"match_all": {}},
            },
        )
    finally:
        es_client.client.close()

    hits = response.get("hits", {}).get("hits", [])
    if not hits:
        return dict(_DEFAULT_PARENT_CURSOR)

    source = hits[0].get("_source", {})
    updated_at = str(source.get("updated_at") or _DEFAULT_PARENT_CURSOR["updated_at"])
    doc_id = str(
        source.get("doc_id") or hits[0].get("_id") or _DEFAULT_PARENT_CURSOR["_id"]
    )
    return {"updated_at": updated_at, "_id": doc_id}


def _convert_parent_batch_safe(
    rows: list[dict[str, Any]],
    dlq_collection,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    es_docs: list[dict[str, Any]] = []
    valid_rows: list[dict[str, Any]] = []
    skip_count = 0

    for row in rows:
        try:
            es_doc = mongo_to_es_parent_v2(row)
            es_docs.append(es_doc)
            valid_rows.append(row)
        except Exception as exc:
            skip_count += 1
            doc_id = str(row.get("_id", "unknown"))
            _log(f"DLQ: parent doc {doc_id} conversion failed: {exc}")
            try:
                dlq_collection.update_one(
                    {"_id": doc_id},
                    {
                        "$set": {
                            "error": str(exc),
                            "traceback": traceback.format_exc(),
                            "failed_at": datetime.now(timezone.utc),
                            "target_index": row.get("target_index") or None,
                            "mapper": "mongo_to_es_parent_v2",
                        },
                        "$setOnInsert": {"_id": doc_id},
                    },
                    upsert=True,
                )
            except Exception as dlq_exc:
                _log(f"DLQ: failed to write parent dlq entry for {doc_id}: {dlq_exc}")

    return es_docs, valid_rows, skip_count


class _CursorLock:
    def __init__(self, lock_path: Path) -> None:
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
                f"Another reindex_v3 process is already running (lock: {self._path})"
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


class IndexClient:
    def __init__(self, index: str) -> None:
        self.url = _es_url()
        self.index = index
        self.client = _http_client()

    def request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = self.client.request(
            method=method, url=f"{self.url}{path}", json=payload
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Invalid Elasticsearch response")
        return data

    def ensure_index(self, mapping_path: Path, recreate: bool = False) -> None:
        with mapping_path.open("r", encoding="utf-8") as handle:
            mapping = json.load(handle)

        if recreate:
            self.client.request(method="DELETE", url=f"{self.url}/{self.index}")

        exists_response = self.client.request(
            method="HEAD", url=f"{self.url}/{self.index}"
        )
        if exists_response.status_code == 404:
            _log(f"creating index {self.index} using mapping {mapping_path.name}")
            self.request("PUT", f"/{self.index}", mapping)
        elif exists_response.status_code >= 400:
            exists_response.raise_for_status()

        self.request(
            "GET",
            f"/_cluster/health/{self.index}?wait_for_status=yellow&wait_for_active_shards=1&timeout=120s",
        )

    def refresh(self) -> None:
        self.request("POST", f"/{self.index}/_refresh")

    def wait_for_healthy(self, max_wait: int = 60) -> bool:
        waited = 0
        while waited < max_wait:
            try:
                response = self.client.request(
                    method="GET", url=f"{self.url}/_cluster/health?timeout=5s"
                )
                if response.status_code == 200:
                    data = response.json()
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
            doc_id = (
                doc.get("chunk_id")
                or doc.get("doc_id")
                or doc.get("logical_doc_id")
                or doc.get("_id")
            )
            if not doc_id:
                raise RuntimeError("Document is missing an index identifier")
            lines.append(
                json.dumps(
                    {"index": {"_index": self.index, "_id": doc_id}}, ensure_ascii=False
                )
            )
            lines.append(json.dumps(doc, ensure_ascii=False))
        body = "\n".join(lines) + "\n"

        last_error: str | None = None
        for attempt in range(1, retries + 1):
            try:
                response = self.client.post(
                    f"{self.url}/_bulk",
                    data=body.encode("utf-8"),
                    headers={"Content-Type": "application/x-ndjson"},
                )
            except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.ConnectTimeout) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < retries:
                    time.sleep(1.5 * attempt)
                    continue
                raise RuntimeError(
                    f"bulk timed out after retries: {last_error}"
                ) from exc

            if response.status_code in (429, 502, 503, 504):
                last_error = f"http {response.status_code}"
                time.sleep(1.5 * attempt)
                continue

            response.raise_for_status()
            data = response.json()
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
                    if (
                        isinstance(err, dict)
                        and err.get("type") == "unavailable_shards_exception"
                    ):
                        retryable_item_failure = True
                    if first_error is None:
                        first_error = (
                            json.dumps(err, ensure_ascii=True)
                            if err
                            else f"status={status}"
                        )

            if failed and retryable_item_failure and attempt < retries:
                last_error = first_error or "unavailable_shards_exception"
                time.sleep(1.5 * attempt)
                continue
            if failed:
                raise RuntimeError(
                    f"bulk indexing failed: failed={failed} ok={ok} first_error={first_error}"
                )
            return ok, failed

        raise RuntimeError(f"bulk failed after retries: {last_error}")

    def swap_alias(self, alias: str, new_index: str, old_indices: list[str]) -> None:
        actions = [
            {"remove": {"index": index_name, "alias": alias}}
            for index_name in old_indices
        ]
        actions.append({"add": {"index": new_index, "alias": alias}})
        self.request("POST", "/_aliases", {"actions": actions})


def _run_parent_backfill(
    *,
    index_name: str,
    mapping_path: Path,
    reset_cursor: bool,
    recreate_index: bool,
    batch_size: int,
    cursor_path: Path,
    lock_path: Path,
    max_batches: int | None,
) -> None:
    lock = _CursorLock(lock_path)
    lock.acquire()
    try:
        _run_parent_backfill_inner(
            index_name=index_name,
            mapping_path=mapping_path,
            reset_cursor=reset_cursor,
            recreate_index=recreate_index,
            batch_size=batch_size,
            cursor_path=cursor_path,
            max_batches=max_batches,
        )
    finally:
        lock.release()


def _run_parent_backfill_inner(
    *,
    index_name: str,
    mapping_path: Path,
    reset_cursor: bool,
    recreate_index: bool,
    batch_size: int,
    cursor_path: Path,
    max_batches: int | None,
) -> None:
    es_client = IndexClient(index_name)
    es_client.ensure_index(mapping_path=mapping_path, recreate=recreate_index)

    if reset_cursor:
        cursor = dict(_DEFAULT_PARENT_CURSOR)
    else:
        cursor = _load_cursor(cursor_path)

    _log(
        "parent backfill starting index=%s cursor_updated_at=%s cursor_id=%s"
        % (index_name, cursor["updated_at"], cursor["_id"])
    )

    client, db = _mongo_client()
    collection = db[_mongo_collection_name()]
    dlq = db["dlq_reindex_v3_parent"]
    collection.create_index([("updated_at", 1), ("_id", 1)])
    total_ok = 0
    total_failed = 0
    total_skipped = 0
    loops = 0
    consecutive_corrupt = 0
    health_check_interval = 50
    try:
        while True:
            if max_batches is not None and loops >= max_batches:
                _log(f"reached max_batches={max_batches}, stopping early")
                break

            if loops % health_check_interval == 0:
                if not es_client.wait_for_healthy(max_wait=60):
                    _log("ABORT: ES cluster not healthy")
                    break

            loops += 1
            rows = _fetch_batch(collection, cursor, batch_size)
            if not rows:
                break

            es_docs, valid_rows, skip_count = _convert_parent_batch_safe(rows, dlq)
            total_skipped += skip_count

            if not valid_rows:
                consecutive_corrupt += 1
                _log(
                    f"batch={loops} all {len(rows)} parent docs corrupt (consecutive={consecutive_corrupt})"
                )
                if consecutive_corrupt >= 3:
                    _log(
                        "ABORT: 3 consecutive fully-corrupt batches — manual investigation required"
                    )
                    break
                last = rows[-1]
                last_updated_at = last.get("updated_at") or last.get("indexed_at")
                if isinstance(last_updated_at, datetime):
                    cursor["updated_at"] = last_updated_at.astimezone(
                        timezone.utc
                    ).isoformat(timespec="microseconds")
                    cursor["_id"] = str(last["_id"])
                    _save_cursor(cursor_path, last_updated_at, cursor["_id"])
                continue

            consecutive_corrupt = 0
            ok, failed = es_client.bulk(es_docs)
            total_ok += ok
            total_failed += failed

            last = valid_rows[-1]
            last_updated_at = last.get("updated_at") or last.get("indexed_at")
            if not isinstance(last_updated_at, datetime):
                raise RuntimeError(
                    "Mongo row is missing datetime updated_at for cursor pagination"
                )

            cursor["updated_at"] = last_updated_at.astimezone(timezone.utc).isoformat(
                timespec="microseconds"
            )
            cursor["_id"] = str(last["_id"])
            _save_cursor(cursor_path, last_updated_at, cursor["_id"])

            _log(
                "parent batch=%d fetched=%d indexed_ok=%d failed=%d skipped=%d cursor_updated_at=%s cursor_id=%s"
                % (
                    loops,
                    len(rows),
                    ok,
                    failed,
                    skip_count,
                    cursor["updated_at"],
                    cursor["_id"],
                )
            )

        es_client.refresh()
        mongo_count, es_count = _counts(collection, es_client)
        _log(
            "parent done indexed_ok=%d failed=%d skipped=%d mongo_count=%d es_count=%d target_index=%s"
            % (total_ok, total_failed, total_skipped, mongo_count, es_count, index_name)
        )
    finally:
        client.close()
        es_client.client.close()


def _upsert_chunk_ledger(collection, ledger: dict[str, Any]) -> None:
    collection.update_one(
        {"_id": ledger["_id"]},
        {"$set": ledger},
        upsert=True,
    )


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * pct))))
    return ordered[index]


def _run_chunk_backfill(
    *,
    index_name: str,
    mapping_path: Path,
    batch_size: int,
    cursor_path: Path,
    lock_path: Path,
    max_batches: int | None,
    recreate_index: bool,
    reset_cursor: bool,
) -> None:
    lock = _CursorLock(lock_path)
    lock.acquire()
    try:
        _run_chunk_backfill_inner(
            index_name=index_name,
            mapping_path=mapping_path,
            batch_size=batch_size,
            cursor_path=cursor_path,
            max_batches=max_batches,
            recreate_index=recreate_index,
            reset_cursor=reset_cursor,
        )
    finally:
        lock.release()


def _run_chunk_backfill_inner(
    *,
    index_name: str,
    mapping_path: Path,
    batch_size: int,
    cursor_path: Path,
    max_batches: int | None,
    recreate_index: bool,
    reset_cursor: bool,
) -> None:
    es_client = IndexClient(index_name)
    es_client.ensure_index(mapping_path=mapping_path, recreate=recreate_index)
    cursor = dict(_DEFAULT_CHUNK_CURSOR) if reset_cursor else _load_cursor(cursor_path)
    chunker = DouChunker()

    _log(
        "chunk backfill starting index=%s cursor_updated_at=%s cursor_id=%s"
        % (index_name, cursor["updated_at"], cursor["_id"])
    )

    client, db = _mongo_client()
    collection = db[_mongo_collection_name()]
    ledger_collection = db[_CHUNK_LEDGER_COLLECTION]
    collection.create_index([("updated_at", 1), ("_id", 1)])

    total_docs = 0
    total_chunked_docs = 0
    total_chunks = 0
    total_skipped_docs = 0
    loops = 0

    try:
        while True:
            if max_batches is not None and loops >= max_batches:
                _log(f"reached max_batches={max_batches}, stopping early")
                break

            loops += 1
            rows = _fetch_batch(collection, cursor, batch_size)
            if not rows:
                break

            batch_chunk_docs: list[dict[str, Any]] = []
            batch_chunked_docs = 0
            for row in rows:
                total_docs += 1
                chunk_docs, ledger = chunker.build_chunk_docs(row)
                _upsert_chunk_ledger(ledger_collection, ledger)
                if chunk_docs:
                    batch_chunked_docs += 1
                    batch_chunk_docs.extend(chunk_docs)
                else:
                    total_skipped_docs += 1

            if batch_chunk_docs:
                ok, failed = es_client.bulk(batch_chunk_docs)
                if failed:
                    raise RuntimeError(
                        f"chunk bulk failed for batch={loops} failed={failed}"
                    )
                total_chunks += ok
            total_chunked_docs += batch_chunked_docs

            last = rows[-1]
            last_updated_at = last.get("updated_at") or last.get("indexed_at")
            if not isinstance(last_updated_at, datetime):
                raise RuntimeError(
                    "Mongo row is missing datetime updated_at for cursor pagination"
                )
            cursor["_id"] = str(last["_id"])
            cursor["updated_at"] = last_updated_at.astimezone(timezone.utc).isoformat(
                timespec="microseconds"
            )
            _save_cursor(cursor_path, last_updated_at, cursor["_id"])

            _log(
                "chunk batch=%d docs=%d chunked_docs=%d chunks=%d skipped_docs=%d cursor_updated_at=%s cursor_id=%s"
                % (
                    loops,
                    len(rows),
                    batch_chunked_docs,
                    len(batch_chunk_docs),
                    len(rows) - batch_chunked_docs,
                    cursor["updated_at"],
                    cursor["_id"],
                )
            )

        es_client.refresh()
        report = {
            "backend": "dou_chunk_backfill",
            "index": index_name,
            "docs_seen": total_docs,
            "chunked_docs": total_chunked_docs,
            "skipped_docs": total_skipped_docs,
            "chunks_indexed": total_chunks,
            "cursor": cursor,
        }
        print(json.dumps(report, ensure_ascii=True, indent=2))
    finally:
        client.close()
        es_client.client.close()


def _run_chunk_pilot(sample_size: int) -> dict[str, Any]:
    chunker = DouChunker()
    client, db = _mongo_client()
    collection = db[_mongo_collection_name()]
    try:
        sampled = list(collection.aggregate([{"$sample": {"size": sample_size}}]))
        total_docs = collection.estimated_document_count()
    finally:
        client.close()

    chunk_counts: list[int] = []
    chunked_docs = 0
    total_chunks = 0
    pruned_docs = 0
    for doc in sampled:
        chunk_docs, ledger = chunker.build_chunk_docs(doc)
        count = len(chunk_docs)
        chunk_counts.append(count)
        total_chunks += count
        if count > 0:
            chunked_docs += 1
        if int(ledger.get("pruned_chunk_count") or 0) > 0:
            pruned_docs += 1

    avg_chunks = round(total_chunks / max(chunked_docs, 1), 4) if chunked_docs else 0.0
    eligibility_rate = chunked_docs / max(len(sampled), 1)
    projected_total = int(round(total_docs * eligibility_rate * avg_chunks))
    report = {
        "sample_size": len(sampled),
        "total_docs": total_docs,
        "chunked_docs": chunked_docs,
        "eligibility_rate": round(eligibility_rate, 4),
        "percent_chunked": round(eligibility_rate, 4),
        "avg_chunks_per_chunked_doc": avg_chunks,
        "p95_chunks_per_doc": _percentile(chunk_counts, 0.95),
        "p99_chunks_per_doc": _percentile(chunk_counts, 0.99),
        "projected_total_chunks": projected_total,
        "pruned_docs": pruned_docs,
        "passes_gates": bool(
            projected_total <= 25_000_000
            and avg_chunks <= 5.0
            and _percentile(chunk_counts, 0.99) <= 8
        ),
    }
    return report


def _resolve_alias_indices(target: str) -> list[str]:
    with _http_client() as http:
        alias_resp = http.get(f"{_es_url()}/_alias/{target}")
        if alias_resp.status_code == 404:
            return []
        alias_resp.raise_for_status()
        data = alias_resp.json()
        if not isinstance(data, dict):
            return []
        return sorted(data.keys())


def cmd_parent_cutover(args: argparse.Namespace) -> None:
    alias = args.alias.strip()
    target_index = _parent_index_name(args.index)
    current_indices = _resolve_alias_indices(alias)
    if target_index in current_indices and len(current_indices) == 1:
        _log(f"alias {alias} already points to {target_index}")
        return

    es_client = IndexClient(target_index)
    try:
        es_client.swap_alias(
            alias,
            target_index,
            [
                index_name
                for index_name in current_indices
                if index_name != target_index
            ],
        )
    finally:
        es_client.client.close()

    print(
        json.dumps(
            {
                "alias": alias,
                "previous_indices": current_indices,
                "new_index": target_index,
            },
            ensure_ascii=True,
            indent=2,
        )
    )


def cmd_mapping_diff(args: argparse.Namespace) -> None:
    expected_mapping_path = _expected_mapping_path(args.expected_mapping)
    report = build_mapping_diff(expected_mapping_path, args.live_target)

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=True, indent=2)
        _log(f"wrote report to {report_path}")

    print(json.dumps(report, ensure_ascii=True, indent=2))


def cmd_parent_backfill(args: argparse.Namespace) -> None:
    if args.recreate_index and not args.yes_destroy:
        _log(
            "ERROR: --recreate-index requires --yes-destroy to confirm destructive operation"
        )
        sys.exit(1)

    _run_parent_backfill(
        index_name=_parent_index_name(args.index),
        mapping_path=_expected_mapping_path(args.mapping_path),
        reset_cursor=True,
        recreate_index=args.recreate_index,
        batch_size=args.batch_size,
        cursor_path=Path(args.cursor),
        lock_path=Path(args.lock),
        max_batches=args.max_batches,
    )


def cmd_parent_sync(args: argparse.Namespace) -> None:
    _run_parent_backfill(
        index_name=_parent_index_name(args.index),
        mapping_path=_expected_mapping_path(args.mapping_path),
        reset_cursor=False,
        recreate_index=False,
        batch_size=args.batch_size,
        cursor_path=Path(args.cursor),
        lock_path=Path(args.lock),
        max_batches=args.max_batches,
    )


def cmd_parent_repair_cursor(args: argparse.Namespace) -> None:
    index_name = _parent_index_name(args.index)
    cursor_path = Path(args.cursor)
    raw_before = _read_cursor_raw(cursor_path)
    repaired = _repair_cursor_from_index(index_name)
    repaired_updated_at = _parse_cursor_timestamp(repaired["updated_at"])
    _save_cursor(cursor_path, repaired_updated_at, repaired["_id"])

    report = {
        "index": index_name,
        "cursor_path": str(cursor_path),
        "previous_cursor_raw": raw_before,
        "repaired_cursor": repaired,
    }
    print(json.dumps(report, ensure_ascii=True, indent=2))


def cmd_parent_stats(args: argparse.Namespace) -> None:
    index_name = _parent_index_name(args.index)
    cursor_path = Path(args.cursor)
    es_client = IndexClient(index_name)
    client, db = _mongo_client()
    collection = db[_mongo_collection_name()]
    try:
        mongo_count, es_count = _counts(collection, es_client)
    finally:
        client.close()
        es_client.client.close()

    health = es_client.request("GET", "/_cluster/health")
    idx_stats = es_client.request("GET", f"/{index_name}/_stats/docs,store")
    cursor = _load_cursor(cursor_path)

    print(
        json.dumps(
            {
                "backend": "es_parent_v2",
                "index": index_name,
                "cluster_status": health.get("status"),
                "mongo_count": mongo_count,
                "es_count": es_count,
                "count_delta": mongo_count - es_count,
                "cursor": cursor,
                "index_stats": idx_stats.get("indices", {}).get(index_name, {}),
            },
            ensure_ascii=True,
            indent=2,
        )
    )


def cmd_parent_verify(args: argparse.Namespace) -> None:
    sample_size = args.sample_size
    index_name = _parent_index_name(args.index)
    es_client = IndexClient(index_name)
    client, db = _mongo_client()
    collection = db[_mongo_collection_name()]

    try:
        sampled = list(collection.aggregate([{"$sample": {"size": sample_size}}]))
    finally:
        client.close()

    if not sampled:
        _log("no Mongo documents available for parent verification")
        es_client.client.close()
        return

    expected: dict[str, dict[str, Any]] = {}
    conversion_failures = 0
    for doc in sampled:
        doc_id = str(doc["_id"])
        try:
            expected[doc_id] = mongo_to_es_parent_v2(doc)
        except Exception as exc:
            _log(f"parent verify: doc {doc_id} conversion failed: {exc}")
            conversion_failures += 1

    response = es_client.client.post(
        f"{es_client.url}/{index_name}/_mget",
        json={"ids": list(expected.keys())},
        headers={"Content-Type": "application/json"},
    )
    response.raise_for_status()

    es_docs_by_id: dict[str, dict[str, Any]] = {}
    for hit in response.json().get("docs", []):
        if hit.get("found"):
            es_docs_by_id[hit["_id"]] = hit.get("_source", {})

    checked = len(expected)
    missing_in_es = 0
    field_mismatches = conversion_failures
    mismatch_details: list[dict[str, Any]] = []

    for doc_id, es_doc in expected.items():
        es_source = es_docs_by_id.get(doc_id)
        if es_source is None:
            missing_in_es += 1
            continue

        for field in _PARENT_VERIFY_FIELDS:
            if es_source.get(field) != es_doc.get(field):
                field_mismatches += 1
                mismatch_details.append(
                    {
                        "doc_id": doc_id,
                        "field": field,
                        "expected": es_doc.get(field),
                        "actual": es_source.get(field),
                    }
                )
                break

    report = {
        "sampled": len(sampled),
        "checked": checked,
        "missing_in_es": missing_in_es,
        "field_mismatches": field_mismatches,
        "ok": checked - missing_in_es - field_mismatches,
    }
    if mismatch_details:
        report["mismatch_details"] = mismatch_details[:10]

    print(json.dumps(report, ensure_ascii=True, indent=2, default=str))
    es_client.client.close()

    if missing_in_es > 0 or field_mismatches > 0:
        sys.exit(1)


def cmd_chunk_backfill(args: argparse.Namespace) -> None:
    if args.recreate_index and not args.yes_destroy:
        _log(
            "ERROR: --recreate-index requires --yes-destroy to confirm destructive operation"
        )
        sys.exit(1)

    _run_chunk_backfill(
        index_name=_chunk_index_name(args.index),
        mapping_path=Path(args.mapping_path)
        if args.mapping_path
        else _DEFAULT_CHUNK_MAPPING_PATH,
        batch_size=args.batch_size,
        cursor_path=Path(args.cursor),
        lock_path=Path(args.lock),
        max_batches=args.max_batches,
        recreate_index=args.recreate_index,
        reset_cursor=True,
    )


def cmd_chunk_sync(args: argparse.Namespace) -> None:
    _run_chunk_backfill(
        index_name=_chunk_index_name(args.index),
        mapping_path=Path(args.mapping_path)
        if args.mapping_path
        else _DEFAULT_CHUNK_MAPPING_PATH,
        batch_size=args.batch_size,
        cursor_path=Path(args.cursor),
        lock_path=Path(args.lock),
        max_batches=args.max_batches,
        recreate_index=False,
        reset_cursor=False,
    )


def cmd_chunk_pilot(args: argparse.Namespace) -> None:
    report = _run_chunk_pilot(args.sample)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    if args.require_pass and not report["passes_gates"]:
        sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reindex V3 utilities for DOU parent/chunk rollout"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser(
        "mapping-diff",
        help="Compare the live alias/index mapping against the expected mapping file",
    )
    sp.add_argument(
        "--live-target",
        default=settings.es_target_index,
        help="Alias or index to compare against",
    )
    sp.add_argument(
        "--expected-mapping", default=None, help="Expected mapping JSON file path"
    )
    sp.add_argument(
        "--report", default=None, help="Optional path to write the JSON diff report"
    )
    sp.set_defaults(func=cmd_mapping_diff)

    sp = sub.add_parser(
        "parent-backfill",
        help="Backfill the frozen parent-v2 index without mutating aliases",
    )
    sp.add_argument(
        "--index",
        default=None,
        help="Target physical ES index name (default: gabi_documents_v2)",
    )
    sp.add_argument(
        "--mapping-path", default=None, help="Parent-v2 mapping JSON file path"
    )
    sp.add_argument(
        "--cursor",
        default=str(_DEFAULT_PARENT_CURSOR_PATH),
        help="Parent-v2 cursor state file path",
    )
    sp.add_argument(
        "--lock",
        default=str(_DEFAULT_PARENT_LOCK_PATH),
        help="Parent-v2 lock file path",
    )
    sp.add_argument("--batch-size", type=int, default=1000, help="Mongo batch size")
    sp.add_argument(
        "--max-batches", type=int, default=None, help="Optional cap for pilot runs"
    )
    sp.add_argument(
        "--recreate-index",
        action="store_true",
        help="Delete and recreate the target physical index",
    )
    sp.add_argument(
        "--yes-destroy",
        action="store_true",
        help="Confirm destructive --recreate-index",
    )
    sp.set_defaults(func=cmd_parent_backfill)

    sp = sub.add_parser(
        "parent-sync",
        help="Resume parent-v2 indexing from the saved cursor without recreating the index",
    )
    sp.add_argument(
        "--index",
        default=None,
        help="Target physical ES index name (default: gabi_documents_v2)",
    )
    sp.add_argument(
        "--mapping-path", default=None, help="Parent-v2 mapping JSON file path"
    )
    sp.add_argument(
        "--cursor",
        default=str(_DEFAULT_PARENT_CURSOR_PATH),
        help="Parent-v2 cursor state file path",
    )
    sp.add_argument(
        "--lock",
        default=str(_DEFAULT_PARENT_LOCK_PATH),
        help="Parent-v2 lock file path",
    )
    sp.add_argument("--batch-size", type=int, default=1000, help="Mongo batch size")
    sp.add_argument(
        "--max-batches", type=int, default=None, help="Optional cap for pilot runs"
    )
    sp.set_defaults(func=cmd_parent_sync)

    sp = sub.add_parser(
        "parent-repair-cursor",
        help="Repair the parent-v2 cursor from the highest updated_at/doc_id in the target index",
    )
    sp.add_argument(
        "--index",
        default=None,
        help="Target physical ES index name (default: gabi_documents_v2)",
    )
    sp.add_argument(
        "--cursor",
        default=str(_DEFAULT_PARENT_CURSOR_PATH),
        help="Parent-v2 cursor state file path",
    )
    sp.set_defaults(func=cmd_parent_repair_cursor)

    sp = sub.add_parser(
        "parent-stats",
        help="Show parity and index stats for the parent-v2 target index",
    )
    sp.add_argument(
        "--index",
        default=None,
        help="Target physical ES index name (default: gabi_documents_v2)",
    )
    sp.add_argument(
        "--cursor",
        default=str(_DEFAULT_PARENT_CURSOR_PATH),
        help="Parent-v2 cursor state file path",
    )
    sp.set_defaults(func=cmd_parent_stats)

    sp = sub.add_parser(
        "parent-verify",
        help="Sample-based Mongo vs ES verification for the parent-v2 target index",
    )
    sp.add_argument(
        "--index",
        default=None,
        help="Target physical ES index name (default: gabi_documents_v2)",
    )
    sp.add_argument(
        "--sample-size", type=int, default=100, help="Number of random docs to verify"
    )
    sp.set_defaults(func=cmd_parent_verify)

    sp = sub.add_parser(
        "parent-cutover",
        help="Atomically repoint the parent read alias at a new physical index",
    )
    sp.add_argument(
        "--alias",
        default=settings.ES_ALIAS or "gabi_documents",
        help="Read alias to swap",
    )
    sp.add_argument("--index", default=None, help="Target physical ES index name")
    sp.set_defaults(func=cmd_parent_cutover)

    sp = sub.add_parser(
        "chunk-backfill",
        help="Backfill deterministic DOU chunk docs into the sidecar index",
    )
    sp.add_argument("--index", default=None, help="Target physical ES chunk index name")
    sp.add_argument(
        "--mapping-path", default=None, help="Chunk index mapping JSON file path"
    )
    sp.add_argument(
        "--cursor",
        default=str(_DEFAULT_CHUNK_CURSOR_PATH),
        help="Chunk cursor state file path",
    )
    sp.add_argument(
        "--lock", default=str(_DEFAULT_CHUNK_LOCK_PATH), help="Chunk lock file path"
    )
    sp.add_argument("--batch-size", type=int, default=500, help="Mongo batch size")
    sp.add_argument(
        "--max-batches", type=int, default=None, help="Optional cap for pilot runs"
    )
    sp.add_argument(
        "--recreate-index",
        action="store_true",
        help="Delete and recreate the target chunk index",
    )
    sp.add_argument(
        "--yes-destroy",
        action="store_true",
        help="Confirm destructive --recreate-index",
    )
    sp.set_defaults(func=cmd_chunk_backfill)

    sp = sub.add_parser(
        "chunk-sync", help="Resume chunk indexing from the saved cursor"
    )
    sp.add_argument("--index", default=None, help="Target physical ES chunk index name")
    sp.add_argument(
        "--mapping-path", default=None, help="Chunk index mapping JSON file path"
    )
    sp.add_argument(
        "--cursor",
        default=str(_DEFAULT_CHUNK_CURSOR_PATH),
        help="Chunk cursor state file path",
    )
    sp.add_argument(
        "--lock", default=str(_DEFAULT_CHUNK_LOCK_PATH), help="Chunk lock file path"
    )
    sp.add_argument("--batch-size", type=int, default=500, help="Mongo batch size")
    sp.add_argument(
        "--max-batches", type=int, default=None, help="Optional cap for pilot runs"
    )
    sp.set_defaults(func=cmd_chunk_sync)

    sp = sub.add_parser(
        "chunk-pilot",
        help="Sample DOU docs and estimate chunk rollout size before full backfill",
    )
    sp.add_argument(
        "--sample", type=int, default=10000, help="Number of Mongo docs to sample"
    )
    sp.add_argument(
        "--require-pass",
        action="store_true",
        help="Exit non-zero if rollout gates do not pass",
    )
    sp.set_defaults(func=cmd_chunk_pilot)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
