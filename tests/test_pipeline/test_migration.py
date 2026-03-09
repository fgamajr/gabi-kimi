"""Tests for the JSON catalog -> SQLite migration script."""

import json

import pytest
import pytest_asyncio

from src.backend.worker.migration import migrate_catalog_to_sqlite
from src.backend.worker.registry import FileStatus


pytestmark = pytest.mark.asyncio


@pytest.fixture
def catalog_path(tmp_path):
    """Create a sample catalog JSON file."""
    catalog = {
        "files": [
            {
                "filename": "S01012026.zip",
                "year_month": "2026-01",
                "section": "do1",
                "folder_id": 12345,
            },
            {
                "filename": "S02012026.zip",
                "year_month": "2026-01",
                "section": "do2",
                "folder_id": 12346,
            },
            {
                "filename": "S01022026.zip",
                "year_month": "2026-02",
                "section": "do1",
                "folder_id": 12347,
            },
            {
                "filename": "S03032025.zip",
                "year_month": "2025-03",
                "section": "do3",
                "folder_id": 12348,
            },
        ]
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog))
    return str(path)


def _mock_es_coverage(ingested_combos, monkeypatch):
    """Patch _get_es_coverage to return a set of (year_month, section) tuples."""

    async def mock_get_es_coverage(es_url):
        return set(ingested_combos)

    monkeypatch.setattr(
        "src.backend.worker.migration._get_es_coverage",
        mock_get_es_coverage,
    )


async def test_migration_creates_records(registry, catalog_path, monkeypatch):
    """migrate_catalog_to_sqlite() reads catalog JSON and creates dou_files records."""
    _mock_es_coverage([("2026-01", "do1")], monkeypatch)

    stats = await migrate_catalog_to_sqlite(
        catalog_path=catalog_path,
        registry=registry,
        es_url="http://localhost:9200",
    )
    assert stats["total"] == 4


async def test_ingested_files_marked_correctly(registry, catalog_path, monkeypatch):
    """Files with matching (year_month, section) in ES are marked INGESTED."""
    _mock_es_coverage([("2026-01", "do1")], monkeypatch)

    await migrate_catalog_to_sqlite(
        catalog_path=catalog_path,
        registry=registry,
        es_url="http://localhost:9200",
    )

    file_rec = await registry.get_file_by_filename("S01012026.zip")
    assert file_rec is not None
    assert file_rec["status"] == "INGESTED"


async def test_non_ingested_files_marked_discovered(registry, catalog_path, monkeypatch):
    """Files without ES match are marked DISCOVERED."""
    _mock_es_coverage([("2026-01", "do1")], monkeypatch)

    await migrate_catalog_to_sqlite(
        catalog_path=catalog_path,
        registry=registry,
        es_url="http://localhost:9200",
    )

    file_rec = await registry.get_file_by_filename("S02012026.zip")
    assert file_rec is not None
    assert file_rec["status"] == "DISCOVERED"


async def test_migration_idempotent(registry, catalog_path, monkeypatch):
    """Running migration twice is idempotent (INSERT OR IGNORE)."""
    _mock_es_coverage([("2026-01", "do1")], monkeypatch)

    stats1 = await migrate_catalog_to_sqlite(
        catalog_path=catalog_path,
        registry=registry,
        es_url="http://localhost:9200",
    )
    stats2 = await migrate_catalog_to_sqlite(
        catalog_path=catalog_path,
        registry=registry,
        es_url="http://localhost:9200",
    )
    assert stats1["total"] == stats2["total"]

    # Should still have exactly 4 records, not 8
    counts = await registry.get_status_counts()
    total = sum(counts.values())
    assert total == 4


async def test_migration_returns_stats(registry, catalog_path, monkeypatch):
    """Stats are returned (total, ingested, discovered counts)."""
    _mock_es_coverage([("2026-01", "do1"), ("2025-03", "do3")], monkeypatch)

    stats = await migrate_catalog_to_sqlite(
        catalog_path=catalog_path,
        registry=registry,
        es_url="http://localhost:9200",
    )
    assert stats["total"] == 4
    assert stats["ingested"] == 2
    assert stats["discovered"] == 2
