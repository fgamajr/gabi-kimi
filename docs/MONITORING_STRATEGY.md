# GABI Production Monitoring Strategy

## Overview

This document outlines the comprehensive monitoring and observability strategy for GABI (Gerador Automático de Boletins por IA) deployed on Fly.io.

**Last Updated:** 2026-02-11  
**Version:** 1.0.0  
**Environment:** Production (Fly.io)

---

## 1. Monitoring Stack Architecture

### 1.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Fly.io Infrastructure                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │  GABI API   │  │   Worker    │  │  Scheduler  │  │   TEI (Embeddings)  │ │
│  │  (FastAPI)  │  │  (Celery)   │  │   (Beat)    │  │    (TEI Service)    │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘ │
│         │                │                │                    │           │
│         └────────────────┴────────────────┴────────────────────┘           │
│                              │                                             │
│                    ┌─────────┴─────────┐                                   │
│                    │   Fly Metrics     │                                   │
│                    │  (Prometheus API) │                                   │
│                    └─────────┬─────────┘                                   │
└──────────────────────────────┼─────────────────────────────────────────────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
           ┌────────▼─────────┐  ┌────────▼─────────┐
           │  Grafana Cloud   │  │   UptimeRobot    │
           │   (Dashboards)   │  │  (External Ping) │
           └────────┬─────────┘  └──────────────────┘
                    │
           ┌────────▼─────────┐
           │  Alertmanager    │
           │ (Grafana Cloud)  │
           └────────┬─────────┘
                    │
           ┌────────▼─────────┐
           │  PagerDuty/Slack │
           │  (Notifications) │
           └──────────────────┘
```

### 1.2 Component Breakdown

| Component | Technology | Purpose | Cost |
|-----------|-----------|---------|------|
| Metrics Collection | Fly Metrics + Prometheus | Infrastructure and app metrics | Included in Fly |
| Metrics Storage | Grafana Cloud (10k series free) | Long-term storage and querying | Free tier |
| Dashboards | Grafana Cloud | Visualization and alerting | Free tier |
| Log Aggregation | Fly Logs + Grafana Loki | Centralized log storage | Free tier |
| External Monitoring | UptimeRobot | External health checks | Free tier |
| Alerting | Grafana Alerting + PagerDuty | Alert routing and escalation | Free tier |
| Tracing | Grafana Tempo (optional) | Distributed tracing | Free tier |

### 1.3 Fly.io Native Integrations

```yaml
# fly.toml monitoring configuration
[metrics]
  port = 8000
  path = "/metrics"

[[http_service.checks]]
  interval = '30s'
  timeout = '5s'
  grace_period = '10s'
  method = 'GET'
  path = '/health'
```

### 1.4 Multi-Region Monitoring

```yaml
# Primary: gru (São Paulo)
# Failover: (if applicable)

# Regional health checks per machine
fly checks list --app gabi-api

# Machine-level metrics
fly status --app gabi-api
```

---

## 2. Prometheus Metrics Exposure

### 2.1 Application Metrics (Already Implemented)

The following metrics are already exposed by GABI at `/metrics`:

#### HTTP Metrics
```prometheus
# Request count by method, endpoint, status
gabi_http_requests_total{method="GET",endpoint="/api/v1/search",status="200"}

# Request duration histogram
gabi_http_request_duration_seconds_bucket{method="POST",endpoint="/api/v1/search",le="0.1"}

# Active connections
gabi_active_connections

# Rate limit hits
gabi_rate_limit_hits_total{client_id="api_client_1"}
```

#### Database Metrics
```prometheus
# PostgreSQL connections
gabi_db_connections{state="active"}
gabi_db_connections{state="idle"}
gabi_db_query_duration_seconds_bucket{operation="select",le="0.01"}
gabi_db_query_errors_total{operation="insert",error_type="ConnectionError"}
```

#### Elasticsearch Metrics
```prometheus
gabi_elasticsearch_requests_total{operation="search",status="success"}
gabi_elasticsearch_request_duration_seconds_bucket{operation="index",le="0.1"}
gabi_elasticsearch_index_size_bytes{index_name="gabi_documents_v1"}
gabi_elasticsearch_documents_total{index_name="gabi_documents_v1"}
```

#### Redis Metrics
```prometheus
gabi_redis_connections
gabi_redis_operations_total{operation="get"}
gabi_redis_operation_duration_seconds_bucket{operation="set",le="0.001"}
```

#### Pipeline Metrics
```prometheus
gabi_pipeline_documents_total{source_id="tcu_acordaos",status="success"}
gabi_pipeline_documents_total{source_id="tcu_acordaos",status="failed"}
gabi_pipeline_chunks_total{source_id="tcu_acordaos"}
gabi_pipeline_embeddings_total{source_id="tcu_acordaos",status="success"}
gabi_pipeline_duration_seconds_bucket{source_id="tcu_acordaos",phase="total",le="300"}
gabi_pipeline_queue_size{source_id="tcu_acordaos"}
gabi_pipeline_memory_bytes{source_id="tcu_acordaos"}
```

#### Search Metrics
```prometheus
gabi_search_requests_total{search_type="hybrid"}
gabi_search_duration_seconds_bucket{search_type="hybrid",le="0.1"}
gabi_search_results_count_bucket{search_type="hybrid",le="10"}
gabi_search_errors_total{search_type="hybrid",error_type="timeout"}
```

#### Embedding Metrics
```prometheus
gabi_embedding_requests_total{status="success"}
gabi_embedding_duration_seconds_bucket{batch_size="32",le="0.1"}
gabi_embedding_batch_size_bucket{le="32"}
gabi_embedding_dimensions 384
```

#### DLQ Metrics
```prometheus
gabi_dlq_messages_total{source_id="tcu_acordaos",action="created"}
gabi_dlq_messages_total{source_id="tcu_acordaos",action="retried"}
gabi_dlq_messages_total{source_id="tcu_acordaos",action="resolved"}
gabi_dlq_queue_size{source_id="tcu_acordaos"}
```

#### Business Metrics
```prometheus
gabi_documents_total{source_id="tcu_acordaos",status="active"}
gabi_sources_total{status="active"}
gabi_sync_last_success_timestamp{source_id="tcu_acordaos"}
gabi_sync_duration_seconds_bucket{source_id="tcu_acordaos",le="600"}
```

#### MCP Metrics
```prometheus
gabi_mcp_connections_total
gabi_mcp_tool_calls_total{tool_name="search_documents"}
gabi_mcp_tool_duration_seconds_bucket{tool_name="search_documents",le="0.1"}
gabi_mcp_session_duration_seconds_bucket{le="300"}
gabi_mcp_errors_total{error_type="timeout"}
```

### 2.2 Fly.io Infrastructure Metrics

Fly automatically exposes infrastructure metrics:

```prometheus
# Machine metrics (from Fly Metrics API)
fly_instance_cpu{app="gabi-api"}
fly_instance_memory{app="gabi-api"}
fly_instance_net_receive_bytes{app="gabi-api"}
fly_instance_net_transmit_bytes{app="gabi-api"}

# HTTP metrics
fly_edge_http_responses_count{app="gabi-api",status="200"}
fly_edge_http_response_time_seconds{app="gabi-api"}

# Volume metrics (if using volumes)
fly_volume_used_bytes{app="gabi-api"}
fly_volume_size_bytes{app="gabi-api"}
```

### 2.3 Celery Worker Metrics

```prometheus
# Celery metrics (via flower or custom exporter)
celery_worker_up{worker="celery@worker-1"}
celery_tasks_total{task="gabi.tasks.sync.sync_source_task",state="success"}
celery_tasks_total{task="gabi.tasks.sync.sync_source_task",state="failure"}
celery_tasks_duration_seconds_bucket{task="gabi.tasks.sync.sync_source_task",le="300"}
celery_queue_length{queue="gabi.sync"}
celery_worker_tasks_active{worker="celery@worker-1"}
```

---

## 3. Log Aggregation Configuration

### 3.1 Fly.io Log Shipper Setup

Create a log shipper app to forward logs to Grafana Loki:

```bash
# Create log shipper app
fly apps create gabi-logs --machines-only

# Deploy vector-based log shipper
fly deploy --config fly.logs.toml
```

### 3.2 Log Shipper Configuration (fly.logs.toml)

```toml
app = 'gabi-logs'
primary_region = 'gru'

[build]
  image = 'timberio/vector:0.35.0-debian'

[env]
  GRAFANA_CLOUD_URL = 'https://logs-prod-012.grafana.net'
  # GRAFANA_API_KEY set via fly secrets

[[services]]
  internal_port = 8686
  protocol = "tcp"
  auto_stop_machines = false
  auto_start_machines = false

[metrics]
  port = 8686
  path = "/metrics"
```

### 3.3 Vector Configuration (vector.toml)

```toml
# Source: Fly.io NATS logs
[sources.fly_logs]
type = "nats"
url = "nats://[fdaa::3]:4223"
queue = "gabi-logs"
subject = "logs.>"
auth.strategy = "user_token"
auth.token = "${FLY_API_TOKEN}"

# Transform: Parse JSON logs
[transforms.parse_logs]
type = "remap"
inputs = ["fly_logs"]
source = '''
  # Parse JSON message
  parsed, err = parse_json(.message)
  if err != null {
    parsed = {}
  }
  
  # Extract fields
  .level = parsed.level ?? "info"
  .service = parsed.service ?? "gabi"
  .environment = parsed.environment ?? "production"
  .request_id = parsed.request_id
  .source_id = parsed.source_id
  .document_id = parsed.document_id
  .user_id = parsed.user_id
  .duration_ms = parsed.duration_ms
  .error_code = parsed.error?.code
  
  # Add Fly-specific labels
  .app = .fly.app.name
  .region = .fly.region
  .instance = .fly.alloc.id
'''

# Sink: Grafana Loki
[sinks.grafana_loki]
type = "loki"
inputs = ["parse_logs"]
endpoint = "${GRAFANA_CLOUD_URL}"
auth.strategy = "basic"
auth.user = "${GRAFANA_LOKI_USER}"
auth.password = "${GRAFANA_API_KEY}"

labels.job = "gabi"
labels.app = "{{ app }}"
labels.region = "{{ region }}"
labels.instance = "{{ instance }}"
labels.level = "{{ level }}"
labels.service = "{{ service }}"
labels.environment = "{{ environment }}"

encoding.codec = "json"
encoding.timestamp_format = "rfc3339"
healthcheck.enabled = true

# Sink: Console (for debugging)
[sinks.console]
type = "console"
inputs = ["parse_logs"]
encoding.codec = "json"
```

### 3.4 Application Log Configuration

Ensure GABI logs in structured JSON format (already configured in `logging_config.py`):

```yaml
# In fly.toml
[env]
  LOG_LEVEL = "INFO"
  LOG_FORMAT = "json"
```

Example log output:
```json
{
  "timestamp": "2026-02-11T12:34:56.789Z",
  "level": "INFO",
  "message": "Search completed",
  "logger": "gabi.services.search",
  "request_id": "req-abc123",
  "source_id": "tcu_acordaos",
  "duration_ms": 45.2,
  "results_count": 10,
  "search_type": "hybrid"
}
```

---

## 4. Alerting Rules

### 4.1 Grafana Alert Rules

#### Critical Alerts (PagerDuty)

```yaml
# alert-rules-critical.yaml
apiVersion: 1
groups:
  - name: gabi-critical
    interval: 30s
    rules:
      # API Down
      - alert: GABIAPIDown
        expr: |
          up{job="gabi-api"} == 0
        for: 2m
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "GABI API is down"
          description: "GABI API has been down for more than 2 minutes"
          runbook_url: "https://wiki.tcu.gov.br/runbooks/api-down"

      # Database Connection Failure
      - alert: GABIDatabaseDown
        expr: |
          gabi_db_connections{state="active"} == 0
        for: 1m
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "GABI cannot connect to PostgreSQL"
          description: "No active database connections for 1 minute"

      # High Error Rate
      - alert: GABIHighErrorRate
        expr: |
          (
            sum(rate(gabi_http_requests_total{status=~"5.."}[5m]))
            /
            sum(rate(gabi_http_requests_total[5m]))
          ) > 0.1
        for: 5m
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "High error rate on GABI API"
          description: "Error rate is above 10% for 5 minutes"

      # Pipeline Stalled
      - alert: GABIPipelineStalled
        expr: |
          time() - gabi_sync_last_success_timestamp{source_id=~"tcu_.*"} > 86400
        for: 5m
        labels:
          severity: critical
          team: data
        annotations:
          summary: "Pipeline stalled for {{ $labels.source_id }}"
          description: "No successful sync in the last 24 hours"
```

#### Warning Alerts (Slack)

```yaml
# alert-rules-warning.yaml
groups:
  - name: gabi-warning
    interval: 1m
    rules:
      # High Response Time
      - alert: GABIHighResponseTime
        expr: |
          histogram_quantile(0.95, 
            sum(rate(gabi_http_request_duration_seconds_bucket[5m])) by (le)
          ) > 2
        for: 5m
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "High response time on GABI API"
          description: "95th percentile response time is above 2 seconds"

      # Memory Usage
      - alert: GABIHighMemoryUsage
        expr: |
          fly_instance_memory{app="gabi-api"} / 
          fly_instance_memory_limit{app="gabi-api"} > 0.85
        for: 5m
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "High memory usage on GABI API"
          description: "Memory usage is above 85%"

      # DLQ Growing
      - alert: GABIDLQGrowing
        expr: |
          sum(gabi_dlq_queue_size) > 100
        for: 10m
        labels:
          severity: warning
          team: data
        annotations:
          summary: "DLQ has many pending messages"
          description: "DLQ has {{ $value }} pending messages"

      # Elasticsearch Degraded
      - alert: GABIESDegraded
        expr: |
          gabi_elasticsearch_request_duration_seconds_bucket{le="1.0",operation="search"} < 0.95
        for: 10m
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "Elasticsearch search performance degraded"
          description: "Less than 95% of searches complete within 1 second"

      # Celery Worker Down
      - alert: GABIWorkerDown
        expr: |
          celery_worker_up == 0
        for: 5m
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "Celery worker is down"
          description: "Worker {{ $labels.worker }} has been down for 5 minutes"

      # Search Failure Rate
      - alert: GABISearchFailures
        expr: |
          (
            sum(rate(gabi_search_errors_total[10m]))
            /
            sum(rate(gabi_search_requests_total[10m]))
          ) > 0.05
        for: 5m
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "Search failure rate is high"
          description: "Search error rate is above 5%"
```

#### Info Alerts (Slack - Low Priority)

```yaml
# alert-rules-info.yaml
groups:
  - name: gabi-info
    interval: 5m
    rules:
      # Successful Deployment
      - alert: GABIDeploymentSuccess
        expr: |
          changes(up{job="gabi-api"}[10m]) > 0
        labels:
          severity: info
          team: platform
        annotations:
          summary: "GABI API deployment detected"

      # Pipeline Completed
      - alert: GABIPipelineCompleted
        expr: |
          increase(gabi_pipeline_documents_total{status="success"}[1h]) > 0
        labels:
          severity: info
          team: data
        annotations:
          summary: "Pipeline completed for {{ $labels.source_id }}"
```

### 4.2 PagerDuty Integration

```yaml
# grafana-contact-points.yaml
apiVersion: 1
contactPoints:
  - name: pagerduty-critical
    receivers:
      - uid: pagerduty-gabi
        type: pagerduty
        settings:
          integrationKey: "${PAGERDUTY_INTEGRATION_KEY}"
          severity: critical
          class: error
          component: gabi-api
          group: platform
          summary: "{{ .CommonAnnotations.summary }}"

  - name: slack-alerts
    receivers:
      - uid: slack-gabi-alerts
        type: slack
        settings:
          url: "${SLACK_WEBHOOK_URL}"
          title: "{{ .CommonAnnotations.summary }}"
          text: "{{ .CommonAnnotations.description }}"
          color: |
            {{ if eq .CommonLabels.severity "critical" }}danger{{ end }}
            {{ if eq .CommonLabels.severity "warning" }}warning{{ end }}
            {{ if eq .CommonLabels.severity "info" }}good{{ end }}

  - name: oncall-sms
    receivers:
      - uid: sms-oncall
        type: webhook
        settings:
          url: "https://api.twilio.com/..."
          httpMethod: POST
```

### 4.3 Notification Routing

```yaml
# grafana-notification-policies.yaml
apiVersion: 1
policies:
  - receiver: default
    group_by: ['alertname', 'severity', 'team']
    group_wait: 30s
    group_interval: 5m
    repeat_interval: 4h
    routes:
      # Critical alerts -> PagerDuty + SMS
      - receiver: pagerduty-critical
        matchers:
          - severity = critical
        continue: true
        routes:
          - receiver: oncall-sms
            matchers:
              - severity = critical
            mute_time_intervals:
              - business_hours

      # Warning alerts -> Slack
      - receiver: slack-alerts
        matchers:
          - severity = warning

      # Info alerts -> Slack (business hours only)
      - receiver: slack-alerts
        matchers:
          - severity = info
        active_time_intervals:
          - business_hours

      # Team-specific routing
      - receiver: slack-data-team
        matchers:
          - team = data
```

---

## 5. Grafana Dashboards

### 5.1 Main Dashboard (JSON)

See: [grafana-dashboard-main.json](./grafana-dashboard-main.json)

### 5.2 Dashboard Panels Overview

| Panel | Query | Thresholds |
|-------|-------|------------|
| API Availability | `up{job="gabi-api"}` | Critical: < 1 |
| Request Rate | `sum(rate(gabi_http_requests_total[5m]))` | Warning: > 1000/s |
| Error Rate | `sum(rate(gabi_http_requests_total{status=~"5.."}[5m])) / sum(rate(gabi_http_requests_total[5m]))` | Warning: > 5%, Critical: > 10% |
| P95 Latency | `histogram_quantile(0.95, sum(rate(gabi_http_request_duration_seconds_bucket[5m])) by (le))` | Warning: > 500ms, Critical: > 2s |
| DB Connections | `gabi_db_connections{state="active"}` | Warning: > 80% of max |
| ES Cluster Status | `elasticsearch_cluster_health_status{color="green"}` | Critical: != 1 |
| Pipeline Documents | `sum(rate(gabi_pipeline_documents_total[1h])) by (status)` | Warning: failed > 5% |
| DLQ Size | `sum(gabi_dlq_queue_size)` | Warning: > 50, Critical: > 100 |
| Search Performance | `histogram_quantile(0.95, sum(rate(gabi_search_duration_seconds_bucket[5m])) by (le))` | Warning: > 200ms |

---

## 6. SLA Monitoring

### 6.1 SLIs and SLOs

| SLI | SLO | Measurement |
|-----|-----|-------------|
| API Availability | 99.9% | `avg_over_time(up[30d])` |
| API Latency (p95) | < 500ms | `histogram_quantile(0.95, rate(gabi_http_request_duration_seconds_bucket[30d]))` |
| Error Rate | < 1% | `rate(gabi_http_requests_total{status=~"5.."}[30d]) / rate(gabi_http_requests_total[30d])` |
| Pipeline Success | 95% | `rate(gabi_pipeline_documents_total{status="success"}[1d]) / rate(gabi_pipeline_documents_total[1d])` |
| Search Success | 99% | `rate(gabi_search_requests_total[1d]) - rate(gabi_search_errors_total[1d]) / rate(gabi_search_requests_total[1d])` |

### 6.2 Error Budget Calculation

```promql
# Monthly error budget (0.1% downtime = ~43 minutes)
1 - avg_over_time(up{job="gabi-api"}[30d])

# Remaining error budget this month
0.001 - (1 - avg_over_time(up{job="gabi-api"}[30d]))
```

---

## 7. Cost Monitoring

### 7.1 Fly.io Cost Estimation

```yaml
# Monthly estimated costs (as of 2026-02)
infra:
  gabi-api:
    machines: 2 × shared-cpu-2x @ $2.74/mo = $5.48
    memory: 2GB × 2 = included
  
  gabi-worker:
    machines: 2 × shared-cpu-4x @ $5.48/mo = $10.96
    memory: 4GB × 2 = included
  
  gabi-scheduler:
    machine: 1 × shared-cpu-1x @ $1.37/mo
  
  database:  # Fly Postgres
    cluster: 2 × shared-cpu-1x @ $1.37/mo = $2.74
    storage: 50GB @ $0.15/GB = $7.50
  
  redis:  # Fly Redis/Upstash
    instance: $10/mo (estimated)
  
  elasticsearch:  # Bonsai or similar
    cluster: $29/mo (estimated)
  
  bandwidth:
    estimated: 100GB @ $0.02/GB = $2
  
  total_monthly: ~$70
```

### 7.2 Cost Alerts

```yaml
# Cost monitoring alerts
- alert: FlyHighBandwidth
  expr: fly_instance_net_transmit_bytes > 100e9  # 100GB
  for: 1d
  labels:
    severity: warning
  annotations:
    summary: "High bandwidth usage detected"
```

---

## 8. Runbooks

### 8.1 API Down (Critical)

**Symptoms:**
- `GABIAPIDown` alert firing
- Health endpoint returns non-200
- Users reporting service unavailable

**Investigation:**
```bash
# Check Fly status
fly status --app gabi-api

# Check logs
fly logs --app gabi-api --recent

# Check if database is accessible
fly ssh console --app gabi-api
# Inside container:
curl http://localhost:8000/health
```

**Resolution:**
1. Check if it's a deployment issue: `fly releases list --app gabi-api`
2. Rollback if needed: `fly deploy --app gabi-api --image <previous-image>`
3. Check database connectivity from the app
4. Restart machines: `fly machine restart --app gabi-api`

**Escalation:**
- If issue persists > 30 min, escalate to platform team lead
- If database is down, escalate to DBA on-call

---

### 8.2 Database Connection Issues (Critical)

**Symptoms:**
- `GABIDatabaseDown` alert firing
- API returning 500 errors
- Logs show connection timeouts

**Investigation:**
```bash
# Check database status
fly status --app gabi-db

# Check connection pool
fly ssh console --app gabi-api
# Inside container:
python -c "import asyncio; from gabi.db import init_db; asyncio.run(init_db())"
```

**Resolution:**
1. Check database machine health: `fly machine list --app gabi-db`
2. Restart database if needed: `fly machine restart --app gabi-db <machine-id>`
3. Verify connection string in secrets: `fly secrets list --app gabi-api`
4. Check if max connections reached in PostgreSQL

---

### 8.3 High Error Rate (Critical)

**Symptoms:**
- `GABIHighErrorRate` alert firing
- Error rate > 10%
- Multiple 5xx responses

**Investigation:**
```bash
# Check recent errors in logs
fly logs --app gabi-api --recent | grep ERROR

# Check specific error patterns
fly logs --app gabi-api --recent | grep -E "(500|502|503|504)"

# Query Grafana for error breakdown by endpoint
```

**Common Causes:**
1. **Elasticsearch unavailable**: Check ES cluster health
2. **Rate limiting**: Check if external APIs are rate-limiting requests
3. **Memory issues**: Check if OOM kills are happening
4. **Deployment bug**: Check recent commits/deployments

**Resolution:**
1. Identify the specific endpoint causing errors
2. Check upstream dependencies (ES, TEI, external APIs)
3. Scale up if resource-constrained
4. Rollback if deployment-related

---

### 8.4 Pipeline Stalled (Warning)

**Symptoms:**
- `GABIPipelineStalled` alert firing
- No new documents in 24+ hours
- Last sync timestamp old

**Investigation:**
```bash
# Check Celery worker status
fly status --app gabi-worker

# Check Celery queue depth
fly ssh console --app gabi-worker
celery -A gabi.worker inspect active
celery -A gabi.worker inspect scheduled
celery -A gabi.worker inspect reserved

# Check for failed tasks
fly logs --app gabi-worker --recent | grep -i "failed\|error"
```

**Resolution:**
1. Check if workers are running: `fly machine list --app gabi-worker`
2. Restart workers if stuck: `fly machine restart --app gabi-worker`
3. Check DLQ for failed messages
4. Manually trigger sync for affected source
5. Check if source website is accessible

---

### 8.5 DLQ Growing (Warning)

**Symptoms:**
- `GABIDLQGrowing` alert firing
- DLQ size > 100 messages
- Multiple document processing failures

**Investigation:**
```bash
# Check DLQ messages
curl -H "Authorization: Bearer $TOKEN" \
  https://gabi-api.tcu.gov.br/api/v1/admin/dlq

# Check logs for patterns
fly logs --app gabi-worker | grep "DLQ"
```

**Resolution:**
1. Identify error patterns in DLQ messages
2. Fix root cause (e.g., parser bug, schema change)
3. Retry DLQ messages via admin API
4. Purge if messages are invalid/unrecoverable

---

### 8.6 High Response Time (Warning)

**Symptoms:**
- `GABIHighResponseTime` alert firing
- p95 latency > 2 seconds
- User complaints about slowness

**Investigation:**
```bash
# Check resource utilization
fly status --app gabi-api

# Profile slow endpoints
# In Grafana: identify which endpoint has high latency

# Check database query performance
# In logs: identify slow queries
```

**Resolution:**
1. Scale up machines if CPU/memory constrained
2. Optimize slow database queries
3. Check Elasticsearch performance
4. Enable caching for frequent queries
5. Consider CDN for static assets

---

### 8.7 Elasticsearch Degraded (Warning)

**Symptoms:**
- `GABIESDegraded` alert firing
- Search results slow or incomplete
- ES cluster status yellow/red

**Investigation:**
```bash
# Check ES cluster health
curl $ES_URL/_cluster/health

# Check index status
curl $ES_URL/_cat/indices?v

# Check node status
curl $ES_URL/_cat/nodes?v
```

**Resolution:**
1. Check if ES cluster has enough resources
2. Review shard allocation if status is yellow/red
3. Restart ES nodes if needed
4. Scale up ES cluster if capacity issue

---

### 8.8 Memory Issues (Warning)

**Symptoms:**
- `GABIHighMemoryUsage` alert firing
- OOM kills in logs
- Machines restarting unexpectedly

**Investigation:**
```bash
# Check memory metrics in Fly dashboard
fly machine status --app gabi-api <machine-id>

# Check for memory leaks
fly logs --app gabi-api | grep -i "memory\|oom\|killed"
```

**Resolution:**
1. Increase memory allocation in fly.toml
2. Restart machines to clear memory fragmentation
3. Profile application for memory leaks
4. Check for unclosed connections (DB, ES, Redis)

---

## 9. Implementation Checklist

### Phase 1: Basic Monitoring (Week 1)
- [ ] Verify Prometheus metrics endpoint is accessible
- [ ] Set up Grafana Cloud account
- [ ] Configure Fly metrics integration
- [ ] Import main dashboard JSON
- [ ] Set up UptimeRobot external monitoring

### Phase 2: Log Aggregation (Week 2)
- [ ] Deploy log shipper app
- [ ] Configure Vector to ship to Grafana Loki
- [ ] Verify logs are appearing in Grafana
- [ ] Set up log-based alerts

### Phase 3: Alerting (Week 3)
- [ ] Configure PagerDuty integration
- [ ] Set up Slack webhook
- [ ] Import alert rules to Grafana
- [ ] Test alert routing
- [ ] Document escalation procedures

### Phase 4: Advanced Monitoring (Week 4)
- [ ] Set up SLO dashboards
- [ ] Configure error budget alerts
- [ ] Implement distributed tracing (optional)
- [ ] Create custom runbooks
- [ ] Train team on monitoring tools

---

## 10. References

- [Fly.io Metrics Documentation](https://fly.io/docs/reference/metrics/)
- [Grafana Cloud Documentation](https://grafana.com/docs/grafana-cloud/)
- [Prometheus Best Practices](https://prometheus.io/docs/practices/)
- [GABI Architecture Documentation](./ARCHITECTURE.md)
- [GABI Operations Runbooks](./runbooks/)

---

## Appendix A: Quick Commands Reference

```bash
# Check all app status
fly status --app gabi-api
fly status --app gabi-worker
fly status --app gabi-db

# View logs
fly logs --app gabi-api --recent
fly logs --app gabi-worker --follow

# SSH into machines
fly ssh console --app gabi-api
fly ssh console --app gabi-worker

# Restart services
fly machine restart --app gabi-api
fly machine restart --app gabi-worker

# Check metrics
curl https://gabi-api.tcu.gov.br/metrics

# Trigger manual health check
fly ssh console --app gabi-worker
celery -A gabi.worker call gabi.tasks.health.health_check_task

# View DLQ
curl -H "Authorization: Bearer $TOKEN" \
  https://gabi-api.tcu.gov.br/api/v1/admin/dlq
```
