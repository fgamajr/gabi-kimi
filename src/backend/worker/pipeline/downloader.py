"""Downloader pipeline module — fetches QUEUED DOU ZIP files.

Downloads ZIP files from in.gov.br with rate limiting (max 5 req/s),
computes SHA256 hashes, and transitions files through the registry
state machine.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from pathlib import Path
from typing import Any

import requests

from src.backend.ingest.zip_downloader import _build_session, _random_ua
from src.backend.worker.registry import FileStatus, Registry

logger = logging.getLogger(__name__)

RATE_LIMIT_DELAY = 0.2  # 1/5 = 0.2s -> max 5 req/s
DEFAULT_DOWNLOAD_DIR = "/data/tmp"


def _download_file(
    url: str,
    session: requests.Session | None = None,
) -> tuple[bytes | None, str | None]:
    """Download a file from URL. Returns (content, error_message).

    Uses sync requests with random UA rotation.
    """
    own_session = session is None
    if own_session:
        session = _build_session()

    try:
        resp = session.get(
            url,
            headers={"User-Agent": _random_ua()},
            timeout=120,
            stream=False,
        )
        resp.raise_for_status()
        return resp.content, None
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        return None, f"HTTP {status}"
    except Exception as e:
        return None, str(e)
    finally:
        if own_session and session:
            session.close()


async def run_download(
    registry: Registry,
    run_id: str,
    download_dir: str = DEFAULT_DOWNLOAD_DIR,
) -> dict[str, Any]:
    """Download all QUEUED files from registry.

    Args:
        registry: SQLite registry instance
        run_id: Pipeline run identifier for logging
        download_dir: Directory to save downloaded ZIPs

    Returns:
        Stats dict: {"downloaded": N, "failed": M}
    """
    download_path = Path(download_dir)
    download_path.mkdir(parents=True, exist_ok=True)

    queued_files = await registry.get_files_by_status(FileStatus.QUEUED)
    downloaded = 0
    failed = 0

    session = _build_session()
    try:
        for i, file_rec in enumerate(queued_files):
            file_id = file_rec["id"]
            filename = file_rec["filename"]
            file_url = file_rec.get("file_url") or ""

            if not file_url:
                # Construct URL from folder_id if available
                folder_id = file_rec.get("folder_id")
                if folder_id:
                    file_url = f"https://www.in.gov.br/documents/49035712/{folder_id}/{filename}"
                else:
                    await registry.update_status(file_id, FileStatus.DOWNLOADING)
                    await registry.update_status(file_id, FileStatus.DOWNLOAD_FAILED)
                    await registry.update_file_fields(file_id, error_message="No download URL available")
                    await registry.add_log_entry(run_id, file_id, "ERROR", "No download URL")
                    failed += 1
                    continue

            # Transition to DOWNLOADING
            await registry.update_status(file_id, FileStatus.DOWNLOADING)

            # Download file
            content, error = _download_file(file_url, session=session)

            if content is not None:
                # Save to disk
                local_path = download_path / filename
                local_path.write_bytes(content)

                # Compute SHA256
                sha256 = hashlib.sha256(content).hexdigest()
                file_size = len(content)

                # Update registry
                await registry.update_file_fields(
                    file_id,
                    sha256=sha256,
                    file_size_bytes=file_size,
                )
                await registry.update_status(file_id, FileStatus.DOWNLOADED)
                await registry.add_log_entry(
                    run_id, file_id, "INFO",
                    f"Downloaded {filename}: {file_size:,} bytes, sha256={sha256[:16]}..."
                )
                downloaded += 1
            else:
                # Download failed
                await registry.update_status(file_id, FileStatus.DOWNLOAD_FAILED)
                await registry.update_file_fields(file_id, error_message=error)
                await registry.add_log_entry(
                    run_id, file_id, "ERROR",
                    f"Download failed for {filename}: {error}"
                )
                failed += 1

            # Rate limit between downloads
            if i < len(queued_files) - 1:
                await asyncio.sleep(RATE_LIMIT_DELAY)

    finally:
        session.close()

    return {"downloaded": downloaded, "failed": failed}
