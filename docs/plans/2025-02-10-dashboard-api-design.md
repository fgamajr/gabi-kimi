# API Design for GABI Dashboard Web Interface

## Executive Summary

This document outlines the design of a new API module for the GABI (Gerador Automático de Boletins por Inteligência Artificial) platform to support the planned "user-first-view" dashboard webpage. The API will bridge the gap between GABI's existing data models and the frontend's data requirements, providing a unified interface for monitoring document processing pipelines, data sources, and system health.

---

## 1. Understanding the Context

### 1.1 The GABI Platform

GABI is a sophisticated document ingestion and search platform developed for TCU (Tribunal de Contas da União). It processes legal documents through a multi-stage pipeline:

```
Discovery → Fetch → Parse → Chunk → Embed → Index
```

The platform uses a hybrid search architecture combining BM25 (Elasticsearch) with semantic vector search (pgvector), providing intelligent access to acórdãos, normas internas, súmulas, and other institutional publications.

### 1.2 Existing Data Architecture

GABI's data layer is built on PostgreSQL with several key models:

**SourceRegistry**: Central registry for configured data sources (acórdãos, normas, etc.)
- Tracks source metadata, configuration, and sync status
- Maintains document count statistics and error tracking
- Supports soft delete and governance attributes (owner, sensitivity, retention)

**Document**: Core entity for ingested legal documents
- UUID-based identification with external document_id
- Content fingerprinting (SHA-256) for deduplication
- Soft delete support with audit trail
- Elasticsearch synchronization tracking
- JSONB metadata for extensibility

**DocumentChunk**: Vectorized chunks for semantic search
- 384-dimensional embeddings (multilingual MiniLM-L12-v2)
- Section type classification (artigo, parágrafo, ementa)
- Token and character counts

**ExecutionManifest**: Pipeline execution tracking
- Run-level tracking with checkpoint support
- Status management (pending, running, success, failed)
- Statistics and error logging

**DLQMessage**: Dead Letter Queue for failed processing
- Exponential backoff retry logic
- Error classification and resolution workflow

**LineageNode/LineageEdge**: Data lineage as a DAG
- Tracks provenance and dependencies
- Supports audit and compliance requirements

**AuditLog**: Immutable event log with hash chain integrity

### 1.3 The Webpage Requirements

The planned dashboard (user-first-view) requires three primary data domains:

**1. Source Statistics (`StatsResponse`)**
```typescript
interface StatsResponse {
  sources: Source[];           // Configured data sources
  total_documents: number;     // Aggregate document count
  elasticsearch_available: boolean;  // ES health status
}
```

**2. Synchronization Jobs (`JobsResponse`)**
```typescript
interface JobsResponse {
  sync_jobs: SyncJob[];        // Year-by-year sync status
  elastic_indexes: Record<string, number>;  // ES index sizes
  total_elastic_docs: number;  // Total indexed documents
}
```

**3. Pipeline Stages (`PipelineStage`)**
```typescript
interface PipelineStage {
  name: 'harvest' | 'sync' | 'ingest' | 'index';
  label: string;
  description: string;
  count: number;
  total: number;
  status: 'active' | 'idle' | 'error';
  lastActivity?: string;
}
```

---

## 2. Analysis: Mapping Backend to Frontend

### 2.1 Data Availability Assessment

**Well-Mapped Data:**
- `Source` → `SourceRegistry`: Direct mapping with minor field name differences
- `total_documents` → `Document` count aggregation
- `elasticsearch_available` → ES cluster health check

**Partially-Mapped Data:**
- `SyncJob`: The concept of "year-based sync jobs" doesn't directly exist in GABI. The platform uses `ExecutionManifest` for run tracking, but doesn't break down by year in the way the frontend expects.
- `PipelineStage`: GABI has execution manifests and DLQ, but doesn't explicitly track the 4-stage pipeline progress as discrete counters.

**Requires Derivation:**
- The sync job concept needs to be derived from execution history combined with source configuration (which includes year ranges in `sources.yaml`)
- Pipeline stage counts need to be derived from document status transitions and execution manifest statistics

### 2.2 Architectural Considerations

**Performance:**
The dashboard will be frequently refreshed (every 30-60 seconds based on UI patterns). We need:
- Efficient aggregation queries with proper indexing
- Caching strategy for expensive aggregations
- Pagination for large datasets

**Consistency:**
- Real-time accuracy is preferred but not critical for monitoring
- Eventual consistency is acceptable for statistics
- Cache invalidation on pipeline completion events

**Scalability:**
- Current data volume: ~500K documents
- Projected growth: Potentially millions with new sources
- Query patterns: Read-heavy with periodic aggregation

---

## 3. API Design

### 3.1 Endpoint Structure

```
GET  /api/v1/dashboard/stats           # Source statistics and totals
GET  /api/v1/dashboard/jobs            # Sync jobs with filtering
GET  /api/v1/dashboard/pipeline        # Pipeline stage progress
GET  /api/v1/dashboard/health          # Component health status
GET  /api/v1/dashboard/activity        # Recent activity feed
```

### 3.2 Schema Design

**DashboardStatsResponse:**
```json
{
  "timestamp": "2025-02-10T12:00:00Z",
  "sources": [
    {
      "id": "tcu_acordaos",
      "description": "Acórdãos do TCU",
      "source_type": "csv_http",
      "enabled": true,
      "document_count": 497566,
      "last_sync_at": "2025-02-10T10:30:00Z",
      "status": "active"
    }
  ],
  "total_documents": 497566,
  "elasticsearch_available": true,
  "components_health": {
    "postgresql": "healthy",
    "elasticsearch": "healthy",
    "redis": "healthy"
  }
}
```

**DashboardJobsResponse:**
```json
{
  "timestamp": "2025-02-10T12:00:00Z",
  "sync_jobs": [
    {
      "source": "tcu_acordaos",
      "year": 2024,
      "status": "synced",
      "updated_at": "2025-01-21T10:30:00Z",
      "documents_processed": 15420,
      "execution_id": "uuid"
    }
  ],
  "elastic_indexes": {
    "gabi_tcu_acordaos": 497566
  },
  "total_elastic_docs": 497566,
  "pagination": {
    "total": 45,
    "page": 1,
    "per_page": 10
  }
}
```

**DashboardPipelineResponse:**
```json
{
  "timestamp": "2025-02-10T12:00:00Z",
  "stages": [
    {
      "name": "harvest",
      "label": "Harvest",
      "description": "Download from sources",
      "count": 497566,
      "total": 497566,
      "status": "active",
      "last_activity": "2025-02-10T10:30:00Z"
    },
    {
      "name": "sync",
      "label": "Sync",
      "description": "PostgreSQL ingestion",
      "count": 497566,
      "total": 497566,
      "status": "active",
      "last_activity": "2025-02-10T10:30:00Z"
    },
    {
      "name": "ingest",
      "label": "Ingest",
      "description": "Document processing",
      "count": 495234,
      "total": 497566,
      "status": "active",
      "last_activity": "2025-02-10T10:28:00Z"
    },
    {
      "name": "index",
      "label": "Index",
      "description": "Elasticsearch indexing",
      "count": 497566,
      "total": 497566,
      "status": "active",
      "last_activity": "2025-02-10T10:30:00Z"
    }
  ]
}
```

### 3.3 Implementation Strategy

**Option 1: Direct Query (Recommended for MVP)**
- Query existing models directly with optimized SQL
- Add database indexes for aggregation queries
- Implement Redis caching (TTL: 30 seconds)
- Pros: Simple, no data duplication
- Cons: Query performance depends on data volume

**Option 2: Materialized Views**
- Create PostgreSQL materialized views for aggregations
- Refresh on schedule or trigger
- Pros: Fast reads, database-native
- Cons: Stale data between refreshes

**Option 3: Event-Driven Aggregation**
- Emit events on pipeline stage completion
- Maintain counters in Redis/PostgreSQL
- Pros: Real-time accuracy, scalable
- Cons: More complex, eventual consistency

**Recommendation:** Start with Option 1, migrate to Option 3 as scale demands.

---

## 4. Technical Implementation Details

### 4.1 Query Patterns

**Source Statistics:**
```sql
SELECT 
    sr.id,
    sr.name as description,
    sr.type as source_type,
    sr.status = 'active' as enabled,
    sr.document_count,
    sr.last_success_at as last_sync_at
FROM source_registry sr
WHERE sr.deleted_at IS NULL;
```

**Document Counts:**
```sql
SELECT 
    COUNT(*) FILTER (WHERE is_deleted = false) as active_documents,
    COUNT(*) FILTER (WHERE es_indexed = true) as indexed_documents
FROM documents;
```

**Execution Manifests (for sync jobs):**
```sql
SELECT 
    source_id,
    status,
    started_at,
    completed_at,
    stats->>'documents_processed' as documents_processed
FROM execution_manifests
ORDER BY started_at DESC
LIMIT 100;
```

### 4.2 Caching Strategy

```python
# Redis cache keys
"dashboard:stats" → TTL 30s
"dashboard:jobs:{page}" → TTL 30s  
"dashboard:pipeline" → TTL 30s
"dashboard:health" → TTL 10s
```

Cache invalidation:
- On execution manifest completion (webhook/trigger)
- On document ingestion batch completion
- Manual refresh API endpoint

### 4.3 Error Handling

```python
# Graceful degradation
if elasticsearch_unavailable:
    response["elasticsearch_available"] = False
    response["total_elastic_docs"] = None
    # Still return source stats from PostgreSQL
```

---

## 5. Integration Points

### 5.1 Frontend Integration

The dashboard expects data at these endpoints:
```
GET /api/v1/dashboard/stats    → StatsResponse
GET /api/v1/dashboard/jobs     → JobsResponse  
GET /api/v1/dashboard/pipeline → PipelineStage[]
```

### 5.2 Existing GABI API Integration

New endpoints should:
- Use existing `RequireAuth` middleware for consistency
- Follow existing error response formats
- Support the same CORS configuration
- Use existing database session management

### 5.3 Celery/Task Integration

Pipeline stage tracking requires:
- Task callbacks to update stage counters
- Execution manifest enrichment with year breakdown
- Event emission for cache invalidation

---

## 6. Security Considerations

### 6.1 Authorization
- Dashboard endpoints require authentication
- Admin role required for sensitive operations (trigger sync)
- Source-level permissions for multi-tenant scenarios

### 6.2 Rate Limiting
- Dashboard polling: 30 requests/minute per user
- Health checks: 60 requests/minute
- Export operations: 10 requests/minute

### 6.3 Data Exposure
- Exclude sensitive metadata from public endpoints
- Filter sources by user permissions
- Sanitize error messages in production

---

## 7. Future Enhancements

### 7.1 Real-Time Updates
- WebSocket support for live pipeline updates
- Server-Sent Events (SSE) for activity feed
- Push notifications for error conditions

### 7.2 Analytics
- Historical trend data
- Processing time percentiles
- Error rate tracking
- Source comparison metrics

### 7.3 Operational Features
- Manual sync triggering
- DLQ message management
- Configuration editing
- Audit log viewing

---

## 8. Implementation Plan

### Phase 1: Core Endpoints (Week 1)
1. Implement `/dashboard/stats` endpoint
2. Implement `/dashboard/health` endpoint
3. Add caching layer
4. Write unit tests

### Phase 2: Pipeline Tracking (Week 2)
1. Implement `/dashboard/pipeline` endpoint
2. Add execution manifest enrichment
3. Implement stage counter derivation
4. Add integration tests

### Phase 3: Job History (Week 3)
1. Implement `/dashboard/jobs` endpoint
2. Add year-based grouping
3. Implement pagination
4. Add filtering capabilities

### Phase 4: Frontend Integration (Week 4)
1. CORS configuration
2. API documentation (OpenAPI)
3. Frontend integration testing
4. Performance optimization

---

## 9. Conclusion

The proposed dashboard API design bridges the gap between GABI's existing data models and the planned user interface requirements. By leveraging existing database structures while adding efficient aggregation and caching, we can deliver a responsive dashboard experience without significant architectural changes.

The design prioritizes:
- **Simplicity**: Uses existing models and patterns
- **Performance**: Implements caching for frequently-accessed aggregations
- **Extensibility**: Allows future enhancements like real-time updates
- **Reliability**: Includes graceful degradation and error handling

This API will enable users to effectively monitor the document processing pipeline, track data source health, and quickly identify issues requiring attention.

---

## Appendix A: Data Model Mapping

| Frontend Concept | GABI Model | Mapping Notes |
|-----------------|------------|---------------|
| Source | SourceRegistry | Direct mapping |
| Document Count | Document | Aggregate query |
| Sync Job | ExecutionManifest | Requires enrichment |
| Pipeline Stage | ExecutionManifest + DLQ | Derived from stats |
| ES Index Size | ES Cluster API | Direct query |
| Health Status | Multiple services | Aggregated health |

## Appendix B: Query Performance Notes

Current data volumes:
- Documents: ~500K
- Sources: < 10
- Executions: < 10K
- DLQ: < 1K

Expected query times:
- Stats aggregation: < 100ms
- Jobs query (with pagination): < 50ms
- Pipeline aggregation: < 100ms
- Health check: < 200ms (parallel)

With proper indexing and caching, all dashboard endpoints should respond in < 300ms.
