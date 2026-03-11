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
    """Walk the full happy-path state machine (BM25-only, no embedding)."""
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
        FileStatus.VERIFYING,
        FileStatus.VERIFIED,
    ]
    for status in path:
        await registry.update_status(file_id, status)
    row = await registry.get_file(file_id)
    assert row["status"] == "VERIFIED"


async def test_verified_file_can_reverify(registry):
    """Previously verified files can re-enter verification."""
    file_id = await registry.insert_file(
        filename="reverify_test.zip", section="do1", year_month="2026-03"
    )
    path = [
        FileStatus.QUEUED,
        FileStatus.DOWNLOADING,
        FileStatus.DOWNLOADED,
        FileStatus.EXTRACTING,
        FileStatus.EXTRACTED,
        FileStatus.BM25_INDEXING,
        FileStatus.BM25_INDEXED,
        FileStatus.VERIFYING,
        FileStatus.VERIFIED,
        FileStatus.VERIFYING,
    ]
    for status in path:
        await registry.update_status(file_id, status)
    row = await registry.get_file(file_id)
    assert row["status"] == "VERIFYING"


async def test_bm25_indexed_transitions_to_verifying(registry):
    """BM25_INDEXED -> VERIFYING is a valid transition (bypasses embedding)."""
    from src.backend.worker.registry import VALID_TRANSITIONS
    assert FileStatus.VERIFYING in VALID_TRANSITIONS[FileStatus.BM25_INDEXED]


async def test_bm25_indexed_does_not_transition_to_embedding(registry):
    """BM25_INDEXED -> EMBEDDING is no longer a valid transition."""
    from src.backend.worker.registry import VALID_TRANSITIONS
    assert FileStatus.EMBEDDING not in VALID_TRANSITIONS[FileStatus.BM25_INDEXED]


async def test_verified_transitions_to_verifying_not_embedding(registry):
    """VERIFIED -> VERIFYING is valid (re-verify, not re-embed)."""
    from src.backend.worker.registry import VALID_TRANSITIONS
    assert FileStatus.VERIFYING in VALID_TRANSITIONS[FileStatus.VERIFIED]
    assert FileStatus.EMBEDDING not in VALID_TRANSITIONS[FileStatus.VERIFIED]


async def test_embedded_status_still_exists_in_enum():
    """EMBEDDED status still exists in enum for backward compat with historical data."""
    assert hasattr(FileStatus, "EMBEDDED")
    assert hasattr(FileStatus, "EMBEDDING")
    assert hasattr(FileStatus, "EMBEDDING_FAILED")


async def test_failure_transitions(registry):
    """Processing states can transition to their failure states.

    Tests the reachable failure transitions in the BM25-only pipeline.
    EMBEDDING failure is excluded since EMBEDDING is unreachable in normal flow.
    """
    transitions = [
        (FileStatus.DOWNLOADING, FileStatus.DOWNLOAD_FAILED),
        (FileStatus.EXTRACTING, FileStatus.EXTRACT_FAILED),
        (FileStatus.BM25_INDEXING, FileStatus.BM25_INDEX_FAILED),
        (FileStatus.VERIFYING, FileStatus.VERIFY_FAILED),
    ]
    for i, (from_status, to_status) in enumerate(transitions):
        file_id = await registry.insert_file(
            filename=f"fail_test_{i}.zip", section="do1", year_month="2026-01"
        )
        # Walk to from_status via the happy path
        current = FileStatus.DISCOVERED
        while current != from_status:
            from src.backend.worker.registry import VALID_TRANSITIONS
            nexts = VALID_TRANSITIONS[current]
            # pick the next normal state on the path
            for n in nexts:
                if not n.name.endswith("_FAILED") and n != FileStatus.FALLBACK_PENDING:
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


async def test_get_catalog_months_includes_live_postgres_coverage(registry, monkeypatch):
    """Catalog months are enriched with live PostgreSQL ingest/chunk coverage."""
    await registry.catalog_month_upsert("2002-03", source_of_truth="json_bootstrap")
    await registry.insert_file("S01032002.zip", "do1", "2002-03")
    await registry.insert_file("S02032002.zip", "do2", "2002-03")
    await registry.insert_file("S03032002.zip", "do3", "2002-03")

    async def fake_snapshot(**_kwargs):
        return {
            "summary": {
                "pg_ingested_files": 3,
                "pg_total_docs": 123,
                "pg_chunked_files": 2,
                "pg_chunked_docs": 45,
                "pg_chunk_rows": 90,
            },
            "files": {},
            "months": {
                "2002-03": {
                    "pg_ingested_file_count": 3,
                    "pg_doc_count": 123,
                    "pg_chunked_file_count": 2,
                    "pg_chunked_doc_count": 45,
                    "pg_chunk_rows": 90,
                }
            },
        }

    monkeypatch.setattr("src.backend.worker.registry.fetch_postgres_live_snapshot", fake_snapshot)

    months = await registry.get_catalog_months(year=2002)
    assert len(months) == 1
    assert months[0]["pg_ingested_file_count"] == 3
    assert months[0]["pg_doc_count"] == 123
    assert months[0]["pg_chunked_file_count"] == 2
    assert months[0]["ingested_coverage_pct"] == 100.0
    assert months[0]["chunked_coverage_pct"] == pytest.approx(66.7, rel=0.01)


async def test_get_months_overlays_live_postgres_file_metrics(registry, monkeypatch):
    """Timeline file rows are enriched with live PostgreSQL file metrics."""
    await registry.insert_file("S01032002.zip", "do1", "2002-03")

    async def fake_snapshot(**_kwargs):
        return {
            "summary": {},
            "files": {
                ("2002-03", "do1", "S01032002.zip"): {
                    "doc_count": 123,
                    "chunked_doc_count": 45,
                    "chunk_row_count": 90,
                    "downloaded_at": "2002-03-01T03:00:00Z",
                }
            },
            "months": {},
            "es_summary": {},
        }

    monkeypatch.setattr("src.backend.worker.registry.fetch_postgres_live_snapshot", fake_snapshot)

    months = await registry.get_months(year=2002)
    assert len(months) == 1
    assert months[0]["doc_count"] == 123
    assert months[0]["pg_doc_count"] == 123
    assert months[0]["pg_chunked_doc_count"] == 45
    assert months[0]["pg_chunk_rows"] == 90
    assert months[0]["pg_downloaded_at"] == "2002-03-01T03:00:00Z"


async def test_get_months_falls_back_to_unique_year_month_section_live_metrics(registry, monkeypatch):
    """Historical imports may have different source_zip filenames; fallback by month+section when unique."""
    await registry.insert_file("S01012002.zip", "do1", "2002-01")

    async def fake_snapshot(**_kwargs):
        return {
            "summary": {},
            "files": {
                ("2002-01", "do1", "2002-01_DO1.zip"): {
                    "doc_count": 321,
                    "chunked_doc_count": 111,
                    "chunk_row_count": 654,
                    "downloaded_at": "2002-01-31T03:00:00Z",
                }
            },
            "months": {},
            "es_summary": {},
        }

    monkeypatch.setattr("src.backend.worker.registry.fetch_postgres_live_snapshot", fake_snapshot)

    months = await registry.get_months(year=2002)
    assert len(months) == 1
    assert months[0]["doc_count"] == 321
    assert months[0]["pg_doc_count"] == 321
    assert months[0]["pg_chunked_doc_count"] == 111
    assert months[0]["pg_chunk_rows"] == 654
    assert months[0]["pg_downloaded_at"] == "2002-01-31T03:00:00Z"


async def test_get_months_does_not_duplicate_month_section_live_metrics_when_ambiguous(registry, monkeypatch):
    """Do not smear aggregated PG counts across multiple registry files in the same month+section."""
    await registry.insert_file("S01012002_Parte1.zip", "do1", "2002-01")
    await registry.insert_file("S01012002_Parte2.zip", "do1", "2002-01")

    async def fake_snapshot(**_kwargs):
        return {
            "summary": {},
            "files": {
                ("2002-01", "do1", "2002-01_DO1.zip"): {
                    "doc_count": 321,
                    "chunked_doc_count": 111,
                    "chunk_row_count": 654,
                    "downloaded_at": "2002-01-31T03:00:00Z",
                }
            },
            "months": {},
            "es_summary": {},
        }

    monkeypatch.setattr("src.backend.worker.registry.fetch_postgres_live_snapshot", fake_snapshot)

    months = await registry.get_months(year=2002)
    assert len(months) == 2
    assert months[0]["pg_doc_count"] == 0
    assert months[1]["pg_doc_count"] == 0


async def test_get_months_includes_live_only_postgres_rows(registry, monkeypatch):
    """Timeline includes PG-backed files that do not yet exist in the registry."""

    async def fake_snapshot(**_kwargs):
        return {
            "summary": {},
            "files": {
                ("2004-11", "do2", "S02112004.zip"): {
                    "pg_filename": "S02112004.zip",
                    "doc_count": 88,
                    "chunked_doc_count": 34,
                    "chunk_row_count": 144,
                    "downloaded_at": "2004-11-30T03:00:00Z",
                }
            },
            "months": {},
            "es_summary": {},
        }

    monkeypatch.setattr("src.backend.worker.registry.fetch_postgres_live_snapshot", fake_snapshot)

    months = await registry.get_months(year=2004)
    assert len(months) == 1
    assert months[0]["filename"] == "S02112004.zip"
    assert months[0]["status"] == "VERIFIED"
    assert months[0]["is_live_only"] is True
    assert months[0]["pg_doc_count"] == 88
    assert months[0]["pg_chunked_doc_count"] == 34
    assert months[0]["pg_chunk_rows"] == 144
    assert months[0]["pg_downloaded_at"] == "2004-11-30T03:00:00Z"


async def test_get_summary_stats_includes_live_postgres_metrics(registry, monkeypatch, sample_file):
    """Summary stats include PostgreSQL ingest/chunk totals when live sync is available."""
    async def fake_snapshot(**_kwargs):
        return {
            "summary": {
                "pg_ingested_files": 12,
                "pg_doc_backed_files": 12,
                "pg_total_docs": 345,
                "pg_chunked_files": 9,
                "pg_chunked_docs": 210,
                "pg_chunk_rows": 840,
                "pg_min_month": "2002-01",
                "pg_max_month": "2004-11",
            },
            "files": {},
            "months": {},
            "es_summary": {
                "es_status": "green",
                "es_doc_count": 57,
                "es_chunk_count": 12,
                "es_chunks_refresh_interval": "-1",
            },
        }

    monkeypatch.setattr("src.backend.worker.registry.fetch_postgres_live_snapshot", fake_snapshot)

    stats = await registry.get_summary_stats()
    assert stats["pg_ingested_files"] == 12
    assert stats["pg_total_docs"] == 345
    assert stats["pg_chunked_files"] == 9
    assert stats["pg_chunked_docs"] == 210
    assert stats["pg_chunk_rows"] == 840
    assert stats["pg_min_month"] == "2002-01"
    assert stats["pg_max_month"] == "2004-11"
    assert stats["es_status"] == "green"
    assert stats["es_doc_count"] == 57
    assert stats["es_chunk_count"] == 12
    assert stats["es_chunks_refresh_interval"] == "-1"


async def test_get_catalog_months_includes_live_only_postgres_months(registry, monkeypatch):
    """Coverage includes months that currently exist only in PostgreSQL."""

    async def fake_snapshot(**_kwargs):
        return {
            "summary": {},
            "files": {},
            "months": {
                "2003-07": {
                    "pg_ingested_file_count": 3,
                    "pg_doc_count": 210,
                    "pg_chunked_file_count": 2,
                    "pg_chunked_doc_count": 140,
                    "pg_chunk_rows": 480,
                }
            },
            "es_summary": {},
        }

    monkeypatch.setattr("src.backend.worker.registry.fetch_postgres_live_snapshot", fake_snapshot)

    months = await registry.get_catalog_months(year=2003)
    assert len(months) == 1
    assert months[0]["year_month"] == "2003-07"
    assert months[0]["source_of_truth"] == "postgres_live"
    assert months[0]["catalog_status"] == "CLOSED"
    assert months[0]["file_count"] == 3
    assert months[0]["verified_file_count"] == 3
    assert months[0]["effective_file_count"] == 3
    assert months[0]["effective_covered_file_count"] == 3
    assert months[0]["coverage_source"] == "postgres_live"
    assert months[0]["coverage_pct"] == 100.0
    assert months[0]["ingested_coverage_pct"] == 100.0
    assert months[0]["chunked_coverage_pct"] == pytest.approx(66.7, rel=0.01)


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
