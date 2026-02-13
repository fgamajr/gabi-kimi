# Dashboard API Contracts

API contracts for the GABI Dashboard frontend (React + TypeScript).

## Base URL

```
/api/v1/dashboard
```

## Endpoints

### GET /stats

Returns dashboard statistics including sources, document counts, and Elasticsearch availability.

**Response:**

```typescript
interface DashboardStatsResponse {
  sources: Source[];
  total_documents: number;
  elasticsearch_available: boolean;
}

interface Source {
  id: string;
  description: string;
  source_type: string;  // "csv_http" | "web_crawl" | "api_pagination"
  enabled: boolean;
  document_count: number;
}
```

### GET /jobs

Returns synchronization jobs and Elasticsearch index statistics.

**Response:**

```typescript
interface JobsResponse {
  sync_jobs: SyncJob[];
  elastic_indexes: Record<string, number>;
  total_elastic_docs: number;
}

interface SyncJob {
  source: string;
  year: number | string;
  status: 'synced' | 'pending' | 'failed' | 'in_progress';
  updated_at: string | null;  // ISO 8601 format
}
```

### GET /pipeline

Returns the status of the 4-stage document processing pipeline.

**Response:**

```typescript
interface PipelineStage {
  name: 'harvest' | 'sync' | 'ingest' | 'index';
  label: string;
  description: string;
  count: number;
  total: number;
  status: 'active' | 'idle' | 'error';
  lastActivity?: string;  // ISO 8601 format
}
```

### GET /health

Returns system health status for all services.

**Response:**

```typescript
interface SystemHealthResponse {
  status: 'ok' | 'degraded' | 'error';
  timestamp: string;  // ISO 8601 format
  services: Record<string, ServiceHealth>;
}

interface ServiceHealth {
  status: 'ok' | 'error' | 'unknown' | 'disabled';
  response_time_ms?: number;
  message?: string;
}
```

### POST /sources/{sourceId}/refresh

Triggers a refresh (re-discovery) for a specific source.

**Request:**

```typescript
interface RefreshSourceRequest {
  force?: boolean;  // Force refresh even if recently updated
  year?: number;    // Optional: specific year to refresh
}
```

**Response:**

```typescript
interface RefreshSourceResponse {
  success: boolean;
  job_id?: string;  // UUID of the enqueued job
  message: string;
}
```

## Status Mappings

### Job Status

| PostgreSQL Status | API Status    | UI Display   |
|-------------------|---------------|--------------|
| `pending`         | `pending`     | Pending      |
| `processing`      | `in_progress` | In Progress  |
| `completed`       | `synced`      | Synced       |
| `failed`          | `failed`      | Failed       |

### Pipeline Stage Status

| Condition                  | Status   | UI Indicator |
|----------------------------|----------|--------------|
| Jobs running               | `active` | Green pulse  |
| Jobs failed                | `error`  | Red          |
| No activity                | `idle`   | Gray         |

### Source Type Mapping

| Discovery Strategy | source_type    |
|--------------------|----------------|
| `static_url`       | `csv_http`     |
| `url_pattern`      | `csv_http`     |
| `web_crawl`        | `web_crawl`    |
| `api_pagination`   | `api_pagination` |

## Error Handling

All endpoints return standard HTTP status codes:

- `200 OK` - Success
- `404 Not Found` - Source not found
- `500 Internal Server Error` - Server error

Error responses include a message:

```json
{
  "success": false,
  "message": "Source not found: tcu_acordaos_2024"
}
```

## CORS

The API supports CORS for the following origins in development:

- `http://localhost:3000`
- `http://localhost:5173`

## Related Components

These contracts are designed to work with the following React components from the reference project:

- `MetricCard` - Displays key metrics
- `PipelineOverview` - Shows 4-stage pipeline status
- `ActivityFeed` - Lists recent sync jobs
- `SourcesTable` - Displays source configuration
- `SystemHealth` - Shows service health indicators
