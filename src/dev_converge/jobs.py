from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from pymongo import ASCENDING, MongoClient, ReturnDocument

from src.dev_converge.config import settings

_client: MongoClient | None = None
_collection = None


def _now() -> datetime:
    return datetime.now(UTC)


def _connect():
    global _client, _collection
    if _collection is not None:
        return _collection
    _client = MongoClient(
        settings.DEV_CONVERGE_MONGO_STRING,
        readPreference="primary",
    )
    db = _client[settings.DEV_CONVERGE_DB_NAME]
    _collection = db["dev_converge_jobs"]
    return _collection


def collection():
    return _connect()


def ensure_indexes() -> None:
    coll = collection()
    coll.create_index([("job_id", ASCENDING)], unique=True)
    coll.create_index([("status", ASCENDING), ("created_at", ASCENDING)])
    coll.create_index([("updated_at", ASCENDING)])


def _job_dir(job_id: str) -> Path:
    path = settings.data_root / "jobs" / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json_artifact(job_id: str, filename: str, payload: Any) -> str:
    target = _job_dir(job_id) / filename
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return str(target)


def _preview_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        preview: dict[str, Any] = {}
        for key in (
            "job_type",
            "task",
            "result",
            "summary",
            "output",
            "agent",
            "agents",
            "status",
        ):
            value = result.get(key)
            if value:
                preview[key] = value
        if not preview:
            preview = {key: result[key] for key in list(result.keys())[:5]}
        return preview
    if isinstance(result, list):
        return {"items": len(result), "preview": result[:2]}
    return {"value": str(result)[:500]}


def create_job(
    job_type: str,
    payload: dict[str, Any],
    token_label: str,
    catalog_redacted: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Insert a job record into MongoDB. Never stores api_keys — pass redact_catalog() output."""
    ensure_indexes()
    now = _now()
    job_id = uuid4().hex
    doc: dict[str, Any] = {
        "job_id": job_id,
        "job_type": job_type,
        "status": "queued",
        "payload": payload,
        "token_label": token_label or "anonymous",
        "agents": catalog_redacted or [],
        "attempts": 0,
        "created_at": now,
        "updated_at": now,
    }
    collection().insert_one(doc)
    return serialize_job(doc, include_result=False)


def mark_running_as_failed(reason: str) -> int:
    """Mark all in-flight jobs as failed — call at service startup after a restart."""
    result = collection().update_many(
        {"status": {"$in": ["queued", "running"]}},
        {
            "$set": {
                "status": "failed",
                "error": reason,
                "updated_at": _now(),
            }
        },
    )
    return result.modified_count


def complete_job(job_id: str, result: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    artifact_path = write_json_artifact(job_id, "result.json", result)
    preview = _preview_payload(result)
    doc = collection().find_one_and_update(
        {"job_id": job_id},
        {
            "$set": {
                "status": "succeeded",
                "result_preview": preview,
                "artifact_paths": {"result": artifact_path},
                "finished_at": now,
                "updated_at": now,
                "error": None,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    return serialize_job(doc, include_result=False)


def fail_job(job_id: str, error: str) -> dict[str, Any] | None:
    now = _now()
    artifact_path = write_json_artifact(
        job_id,
        "error.json",
        {"error": error, "finished_at": now.isoformat()},
    )
    doc = collection().find_one_and_update(
        {"job_id": job_id},
        {
            "$set": {
                "status": "failed",
                "error": error,
                "artifact_paths": {"error": artifact_path},
                "finished_at": now,
                "updated_at": now,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    return serialize_job(doc, include_result=False) if doc else None


def get_job(job_id: str) -> dict[str, Any] | None:
    ensure_indexes()
    return collection().find_one({"job_id": job_id})


def expire_old_jobs() -> int:
    ensure_indexes()
    cutoff = _now() - timedelta(hours=settings.DEV_CONVERGE_JOB_RETENTION_HOURS)
    expirable = list(
        collection().find(
            {
                "status": {"$in": ["succeeded", "failed", "cancelled"]},
                "updated_at": {"$lt": cutoff},
            },
            {"job_id": 1},
        )
    )
    if not expirable:
        return 0
    job_ids = [doc["job_id"] for doc in expirable]
    for job_id in job_ids:
        artifact_dir = settings.data_root / "jobs" / job_id
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir, ignore_errors=True)
    collection().update_many(
        {"job_id": {"$in": job_ids}},
        {
            "$set": {
                "status": "expired",
                "expired_at": _now(),
                "updated_at": _now(),
            },
            "$unset": {"artifact_paths": "", "result_preview": ""},
        },
    )
    return len(job_ids)


def queue_stats() -> dict[str, int]:
    ensure_indexes()
    return {
        "queued": collection().count_documents({"status": "queued"}),
        "running": collection().count_documents({"status": "running"}),
        "succeeded": collection().count_documents({"status": "succeeded"}),
        "failed": collection().count_documents({"status": "failed"}),
        "expired": collection().count_documents({"status": "expired"}),
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items() if key != "_id"}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def serialize_job(
    job: dict[str, Any] | None, include_result: bool = False
) -> dict[str, Any]:
    if not job:
        return {"found": False}
    result = _json_safe(job)
    result["found"] = True
    if include_result:
        artifact_path = (
            job.get("artifact_paths", {}).get("result")
            if isinstance(job.get("artifact_paths"), dict)
            else None
        )
        if artifact_path:
            path = Path(artifact_path)
            if path.exists():
                try:
                    result["result"] = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    result["result"] = {
                        "error": f"Could not decode artifact at {artifact_path}"
                    }
    return result
