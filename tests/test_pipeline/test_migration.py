"""Tests for the JSON catalog -> SQLite migration script."""

import json

import pytest
import pytest_asyncio

from src.backend.worker.migration import (
    bootstrap_registry_if_empty,
    ensure_registry_seed_audit_trail,
    migrate_catalog_to_sqlite,
)
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


async def test_covered_files_marked_verified(registry, catalog_path, monkeypatch):
    """Files with matching (year_month, section) in ES are marked VERIFIED."""
    _mock_es_coverage([("2026-01", "do1")], monkeypatch)

    await migrate_catalog_to_sqlite(
        catalog_path=catalog_path,
        registry=registry,
        es_url="http://localhost:9200",
    )

    file_rec = await registry.get_file_by_filename("S01012026.zip")
    assert file_rec is not None
    assert file_rec["status"] == "VERIFIED"


async def test_non_covered_files_marked_discovered(registry, catalog_path, monkeypatch):
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
    """Stats are returned (total, verified, discovered counts)."""
    _mock_es_coverage([("2026-01", "do1"), ("2025-03", "do3")], monkeypatch)

    stats = await migrate_catalog_to_sqlite(
        catalog_path=catalog_path,
        registry=registry,
        es_url="http://localhost:9200",
    )
    assert stats["total"] == 4
    assert stats["verified"] == 2
    assert stats["discovered"] == 2


async def test_bootstrap_registry_if_empty_populates_from_catalog(registry, catalog_path, monkeypatch):
    """Empty registries are auto-populated from the catalog."""
    _mock_es_coverage([], monkeypatch)

    stats = await bootstrap_registry_if_empty(
        registry,
        es_url="http://localhost:9200",
        catalog_path=catalog_path,
    )

    assert stats is not None
    counts = await registry.get_status_counts()
    assert sum(counts.values()) == 4
    runs = await registry.get_pipeline_runs(limit=5)
    assert len(runs) == 1
    assert runs[0]["phase"] == "catalog-bootstrap"


async def test_ensure_registry_seed_audit_trail_backfills_initial_run(registry):
    """Seeded registries without historical runs get a synthetic audit entry once."""
    await registry.insert_file("existing.zip", "do1", "2026-01")

    run_id = await ensure_registry_seed_audit_trail(registry)

    assert run_id is not None
    runs = await registry.get_pipeline_runs(limit=5)
    assert len(runs) == 1
    assert runs[0]["phase"] == "state-seed"

    second_run_id = await ensure_registry_seed_audit_trail(registry)
    assert second_run_id is None


async def test_bootstrap_registry_if_empty_is_noop_when_already_populated(registry, catalog_path, monkeypatch):
    """Bootstrap does not rerun when the registry already has rows."""
    _mock_es_coverage([], monkeypatch)
    await registry.insert_file("existing.zip", "do1", "2026-01")

    stats = await bootstrap_registry_if_empty(
        registry,
        es_url="http://localhost:9200",
        catalog_path=catalog_path,
    )

    assert stats is None


async def test_migration_accepts_grouped_catalog_layout(registry, tmp_path, monkeypatch):
    """The real catalog layout maps year_month -> filenames and folder_ids by month."""
    catalog = {
        "group_id": "49035712",
        "folder_ids": {"2002-01": 50300469, "2024-12": 685674000},
        "files": {
            "2002-01": ["S01012002.zip", "S02012002.zip", "S03012002.zip"],
            "2024-12": ["S01122024_Parte_01.zip", "S01122024_Parte_02.zip", "S02122024.zip"],
        },
    }
    path = tmp_path / "grouped_catalog.json"
    path.write_text(json.dumps(catalog))
    _mock_es_coverage([], monkeypatch)

    stats = await migrate_catalog_to_sqlite(
        catalog_path=str(path),
        registry=registry,
        es_url="http://localhost:9200",
    )

    assert stats["total"] == 6
    jan = await registry.get_file_by_filename("S01012002.zip")
    assert jan is not None
    assert jan["section"] == "do1"
    assert jan["folder_id"] == 50300469

    split = await registry.get_file_by_filename("S01122024_Parte_01.zip")
    assert split is not None
    assert split["section"] == "do1"
