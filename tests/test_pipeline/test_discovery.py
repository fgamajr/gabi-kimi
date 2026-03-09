"""Tests for pipeline discovery module."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.worker.registry import FileStatus, Registry
from src.backend.worker.pipeline.discovery import run_discovery


pytestmark = pytest.mark.asyncio


async def test_discovery_returns_new_files_count(registry):
    """run_discovery with mocked Liferay API returns new files count and inserts them into registry."""
    mock_folders = [
        {"folderId": 12345, "name": "Janeiro 2026"},
    ]
    mock_files = [
        {"fileName": "S01012026.zip", "fileEntryId": 100, "title": "S01012026.zip"},
        {"fileName": "S02012026.zip", "fileEntryId": 101, "title": "S02012026.zip"},
    ]

    with patch("src.backend.worker.pipeline.discovery._fetch_liferay_folders", new_callable=AsyncMock) as mock_fold, \
         patch("src.backend.worker.pipeline.discovery._fetch_liferay_files", new_callable=AsyncMock) as mock_fls:
        mock_fold.return_value = mock_folders
        mock_fls.return_value = mock_files

        run_id = await registry.create_pipeline_run("discovery")
        result = await run_discovery(registry, run_id, "http://localhost:9200")

    assert result["new_files"] == 2
    files = await registry.get_files_by_status(FileStatus.DISCOVERED)
    assert len(files) == 2


async def test_discovery_skips_existing_files(registry):
    """Files already in registry are skipped (not duplicated)."""
    # Pre-insert a file
    await registry.insert_file("S01012026.zip", "do1", "2026-01")

    mock_folders = [{"folderId": 12345, "name": "Janeiro 2026"}]
    mock_files = [
        {"fileName": "S01012026.zip", "fileEntryId": 100, "title": "S01012026.zip"},
        {"fileName": "S02012026.zip", "fileEntryId": 101, "title": "S02012026.zip"},
    ]

    with patch("src.backend.worker.pipeline.discovery._fetch_liferay_folders", new_callable=AsyncMock) as mock_fold, \
         patch("src.backend.worker.pipeline.discovery._fetch_liferay_files", new_callable=AsyncMock) as mock_fls:
        mock_fold.return_value = mock_folders
        mock_fls.return_value = mock_files

        run_id = await registry.create_pipeline_run("discovery")
        result = await run_discovery(registry, run_id, "http://localhost:9200")

    assert result["new_files"] == 1
    assert result["existing_files"] == 1


async def test_discovery_rate_limiting_semaphore(registry):
    """Rate limiting semaphore caps concurrent requests to 5."""
    from src.backend.worker.pipeline.discovery import MAX_CONCURRENT_REQUESTS
    assert MAX_CONCURRENT_REQUESTS == 5


async def test_discovery_fallback_head_probes(registry):
    """Fallback to HEAD probes when Liferay API returns error."""
    with patch("src.backend.worker.pipeline.discovery._fetch_liferay_folders", new_callable=AsyncMock) as mock_fold, \
         patch("src.backend.worker.pipeline.discovery._probe_head_fallback", new_callable=AsyncMock) as mock_probe:
        mock_fold.side_effect = Exception("Liferay API unavailable")
        mock_probe.return_value = [
            {"fileName": "S01012026.zip", "section": "do1", "year_month": "2026-01"},
        ]

        run_id = await registry.create_pipeline_run("discovery")
        result = await run_discovery(registry, run_id, "http://localhost:9200")

    assert result["new_files"] == 1
    assert result.get("fallback_used", False) is True


async def test_discovery_filename_parsing(registry):
    """Filename parsing extracts correct section and year_month from S01022026.zip."""
    from src.backend.worker.pipeline.discovery import parse_dou_filename

    section, year_month = parse_dou_filename("S01022026.zip")
    assert section == "do1"
    assert year_month == "2026-02"

    section2, ym2 = parse_dou_filename("S03112025.zip")
    assert section2 == "do3"
    assert ym2 == "2025-11"
