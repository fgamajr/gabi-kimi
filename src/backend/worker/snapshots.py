"""ES snapshot management — daily backups to Tigris (S3-compatible).

Registers a Tigris S3 snapshot repository in Elasticsearch and creates
daily named snapshots of the gabi_documents_v1 index.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

REPO_NAME = "tigris_backup"
SNAPSHOT_BUCKET = "gabi-dou-es-snapshots"
SNAPSHOT_ENDPOINT = "fly.storage.tigris.dev"
INDEX_NAME = "gabi_documents_v1"


async def register_snapshot_repo(es_url: str) -> bool:
    """Register Tigris S3 snapshot repository in Elasticsearch.

    Called once during worker startup. Logs and returns False on failure
    (does not crash the worker).
    """
    url = f"{es_url}/_snapshot/{REPO_NAME}"
    body = {
        "type": "s3",
        "settings": {
            "bucket": SNAPSHOT_BUCKET,
            "endpoint": SNAPSHOT_ENDPOINT,
            "protocol": "https",
            "path_style_access": True,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.put(url, json=body)
            if resp.status_code in (200, 201):
                logger.info("Snapshot repo '%s' registered successfully", REPO_NAME)
                return True
            else:
                logger.warning(
                    "Failed to register snapshot repo: %s %s",
                    resp.status_code,
                    resp.text,
                )
                return False
    except Exception:
        logger.warning("Could not reach ES for snapshot repo registration", exc_info=True)
        return False


async def create_snapshot(es_url: str) -> bool:
    """Create a daily named snapshot of the documents index.

    Snapshot name: daily-YYYYMMDD-HHMM. Logs errors but does not crash.
    """
    now = datetime.now(timezone.utc)
    snap_name = f"daily-{now.strftime('%Y%m%d-%H%M')}"
    url = f"{es_url}/_snapshot/{REPO_NAME}/{snap_name}"
    body = {
        "indices": INDEX_NAME,
        "include_global_state": False,
    }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.put(url, json=body)
            if resp.status_code in (200, 201, 202):
                logger.info("Snapshot '%s' created successfully", snap_name)
                return True
            else:
                logger.error(
                    "Snapshot '%s' failed: %s %s",
                    snap_name,
                    resp.status_code,
                    resp.text,
                )
                return False
    except Exception:
        logger.error("Snapshot creation failed", exc_info=True)
        return False
