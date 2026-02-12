# GABI Dashboard API Specification

> **Agent 1 Analysis - Frontend Dashboard Control Panel**
> 
> Date: 2026-02-11
> Project: GABI (Gerador Automático de Boletins por Inteligência Artificial)
> Backend: FastAPI + PostgreSQL + Elasticsearch + Redis + Celery
> Frontend: React + TypeScript (located at `/home/fgamajr/dev/user-first-view`)

---

## 1. Executive Summary

This document provides a detailed API specification for the GABI dashboard control panel endpoints. It covers:
- **Existing endpoints** that require NO changes
- **Existing endpoints** that need MODIFICATIONS
- **New endpoints** that need to be CREATED

### Mapping: 9 Backend Phases → 4 Frontend Stages

The backend has 9 pipeline phases (PipelinePhase enum), but the frontend displays 4 conceptual stages:

| Frontend Stage | Backend Phases | Description |
|----------------|----------------|-------------|
| `harvest` | `discovery`, `change_detection` | Discovery of URLs and change detection |
| `sync` | `fetch`, `parse`, `fingerprint` | Download, parsing, and fingerprinting |
| `ingest` | `deduplication`, `chunking`, `embedding` | Deduplication, chunking, and embedding |
| `index` | `indexing` | Elasticsearch indexing |

---

## 2. Current API Structure

```
/api/v1/
├── dashboard/
│   ├── stats              GET    - Dashboard statistics
│   ├── pipeline           GET    - Pipeline stage progress (9 phases)
│   ├── activity           GET    - Activity feed
│   ├── health             GET    - System health
│   └── trigger-ingestion  POST   - Trigger ingestion (admin)
├── admin/
│   ├── executions         GET    - List executions
│   ├── executions/{id}    GET    - Execution detail
│   ├── dlq                GET    - DLQ messages
│   ├── dlq/{id}/retry     POST   - Retry DLQ message
│   └── stats              GET    - System stats
├── search/                - Search endpoints
├── documents/             - Document endpoints
├── sources/               - Source management
└── health/                - Health checks
```

---

## 3. Endpoint Specifications

### 3.1 Dashboard Stats Endpoint (EXISTS - No Changes Needed)

**Endpoint:** `GET /api/v1/dashboard/stats`

**Current State:** ✅ Fully implemented

**Authentication:** Required (any authenticated user)

**Response Schema (DashboardStatsResponse):**
```python
class DashboardStatsResponse(BaseModel):
    sources: List[DashboardSourceSummary]     # Source summaries
    total_documents: int                      # Active documents
    total_chunks: int                         # Total chunks
    total_indexed: int                        # ES indexed docs
    total_embeddings: int                     # Chunks with embeddings
    active_sources: int                       # Active source count
    documents_last_24h: int                   # Recent documents
    dlq_pending: int                          # Pending DLQ messages
    elasticsearch_available: bool             # ES availability
    total_elastic_docs: Optional[int]         # ES document count
    generated_at: datetime                    # Response timestamp
```

**Integration Points:**
- Queries `source_registry` table for source information
- Queries `documents`, `document_chunks`, `dlq_messages` for counts
- Probes Elasticsearch for availability and document count

---

### 3.2 Pipeline Status Endpoints

#### 3.2.1 Existing: 9-Phase Pipeline Status (EXISTS - No Changes)

**Endpoint:** `GET /api/v1/dashboard/pipeline`

**Current State:** ✅ Fully implemented (returns 9 phases)

**Use Case:** Detailed backend monitoring

**Response Schema (DashboardPipelineResponse):**
```python
class DashboardPipelineResponse(BaseModel):
    stages: List[PipelineStageInfo]           # 9 phases exactly
    overall_status: Literal["healthy", "degraded", "stalled"]
    generated_at: datetime

class PipelineStageInfo(BaseModel):
    name: PipelinePhase                       # discovery, fetch, etc.
    label: str                                # Human-readable label (pt-BR)
    description: str                          # Phase description
    count: int                                # Documents completed
    total: int                                # Total documents
    failed: int                               # Failed count
    status: Literal["active", "idle", "error"]
    last_activity: Optional[datetime]
```

#### 3.2.2 NEW: 4-Stage Pipeline Status (Frontend-Friendly)

**Endpoint:** `GET /api/v1/dashboard/pipeline/summary`

**Status:** 🔧 **TO BE CREATED**

**Purpose:** Returns the 4-stage view matching frontend expectations

**Authentication:** Required (any authenticated user)

**Request Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| source_id | str | No | Filter by specific source |

**Response Schema (NEW):**
```python
class PipelineSummaryStage(BaseModel):
    """One of the 4 frontend-facing pipeline stages."""
    name: Literal["harvest", "sync", "ingest", "index"]
    label: str                                    # pt-BR label
    description: str                              # Description
    count: int                                    # Documents in stage
    total: int                                    # Total documents
    progress_pct: float                           # 0.0 - 100.0
    status: Literal["active", "idle", "error", "paused"]
    last_activity: Optional[datetime]
    substages: List[str]                          # Backend phases included

class PipelineSummaryResponse(BaseModel):
    """4-stage pipeline summary for frontend dashboard."""
    stages: List[PipelineSummaryStage]            # Exactly 4 stages
    overall_status: Literal["healthy", "degraded", "stalled", "paused"]
    active_source_count: int                      # Sources being processed
    queued_source_count: int                      # Sources queued
    generated_at: datetime
```

**Stage Mapping Logic:**
```python
STAGE_MAPPING = {
    "harvest": ["discovery", "change_detection"],
    "sync": ["fetch", "parse", "fingerprint"],
    "ingest": ["deduplication", "chunking", "embedding"],
    "index": ["indexing"]
}

# Stage progress calculation:
# - harvest: count = documents discovered (from execution_manifests)
# - sync: count = documents with content_hash (fetched/parsed)
# - ingest: count = chunks with embeddings
# - index: count = documents with es_indexed=true
```

**Implementation Notes:**
- File: `/src/gabi/api/dashboard.py`
- Reuse existing CTE query patterns from `get_dashboard_pipeline()`
- Aggregate 9 phases into 4 stages using SQL CASE statements

---

### 3.3 Jobs Endpoint (NEW)

**Endpoint:** `GET /api/v1/dashboard/jobs`

**Status:** 🔧 **TO BE CREATED**

**Purpose:** Returns sync jobs grouped by year and Elasticsearch indexes

**Authentication:** Required (any authenticated user)

**Request Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| source_id | str | No | Filter by specific source |
| year_from | int | No | Start year filter |
| year_to | int | No | End year filter |

**Response Schema (NEW):**
```python
class SyncJob(BaseModel):
    """Represents a synchronization job for a specific year."""
    source_id: str                                # Source identifier
    source_name: str                              # Human-readable name
    year: int                                     # Year (e.g., 2024)
    status: Literal["synced", "pending", "failed", "in_progress", "not_started"]
    document_count: int                           # Documents for this year
    updated_at: Optional[datetime]                # Last update timestamp
    started_at: Optional[datetime]                # When sync started
    completed_at: Optional[datetime]              # When sync completed
    error_message: Optional[str]                  # Error if failed

class ElasticIndexInfo(BaseModel):
    """Information about an Elasticsearch index."""
    name: str                                     # Index name (e.g., "gabi_tcu_acordaos")
    alias: Optional[str]                          # Index alias
    document_count: int                           # Number of documents
    size_bytes: int                               # Index size in bytes
    health: Literal["green", "yellow", "red"]     # Index health
    created_at: Optional[datetime]                # Index creation date

class JobsResponse(BaseModel):
    """Response for jobs endpoint."""
    sync_jobs: List[SyncJob]                      # Sync jobs by year
    elastic_indexes: List[ElasticIndexInfo]       # ES indexes info
    total_elastic_docs: int                       # Total across all indexes
    years_available: List[int]                    # Years with data
    generated_at: datetime
```

**Data Sources:**
- `execution_manifests` table for execution history
- `documents` table with date filtering for year counts
- Elasticsearch cat API for index information

**Implementation Approach:**
```python
# SQL for year-based aggregation:
"""
SELECT 
    source_id,
    EXTRACT(YEAR FROM created_at) as year,
    COUNT(*) as document_count,
    MAX(created_at) as last_updated
FROM documents
WHERE is_deleted = false
GROUP BY source_id, EXTRACT(YEAR FROM created_at)
ORDER BY year DESC
"""

# Execution status from execution_manifests by year
"""
SELECT 
    source_id,
    status,
    started_at,
    completed_at,
    stats->>'documents_indexed' as docs_indexed
FROM execution_manifests
WHERE started_at >= :year_start AND started_at < :year_end
ORDER BY started_at DESC
"""
```

---

### 3.4 Activity Feed Endpoint (EXISTS - Minor Enhancement)

**Endpoint:** `GET /api/v1/dashboard/activity`

**Current State:** ✅ Implemented, minor enhancements needed

**Authentication:** Required (any authenticated user)

**Existing Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| limit | int | 50 | Max events to return (1-200) |
| severity | str | None | Filter by severity |
| event_type | str | None | Filter by event type |
| source_id | str | None | Filter by source ID |

**Suggested Enhancement:** Add pagination support
```python
class DashboardActivityResponse(BaseModel):
    events: List[ActivityEvent]
    total: int
    has_more: bool
    # NEW FIELDS:
    page: int = 1
    page_size: int
    next_cursor: Optional[str]  # For cursor-based pagination
```

---

### 3.5 Health Check Endpoint (EXISTS - No Changes Needed)

**Endpoint:** `GET /api/v1/dashboard/health`

**Current State:** ✅ Fully implemented

**Response Schema (DashboardHealthResponse):**
```python
class ComponentHealth(BaseModel):
    name: str                                     # postgresql, elasticsearch, redis, tei
    status: Literal["online", "degraded", "offline"]
    latency_ms: Optional[float]
    version: Optional[str]
    details: Dict[str, Any]

class DashboardHealthResponse(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    uptime_seconds: float
    components: List[ComponentHealth]
    generated_at: datetime
```

---

### 3.6 Pipeline Control Endpoints (NEW)

**Base Path:** `/api/v1/dashboard/pipeline`

**Status:** 🔧 **TO BE CREATED**

**Purpose:** Start, stop, restart pipeline phases

#### 3.6.1 Get Pipeline State

**Endpoint:** `GET /api/v1/dashboard/pipeline/state`

**Response Schema:**
```python
class PipelineState(BaseModel):
    """Current state of the pipeline processing."""
    is_running: bool
    current_phase: Optional[PipelinePhase]
    active_sources: List[str]
    queued_sources: List[str]
    paused_phases: List[PipelinePhase]
    rate_limit_docs_per_min: int
    
class PipelineStateResponse(BaseModel):
    state: PipelineState
    generated_at: datetime
```

#### 3.6.2 Start Pipeline Phase

**Endpoint:** `POST /api/v1/dashboard/pipeline/{phase}/start`

**Authentication:** Admin role required

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| phase | str | Phase name: discovery, change_detection, fetch, parse, fingerprint, deduplication, chunking, embedding, indexing |

**Request Body:**
```python
class StartPhaseRequest(BaseModel):
    source_ids: Optional[List[str]] = None        # Specific sources (null = all)
    resume_from: Optional[str] = None             # Run ID to resume
    priority: Literal["normal", "high"] = "normal"
    rate_limit: Optional[int] = None              # Max docs per minute
```

**Response Schema:**
```python
class StartPhaseResponse(BaseModel):
    success: bool
    run_id: Optional[str]
    phase: PipelinePhase
    sources_affected: List[str]
    estimated_completion: Optional[datetime]
    message: str
    started_at: datetime
```

#### 3.6.3 Stop/Pause Pipeline Phase

**Endpoint:** `POST /api/v1/dashboard/pipeline/{phase}/stop`

**Authentication:** Admin role required

**Request Body:**
```python
class StopPhaseRequest(BaseModel):
    graceful: bool = True                         # Wait for current items
    timeout_seconds: int = 60                     # Max wait time
    reason: Optional[str] = None                  # Reason for stopping
```

**Response Schema:**
```python
class StopPhaseResponse(BaseModel):
    success: bool
    phase: PipelinePhase
    items_in_progress: int                        # Items being processed
    items_queued: int                             # Items remaining
    stopped_at: datetime
    message: str
```

#### 3.6.4 Restart Pipeline Phase

**Endpoint:** `POST /api/v1/dashboard/pipeline/{phase}/restart`

**Authentication:** Admin role required

**Request Body:**
```python
class RestartPhaseRequest(BaseModel):
    source_ids: Optional[List[str]] = None
    clear_errors: bool = False                    # Clear previous errors
    full_reprocess: bool = False                  # Reprocess all docs
    reason: Optional[str] = None
```

**Response Schema:**
```python
class RestartPhaseResponse(BaseModel):
    success: bool
    run_id: str
    phase: PipelinePhase
    sources_affected: List[str]
    cleared_errors: int                           # If clear_errors=true
    message: str
    restarted_at: datetime
```

#### 3.6.5 Bulk Pipeline Control

**Endpoint:** `POST /api/v1/dashboard/pipeline/bulk-control`

**Authentication:** Admin role required

**Request Body:**
```python
class BulkControlAction(str, Enum):
    PAUSE_ALL = "pause_all"
    RESUME_ALL = "resume_all"
    STOP_ALL = "stop_all"
    RESTART_FAILED = "restart_failed"

class BulkControlRequest(BaseModel):
    action: BulkControlAction
    source_ids: Optional[List[str]] = None
```

**Response Schema:**
```python
class BulkControlResponse(BaseModel):
    success: bool
    action: BulkControlAction
    affected_phases: List[PipelinePhase]
    affected_sources: List[str]
    message: str
    executed_at: datetime
```

---

## 4. Schema Extensions

### 4.1 New Schemas to Add to `dashboard.py`

```python
# /src/gabi/schemas/dashboard.py additions

from typing import List, Literal, Optional
from datetime import datetime
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# GET /dashboard/pipeline/summary (4-stage view)
# ---------------------------------------------------------------------------

class PipelineSummaryStage(BaseModel):
    name: Literal["harvest", "sync", "ingest", "index"]
    label: str = Field(..., description="Rótulo em português")
    description: str
    count: int = Field(..., ge=0)
    total: int = Field(..., ge=0)
    progress_pct: float = Field(..., ge=0.0, le=100.0)
    status: Literal["active", "idle", "error", "paused"]
    last_activity: Optional[datetime] = None
    substages: List[str] = Field(default_factory=list)

class PipelineSummaryResponse(BaseModel):
    stages: List[PipelineSummaryStage] = Field(..., min_length=4, max_length=4)
    overall_status: Literal["healthy", "degraded", "stalled", "paused"]
    active_source_count: int = Field(..., ge=0)
    queued_source_count: int = Field(..., ge=0)
    generated_at: datetime

# ---------------------------------------------------------------------------
# GET /dashboard/jobs
# ---------------------------------------------------------------------------

class SyncJob(BaseModel):
    source_id: str
    source_name: str
    year: int
    status: Literal["synced", "pending", "failed", "in_progress", "not_started"]
    document_count: int = Field(..., ge=0)
    updated_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

class ElasticIndexInfo(BaseModel):
    name: str
    alias: Optional[str] = None
    document_count: int = Field(..., ge=0)
    size_bytes: int = Field(..., ge=0)
    health: Literal["green", "yellow", "red"]
    created_at: Optional[datetime] = None

class JobsResponse(BaseModel):
    sync_jobs: List[SyncJob]
    elastic_indexes: List[ElasticIndexInfo]
    total_elastic_docs: int = Field(..., ge=0)
    years_available: List[int] = Field(default_factory=list)
    generated_at: datetime

# ---------------------------------------------------------------------------
# Pipeline Control Schemas
# ---------------------------------------------------------------------------

class PipelineState(BaseModel):
    is_running: bool
    current_phase: Optional[str] = None
    active_sources: List[str] = Field(default_factory=list)
    queued_sources: List[str] = Field(default_factory=list)
    paused_phases: List[str] = Field(default_factory=list)
    rate_limit_docs_per_min: int = Field(default=0)

class PipelineStateResponse(BaseModel):
    state: PipelineState
    generated_at: datetime

class StartPhaseRequest(BaseModel):
    source_ids: Optional[List[str]] = None
    resume_from: Optional[str] = None
    priority: Literal["normal", "high"] = "normal"
    rate_limit: Optional[int] = Field(None, ge=1, le=10000)

class StartPhaseResponse(BaseModel):
    success: bool
    run_id: Optional[str] = None
    phase: str
    sources_affected: List[str] = Field(default_factory=list)
    estimated_completion: Optional[datetime] = None
    message: str
    started_at: datetime

class StopPhaseRequest(BaseModel):
    graceful: bool = True
    timeout_seconds: int = Field(60, ge=0, le=300)
    reason: Optional[str] = None

class StopPhaseResponse(BaseModel):
    success: bool
    phase: str
    items_in_progress: int = Field(..., ge=0)
    items_queued: int = Field(..., ge=0)
    stopped_at: datetime
    message: str

class RestartPhaseRequest(BaseModel):
    source_ids: Optional[List[str]] = None
    clear_errors: bool = False
    full_reprocess: bool = False
    reason: Optional[str] = None

class RestartPhaseResponse(BaseModel):
    success: bool
    run_id: str
    phase: str
    sources_affected: List[str] = Field(default_factory=list)
    cleared_errors: int = Field(..., ge=0)
    message: str
    restarted_at: datetime

class BulkControlAction(str, Enum):
    PAUSE_ALL = "pause_all"
    RESUME_ALL = "resume_all"
    STOP_ALL = "stop_all"
    RESTART_FAILED = "restart_failed"

class BulkControlRequest(BaseModel):
    action: BulkControlAction
    source_ids: Optional[List[str]] = None

class BulkControlResponse(BaseModel):
    success: bool
    action: BulkControlAction
    affected_phases: List[str] = Field(default_factory=list)
    affected_sources: List[str] = Field(default_factory=list)
    message: str
    executed_at: datetime
```

---

## 5. Implementation Guide

### 5.1 File Modifications

#### 5.1.1 `/src/gabi/schemas/dashboard.py`

**Action:** Append new schemas (section 4.1 above) to the existing file

**Lines to add after line 214:** ~250 lines of new schema definitions

#### 5.1.2 `/src/gabi/api/dashboard.py`

**Action:** Add new endpoint handlers

**New endpoints to add:**

1. `GET /api/v1/dashboard/pipeline/summary` - 4-stage pipeline view
2. `GET /api/v1/dashboard/jobs` - Sync jobs and ES indexes
3. `GET /api/v1/dashboard/pipeline/state` - Current pipeline state
4. `POST /api/v1/dashboard/pipeline/{phase}/start` - Start phase
5. `POST /api/v1/dashboard/pipeline/{phase}/stop` - Stop phase
6. `POST /api/v1/dashboard/pipeline/{phase}/restart` - Restart phase
7. `POST /api/v1/dashboard/pipeline/bulk-control` - Bulk operations

### 5.2 Integration with Orchestrator

The pipeline control endpoints must integrate with `PipelineOrchestrator` at `/src/gabi/pipeline/orchestrator.py`:

```python
# Integration points:

1. State Management:
   - Orchestrator maintains _manifest: PipelineManifest
   - Need to expose state query methods
   - Store state in Redis for distributed access

2. Start Phase:
   - Calls orchestrator.run() for each source
   - Queue via Celery for async execution
   - Track run_id in execution_manifests

3. Stop Phase:
   - Set cancellation flag in Redis
   - Orchestrator checks flag in _processing_phase()
   - Graceful: wait for current URLs, Force: immediate stop

4. Restart Phase:
   - Stop current execution if running
   - Clear checkpoint if full_reprocess
   - Start new execution
```

### 5.3 Redis State Keys

```python
# Redis key structure for pipeline state:
"gabi:pipeline:state"                    # Global pipeline state
"gabi:pipeline:active_runs"              # Set of active run_ids
"gabi:pipeline:phase:{phase}:status"     # Per-phase status
"gabi:pipeline:source:{source_id}:run"   # Current run for source
"gabi:pipeline:pause_requested"          # Pause flag
"gabi:pipeline:cancel:{run_id}"          # Cancellation flag per run
```

---

## 6. Authentication & Authorization

### 6.1 Auth Requirements by Endpoint

| Endpoint | Auth | Roles |
|----------|------|-------|
| GET /stats | Required | Any |
| GET /pipeline | Required | Any |
| GET /pipeline/summary | Required | Any |
| GET /jobs | Required | Any |
| GET /activity | Required | Any |
| GET /health | Required | Any |
| GET /pipeline/state | Required | Any |
| POST /trigger-ingestion | Required | admin |
| POST /pipeline/{phase}/start | Required | admin |
| POST /pipeline/{phase}/stop | Required | admin |
| POST /pipeline/{phase}/restart | Required | admin |
| POST /pipeline/bulk-control | Required | admin |

### 6.2 Using RequireAuth Middleware

```python
from gabi.auth.middleware import RequireAuth

# For public read access (any authenticated user):
@router.get("/stats")
async def get_stats(_user: dict = Depends(RequireAuth())):
    ...

# For admin-only operations:
@router.post("/pipeline/{phase}/start")
async def start_phase(_user: dict = Depends(RequireAuth(roles=["admin"]))):
    ...
```

---

## 7. Error Handling Patterns

### 7.1 Standard Error Response

```python
{
    "error": {
        "code": "PIPELINE_ALREADY_RUNNING",
        "message": "Phase 'indexing' is already running for source 'tcu_acordaos'",
        "request_id": "req_1234567890",
        "details": {
            "phase": "indexing",
            "source_id": "tcu_acordaos",
            "current_run_id": "run_abc123"
        }
    }
}
```

### 7.2 HTTP Status Codes

| Code | Usage |
|------|-------|
| 200 | Successful GET/POST |
| 400 | Bad request (invalid parameters) |
| 401 | Unauthorized (missing/invalid token) |
| 403 | Forbidden (insufficient permissions) |
| 404 | Resource not found |
| 409 | Conflict (e.g., phase already running) |
| 422 | Validation error |
| 429 | Rate limited |
| 500 | Internal server error |

### 7.3 Custom Exceptions

```python
# Add to /src/gabi/exceptions.py

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

## 8. Frontend Type Alignment

### 8.1 TypeScript Types (for /home/fgamajr/dev/user-first-view)

```typescript
// Types matching the new API responses

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

## 9. Testing Strategy

### 9.1 Unit Tests

```python
# Test file: /tests/api/test_dashboard.py

class TestPipelineSummary:
    async def test_returns_4_stages(self, client):
        response = await client.get("/api/v1/dashboard/pipeline/summary")
        assert len(response.json()["stages"]) == 4
        
    async def test_stage_mapping(self, client):
        response = await client.get("/api/v1/dashboard/pipeline/summary")
        stages = response.json()["stages"]
        names = [s["name"] for s in stages]
        assert names == ["harvest", "sync", "ingest", "index"]

class TestJobsEndpoint:
    async def test_returns_sync_jobs(self, client):
        response = await client.get("/api/v1/dashboard/jobs")
        assert "sync_jobs" in response.json()
        assert "elastic_indexes" in response.json()
        
    async def test_year_filtering(self, client):
        response = await client.get("/api/v1/dashboard/jobs?year_from=2020&year_to=2024")
        jobs = response.json()["sync_jobs"]
        for job in jobs:
            assert 2020 <= job["year"] <= 2024

class TestPipelineControl:
    async def test_start_phase_requires_admin(self, client, normal_user_token):
        response = await client.post(
            "/api/v1/dashboard/pipeline/indexing/start",
            headers={"Authorization": f"Bearer {normal_user_token}"}
        )
        assert response.status_code == 403
        
    async def test_cannot_start_already_running_phase(self, client, admin_token):
        # Start phase
        await client.post(
            "/api/v1/dashboard/pipeline/indexing/start",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        # Try to start again
        response = await client.post(
            "/api/v1/dashboard/pipeline/indexing/start",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 409
```

---

## 10. Summary of Changes

### 10.1 Files to Modify

| File | Action | Lines |
|------|--------|-------|
| `/src/gabi/schemas/dashboard.py` | Append new schemas | +250 lines |
| `/src/gabi/api/dashboard.py` | Add 7 new endpoints | +400 lines |
| `/src/gabi/exceptions.py` | Add pipeline exceptions | +30 lines |

### 10.2 Existing Endpoints (No Changes)

- ✅ `GET /api/v1/dashboard/stats`
- ✅ `GET /api/v1/dashboard/pipeline` (9-phase view)
- ✅ `GET /api/v1/dashboard/activity`
- ✅ `GET /api/v1/dashboard/health`
- ✅ `POST /api/v1/dashboard/trigger-ingestion`

### 10.3 New Endpoints to Create

| # | Method | Path | Purpose |
|---|--------|------|---------|
| 1 | GET | `/api/v1/dashboard/pipeline/summary` | 4-stage pipeline view |
| 2 | GET | `/api/v1/dashboard/jobs` | Sync jobs & ES indexes |
| 3 | GET | `/api/v1/dashboard/pipeline/state` | Current pipeline state |
| 4 | POST | `/api/v1/dashboard/pipeline/{phase}/start` | Start a phase |
| 5 | POST | `/api/v1/dashboard/pipeline/{phase}/stop` | Stop a phase |
| 6 | POST | `/api/v1/dashboard/pipeline/{phase}/restart` | Restart a phase |
| 7 | POST | `/api/v1/dashboard/pipeline/bulk-control` | Bulk operations |

### 10.4 Integration Requirements

1. **Redis:** Add state management keys for pipeline control
2. **Celery:** Queue long-running phase operations
3. **Orchestrator:** Extend with cancellation/resume support
4. **Audit Log:** Log all control operations

---

## 11. Appendix: Database Queries

### 11.1 Pipeline Summary Query

```sql
-- Aggregate 9 phases into 4 stages
WITH phase_stats AS (
    SELECT
        -- Harvest: discovery + change_detection (implied by document creation)
        COUNT(*) FILTER (WHERE is_deleted = false) AS harvest_total,
        
        -- Sync: fetch + parse + fingerprint (has content_hash)
        COUNT(*) FILTER (WHERE content_hash IS NOT NULL AND is_deleted = false) AS sync_count,
        
        -- Ingest: chunks with embeddings
        (SELECT COUNT(DISTINCT document_id) 
         FROM document_chunks 
         WHERE embedding IS NOT NULL AND is_deleted = false) AS ingest_count,
        
        -- Index: es_indexed
        COUNT(*) FILTER (WHERE es_indexed = true AND is_deleted = false) AS index_count,
        
        -- Totals
        COUNT(*) FILTER (WHERE is_deleted = false) AS total_docs
    FROM documents
),
activity AS (
    SELECT 
        MAX(ingested_at) as last_ingest,
        MAX(es_indexed_at) as last_index,
        MAX(created_at) as last_chunk
    FROM documents d
    LEFT JOIN document_chunks dc ON d.id = dc.document_id
)
SELECT 
    ps.*,
    a.last_ingest,
    a.last_index,
    a.last_chunk
FROM phase_stats ps
CROSS JOIN activity a;
```

### 11.2 Jobs Query (Year-based)

```sql
-- Get sync status by year from execution_manifests
WITH years AS (
    SELECT DISTINCT EXTRACT(YEAR FROM started_at)::int as year
    FROM execution_manifests
    WHERE started_at IS NOT NULL
    ORDER BY year DESC
),
exec_by_year AS (
    SELECT 
        source_id,
        EXTRACT(YEAR FROM started_at)::int as year,
        status,
        started_at,
        completed_at,
        stats->>'documents_indexed' as docs_indexed
    FROM execution_manifests
    WHERE started_at >= NOW() - INTERVAL '5 years'
),
docs_by_year AS (
    SELECT 
        source_id,
        EXTRACT(YEAR FROM created_at)::int as year,
        COUNT(*) as doc_count
    FROM documents
    WHERE is_deleted = false
    GROUP BY source_id, EXTRACT(YEAR FROM created_at)
)
SELECT 
    y.year,
    sr.id as source_id,
    sr.name as source_name,
    COALESCE(dby.doc_count, 0) as document_count,
    eby.status,
    eby.started_at,
    eby.completed_at
FROM years y
CROSS JOIN source_registry sr
LEFT JOIN docs_by_year dby ON y.year = dby.year AND sr.id = dby.source_id
LEFT JOIN exec_by_year eby ON y.year = eby.year AND sr.id = eby.source_id
WHERE sr.deleted_at IS NULL
ORDER BY y.year DESC, sr.id;
```

---

*End of Specification*
