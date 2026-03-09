"""Integration tests for the worker internal API.

Uses httpx.AsyncClient with FastAPI's ASGITransport for real HTTP-level testing.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio

from src.backend.worker.main import app


@pytest_asyncio.fixture
async def client(tmp_path):
    """Create test client with mocked registry and scheduler."""
    db_path = str(tmp_path / "test_api.db")

    from src.backend.worker.registry import Registry

    registry = Registry(db_path=db_path)
    await registry.init_db()

    # Set the registry in both api and scheduler modules
    import src.backend.worker.api as api_mod
    import src.backend.worker.scheduler as sched_mod

    api_mod._registry = registry
    sched_mod._registry = registry

    # Mock start_time for uptime
    import src.backend.worker.main as main_mod
    import time

    main_mod._start_time = time.monotonic() - 10  # 10 seconds uptime
    main_mod._last_heartbeat = "2026-03-09T00:00:00+00:00"

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Cleanup
    api_mod._registry = None
    sched_mod._registry = None
    main_mod._start_time = 0.0


@pytest.mark.asyncio
async def test_health_returns_ok(client):
    """GET /health returns 200 with status, uptime, scheduler fields."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "uptime_seconds" in data
    assert data["uptime_seconds"] > 0
    assert "scheduler_running" in data


@pytest.mark.asyncio
async def test_registry_status(client):
    """GET /registry/status returns dict of status counts."""
    resp = await client.get("/registry/status")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_registry_stats(client):
    """GET /registry/stats returns dashboard summary fields."""
    resp = await client.get("/registry/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_files" in data
    assert "status_counts" in data
    assert "disk_usage" in data


@pytest.mark.asyncio
async def test_registry_file_not_found(client):
    """GET /registry/files/{id} returns 404 for non-existent file."""
    resp = await client.get("/registry/files/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_trigger_invalid_phase(client):
    """POST /pipeline/trigger/invalid returns 400."""
    resp = await client.post("/pipeline/trigger/invalid")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_trigger_discovery(client):
    """POST /pipeline/trigger/discovery returns 200 with triggered field."""
    with patch("src.backend.worker.scheduler.scheduler") as mock_sched:
        mock_sched.add_job = lambda *a, **kw: None
        resp = await client.post("/pipeline/trigger/discovery")
    assert resp.status_code == 200
    data = resp.json()
    assert data["triggered"] == "discovery"


@pytest.mark.asyncio
async def test_trigger_full_cycle(client):
    """POST /pipeline/trigger/full returns 200 with triggered field."""
    with patch("src.backend.worker.scheduler.scheduler") as mock_sched:
        mock_sched.add_job = lambda *a, **kw: None
        resp = await client.post("/pipeline/trigger/full")
    assert resp.status_code == 200
    data = resp.json()
    assert data["triggered"] == "full"


@pytest.mark.asyncio
async def test_pipeline_scheduler(client):
    """GET /pipeline/scheduler returns running state and jobs list."""
    resp = await client.get("/pipeline/scheduler")
    assert resp.status_code == 200
    data = resp.json()
    assert "running" in data
    assert "paused" in data
    assert isinstance(data["jobs"], list)


@pytest.mark.asyncio
async def test_pause(client):
    """POST /pipeline/pause returns paused: true."""
    resp = await client.post("/pipeline/pause")
    assert resp.status_code == 200
    data = resp.json()
    assert data["paused"] is True


@pytest.mark.asyncio
async def test_resume(client):
    """POST /pipeline/resume returns paused: false."""
    resp = await client.post("/pipeline/resume")
    assert resp.status_code == 200
    data = resp.json()
    assert data["paused"] is False
