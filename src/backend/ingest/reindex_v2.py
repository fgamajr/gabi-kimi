"""V2 reindex canary/backfill orchestration helpers.

Usage:
  python3 -m src.backend.ingest.reindex_v2 local-canary --glob 'ops/data/raw_export/2002/01/*.zip'
  python3 -m src.backend.ingest.reindex_v2 local-canary --zip ops/data/raw_export/2002/01/S01012002.zip
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
from typing import Any

from src.backend.data.db import MongoDB
from src.backend.ingest.dou_processor import DouProcessor
from src.backend.ingest.es_indexer import ESClient, _counts, _run_sync
from src.backend.ingest.sync_dou import ingest_documents

_SCHEMA_TO_DEFAULT_INDEX = {
    "v2_minimal": "gabi_documents_v2_minimal_canary",
    "v2_search": "gabi_documents_v2_search_canary",
}


@contextmanager
def _temporary_env(updates: dict[str, str | None]):
    original: dict[str, str | None] = {}
    try:
        for key, value in updates.items():
            original[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _resolve_zip_paths(zip_paths: list[str], glob_patterns: list[str]) -> list[Path]:
    resolved: list[Path] = []
    seen: set[Path] = set()

    for raw in zip_paths:
        path = Path(raw)
        if path.exists() and path.is_file():
            real = path.resolve()
            if real not in seen:
                resolved.append(real)
                seen.add(real)

    for pattern in glob_patterns:
        for path in sorted(Path().glob(pattern)):
            if path.is_file():
                real = path.resolve()
                if real not in seen:
                    resolved.append(real)
                    seen.add(real)

    return resolved


def _sample_report(collection) -> dict[str, Any]:
    placeholder_primary = collection.count_documents(
        {"primary_signer": {"$regex": r"^[\(]?\s*[Oo]f\.\s*[Ee]l\."}}
    )
    return {
        "mongo_count": collection.count_documents({}),
        "distinct_logical_doc_id": len(collection.distinct("logical_doc_id")),
        "multipart_docs": collection.count_documents({"is_multipart": True}),
        "page_fragment_merged_docs": collection.count_documents({"was_page_fragment_merged": True}),
        "blob_split_docs": collection.count_documents({"was_blob_split": True}),
        "multi_signer_docs": collection.count_documents({"has_multiple_signers": True}),
        "normative_reference_docs": collection.count_documents({"reference_count": {"$gt": 0}}),
        "placeholder_primary_signer_docs": placeholder_primary,
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _run_local_canary(args: argparse.Namespace) -> None:
    zip_files = _resolve_zip_paths(args.zip, args.glob)
    if not zip_files:
        raise SystemExit("No ZIP files matched the provided --zip/--glob inputs")

    processor = DouProcessor()
    db = MongoDB.get_db()
    collection = db[args.mongo_collection]

    if args.drop_collection:
        collection.drop()

    with _temporary_env({"MONGO_COLLECTION": args.mongo_collection}):
        for zip_path in zip_files:
            docs = processor.process_zip(zip_path.read_bytes(), zip_path.name)
            print(f"[reindex-v2] {zip_path} -> {len(docs)} docs", flush=True)
            ingest_documents(docs)

    mongo_report = _sample_report(collection)

    cursor_path = Path(args.cursor)
    with _temporary_env(
        {
            "MONGO_COLLECTION": args.mongo_collection,
            "ES_DOC_SCHEMA": args.schema,
            "ES_INDEX": args.es_index,
            "ES_TIMEOUT_SEC": str(args.es_timeout_sec),
        }
    ):
        _run_sync(
            reset_cursor=True,
            recreate_index=args.recreate_index,
            batch_size=args.batch_size,
            cursor_path=cursor_path,
        )
        es = ESClient()
        es.refresh()
        mongo_count, es_count = _counts(collection, es)

    report = {
        "mongo_collection": args.mongo_collection,
        "schema": args.schema,
        "es_index": args.es_index,
        "zip_files": [str(path) for path in zip_files],
        "zip_count": len(zip_files),
        "mongo": mongo_report,
        "parity": {
            "mongo_count": mongo_count,
            "es_count": es_count,
            "count_delta": mongo_count - es_count,
        },
        "cursor_path": str(cursor_path),
    }
    print(json.dumps(report, ensure_ascii=True, indent=2), flush=True)

    if args.report:
        _write_report(Path(args.report), report)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="V2 reindex helpers for local canary and backfill runs")
    sub = parser.add_subparsers(dest="cmd", required=True)

    canary = sub.add_parser("local-canary", help="Ingest local ZIPs into a v2 Mongo collection and ES canary index")
    canary.add_argument("--zip", action="append", default=[], help="ZIP path to ingest (repeatable)")
    canary.add_argument("--glob", action="append", default=[], help="Glob pattern for ZIPs (repeatable)")
    canary.add_argument("--mongo-collection", default="documents_v2_canary", help="Mongo collection for reconstructed docs")
    canary.add_argument("--schema", choices=sorted(_SCHEMA_TO_DEFAULT_INDEX), default="v2_minimal", help="ES schema to use for the canary index")
    canary.add_argument("--es-index", help="ES index name override")
    canary.add_argument("--cursor", default="/tmp/es_sync_cursor_v2_canary.json", help="Cursor file for ES backfill")
    canary.add_argument("--batch-size", type=int, default=2000, help="ES bulk batch size")
    canary.add_argument("--es-timeout-sec", type=int, default=120, help="Elasticsearch HTTP timeout in seconds")
    canary.add_argument("--drop-collection", action="store_true", help="Drop the target Mongo collection before ingest")
    canary.add_argument("--recreate-index", action="store_true", help="Recreate the target ES index before backfill")
    canary.add_argument("--report", help="Optional JSON report output path")
    canary.set_defaults(func=_run_local_canary)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    if getattr(args, "cmd", None) == "local-canary" and not args.es_index:
        args.es_index = _SCHEMA_TO_DEFAULT_INDEX[args.schema]
    args.func(args)


if __name__ == "__main__":
    main()
