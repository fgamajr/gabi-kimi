"""Shared fixtures for pipeline tests."""

import pytest
import pytest_asyncio

from src.backend.worker.registry import Registry


@pytest_asyncio.fixture
async def registry(tmp_path):
    """Create a Registry instance using a temp DB, initialize schema, yield it."""
    db_path = str(tmp_path / "test.db")
    reg = Registry(db_path=db_path)
    await reg.init_db()
    yield reg


@pytest_asyncio.fixture
async def sample_file(registry):
    """Insert a sample file into the registry and return its id."""
    file_id = await registry.insert_file(
        filename="S01012026.zip",
        section="do1",
        year_month="2026-01",
        folder_id=12345,
        file_url="https://www.in.gov.br/documents/49035712/12345/S01012026.zip",
    )
    return file_id
