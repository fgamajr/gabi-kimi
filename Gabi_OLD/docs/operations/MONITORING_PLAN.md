# GABI Pipeline Monitoring Plan

> **Status:** DRAFT  
> **Scope:** Worker + API observability, metrics, alerts, and debugging  
> **Last Updated:** 2026-02-27

---

## 1. Log Aggregation Strategy

### 1.1 Current State

| Component | Logging Framework | Output Format | Key Fields |
|-----------|------------------|---------------|------------|
| **Gabi.Api** | Serilog | JSON (production), Text (dev) | Timestamp, Level, Message, Properties |
| **Gabi.Worker** | Serilog | JSON (production), Text (dev) | Application="Gabi.Worker", Enriched context |
| **Hangfire** | Built-in | Console + PostgreSQL | Job states, execution times |
| **PostgreSQL** | Native | stderr | Slow queries, connections |
| **Elasticsearch** | Native | stdout | Cluster health, indexing rates |

### 1.2 Recommended Aggregation Architecture

```
┌──────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Gabi.Api    │────▶│  Vector/     │────▶│  Grafana Loki   │
│  (Serilog)   │     │  Fluent Bit  │     │  (Log Storage)  │
└──────────────┘     └──────────────┘     └─────────────────┘
                                              │
┌──────────────┐     ┌──────────────┐         │
│ Gabi.Worker  │────▶│  (Sidecar)   │─────────┤
│  (Serilog)   │     │              │         │
└──────────────┘     └──────────────┘         ▼
                                        ┌─────────────────┐
                                        │  Grafana/       │
                                        │  AlertManager   │
                                        └─────────────────┘
```

### 1.3 Critical Log Patterns to Track

```csharp
// Job Lifecycle (already implemented in HangfireJobQueueRepository)
Log.Information("Enqueued job {JobId} ({JobType}) to queue '{Queue}' for source {SourceId}", ...);
Log.Information("Hangfire job created successfully for {JobId}", ...);
Log.Error(ex, "Failed to enqueue Hangfire job {JobId} of type {JobType}", ...);

// DLQ Events (DlqFilter)
Log.Warning("Job {JobId} failed, will retry. Error: {Error}", ...);
Log.Error("Job {JobId} failed permanently. Error: {Error}", ...);

// Pipeline Progress (Job Executors)
Log.Information("Progress {JobId}: {Percent}% - {Message}", ...);

// Source Pipeline State Changes
Log.Information("Pipeline {SourceId}: {OldState} -> {NewState} (phase: {Phase})", ...);
```

### 1.4 Log Correlation

All logs should include these correlation IDs:

| Field | Source | Example |
|-------|--------|---------|
| `trace_id` | Activity.Current.TraceId | `0af7651916cd43dd8448eb211c80319c` |
| `job_id` | IngestJob.Id | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` |
| `source_id` | SourceRegistryEntity.Id | `dou_csv_2025` |
| `worker_id` | Hangfire ServerName | `pipeline-stages:worker-1` |

---

## 2. Key Metrics to Track

### 2.1 Queue Metrics (Critical)

```sql
-- Queue Depth by Status
SELECT 
    status,
    COUNT(*) as count,
    MIN(created_at) as oldest_job,
    MAX(created_at) as newest_job
FROM job_registry
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY status;

-- Queue Depth by Type and Status
SELECT 
    job_type,
    status,
    COUNT(*) as count
FROM job_registry
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY job_type, status
ORDER BY job_type, status;
```

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| `gabi.queue.pending.count` | Jobs waiting to be processed | > 1000 |
| `gabi.queue.running.count` | Jobs currently processing | > 10 |
| `gabi.queue.failed.count` | Failed jobs in last hour | > 10 |
| `gabi.queue.oldest_pending_minutes` | Age of oldest pending job | > 60 |

### 2.2 Processing Rate Metrics

```sql
-- Processing Rate (jobs per hour)
SELECT 
    DATE_TRUNC('hour', completed_at) as hour,
    COUNT(*) as completed_count,
    AVG(EXTRACT(EPOCH FROM (completed_at - started_at))) as avg_duration_seconds
FROM job_registry
WHERE status = 'completed'
  AND completed_at > NOW() - INTERVAL '24 hours'
GROUP BY DATE_TRUNC('hour', completed_at)
ORDER BY hour DESC;

-- Throughput by Source
SELECT 
    source_id,
    job_type,
    COUNT(*) as count,
    AVG(EXTRACT(EPOCH FROM (completed_at - started_at))) as avg_duration_seconds
FROM job_registry
WHERE status = 'completed'
  AND completed_at > NOW() - INTERVAL '24 hours'
GROUP BY source_id, job_type;
```

| Metric | Description | Target |
|--------|-------------|--------|
| `gabi.processing.jobs_per_minute` | Jobs completed per minute | > 5 |
| `gabi.processing.avg_duration_seconds` | Average job duration | < 300 |
| `gabi.processing.docs_per_minute` | Documents processed per minute | > 50 |

### 2.3 Error Rate Metrics

```sql
-- Error Rate by Category (using ErrorClassifier)
SELECT 
    COALESCE(error_details->>'category', 'unknown') as error_category,
    COUNT(*) as count
FROM dlq_entries
WHERE failed_at > NOW() - INTERVAL '24 hours'
GROUP BY COALESCE(error_details->>'category', 'unknown');

-- Error Rate by Job Type
SELECT 
    job_type,
    COUNT(*) as failed_count
FROM job_registry
WHERE status = 'failed'
  AND completed_at > NOW() - INTERVAL '24 hours'
GROUP BY job_type;

-- Retry Distribution
SELECT 
    retry_count,
    COUNT(*) as count
FROM dlq_entries
WHERE failed_at > NOW() - INTERVAL '24 hours'
GROUP BY retry_count;
```

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| `gabi.errors.rate_per_minute` | Errors per minute | > 5 |
| `gabi.errors.transient_pct` | % of transient errors | > 50% |
| `gabi.errors.permanent_pct` | % of permanent errors | > 10% |
| `gabi.dlq.size` | DLQ entries count | > 100 |

### 2.4 System Health Metrics

```sql
-- Database Connection Health
SELECT 
    count(*) as active_connections,
    state
FROM pg_stat_activity
WHERE datname = 'gabi'
GROUP BY state;

-- Table Bloat Estimation
SELECT 
    schemaname,
    relname as table_name,
    n_live_tup as live_tuples,
    n_dead_tup as dead_tuples,
    CASE WHEN n_live_tup > 0 
         THEN ROUND(100.0 * n_dead_tup / n_live_tup, 2)
         ELSE 0 
    END as dead_tuple_ratio
FROM pg_stat_user_tables
WHERE schemaname = 'public'
ORDER BY n_dead_tup DESC
LIMIT 10;
```

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| `gabi.db.connections.active` | Active DB connections | > 150 |
| `gabi.db.connections.idle` | Idle DB connections | > 50 |
| `gabi.db.dead_tuple_ratio` | Dead tuple ratio | > 20% |
| `gabi.es.cluster_health` | ES cluster status | != 'green' |

### 2.5 Pipeline Stage Metrics

```sql
-- Documents by Status
SELECT 
    status,
    COUNT(*) as count
FROM documents
GROUP BY status;

-- Links by Pipeline Phase Status
SELECT 
    source_id,
    discovery_status,
    fetch_status,
    ingest_status,
    COUNT(*) as count
FROM discovered_links
GROUP BY source_id, discovery_status, fetch_status, ingest_status;

-- Source Pipeline States
SELECT 
    state,
    active_phase,
    COUNT(*) as count
FROM source_pipeline_state
GROUP BY state, active_phase;
```

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| `gabi.pipeline.pending_docs` | Documents pending processing | > 10000 |
| `gabi.pipeline.failed_docs` | Documents in failed status | > 100 |
| `gabi.pipeline.stalled_sources` | Sources stuck in 'running' state | > 0 |

---

## 3. Database Queries for Progress Tracking

### 3.1 Real-Time Pipeline Progress

```sql
-- Overall Pipeline Progress
WITH stats AS (
    SELECT 
        COUNT(*) as total_links,
        COUNT(*) FILTER (WHERE fetch_status = 'completed') as fetched,
        COUNT(*) FILTER (WHERE ingest_status = 'completed') as ingested
    FROM discovered_links
    WHERE status != 'skipped'
)
SELECT 
    total_links,
    fetched,
    ingested,
    ROUND(100.0 * fetched / NULLIF(total_links, 0), 2) as fetch_pct,
    ROUND(100.0 * ingested / NULLIF(total_links, 0), 2) as ingest_pct
FROM stats;

-- Progress by Source
SELECT 
    source_id,
    COUNT(*) as total_links,
    COUNT(*) FILTER (WHERE discovery_status = 'completed') as discovered,
    COUNT(*) FILTER (WHERE fetch_status = 'completed') as fetched,
    COUNT(*) FILTER (WHERE ingest_status = 'completed') as ingested,
    MAX(discovered_at) as last_activity
FROM discovered_links
GROUP BY source_id
ORDER BY total_links DESC;
```

### 3.2 Job Execution Tracking

```sql
-- Recent Job Executions
SELECT 
    job_id,
    source_id,
    job_type,
    status,
    progress_percent,
    created_at,
    started_at,
    completed_at,
    EXTRACT(EPOCH FROM (completed_at - started_at)) as duration_seconds
FROM job_registry
ORDER BY created_at DESC
LIMIT 20;

-- Long-Running Jobs (> 10 minutes)
SELECT 
    job_id,
    source_id,
    job_type,
    started_at,
    progress_percent,
    progress_message,
    EXTRACT(EPOCH FROM (NOW() - started_at)) / 60 as running_minutes
FROM job_registry
WHERE status = 'processing'
  AND started_at < NOW() - INTERVAL '10 minutes'
ORDER BY started_at;
```

### 3.3 DLQ Monitoring

```sql
-- DLQ Overview
SELECT 
    status,
    COUNT(*) as count,
    MIN(failed_at) as oldest_failure,
    MAX(failed_at) as newest_failure
FROM dlq_entries
GROUP BY status;

-- DLQ by Error Category
SELECT 
    CASE 
        WHEN error_message LIKE '%timeout%' OR error_message LIKE '%connection%' THEN 'transient'
        WHEN error_message LIKE '%parse%' OR error_message LIKE '%invalid%' THEN 'permanent'
        ELSE 'unknown'
    END as error_category,
    job_type,
    COUNT(*) as count
FROM dlq_entries
WHERE status = 'pending'
GROUP BY error_category, job_type;

-- Replay Success Rate
SELECT 
    DATE_TRUNC('hour', replayed_at) as hour,
    COUNT(*) as replayed_count,
    COUNT(*) FILTER (WHERE status = 'completed') as successful_count
FROM dlq_entries
WHERE replayed_at IS NOT NULL
GROUP BY DATE_TRUNC('hour', replayed_at)
ORDER BY hour DESC;
```

### 3.4 Run History (Seed, Discovery, Fetch)

```sql
-- Last Seed Run
SELECT 
    id,
    job_id,
    status,
    sources_seeded,
    sources_failed,
    completed_at,
    error_summary
FROM seed_runs
ORDER BY completed_at DESC
LIMIT 1;

-- Discovery Runs Summary
SELECT 
    source_id,
    COUNT(*) as run_count,
    MAX(completed_at) as last_run,
    AVG(links_total) as avg_links,
    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failures
FROM discovery_runs
GROUP BY source_id
ORDER BY last_run DESC;

-- Fetch Runs with Failure Rates
SELECT 
    source_id,
    COUNT(*) as run_count,
    SUM(items_total) as total_items,
    SUM(items_completed) as completed_items,
    SUM(items_failed) as failed_items,
    CASE WHEN SUM(items_total) > 0 
         THEN ROUND(100.0 * SUM(items_failed) / SUM(items_total), 2)
         ELSE 0 
    END as failure_rate_pct
FROM fetch_runs
GROUP BY source_id;
```

---

## 4. Alert Conditions

### 4.1 Critical Alerts (P1 - Page Immediately)

| Alert | Condition | Query |
|-------|-----------|-------|
| **Pipeline Stalled** | No jobs completed in 30 minutes | `SELECT COUNT(*) FROM job_registry WHERE status = 'completed' AND completed_at > NOW() - INTERVAL '30 minutes'` |
| **High Error Rate** | > 10% job failure rate in 15 min | Calculate from `job_registry` grouped by 15-min window |
| **Database Unhealthy** | Connection pool exhausted | `SELECT COUNT(*) FROM pg_stat_activity WHERE datname = 'gabi' AND state = 'active'` > 180 |
| **ES Cluster Down** | ES health != green for > 5 min | HTTP check to `/_cluster/health` |
| **DLQ Overflow** | > 1000 pending DLQ entries | `SELECT COUNT(*) FROM dlq_entries WHERE status = 'pending'` |

### 4.2 Warning Alerts (P2 - Notify Team)

| Alert | Condition | Query |
|-------|-----------|-------|
| **Queue Growing** | Pending jobs increased 50% in 1 hour | Compare current vs 1-hour ago pending count |
| **Slow Processing** | Average job duration > 10 minutes | `SELECT AVG(EXTRACT(EPOCH FROM (completed_at - started_at))) FROM job_registry WHERE completed_at > NOW() - INTERVAL '1 hour'` |
| **Stalled Jobs** | Jobs in 'processing' > 30 minutes | `SELECT COUNT(*) FROM job_registry WHERE status = 'processing' AND started_at < NOW() - INTERVAL '30 minutes'` |
| **Source Stuck** | Source in 'running' state > 2 hours | `SELECT COUNT(*) FROM source_pipeline_state WHERE state = 'running' AND last_resumed_at < NOW() - INTERVAL '2 hours'` |
| **High DLQ Rate** | > 10 DLQ entries in 1 hour | `SELECT COUNT(*) FROM dlq_entries WHERE failed_at > NOW() - INTERVAL '1 hour'` |

### 4.3 Info Alerts (P3 - Log for Review)

| Alert | Condition |
|-------|-----------|
| **Job Retried** | Any job reaches retry attempt 2 |
| **Source Paused** | Source manually paused |
| **Seed Completed** | Seed run finished |
| **Reindex Started** | Reindex job enqueued |

### 4.4 Alert Routing

```yaml
# Example Alertmanager routing
groups:
  - name: gabi-pipeline
    rules:
      - alert: PipelineStalled
        expr: gabi_queue_completed_last_30m == 0
        for: 5m
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "GABI pipeline appears stalled"
          
route:
  group_by: ['alertname', 'severity']
  receiver: 'default'
  routes:
    - match:
        severity: critical
      receiver: 'pagerduty-platform'
      continue: true
    - match:
        severity: warning
      receiver: 'slack-platform'
```

---

## 5. Debugging Commands

### 5.1 Job Debugging

```bash
# Check current job queue status
psql -h localhost -p 5433 -U gabi -d gabi -c "
SELECT status, COUNT(*) 
FROM job_registry 
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY status;"

# Find stuck jobs
psql -h localhost -p 5433 -U gabi -d gabi -c "
SELECT job_id, source_id, job_type, started_at, progress_percent, progress_message
FROM job_registry
WHERE status = 'processing'
  AND started_at < NOW() - INTERVAL '30 minutes'
ORDER BY started_at;"

# View recent failures
psql -h localhost -p 5433 -U gabi -d gabi -c "
SELECT job_id, source_id, job_type, error_message, completed_at
FROM job_registry
WHERE status = 'failed'
ORDER BY completed_at DESC
LIMIT 10;"

# Check Hangfire job queue
psql -h localhost -p 5433 -U gabi -d gabi -c "
SELECT queue, COUNT(*) 
FROM hangfire.jobqueue 
GROUP BY queue;"
```

### 5.2 Source Pipeline Debugging

```bash
# Check source pipeline states
psql -h localhost -p 5433 -U gabi -d gabi -c "
SELECT source_id, state, active_phase, paused_at, last_resumed_at
FROM source_pipeline_state
ORDER BY updated_at DESC;"

# Check links stuck in fetch
psql -h localhost -p 5433 -U gabi -d gabi -c "
SELECT source_id, COUNT(*) as stuck_count
FROM discovered_links
WHERE fetch_status = 'processing'
GROUP BY source_id
HAVING COUNT(*) > 10;"

# Force pause a source (emergency)
curl -X POST http://localhost:5100/api/v1/dashboard/sources/{sourceId}/pause \
  -H "Authorization: Bearer $TOKEN"
```

### 5.3 DLQ Debugging

```bash
# List pending DLQ entries
psql -h localhost -p 5433 -U gabi -d gabi -c "
SELECT id, job_type, source_id, error_type, failed_at, retry_count
FROM dlq_entries
WHERE status = 'pending'
ORDER BY failed_at
LIMIT 20;"

# Get full error details for a DLQ entry
psql -h localhost -p 5433 -U gabi -d gabi -c "
SELECT error_message, stack_trace
FROM dlq_entries
WHERE id = 'ENTRY_UUID_HERE';"

# Replay a DLQ entry via API
curl -X POST http://localhost:5100/api/v1/dlq/{id}/replay \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"notes": "Manual replay after fix"}'
```

### 5.4 Performance Debugging

```bash
# Check slow queries
psql -h localhost -p 5433 -U gabi -d gabi -c "
SELECT query, calls, mean_time, max_time
FROM pg_stat_statements
WHERE query LIKE '%discovered_links%' OR query LIKE '%job_registry%'
ORDER BY mean_time DESC
LIMIT 10;"

# Check table sizes
psql -h localhost -p 5433 -U gabi -d gabi -c "
SELECT 
    relname as table_name,
    pg_size_pretty(pg_total_relation_size(relid)) as total_size,
    n_live_tup as live_rows
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC
LIMIT 10;"

# Check index usage
psql -h localhost -p 5433 -U gabi -d gabi -c "
SELECT 
    schemaname,
    tablename,
    indexrelname,
    idx_scan,
    idx_tup_read
FROM pg_stat_user_indexes
WHERE idx_scan = 0
  AND indexrelname NOT LIKE '%pkey%'
ORDER BY pg_relation_size(indexrelid) DESC
LIMIT 10;"
```

### 5.5 Elasticsearch Debugging

```bash
# Check cluster health
curl http://localhost:9200/_cluster/health?pretty

# Check index stats
curl http://localhost:9200/_stats/indexing,search?pretty

# Check for unassigned shards
curl http://localhost:9200/_cluster/health?pretty | grep unassigned

# Search for specific document
curl http://localhost:9200/gabi-docs/_search?q=source_id:dou_csv_2025&size=5&pretty
```

### 5.6 Hangfire Dashboard

```bash
# Access Hangfire dashboard
open http://localhost:5100/hangfire

# Check Hangfire servers via API
curl http://localhost:5100/hangfire/stats
```

---

## 6. Observability Implementation Checklist

### Phase 1: Metrics (Immediate)

- [ ] Deploy Prometheus/Grafana stack
- [ ] Instrument `PipelineTelemetry` counters (already exists in code)
- [ ] Create dashboard with key metrics
- [ ] Set up basic alerts (queue depth, error rate)

### Phase 2: Logging (Week 2)

- [ ] Deploy Loki or similar log aggregation
- [ ] Configure structured logging for all components
- [ ] Add trace correlation IDs
- [ ] Create log-based alerts

### Phase 3: Tracing (Week 3-4)

- [ ] Configure OpenTelemetry OTLP export
- [ ] Instrument pipeline stages with spans
- [ ] Add span attributes for source_id, job_type
- [ ] Create trace-based dashboards

### Phase 4: Alerting (Week 4)

- [ ] Configure AlertManager
- [ ] Set up PagerDuty/Slack integration
- [ ] Test alert flows
- [ ] Document runbooks for each alert

---

## 7. Runbook Templates

### Runbook: Pipeline Stalled

**Symptoms:** No jobs completing for > 30 minutes

**Investigation:**
1. Check job queue status: `SELECT status, COUNT(*) FROM job_registry GROUP BY status;`
2. Check Hangfire servers: Look for missing servers in dashboard
3. Check worker logs: Look for errors in `docker logs gabi-worker`
4. Check for deadlocks: `SELECT * FROM pg_locks WHERE NOT granted;`

**Resolution:**
- If workers crashed: Restart worker containers
- If jobs stuck in 'processing': Run queue hygiene script
- If database issue: Check connection pool

### Runbook: High DLQ Rate

**Symptoms:** > 10 DLQ entries per hour

**Investigation:**
1. Categorize errors: Check DLQ entries by error type
2. Check for transient errors: Network, timeouts
3. Check for permanent errors: Parse failures, validation errors

**Resolution:**
- For transient: May auto-recover with retry
- For permanent: Fix source config or data issue
- For rate limits: Reduce concurrency

---

## 8. API Endpoints for Monitoring

| Endpoint | Description | Auth |
|----------|-------------|------|
| `GET /health` | Liveness probe | Public |
| `GET /health/ready` | Readiness probe | Public |
| `GET /api/v1/dashboard/stats` | Dashboard statistics | Viewer |
| `GET /api/v1/dashboard/pipeline` | Pipeline stage status | Viewer |
| `GET /api/v1/dlq/stats` | DLQ statistics | Viewer |
| `GET /api/v1/dlq` | DLQ entries list | Viewer |
| `GET /api/v1/dashboard/sources/{id}/metrics` | Source metrics | Viewer |

---

## References

- [CHAOS_PLAYBOOK.md](../reliability/CHAOS_PLAYBOOK.md) - Reliability experiments
- [queue-hygiene.md](./queue-hygiene.md) - Queue cleanup procedures
- [retry-policy.md](./retry-policy.md) - Retry configuration
- [INVARIANTS.md](../architecture/INVARIANTS.md) - System invariants
