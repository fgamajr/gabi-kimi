# GABI Dashboard API Integration Guide

> **Agent 1 Implementation Guide**
>
> This guide explains how to integrate the new dashboard control panel endpoints
> into the existing GABI codebase.

---

## Overview

The new endpoints provide:
1. **4-stage pipeline summary** (`/dashboard/pipeline/summary`)
2. **Jobs endpoint** (`/dashboard/jobs`) - sync jobs by year + ES indexes
3. **Pipeline control endpoints** - start/stop/restart phases
4. **Pipeline state endpoint** - current processing state

---

## Step 1: Merge Schema Files

### Option A: Append to existing `dashboard.py` schemas (Recommended)

Edit `/src/gabi/schemas/dashboard.py` and append the new schemas:

```python
# Add at end of /src/gabi/schemas/dashboard.py

# =============================================================================
# Extended Schemas for Control Panel (NEW)
# =============================================================================

# Stage Mapping: 9 Backend Phases → 4 Frontend Stages
STAGE_MAPPING: Dict[str, List[str]] = {
    "harvest": ["discovery", "change_detection"],
    "sync": ["fetch", "parse", "fingerprint"],
    "ingest": ["deduplication", "chunking", "embedding"],
    "index": ["indexing"],
}

# Import new schemas from dashboard_extended.py content
from .dashboard_extended import (
    PipelineSummaryStage,
    PipelineSummaryResponse,
    SyncJob,
    SyncJobStatus,
    ElasticIndexInfo,
    ElasticIndexHealth,
    JobsResponse,
    PipelineState,
    PipelineStateResponse,
    StartPhaseRequest,
    StartPhaseResponse,
    StopPhaseRequest,
    StopPhaseResponse,
    RestartPhaseRequest,
    RestartPhaseResponse,
    BulkControlAction,
    BulkControlRequest,
    BulkControlResponse,
)
```

### Option B: Keep separate and import

Modify `/src/gabi/schemas/dashboard.py`:

```python
# Add at end of existing imports
from gabi.schemas.dashboard_extended import (
    # Re-export for convenience
    PipelineSummaryStage,
    PipelineSummaryResponse,
    SyncJob,
    SyncJobStatus,
    ElasticIndexInfo,
    ElasticIndexHealth,
    JobsResponse,
    PipelineState,
    PipelineStateResponse,
    StartPhaseRequest,
    StartPhaseResponse,
    StopPhaseRequest,
    StopPhaseResponse,
    RestartPhaseRequest,
    RestartPhaseResponse,
    BulkControlAction,
    BulkControlRequest,
    BulkControlResponse,
)
```

---

## Step 2: Merge Endpoint Implementation

### Option A: Append to existing `dashboard.py` (Recommended)

Edit `/src/gabi/api/dashboard.py`:

```python
# Add at the END of /src/gabi/api/dashboard.py, before __all__

# =============================================================================
# Extended Endpoints for Control Panel (NEW)
# =============================================================================

# Import new schemas
from gabi.schemas.dashboard import (
    PipelineSummaryResponse,
    PipelineSummaryStage,
    JobsResponse,
    SyncJob,
    SyncJobStatus,
    ElasticIndexInfo,
    ElasticIndexHealth,
    PipelineState,
    PipelineStateResponse,
    StartPhaseRequest,
    StartPhaseResponse,
    StopPhaseRequest,
    StopPhaseResponse,
    RestartPhaseRequest,
    RestartPhaseResponse,
    BulkControlAction,
    BulkControlRequest,
    BulkControlResponse,
)

# Copy implementation from dashboard_extended.py
# [Copy all endpoint functions from dashboard_extended.py here]

# Update __all__ exports
__all__ = [
    # ... existing exports ...
    # New endpoints
    "get_pipeline_summary",
    "get_jobs",
    "get_pipeline_state",
    "start_phase",
    "stop_phase",
    "restart_phase",
    "bulk_control",
]
```

### Option B: Import and include extended router

Modify `/src/gabi/api/dashboard.py`:

```python
# Add near the end, before __all__

# Import extended endpoints
from gabi.api.dashboard_extended import router as extended_router

# Include extended routes
router.include_router(extended_router)
```

---

## Step 3: Add Pipeline Exceptions

Create or update `/src/gabi/exceptions.py`:

```python
class PipelineError(GABIException):
    """Base class for pipeline errors."""
    pass


class PhaseAlreadyRunningError(PipelineError):
    """Raised when trying to start a phase that's already running."""
    code = "PHASE_ALREADY_RUNNING"
    status_code = 409


class PhaseNotRunningError(PipelineError):
    """Raised when trying to stop a phase that's not running."""
    code = "PHASE_NOT_RUNNING"
    status_code = 409


class InvalidPhaseError(PipelineError):
    """Raised when an invalid phase is specified."""
    code = "INVALID_PHASE"
    status_code = 400
```

---

## Step 4: Update Frontend Types

Update `/home/fgamajr/dev/user-first-view/src/lib/dashboard-data.ts`:

```typescript
// Add these types alongside existing types

export interface PipelineSummaryStage {
  name: 'harvest' | 'sync' | 'ingest' | 'index';
  label: string;
  description: string;
  count: number;
  total: number;
  progress_pct: number;
  status: 'active' | 'idle' | 'error' | 'paused';
  lastActivity?: string;
  substages: string[];
}

export interface PipelineSummaryResponse {
  stages: PipelineSummaryStage[];
  overall_status: 'healthy' | 'degraded' | 'stalled' | 'paused';
  active_source_count: number;
  queued_source_count: number;
  generated_at: string;
}

export interface SyncJob {
  source_id: string;
  source_name: string;
  year: number;
  status: 'synced' | 'pending' | 'failed' | 'in_progress' | 'not_started';
  document_count: number;
  updated_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
}

export interface ElasticIndexInfo {
  name: string;
  alias?: string;
  document_count: number;
  size_bytes: number;
  health: 'green' | 'yellow' | 'red';
  created_at?: string;
}

export interface JobsResponse {
  sync_jobs: SyncJob[];
  elastic_indexes: ElasticIndexInfo[];
  total_elastic_docs: number;
  years_available: number[];
  generated_at: string;
}

export interface PipelineState {
  is_running: boolean;
  current_phase: string | null;
  active_sources: string[];
  queued_sources: string[];
  paused_phases: string[];
  rate_limit_docs_per_min: number;
}
```

---

## Step 5: Orchestrator Integration

The pipeline control endpoints need to integrate with the orchestrator at `/src/gabi/pipeline/orchestrator.py`.

### 5.1 Add State Management to Orchestrator

Add to `PipelineOrchestrator` class:

```python
class PipelineOrchestrator:
    # ... existing code ...
    
    async def is_cancelled(self, run_id: str) -> bool:
        """Check if the run has been cancelled."""
        if self.redis_client:
            cancelled = await self.redis_client.get(f"gabi:pipeline:cancel:{run_id}")
            return cancelled == b"1"
        return False
    
    async def update_state(self, state: Dict[str, Any]) -> None:
        """Update pipeline state in Redis."""
        if self.redis_client:
            await self.redis_client.hset("gabi:pipeline:state", mapping={
                k: str(v) for k, v in state.items()
            })
    
    async def _processing_phase(self, urls, source_id, source_config, run_id, stats):
        """Modified to check for cancellation."""
        for url in urls:
            # Check for cancellation
            if await self.is_cancelled(run_id):
                logger.info(f"Run {run_id} cancelled")
                raise asyncio.CancelledError(f"Run {run_id} cancelled by user")
            
            # Process URL...
            await self._process_single_url(...)
```

### 5.2 Add Celery Tasks

Create `/src/gabi/tasks/pipeline.py`:

```python
from celery import shared_task
from gabi.pipeline.orchestrator import PipelineOrchestrator

@shared_task(bind=True, max_retries=3)
def run_pipeline_phase(self, run_id: str, source_id: str, phase: str, **kwargs):
    """Run a pipeline phase for a source."""
    # Get database session
    from gabi.db import async_session_factory
    
    async def execute():
        async with async_session_factory() as session:
            orchestrator = PipelineOrchestrator(db_session=session)
            
            # Get source config
            result = await session.execute(
                text("SELECT config_json FROM source_registry WHERE id = :id"),
                {"id": source_id}
            )
            config = result.scalar_one_or_none()
            
            # Run phase
            stats = await orchestrator.run(
                source_id=source_id,
                source_config=config,
                resume_from=kwargs.get("resume_from"),
            )
            
            return stats
    
    import asyncio
    return asyncio.run(execute())
```

---

## Step 6: Testing

### 6.1 Unit Tests

Create `/tests/api/test_dashboard_extended.py`:

```python
import pytest
from fastapi.testclient import TestClient

class TestPipelineSummary:
    """Tests for GET /dashboard/pipeline/summary"""
    
    async def test_returns_4_stages(self, client: TestClient, auth_headers):
        response = client.get("/api/v1/dashboard/pipeline/summary", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["stages"]) == 4
        names = [s["name"] for s in data["stages"]]
        assert names == ["harvest", "sync", "ingest", "index"]
    
    async def test_stage_progress_calculation(self, client: TestClient, auth_headers):
        response = client.get("/api/v1/dashboard/pipeline/summary", headers=auth_headers)
        data = response.json()
        for stage in data["stages"]:
            assert 0 <= stage["progress_pct"] <= 100


class TestJobsEndpoint:
    """Tests for GET /dashboard/jobs"""
    
    async def test_returns_sync_jobs(self, client: TestClient, auth_headers):
        response = client.get("/api/v1/dashboard/jobs", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "sync_jobs" in data
        assert "elastic_indexes" in data
    
    async def test_year_filtering(self, client: TestClient, auth_headers):
        response = client.get(
            "/api/v1/dashboard/jobs?year_from=2020&year_to=2024",
            headers=auth_headers
        )
        data = response.json()
        for job in data["sync_jobs"]:
            assert 2020 <= job["year"] <= 2024


class TestPipelineControl:
    """Tests for pipeline control endpoints"""
    
    async def test_start_phase_requires_admin(self, client: TestClient, user_token):
        response = client.post(
            "/api/v1/dashboard/pipeline/indexing/start",
            json={},
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403
    
    async def test_admin_can_start_phase(self, client: TestClient, admin_token):
        response = client.post(
            "/api/v1/dashboard/pipeline/indexing/start",
            json={"source_ids": ["tcu_acordaos"]},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 202
        data = response.json()
        assert data["success"] is True
        assert "run_id" in data
```

### 6.2 Integration Tests

```python
class TestPipelineIntegration:
    """Integration tests for pipeline control flow"""
    
    async def test_full_pipeline_control_flow(self, client, admin_token):
        # 1. Get initial state
        response = client.get("/api/v1/dashboard/pipeline/state")
        initial_state = response.json()
        
        # 2. Start a phase
        response = client.post(
            "/api/v1/dashboard/pipeline/discovery/start",
            json={"source_ids": ["test_source"]},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        
        # 3. Check state is updated
        response = client.get("/api/v1/dashboard/pipeline/state")
        state = response.json()
        # ... assertions ...
        
        # 4. Stop the phase
        response = client.post(
            "/api/v1/dashboard/pipeline/discovery/stop",
            json={"graceful": True},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
```

---

## Step 7: Verification Checklist

After integration, verify:

- [ ] All new schemas are importable
- [ ] All new endpoints are registered
- [ ] Swagger docs show new endpoints at `/docs`
- [ ] Authentication works correctly (user vs admin)
- [ ] Pipeline summary returns 4 stages
- [ ] Jobs endpoint returns sync jobs and ES indexes
- [ ] Pipeline control endpoints accept admin requests
- [ ] Audit log entries are created for control operations
- [ ] Frontend types match backend responses
- [ ] Tests pass

---

## Quick Reference: API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/dashboard/stats` | User | Dashboard statistics |
| GET | `/dashboard/pipeline` | User | 9-phase pipeline view |
| GET | `/dashboard/pipeline/summary` | User | **NEW: 4-stage view** |
| GET | `/dashboard/jobs` | User | **NEW: Sync jobs & ES indexes** |
| GET | `/dashboard/activity` | User | Activity feed |
| GET | `/dashboard/health` | User | System health |
| GET | `/dashboard/pipeline/state` | User | **NEW: Pipeline state** |
| POST | `/dashboard/trigger-ingestion` | Admin | Trigger ingestion |
| POST | `/dashboard/pipeline/{phase}/start` | Admin | **NEW: Start phase** |
| POST | `/dashboard/pipeline/{phase}/stop` | Admin | **NEW: Stop phase** |
| POST | `/dashboard/pipeline/{phase}/restart` | Admin | **NEW: Restart phase** |
| POST | `/dashboard/pipeline/bulk-control` | Admin | **NEW: Bulk control** |

---

*End of Integration Guide*
