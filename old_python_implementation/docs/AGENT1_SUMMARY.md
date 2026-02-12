# Agent 1 Summary - Dashboard API Analysis & Design

## Task Completed

Analyzed the GABI project codebase and designed a comprehensive API specification for the frontend dashboard control panel.

---

## Files Created

### 1. `/docs/API_SPECIFICATION_DASHBOARD.md`
**Complete API specification document** with:
- Endpoint paths and methods
- Request/response Pydantic schemas
- Authentication requirements
- Error handling patterns
- Integration points with orchestrator
- SQL queries for data aggregation
- Frontend TypeScript type alignment

### 2. `/src/gabi/schemas/dashboard_extended.py`
**New Pydantic schemas** for:
- `PipelineSummaryResponse` - 4-stage pipeline view
- `JobsResponse` - Sync jobs by year + ES indexes
- `PipelineStateResponse` - Current pipeline state
- Control request/response schemas (start/stop/restart/bulk)

### 3. `/src/gabi/api/dashboard_extended.py`
**Implementation of new endpoints**:
- `GET /dashboard/pipeline/summary` - 4-stage pipeline progress
- `GET /dashboard/jobs` - Sync jobs and ES index info
- `GET /dashboard/pipeline/state` - Current processing state
- `POST /dashboard/pipeline/{phase}/start` - Start phase
- `POST /dashboard/pipeline/{phase}/stop` - Stop phase
- `POST /dashboard/pipeline/{phase}/restart` - Restart phase
- `POST /dashboard/pipeline/bulk-control` - Bulk operations

### 4. `/docs/INTEGRATION_GUIDE.md`
**Step-by-step integration instructions** for:
- Merging schemas with existing dashboard.py
- Merging endpoints with existing dashboard.py
- Adding pipeline exceptions
- Updating frontend TypeScript types
- Orchestrator integration requirements
- Testing strategy

---

## Key Design Decisions

### 1. 9 Phases → 4 Stages Mapping
The backend has 9 pipeline phases, but the frontend needs 4 conceptual stages:

| Frontend | Backend Phases |
|----------|----------------|
| `harvest` | discovery, change_detection |
| `sync` | fetch, parse, fingerprint |
| `ingest` | deduplication, chunking, embedding |
| `index` | indexing |

### 2. Authentication Levels
- **User access**: Read-only endpoints (stats, pipeline, jobs, activity, health)
- **Admin access**: Control endpoints (start, stop, restart, trigger-ingestion)

### 3. Integration with Orchestrator
Control endpoints set Redis flags that the orchestrator checks:
- `gabi:pipeline:cancel:{run_id}` - Cancellation flag
- `gabi:pipeline:paused` - Global pause flag
- `gabi:pipeline:state` - Current state hash

### 4. Data Sources
- **Pipeline summary**: Aggregates from `documents`, `document_chunks`, `execution_manifests`
- **Jobs endpoint**: Queries `execution_manifests` by year, ES cat API for indexes
- **State endpoint**: Redis (preferred) or computed from `execution_manifests`

---

## Existing Endpoints (No Changes Needed)

| Endpoint | Status | Notes |
|----------|--------|-------|
| `GET /dashboard/stats` | ✅ Works | May need to align with frontend types |
| `GET /dashboard/pipeline` | ✅ Works | Returns 9 phases (detailed view) |
| `GET /dashboard/activity` | ✅ Works | May add pagination |
| `GET /dashboard/health` | ✅ Works | Already returns component health |
| `POST /dashboard/trigger-ingestion` | ✅ Works | Admin only |

---

## New Endpoints Required

| # | Endpoint | Purpose |
|---|----------|---------|
| 1 | `GET /dashboard/pipeline/summary` | Frontend-friendly 4-stage view |
| 2 | `GET /dashboard/jobs` | Sync jobs by year + ES indexes |
| 3 | `GET /dashboard/pipeline/state` | Current pipeline state |
| 4 | `POST /dashboard/pipeline/{phase}/start` | Start a phase |
| 5 | `POST /dashboard/pipeline/{phase}/stop` | Stop a phase |
| 6 | `POST /dashboard/pipeline/{phase}/restart` | Restart a phase |
| 7 | `POST /dashboard/pipeline/bulk-control` | Bulk operations |

---

## Files Requiring Modification

| File | Action | Lines Added |
|------|--------|-------------|
| `/src/gabi/schemas/dashboard.py` | Import or merge extended schemas | ~20 |
| `/src/gabi/api/dashboard.py` | Import or merge extended endpoints | ~30 |
| `/src/gabi/exceptions.py` | Add pipeline exceptions | ~30 |
| `/src/gabi/pipeline/orchestrator.py` | Add cancellation checks | ~50 |

---

## Integration Status

### ✅ Ready for Integration
- Schemas defined and typed
- Endpoints implemented
- SQL queries optimized
- Auth requirements specified

### ⚠️ Requires Additional Work
- Celery task implementation for async execution
- Redis state management in orchestrator
- Frontend TypeScript type updates
- Unit and integration tests

---

## Frontend Alignment

The existing frontend types at `/home/fgamajr/dev/user-first-view/src/lib/dashboard-data.ts`:

```typescript
// Current (mock data)
interface PipelineStage {
  name: 'harvest' | 'sync' | 'ingest' | 'index';
  // ...
}

interface SyncJob {
  source: string;
  year: number;
  status: 'synced' | 'pending' | 'failed' | 'in_progress';
  // ...
}
```

The new API matches these types with minor enhancements (added `progress_pct`, `source_name`, etc.)

---

## Next Steps for Other Agents

1. **Agent 2 (Backend Implementation)**: Merge schemas and endpoints into existing files
2. **Agent 3 (Orchestrator Integration)**: Add Redis state management and cancellation
3. **Agent 4 (Frontend Integration)**: Update TypeScript types and API client
4. **Agent 5 (Testing)**: Create unit and integration tests

---

## Key SQL Patterns

### Pipeline Summary Query
```sql
-- Aggregate 9 phases into 4 stages
SELECT
    COUNT(*) FILTER (WHERE is_deleted = false) AS harvest_count,
    COUNT(*) FILTER (WHERE content_hash IS NOT NULL) AS sync_count,
    (SELECT COUNT(DISTINCT document_id) FROM document_chunks WHERE embedding IS NOT NULL) AS ingest_count,
    COUNT(*) FILTER (WHERE es_indexed = true) AS index_count
FROM documents
```

### Jobs by Year Query
```sql
-- Get sync status by year
SELECT 
    source_id,
    EXTRACT(YEAR FROM created_at)::int as year,
    COUNT(*) as doc_count,
    MAX(created_at) as last_doc_at
FROM documents
WHERE is_deleted = false
GROUP BY source_id, EXTRACT(YEAR FROM created_at)
```

---

## Deliverables Checklist

- [x] Analyzed existing API at `/src/gabi/api/dashboard.py`
- [x] Analyzed existing API at `/src/gabi/api/admin.py`
- [x] Analyzed frontend types at `/home/fgamajr/dev/user-first-view/src/lib/dashboard-data.ts`
- [x] Analyzed orchestrator at `/src/gabi/pipeline/orchestrator.py`
- [x] Created detailed API specification
- [x] Created Pydantic schemas for new endpoints
- [x] Implemented new endpoint handlers
- [x] Created integration guide
- [x] Mapped 9 backend phases → 4 frontend stages
- [x] Identified authentication requirements
- [x] Specified error handling patterns
- [x] Documented integration points with orchestrator

---

*Analysis completed by Agent 1*
*Date: 2026-02-11*
