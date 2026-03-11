"""Integration tests for the worker internal API.

Uses httpx.AsyncClient with FastAPI's ASGITransport for real HTTP-level testing.
"""
from __future__ import annotations

from unittest.mock import patch

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
    assert "es_doc_count" in data
    assert "es_chunk_count" in data
    assert data["data_sources"]["document_corpus"] == "postgres_live"


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
async def test_trigger_backfill_missing(client):
    """POST /pipeline/trigger/backfill_missing returns 200 with triggered field."""
    with patch("src.backend.worker.scheduler.scheduler") as mock_sched:
        mock_sched.add_job = lambda *a, **kw: None
        resp = await client.post("/pipeline/trigger/backfill_missing")
    assert resp.status_code == 200
    data = resp.json()
    assert data["triggered"] == "backfill_missing"


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
async def test_trigger_retry_job(client):
    """POST /pipeline/trigger/retry returns 200 with triggered field."""
    with patch("src.backend.worker.scheduler.scheduler") as mock_sched:
        mock_sched.add_job = lambda *a, **kw: None
        resp = await client.post("/pipeline/trigger/retry")
    assert resp.status_code == 200
    data = resp.json()
    assert data["triggered"] == "retry"


@pytest.mark.asyncio
async def test_pipeline_scheduler(client):
    """GET /pipeline/scheduler returns running state and jobs list."""
    resp = await client.get("/pipeline/scheduler")
    assert resp.status_code == 200
    data = resp.json()
    assert "running" in data
    assert "paused" in data
    assert data["source_of_truth"] == "apscheduler"
    assert data["timezone"] == "UTC"
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


@pytest.mark.asyncio
async def test_disable_scheduler_job(client):
    """POST /pipeline/jobs/{job_id}/disable disables automatic execution for that job."""
    resp = await client.post("/pipeline/jobs/download/disable")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == "download"
    assert data["enabled"] is False


@pytest.mark.asyncio
async def test_enable_scheduler_job(client):
    """POST /pipeline/jobs/{job_id}/enable enables automatic execution for that job."""
    await client.post("/pipeline/jobs/download/disable")
    resp = await client.post("/pipeline/jobs/download/enable")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == "download"
    assert data["enabled"] is True


@pytest.mark.asyncio
async def test_plant_status_shape(client):
    """GET /registry/plant-status returns aggregated dashboard data with correct shape."""
    resp = await client.get("/registry/plant-status")
    assert resp.status_code == 200
    data = resp.json()
    # Top-level keys
    assert "stages" in data
    assert "master_paused" in data
    assert "storage" in data
    assert "totals" in data
    assert "uptime_seconds" in data
    assert "last_heartbeat" in data
    # Stages is a list
    assert isinstance(data["stages"], list)
    assert len(data["stages"]) > 0
    # Each stage has required fields
    for stage in data["stages"]:
        assert "id" in stage
        assert "state" in stage
        assert stage["state"] in ("AUTO", "PAUSED", "ERROR", "IDLE")
        assert "queue_depth" in stage
        assert "failed_count" in stage
        assert "throughput" in stage or stage.get("throughput") is None
        assert "enabled" in stage
        assert "last_run" in stage
        assert "next_run" in stage
    # Storage shape
    assert "sqlite_bytes" in data["storage"]
    assert "disk_free_bytes" in data["storage"]
    assert "disk_total_bytes" in data["storage"]
    # Totals shape
    assert "total_files" in data["totals"]
    assert "verified" in data["totals"]
    assert "failed" in data["totals"]
    assert "in_transit" in data["totals"]


@pytest.mark.asyncio
async def test_plant_status_stage_state_paused(client):
    """Disabled job should show PAUSED state in plant-status."""
    # Disable a job first
    import src.backend.worker.scheduler as sched_mod
    sched_mod._job_enabled["download"] = False
    resp = await client.get("/registry/plant-status")
    assert resp.status_code == 200
    data = resp.json()
    download_stage = next((s for s in data["stages"] if s["id"] == "download"), None)
    assert download_stage is not None
    assert download_stage["state"] == "PAUSED"
    assert download_stage["enabled"] is False
    # Restore
    sched_mod._job_enabled["download"] = True


@pytest.mark.asyncio
async def test_plant_status_master_paused(client):
    """When master paused, master_paused should be True."""
    import src.backend.worker.scheduler as sched_mod
    sched_mod._paused = True
    resp = await client.get("/registry/plant-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["master_paused"] is True
    # All stages should be PAUSED when master is paused
    for stage in data["stages"]:
        assert stage["state"] == "PAUSED"
    # Restore
    sched_mod._paused = False


@pytest.mark.asyncio
async def test_stage_pause(client):
    """POST /pipeline/stage/{name}/pause disables the job."""
    resp = await client.post("/pipeline/stage/download/pause")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == "download"
    assert data["enabled"] is False
    # Re-enable for cleanup
    await client.post("/pipeline/stage/download/resume")


@pytest.mark.asyncio
async def test_stage_resume(client):
    """POST /pipeline/stage/{name}/resume enables the job."""
    await client.post("/pipeline/stage/download/pause")
    resp = await client.post("/pipeline/stage/download/resume")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == "download"
    assert data["enabled"] is True


@pytest.mark.asyncio
async def test_stage_trigger(client):
    """POST /pipeline/stage/{name}/trigger triggers a phase."""
    with patch("src.backend.worker.scheduler.scheduler") as mock_sched:
        mock_sched.add_job = lambda *a, **kw: None
        resp = await client.post("/pipeline/stage/download/trigger")
    assert resp.status_code == 200
    data = resp.json()
    assert data["triggered"] == "download"


@pytest.mark.asyncio
async def test_stage_trigger_invalid(client):
    """POST /pipeline/stage/{invalid}/trigger returns 400."""
    resp = await client.post("/pipeline/stage/nonexistent/trigger")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_pause_all(client):
    """POST /pipeline/pause-all pauses the scheduler."""
    resp = await client.post("/pipeline/pause-all")
    assert resp.status_code == 200
    data = resp.json()
    assert data["paused"] is True
    # Cleanup
    await client.post("/pipeline/resume-all")


@pytest.mark.asyncio
async def test_resume_all(client):
    """POST /pipeline/resume-all resumes the scheduler."""
    await client.post("/pipeline/pause-all")
    resp = await client.post("/pipeline/resume-all")
    assert resp.status_code == 200
    data = resp.json()
    assert data["paused"] is False


@pytest.mark.asyncio
async def test_pause_persists_across_restart(client):
    """Pause state survives simulated restart (load from pipeline_config)."""
    await client.post("/pipeline/pause")
    # Simulate new process: clear in-memory state and load from DB
    import src.backend.worker.scheduler as sched_mod
    sched_mod._paused = False
    await sched_mod.load_pause_state_from_registry()
    resp = await client.get("/pipeline/scheduler")
    assert resp.status_code == 200
    assert resp.json()["paused"] is True
