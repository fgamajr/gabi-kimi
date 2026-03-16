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
import shutil
from typing import Any

from src.backend.core.config import settings
from src.backend.data.db import MongoDB
from src.backend.ingest.dou_processor import DouProcessor
from src.backend.ingest.es_indexer import ESClient, _counts, _run_sync
from src.backend.ingest.sync_dou import ingest_documents

_SCHEMA_TO_DEFAULT_INDEX = {
    "v2_minimal": "gabi_documents_v2_minimal_canary",
    "v2_search": "gabi_documents_v2_search_canary",
}
_REPO_ROOT = Path(__file__).resolve().parents[3]
_REGISTRY_PATH = _REPO_ROOT / "ops" / "data" / "dou_catalog_registry.json"
_MULTIPART_FIXTURE_DIR = _REPO_ROOT / "ops" / "fixtures" / "reindex_v2_multipart"


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


def _index_exists(es: ESClient) -> bool:
    resp = es.client.request(method="HEAD", url=f"{es.url}/{es.index}")
    if resp.status_code == 404:
        return False
    resp.raise_for_status()
    return True


def _run_preflight(args: argparse.Namespace) -> None:
    zip_files = _resolve_zip_paths(args.zip, args.glob)
    pipeline_tmp = Path(settings.PIPELINE_TMP)
    disk_target = pipeline_tmp if pipeline_tmp.exists() else _REPO_ROOT
    disk_usage = shutil.disk_usage(disk_target)
    free_gb = round(disk_usage.free / (1024**3), 2)

    registry_exists = _REGISTRY_PATH.exists()
    fixture_files = sorted(_MULTIPART_FIXTURE_DIR.glob("*.xml"))
    multipart_fixture_ok = len(fixture_files) >= 3

    db = MongoDB.get_db()
    source_collection = db[args.source_collection]
    target_collection = db[args.mongo_collection]
    source_count = source_collection.count_documents({})
    target_count = target_collection.count_documents({})

    failures: list[str] = []
    warnings: list[str] = []

    if not registry_exists:
        failures.append(f"missing_registry:{_REGISTRY_PATH}")
    if free_gb < args.min_free_gb:
        failures.append(f"low_disk:{free_gb}GB<{args.min_free_gb}GB")
    elif free_gb < args.warn_free_gb:
        warnings.append(f"low_disk_warning:{free_gb}GB<{args.warn_free_gb}GB")
    if args.require_zip_sample and not zip_files:
        failures.append("no_zip_sample")
    elif not zip_files:
        warnings.append("no_zip_sample")
    if not multipart_fixture_ok:
        failures.append("missing_multipart_fixtures")
    if source_count == 0:
        failures.append(f"empty_source_collection:{args.source_collection}")

    with _temporary_env(
        {
            "ES_DOC_SCHEMA": args.schema,
            "ES_INDEX": args.es_index,
            "ES_TIMEOUT_SEC": str(args.es_timeout_sec),
        }
    ):
        es = ESClient()
        health = es.request("GET", "/_cluster/health")
        cluster_status = health.get("status")
        if cluster_status == "red":
            failures.append("es_cluster_red")
        elif cluster_status != "green":
            warnings.append(f"es_cluster_{cluster_status}")

        index_exists = _index_exists(es)
        es_count = 0
        if index_exists:
            try:
                es.refresh()
                es_count = int(es.request("GET", f"/{es.index}/_count").get("count", 0))
            except Exception as exc:
                warnings.append(f"es_count_unavailable:{exc}")

        disk_threshold_enabled = None
        try:
            cluster_settings = es.request("GET", "/_cluster/settings?include_defaults=true")
            disk_threshold_enabled = (
                cluster_settings.get("transient", {})
                .get("cluster", {})
                .get("routing", {})
                .get("allocation", {})
                .get("disk", {})
                .get("threshold_enabled")
            )
            if disk_threshold_enabled is None:
                disk_threshold_enabled = (
                    cluster_settings.get("defaults", {})
                    .get("cluster", {})
                    .get("routing", {})
                    .get("allocation", {})
                    .get("disk", {})
                    .get("threshold_enabled")
                )
        except Exception as exc:
            warnings.append(f"es_settings_unavailable:{exc}")

    report = {
        "schema": args.schema,
        "source_collection": args.source_collection,
        "mongo_collection": args.mongo_collection,
        "es_index": args.es_index,
        "registry_path": str(_REGISTRY_PATH),
        "registry_exists": registry_exists,
        "zip_sample_count": len(zip_files),
        "zip_samples": [str(path) for path in zip_files[:10]],
        "multipart_fixture_count": len(fixture_files),
        "multipart_fixture_dir": str(_MULTIPART_FIXTURE_DIR),
        "disk": {
            "path": str(disk_target),
            "free_gb": free_gb,
            "warn_free_gb": args.warn_free_gb,
            "min_free_gb": args.min_free_gb,
        },
        "mongo": {
            "source_count": source_count,
            "target_count": target_count,
        },
        "elasticsearch": {
            "cluster_status": cluster_status,
            "index_exists": index_exists,
            "index_count": es_count,
            "disk_threshold_enabled": disk_threshold_enabled,
        },
        "warnings": warnings,
        "failures": failures,
        "ok": not failures,
    }

    print(json.dumps(report, ensure_ascii=True, indent=2), flush=True)
    if args.report:
        _write_report(Path(args.report), report)
    if failures:
        raise SystemExit(1)


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

    preflight = sub.add_parser("preflight", help="Check readiness for a broader v2 reindex/backfill")
    preflight.add_argument("--zip", action="append", default=[], help="ZIP path to validate against the current environment")
    preflight.add_argument("--glob", action="append", default=[], help="Glob pattern for ZIP sample validation")
    preflight.add_argument("--require-zip-sample", action="store_true", help="Fail if no ZIP sample resolves")
    preflight.add_argument("--source-collection", default="documents", help="Source Mongo collection for raw corpus")
    preflight.add_argument("--mongo-collection", default="documents_v2_canary", help="Target Mongo collection for reconstructed docs")
    preflight.add_argument("--schema", choices=sorted(_SCHEMA_TO_DEFAULT_INDEX), default="v2_search", help="ES schema to validate")
    preflight.add_argument("--es-index", help="ES index name override")
    preflight.add_argument("--es-timeout-sec", type=int, default=120, help="Elasticsearch HTTP timeout in seconds")
    preflight.add_argument("--warn-free-gb", type=float, default=8.0, help="Warn when free disk drops below this threshold")
    preflight.add_argument("--min-free-gb", type=float, default=4.0, help="Fail when free disk drops below this threshold")
    preflight.add_argument("--report", help="Optional JSON report output path")
    preflight.set_defaults(func=_run_preflight)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    if getattr(args, "cmd", None) in {"local-canary", "preflight"} and not args.es_index:
        args.es_index = _SCHEMA_TO_DEFAULT_INDEX[args.schema]
    args.func(args)


if __name__ == "__main__":
    main()
