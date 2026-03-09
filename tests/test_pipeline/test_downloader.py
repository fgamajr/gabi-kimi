"""Tests for pipeline downloader module."""
from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.worker.registry import FileStatus, Registry
from src.backend.worker.pipeline.downloader import run_download


pytestmark = pytest.mark.asyncio


async def _setup_queued_file(registry, filename="S01012026.zip"):
    """Helper: insert a file and transition to QUEUED."""
    file_id = await registry.insert_file(filename, "do1", "2026-01", "12345")
    await registry.update_status(file_id, FileStatus.QUEUED)
    return file_id


async def test_download_transitions_to_downloaded(registry, tmp_path):
    """run_download fetches QUEUED files and transitions to DOWNLOADED."""
    file_id = await _setup_queued_file(registry)

    fake_content = b"PK\x03\x04fake zip content"

    with patch("src.backend.worker.pipeline.downloader._download_file") as mock_dl:
        mock_dl.return_value = (fake_content, None)

        run_id = await registry.create_pipeline_run("download")
        result = await run_download(registry, run_id, download_dir=str(tmp_path))

    assert result["downloaded"] == 1
    assert result["failed"] == 0

    f = await registry.get_file(file_id)
    assert f["status"] == FileStatus.DOWNLOADED.value


async def test_download_failure_transitions_to_download_failed(registry, tmp_path):
    """Failed download transitions file to DOWNLOAD_FAILED with error_message."""
    file_id = await _setup_queued_file(registry)

    with patch("src.backend.worker.pipeline.downloader._download_file") as mock_dl:
        mock_dl.return_value = (None, "HTTP 503 Service Unavailable")

        run_id = await registry.create_pipeline_run("download")
        result = await run_download(registry, run_id, download_dir=str(tmp_path))

    assert result["failed"] == 1
    f = await registry.get_file(file_id)
    assert f["status"] == FileStatus.DOWNLOAD_FAILED.value
    assert f["error_message"] is not None


async def test_download_stores_sha256_and_size(registry, tmp_path):
    """SHA256 hash and file_size_bytes are stored in registry after download."""
    file_id = await _setup_queued_file(registry)

    fake_content = b"PK\x03\x04fake zip content here"
    expected_sha = hashlib.sha256(fake_content).hexdigest()

    with patch("src.backend.worker.pipeline.downloader._download_file") as mock_dl:
        mock_dl.return_value = (fake_content, None)

        run_id = await registry.create_pipeline_run("download")
        await run_download(registry, run_id, download_dir=str(tmp_path))

    f = await registry.get_file(file_id)
    assert f["sha256"] == expected_sha
    assert f["file_size_bytes"] == len(fake_content)


async def test_download_rate_limiting(registry):
    """Rate limiting enforces max 5 req/s between downloads."""
    from src.backend.worker.pipeline.downloader import RATE_LIMIT_DELAY
    assert RATE_LIMIT_DELAY == 0.2  # 1/5 = 0.2s between requests


async def test_download_uses_inlabs_for_recent_source(registry, tmp_path, monkeypatch):
    """INLABS-sourced files are downloaded through the authenticated client path."""
    monkeypatch.setenv("INLABS_EMAIL", "fernando@example.com")
    monkeypatch.setenv("INLABS_PASSWORD", "secret")

    file_id = await registry.insert_file(
        "2026-03-09-DO1.zip",
        "do1",
        "2026-03",
        publication_date="2026-03-09",
        source="inlabs",
        file_url="https://inlabs.in.gov.br/index.php?p=2026-03-09&dl=2026-03-09-DO1.zip",
    )
    await registry.update_status(file_id, FileStatus.QUEUED)

    async def fake_download(publication_date, section, destination, *, today=None):
        destination.write_bytes(b"PK\x03\x04inlabs content")

    with patch("src.backend.worker.pipeline.downloader.INLabsClient.download", new=AsyncMock(side_effect=fake_download)):
        run_id = await registry.create_pipeline_run("download")
        result = await run_download(registry, run_id, download_dir=str(tmp_path))

    assert result["downloaded"] == 1
    file_rec = await registry.get_file(file_id)
    assert file_rec["status"] == FileStatus.DOWNLOADED.value
