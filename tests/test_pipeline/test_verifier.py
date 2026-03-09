"""Tests for pipeline verifier module."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.worker.registry import FileStatus, Registry
from src.backend.worker.pipeline.verifier import run_verify


pytestmark = pytest.mark.asyncio


async def _setup_ingested_file(registry, filename="S01012026.zip", doc_count=100):
    """Insert file and transition to INGESTED with a doc_count."""
    file_id = await registry.insert_file(filename, "do1", "2026-01")
    await registry.update_status(file_id, FileStatus.QUEUED)
    await registry.update_status(file_id, FileStatus.DOWNLOADING)
    await registry.update_status(file_id, FileStatus.DOWNLOADED)
    await registry.update_status(file_id, FileStatus.EXTRACTING)
    await registry.update_status(file_id, FileStatus.EXTRACTED)
    await registry.update_status(file_id, FileStatus.INGESTING)
    await registry.update_status(file_id, FileStatus.INGESTED)
    await registry.update_file_fields(file_id, doc_count=doc_count)
    return file_id


async def test_verify_match_transitions_to_verified(registry):
    """run_verify queries ES doc count and transitions to VERIFIED on match."""
    file_id = await _setup_ingested_file(registry, doc_count=100)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"count": 100}
    mock_response.raise_for_status = MagicMock()

    with patch("src.backend.worker.pipeline.verifier.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        run_id = await registry.create_pipeline_run("verify")
        result = await run_verify(registry, run_id, "http://localhost:9200")

    assert result["verified"] == 1
    assert result["failed"] == 0

    f = await registry.get_file(file_id)
    assert f["status"] == FileStatus.VERIFIED.value


async def test_verify_mismatch_transitions_to_verify_failed(registry):
    """Mismatch (outside 5% tolerance) transitions to VERIFY_FAILED."""
    file_id = await _setup_ingested_file(registry, doc_count=100)

    # ES returns 80 docs (20% off - outside 5% tolerance)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"count": 80}
    mock_response.raise_for_status = MagicMock()

    with patch("src.backend.worker.pipeline.verifier.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        run_id = await registry.create_pipeline_run("verify")
        result = await run_verify(registry, run_id, "http://localhost:9200")

    assert result["failed"] == 1
    f = await registry.get_file(file_id)
    assert f["status"] == FileStatus.VERIFY_FAILED.value


async def test_verify_stats_return(registry):
    """Stats return verified and failed counts."""
    await _setup_ingested_file(registry, filename="good.zip", doc_count=50)
    await _setup_ingested_file(registry, filename="bad.zip", doc_count=100)

    def _make_response(count):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"count": count}
        resp.raise_for_status = MagicMock()
        return resp

    call_count = 0

    async def mock_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if "good.zip" in str(url) or call_count == 1:
            return _make_response(50)  # matches
        return _make_response(50)  # 100 expected, 50 returned -> fail

    with patch("src.backend.worker.pipeline.verifier.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = mock_get
        mock_client_cls.return_value = mock_client

        run_id = await registry.create_pipeline_run("verify")
        result = await run_verify(registry, run_id, "http://localhost:9200")

    assert result["verified"] + result["failed"] == 2
