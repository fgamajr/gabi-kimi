"""Tests for the SQLite registry module."""

import pytest
import pytest_asyncio

from src.backend.worker.registry import Registry, FileStatus


pytestmark = pytest.mark.asyncio


# --- Schema tests ---


async def test_init_db_creates_tables(registry):
    """Registry.init_db() creates all expected tables."""
    async with registry.get_db() as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in await cursor.fetchall()]
    assert "dou_files" in tables
    assert "pipeline_log" in tables
    assert "pipeline_runs" in tables
    assert "dou_catalog_months" in tables
    assert "pipeline_config" in tables


async def test_dou_files_columns(registry):
    """dou_files table has all expected columns."""
    expected = {
        "id", "filename", "section", "year_month", "publication_date", "source", "folder_id", "file_url",
        "status", "retry_count", "doc_count", "file_size_bytes", "sha256",
        "error_message", "discovered_at", "queued_at", "downloaded_at",
        "extracted_at", "ingested_at", "bm25_indexed_at", "embedded_at", "verified_at", "updated_at",
    }
    async with registry.get_db() as db:
        cursor = await db.execute("PRAGMA table_info(dou_files)")
        columns = {row[1] for row in await cursor.fetchall()}
    assert expected == columns


# --- FileStatus enum tests ---


async def test_file_status_enum_states():
    """FileStatus enum contains all expected states."""
    normal = {"DISCOVERED", "QUEUED", "DOWNLOADING", "DOWNLOADED",
              "EXTRACTING", "EXTRACTED", "BM25_INDEXING", "BM25_INDEXED",
              "EMBEDDING", "EMBEDDED", "VERIFYING", "VERIFIED"}
    failure = {"DOWNLOAD_FAILED", "EXTRACT_FAILED", "BM25_INDEX_FAILED", "EMBEDDING_FAILED", "VERIFY_FAILED"}
    fallback = {"FALLBACK_PENDING"}
    all_expected = normal | failure | fallback
    actual = {s.name for s in FileStatus}
    assert all_expected == actual


# --- State transition tests ---


async def test_valid_transition_discovered_to_queued(registry, sample_file):
    """Valid state transition DISCOVERED -> QUEUED succeeds."""
    await registry.update_status(sample_file, FileStatus.QUEUED)
    row = await registry.get_file(sample_file)
    assert row["status"] == "QUEUED"
    assert row["queued_at"] is not None


async def test_invalid_transition_raises(registry, sample_file):
    """Invalid state transition DISCOVERED -> BM25_INDEXED raises ValueError."""
    with pytest.raises(ValueError, match="Invalid transition"):
        await registry.update_status(sample_file, FileStatus.BM25_INDEXED)


async def test_full_state_machine_transitions(registry):
    """Walk the full happy-path state machine."""
    file_id = await registry.insert_file(
        filename="S02032026.zip", section="do2", year_month="2026-03"
    )
    path = [
        FileStatus.QUEUED,
        FileStatus.DOWNLOADING,
        FileStatus.DOWNLOADED,
        FileStatus.EXTRACTING,
        FileStatus.EXTRACTED,
        FileStatus.BM25_INDEXING,
        FileStatus.BM25_INDEXED,
        FileStatus.EMBEDDING,
        FileStatus.EMBEDDED,
        FileStatus.VERIFYING,
        FileStatus.VERIFIED,
    ]
    for status in path:
        await registry.update_status(file_id, status)
    row = await registry.get_file(file_id)
    assert row["status"] == "VERIFIED"


async def test_verified_file_can_reenter_embedding_for_backfill(registry):
    """Previously verified files can re-enter embedding for legacy backfill."""
    file_id = await registry.insert_file(
        filename="reembed_test.zip", section="do1", year_month="2026-03"
    )
    path = [
        FileStatus.QUEUED,
        FileStatus.DOWNLOADING,
        FileStatus.DOWNLOADED,
        FileStatus.EXTRACTING,
        FileStatus.EXTRACTED,
        FileStatus.BM25_INDEXING,
        FileStatus.BM25_INDEXED,
        FileStatus.EMBEDDING,
        FileStatus.EMBEDDED,
        FileStatus.VERIFYING,
        FileStatus.VERIFIED,
        FileStatus.EMBEDDING,
    ]
    for status in path:
        await registry.update_status(file_id, status)
    row = await registry.get_file(file_id)
    assert row["status"] == "EMBEDDING"


async def test_failure_transitions(registry):
    """Processing states can transition to their failure states."""
    transitions = [
        (FileStatus.DOWNLOADING, FileStatus.DOWNLOAD_FAILED),
        (FileStatus.EXTRACTING, FileStatus.EXTRACT_FAILED),
        (FileStatus.BM25_INDEXING, FileStatus.BM25_INDEX_FAILED),
        (FileStatus.EMBEDDING, FileStatus.EMBEDDING_FAILED),
        (FileStatus.VERIFYING, FileStatus.VERIFY_FAILED),
    ]
    for i, (from_status, to_status) in enumerate(transitions):
        file_id = await registry.insert_file(
            filename=f"fail_test_{i}.zip", section="do1", year_month="2026-01"
        )
        # Walk to from_status
        current = FileStatus.DISCOVERED
        while current != from_status:
            from src.backend.worker.registry import VALID_TRANSITIONS
            nexts = VALID_TRANSITIONS[current]
            # pick the next normal state on the path
            for n in nexts:
                if not n.name.endswith("_FAILED"):
                    current = n
                    break
            await registry.update_status(file_id, current)
        # Now transition to failure
        await registry.update_status(file_id, to_status)
        row = await registry.get_file(file_id)
        assert row["status"] == to_status.value


# --- CRUD tests ---


async def test_insert_file_returns_id(registry):
    """insert_file() creates a new dou_files record and returns its id."""
    file_id = await registry.insert_file(
        filename="S03012026.zip", section="do3", year_month="2026-01"
    )
    assert isinstance(file_id, int)
    assert file_id > 0


async def test_update_status_sets_timestamp(registry, sample_file):
    """update_status() changes status and sets appropriate timestamp column."""
    await registry.update_status(sample_file, FileStatus.QUEUED)
    row = await registry.get_file(sample_file)
    assert row["queued_at"] is not None
    assert row["updated_at"] is not None


async def test_get_files_by_status(registry, sample_file):
    """get_files_by_status() returns only files matching the given status."""
    # sample_file is DISCOVERED
    discovered = await registry.get_files_by_status(FileStatus.DISCOVERED)
    assert len(discovered) >= 1
    assert all(r["status"] == "DISCOVERED" for r in discovered)

    queued = await registry.get_files_by_status(FileStatus.QUEUED)
    assert len(queued) == 0


# --- Pipeline run tests ---


async def test_create_pipeline_run(registry):
    """create_pipeline_run() creates a run record with UUID."""
    run_id = await registry.create_pipeline_run(phase="discovery")
    assert isinstance(run_id, str)
    assert len(run_id) == 36  # UUID format


async def test_add_log_entry(registry, sample_file):
    """add_log_entry() creates a log record linked to a run."""
    run_id = await registry.create_pipeline_run(phase="discovery")
    await registry.add_log_entry(run_id, sample_file, "INFO", "Test log message")
    logs = await registry.get_logs(run_id=run_id)
    assert len(logs) == 1
    assert logs[0]["message"] == "Test log message"


# --- Retry tests ---


async def test_retry_increments_count(registry):
    """retry increments retry_count and resets status to QUEUED."""
    file_id = await registry.insert_file(
        filename="retry_test.zip", section="do1", year_month="2026-01"
    )
    # Move to DOWNLOAD_FAILED
    await registry.update_status(file_id, FileStatus.QUEUED)
    await registry.update_status(file_id, FileStatus.DOWNLOADING)
    await registry.update_status(file_id, FileStatus.DOWNLOAD_FAILED)

    await registry.retry_file(file_id)
    row = await registry.get_file(file_id)
    assert row["retry_count"] == 1
    assert row["status"] == "QUEUED"


async def test_retry_beyond_max_raises(registry):
    """retry beyond max_retries raises ValueError."""
    file_id = await registry.insert_file(
        filename="max_retry_test.zip", section="do1", year_month="2026-01"
    )
    # Simulate 3 retries already done
    async with registry.get_db() as db:
        await db.execute(
            "UPDATE dou_files SET retry_count = 3, status = 'DOWNLOAD_FAILED' WHERE id = ?",
            (file_id,),
        )
        await db.commit()

    with pytest.raises(ValueError, match="max retries"):
        await registry.retry_file(file_id)


# --- Catalog months and pipeline_config (P2) ---


async def test_catalog_month_upsert(registry):
    """catalog_month_upsert() inserts or updates dou_catalog_months."""
    await registry.catalog_month_upsert("2026-01", source_of_truth="json_bootstrap")
    await registry.catalog_month_upsert(
        "2026-02", folder_id=999, group_id="49035712", source_of_truth="inlabs_discovery"
    )

    async with registry.get_db() as db:
        cursor = await db.execute(
            "SELECT year_month, folder_id, source_of_truth FROM dou_catalog_months ORDER BY year_month"
        )
        rows = await cursor.fetchall()
    assert len(rows) == 2
    assert rows[0]["year_month"] == "2026-01"
    assert rows[0]["folder_id"] is None
    assert rows[0]["source_of_truth"] == "json_bootstrap"
    assert rows[1]["year_month"] == "2026-02"
    assert rows[1]["folder_id"] == 999
    assert rows[1]["source_of_truth"] == "inlabs_discovery"


async def test_has_catalog_data_false_when_empty(registry):
    """has_catalog_data() returns False when no files and no catalog months."""
    assert await registry.has_catalog_data() is False


async def test_has_catalog_data_true_when_files_exist(registry, sample_file):
    """has_catalog_data() returns True when dou_files has rows."""
    assert await registry.has_catalog_data() is True


async def test_has_catalog_data_true_when_catalog_months_exist(registry):
    """has_catalog_data() returns True when only dou_catalog_months has rows."""
    await registry.catalog_month_upsert("2026-01", source_of_truth="json_bootstrap")
    assert await registry.has_catalog_data() is True


async def test_get_config_set_config(registry):
    """get_config/set_config round-trip for pipeline_config."""
    assert await registry.get_config("scheduler_paused") is None
    await registry.set_config("scheduler_paused", "true")
    assert await registry.get_config("scheduler_paused") == "true"
    await registry.set_config("scheduler_paused", "false")
    assert await registry.get_config("scheduler_paused") == "false"


async def test_get_catalog_months(registry):
    """get_catalog_months returns rows from dou_catalog_months."""
    await registry.catalog_month_upsert("2026-01", source_of_truth="json_bootstrap")
    await registry.catalog_month_upsert("2025-12", source_of_truth="inlabs_discovery")
    months = await registry.get_catalog_months()
    assert len(months) == 2
    assert months[0]["year_month"] == "2026-01"
    assert months[1]["year_month"] == "2025-12"
    filtered = await registry.get_catalog_months(year=2025)
    assert len(filtered) == 1
    assert filtered[0]["year_month"] == "2025-12"


async def test_refresh_catalog_month_status_closed(registry):
    """Month with all files VERIFIED gets catalog_status CLOSED."""
    from datetime import date, timedelta
    from src.backend.worker.registry import CATALOG_STATUS_CLOSED

    await registry.catalog_month_upsert("2020-01", source_of_truth="json_bootstrap")
    await registry.insert_file("S01012020.zip", "do1", "2020-01")
    await registry.update_status(1, FileStatus.QUEUED)
    await registry.update_status(1, FileStatus.DOWNLOADING)
    await registry.update_status(1, FileStatus.DOWNLOADED)
    await registry.update_status(1, FileStatus.EXTRACTING)
    await registry.update_status(1, FileStatus.EXTRACTED)
    await registry.update_status(1, FileStatus.BM25_INDEXING)
    await registry.update_status(1, FileStatus.BM25_INDEXED)
    await registry.update_status(1, FileStatus.EMBEDDING)
    await registry.update_status(1, FileStatus.EMBEDDED)
    await registry.update_status(1, FileStatus.VERIFYING)
    await registry.update_status(1, FileStatus.VERIFIED)

    n = await registry.refresh_catalog_month_status(today=date(2026, 3, 1))
    assert n == 1
    months = await registry.get_catalog_months()
    assert len(months) == 1
    assert months[0]["catalog_status"] == CATALOG_STATUS_CLOSED
    assert months[0]["month_closed"] == 1


async def test_refresh_catalog_month_status_fallback_eligible(registry):
    """Old month with incomplete files gets FALLBACK_ELIGIBLE."""
    from datetime import date
    from src.backend.worker.registry import CATALOG_STATUS_FALLBACK_ELIGIBLE

    await registry.catalog_month_upsert("2020-01", source_of_truth="json_bootstrap")
    await registry.insert_file("S01012020.zip", "do1", "2020-01")
    # leave as DISCOVERED

    n = await registry.refresh_catalog_month_status(today=date(2026, 3, 1))
    assert n == 1
    months = await registry.get_catalog_months()
    assert len(months) == 1
    assert months[0]["catalog_status"] == CATALOG_STATUS_FALLBACK_ELIGIBLE
