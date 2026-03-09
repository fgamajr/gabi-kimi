"""Tests for the catalog reconciler (P4 — Liferay monthly fallback)."""

import pytest
from unittest.mock import AsyncMock

from src.backend.worker.registry import FileStatus, Registry
from src.backend.worker.reconciler import (
    run_reconciliation,
    transition_aged_failures_to_fallback,
    _date_from_publication_or_month,
)


pytestmark = pytest.mark.asyncio


async def test_transition_aged_failures_to_fallback(registry):
    """DOWNLOAD_FAILED files past window and at max retries transition to FALLBACK_PENDING."""
    file_id = await registry.insert_file(
        "S01012020.zip", "do1", "2020-01", publication_date="2020-01-15"
    )
    await registry.update_status(file_id, FileStatus.QUEUED)
    await registry.update_status(file_id, FileStatus.DOWNLOADING)
    await registry.update_status(file_id, FileStatus.DOWNLOAD_FAILED)
    async with registry.get_db() as db:
        await db.execute(
            "UPDATE dou_files SET retry_count = 3 WHERE id = ?", (file_id,)
        )
        await db.commit()

    n = await transition_aged_failures_to_fallback(registry)
    assert n == 1
    row = await registry.get_file(file_id)
    assert row["status"] == "FALLBACK_PENDING"


async def test_transition_aged_failures_skips_recent(registry):
    """Files still within INLABS window are not transitioned."""
    from datetime import date, timedelta
    recent = (date.today() - timedelta(days=5)).isoformat()
    file_id = await registry.insert_file(
        "S01012026.zip", "do1", "2026-01", publication_date=recent
    )
    await registry.update_status(file_id, FileStatus.QUEUED)
    await registry.update_status(file_id, FileStatus.DOWNLOADING)
    await registry.update_status(file_id, FileStatus.DOWNLOAD_FAILED)
    async with registry.get_db() as db:
        await db.execute(
            "UPDATE dou_files SET retry_count = 3 WHERE id = ?", (file_id,)
        )
        await db.commit()

    n = await transition_aged_failures_to_fallback(registry)
    assert n == 0
    row = await registry.get_file(file_id)
    assert row["status"] == "DOWNLOAD_FAILED"


async def test_date_from_publication_or_month():
    """_date_from_publication_or_month parses publication_date and year_month."""
    assert _date_from_publication_or_month("2026-01-15", "2026-01").year == 2026
    assert _date_from_publication_or_month(None, "2025-06").month == 6


async def test_run_reconciliation_no_eligible_months(registry):
    """run_reconciliation with no FALLBACK_ELIGIBLE months returns zeros."""
    stats = await run_reconciliation(registry)
    assert stats["months_checked"] == 0
    assert stats["recovered_files"] == 0
    assert stats["recovered_months"] == 0


async def test_run_reconciliation_probes_and_recovers(registry, monkeypatch):
    """When Liferay URL returns 200, file is updated and transitioned to DOWNLOADING."""
    await registry.catalog_month_upsert(
        "2020-01", folder_id=12345, group_id="49035712", source_of_truth="json_bootstrap"
    )
    file_id = await registry.insert_file(
        "S01012020.zip", "do1", "2020-01",
        folder_id=12345,
        file_url="https://inlabs.example/old.zip",
    )
    await registry.update_status(file_id, FileStatus.QUEUED)
    await registry.update_status(file_id, FileStatus.DOWNLOADING)
    await registry.update_status(file_id, FileStatus.DOWNLOAD_FAILED)
    await registry.update_status(file_id, FileStatus.FALLBACK_PENDING)
    async with registry.get_db() as db:
        await db.execute(
            "UPDATE dou_catalog_months SET catalog_status = 'FALLBACK_ELIGIBLE' WHERE year_month = '2020-01'"
        )
        await db.commit()

    monkeypatch.setattr(
        "src.backend.worker.reconciler._probe_liferay_url",
        AsyncMock(return_value=True),
    )
    stats = await run_reconciliation(registry)

    assert stats["recovered_files"] == 1
    assert stats["recovered_months"] == 1
    row = await registry.get_file(file_id)
    assert row["status"] == "DOWNLOADING"
    assert "in.gov.br" in (row.get("file_url") or "")
