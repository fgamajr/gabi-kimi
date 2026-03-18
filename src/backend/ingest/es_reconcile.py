from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from src.backend.ingest.es_indexer import ESClient, _mongo_client, _mongo_collection_name, _log
from src.backend.ingest.es_v3_full import mongo_to_es_v3_full


def _iter_mongo_ids(collection, batch_size: int):
    cursor = collection.find({}, {"_id": 1}, no_cursor_timeout=True).batch_size(batch_size)
    try:
        for row in cursor:
            yield str(row["_id"])
    finally:
        cursor.close()


def _iter_es_ids(es: ESClient, batch_size: int):
    response = es.request(
        "POST",
        f"/{es.index}/_search?scroll=2m",
        {
            "size": batch_size,
            "sort": ["_doc"],
            "_source": False,
            "stored_fields": [],
            "query": {"match_all": {}},
        },
    )
    scroll_id = response.get("_scroll_id")
    try:
        hits = response.get("hits", {}).get("hits", [])
        while hits:
            for hit in hits:
                yield str(hit["_id"])
            response = es.request("POST", "/_search/scroll", {"scroll": "2m", "scroll_id": scroll_id})
            scroll_id = response.get("_scroll_id")
            hits = response.get("hits", {}).get("hits", [])
    finally:
        if scroll_id:
            try:
                es.request("DELETE", "/_search/scroll", {"scroll_id": [scroll_id]})
            except Exception:
                pass


def _batched(values: list[str], batch_size: int):
    for idx in range(0, len(values), batch_size):
        yield values[idx : idx + batch_size]


def reconcile(batch_size: int) -> dict[str, int]:
    es = ESClient()
    es.ensure_index(recreate=False)
    client, db = _mongo_client()
    collection = db[_mongo_collection_name()]

    try:
        mongo_count = collection.count_documents({})
        es_count_before = int(es.request("GET", f"/{es.index}/_count").get("count", 0))

        mongo_ids = set(_iter_mongo_ids(collection, batch_size))
        for es_id in _iter_es_ids(es, batch_size):
            mongo_ids.discard(es_id)

        missing_ids = sorted(mongo_ids)
        appended = 0
        for id_batch in _batched(missing_ids, batch_size):
            rows_by_id: dict[str, dict[str, Any]] = {
                str(row["_id"]): row for row in collection.find({"_id": {"$in": id_batch}})
            }
            docs = [mongo_to_es_v3_full(rows_by_id[row_id]) for row_id in id_batch if row_id in rows_by_id]
            if not docs:
                continue
            ok, _failed = es.bulk(docs)
            appended += ok

        es.refresh()
        es_count_after = int(es.request("GET", f"/{es.index}/_count").get("count", 0))
        _log(
            f"reconcile mongo_count={mongo_count} es_count_before={es_count_before} "
            f"appended={appended} es_count_after={es_count_after}"
        )
        return {
            "mongo_count": mongo_count,
            "es_count_before": es_count_before,
            "missing_count": len(missing_ids),
            "appended": appended,
            "es_count_after": es_count_after,
        }
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile MongoDB documents missing from Elasticsearch")
    parser.add_argument("--batch-size", type=int, default=5000)
    args = parser.parse_args()
    reconcile(args.batch_size)


if __name__ == "__main__":
    main()
