# GABI Observability Stack Design

> **Status:** Draft  
> **Target:** Fly.io Production  
> **Memory Constraint:** 1GB per VM  

---

## Executive Summary

This document designs a complete observability stack for GABI ( ingestão de dados jurídicos TCU ) that balances comprehensive visibility with resource constraints. The stack prioritizes **pipeline visibility**, **memory monitoring**, and **cost tracking** while operating within Fly.io's 1GB memory limit.

**Key Decisions:**
- **Metrics:** Prometheus-compatible with Fly.io native metrics as primary
- **Logs:** Structured JSON with correlation IDs (Serilog)
- **Tracing:** OpenTelemetry with selective sampling (10% in prod)
- **Dashboard:** Grafana Cloud (free tier) + Fly.io dashboard
- **Alerting:** Fly.io alerts → Slack + PagerDuty for critical

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              GABI APPS                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                      │
│  │  Gabi.Api    │  │ Gabi.Worker  │  │  Gabi.MCP    │                      │
│  │  (HTTP)      │  │ (Background) │  │   (SSE)      │                      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                      │
└───────┬─┴─────────────────┬─┴─────────────────┬─────────────────────────────┘
        │                   │                   │
        └───────────────────┼───────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
┌───────▼───────┐  ┌────────▼────────┐  ┌──────▼────────┐
│   Prometheus  │  │   OpenTelemetry │  │  Serilog JSON │
│   (Fly.io)    │  │    Collector    │  │   (Console)   │
│               │  │   (Sidecar)     │  │               │
└───────┬───────┘  └────────┬────────┘  └───────┬────────┘
        │                   │                   │
        │         ┌─────────▼─────────┐         │
        │         │  Jaeger/Tempo     │         │
        │         │  (Grafana Cloud)  │         │
        │         └─────────┬─────────┘         │
        │                   │                   │
┌───────▼───────┐  ┌────────▼────────┐  ┌──────▼────────┐
│ Grafana Cloud │  │   PagerDuty     │  │    Slack      │
│  (Dashboard)  │  │   (Critical)    │  │   (Warnings)  │
└───────────────┘  └─────────────────┘  └───────────────┘
```

---

## 2. Structured Logging

### 2.1 Configuration (appsettings.json)

```json
{
  "Serilog": {
    "MinimumLevel": {
      "Default": "Information",
      "Override": {
        "Microsoft": "Warning",
        "Microsoft.Hosting.Lifetime": "Information",
        "System.Net.Http.HttpClient": "Warning",
        "Gabi": "Debug"
      }
    },
    "Enrich": [
      "FromLogContext",
      "WithMachineName",
      "WithProcessId",
      "WithThreadId"
    ],
    "WriteTo": [
      {
        "Name": "Console",
        "Args": {
          "formatter": "Serilog.Formatting.Compact.CompactJsonFormatter, Serilog.Formatting.Compact"
        }
      }
    ],
    "Properties": {
      "Application": "Gabi",
      "Environment": "Production"
    }
  }
}
```

### 2.2 Log Schema

```json
{
  "@t": "2026-02-12T12:30:45.1234567Z",
  "@mt": "Pipeline stage completed for {SourceId}: {Stage} in {DurationMs}ms",
  "@l": "Information",
  "@x": null,
  "SourceId": "tcu_acordaos",
  "Stage": "fetch",
  "DurationMs": 2345,
  "CorrelationId": "exec-550e8400-e29b-41d4-a716-446655440000",
  "TraceId": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
  "SpanId": "b7ad6b7169203331",
  "SourceContext": "Gabi.Sync.Pipeline.FetchStage",
  "MachineName": "gabi-worker-abc123",
  "Environment": "production",
  "App": "gabi-worker",
  "Version": "2.1.0"
}
```

### 2.3 Correlation ID Propagation

```csharp
// Extension method for consistent correlation
public static class LoggingExtensions
{
    public static IDisposable BeginPipelineScope(
        this ILogger logger, 
        string sourceId, 
        string executionId,
        string? documentId = null)
    {
        var scope = new Dictionary<string, object>
        {
            ["CorrelationId"] = executionId,
            ["SourceId"] = sourceId,
            ["Environment"] = Environment.GetEnvironmentVariable("GABI_ENVIRONMENT") ?? "unknown"
        };
        
        if (documentId != null)
            scope["DocumentId"] = documentId;
            
        return logger.BeginScope(scope);
    }
}

// Usage in pipeline
public async Task<PipelineResult> ExecuteAsync(...)
{
    using var scope = _logger.BeginPipelineScope(sourceId, executionId);
    _logger.LogInformation("Pipeline execution started");
    // All logs within scope automatically include CorrelationId and SourceId
}
```

### 2.4 Log Levels by Component

| Component | Development | Staging | Production |
|-----------|-------------|---------|------------|
| Gabi.Sync.Pipeline | Debug | Debug | Information |
| Gabi.Ingest.Fetch | Debug | Information | Information |
| Gabi.Ingest.Parse | Debug | Information | Warning |
| Gabi.Discover | Debug | Information | Information |
| Gabi.Api | Debug | Information | Warning |
| Microsoft.* | Information | Warning | Warning |

---

## 3. Metrics Stack

### 3.1 Fly.io Native Metrics (Primary)

Fly.io automatically collects infrastructure metrics. We supplement with custom application metrics.

```toml
# fly.toml - Enable metrics endpoint
[metrics]
  port = 9091
  path = "/metrics"
```

### 3.2 Custom Prometheus Metrics

Install package: `prometheus-net.AspNetCore`

```csharp
// MetricsRegistry.cs - Centralized metric definitions
public static class GabiMetrics
{
    private static readonly Meter Meter = new("Gabi", "2.1.0");
    
    // ═══════════════════════════════════════════════════════════════════════
    // PIPELINE METRICS
    // ═══════════════════════════════════════════════════════════════════════
    
    /// <summary>Documents processed by source and status</summary>
    public static readonly Counter<long> DocumentsProcessed = Meter.CreateCounter<long>(
        "gabi_pipeline_documents_processed_total",
        description: "Total documents processed through pipeline",
        unit: "{document}");
    
    /// <summary>Pipeline duration histogram</summary>
    public static readonly Histogram<double> PipelineDuration = Meter.CreateHistogram<double>(
        "gabi_pipeline_duration_seconds",
        description: "Pipeline execution duration",
        unit: "s");
    
    /// <summary>Current pipeline state by source</summary>
    public static readonly ObservableGauge<int> PipelineState = Meter.CreateObservableGauge(
        "gabi_pipeline_state",
        () => GetPipelineStates(),
        description: "Current pipeline state (0=idle, 1=running, 2=paused, 3=failed)");
    
    // ═══════════════════════════════════════════════════════════════════════
    // MEMORY METRICS (Critical for 1GB constraint)
    // ═══════════════════════════════════════════════════════════════════════
    
    /// <summary>Current memory usage from MemoryManager</summary>
    public static readonly ObservableGauge<long> MemoryUsage = Meter.CreateObservableGauge(
        "gabi_memory_usage_bytes",
        () => GetMemoryMetrics().CurrentBytes,
        description: "Current memory usage",
        unit: "By");
    
    /// <summary>Peak memory usage in current execution</summary>
    public static readonly ObservableGauge<long> MemoryPeak = Meter.CreateObservableGauge(
        "gabi_memory_peak_bytes",
        () => GetMemoryMetrics().PeakBytes,
        description: "Peak memory usage",
        unit: "By");
    
    /// <summary>Memory pressure ratio (0.0 - 1.0+)</summary>
    public static readonly ObservableGauge<double> MemoryPressure = Meter.CreateObservableGauge(
        "gabi_memory_pressure_ratio",
        () => GetMemoryMetrics().PressureRatio,
        description: "Memory pressure ratio (usage/threshold)");
    
    /// <summary>Backpressure events counter</summary>
    public static readonly Counter<long> BackpressureEvents = Meter.CreateCounter<long>(
        "gabi_memory_backpressure_events_total",
        description: "Total backpressure events triggered");
    
    /// <summary>Documents dropped due to memory pressure</summary>
    public static readonly Counter<long> DocumentsDropped = Meter.CreateCounter<long>(
        "gabi_pipeline_documents_dropped_total",
        description: "Documents dropped due to memory pressure",
        unit: "{document}");
    
    // ═══════════════════════════════════════════════════════════════════════
    // STAGE-SPECIFIC METRICS
    // ═══════════════════════════════════════════════════════════════════════
    
    /// <summary>Stage execution duration</summary>
    public static readonly Histogram<double> StageDuration = Meter.CreateHistogram<double>(
        "gabi_stage_duration_seconds",
        description: "Individual stage execution duration",
        unit: "s");
    
    /// <summary>Fetch metrics</summary>
    public static readonly Counter<long> BytesDownloaded = Meter.CreateCounter<long>(
        "gabi_fetch_bytes_downloaded_total",
        description: "Total bytes downloaded",
        unit: "By");
    
    public static readonly Counter<long> FetchErrors = Meter.CreateCounter<long>(
        "gabi_fetch_errors_total",
        description: "Fetch errors by type");
    
    /// <summary>Deduplication metrics</summary>
    public static readonly Counter<long> DuplicatesDetected = Meter.CreateCounter<long>(
        "gabi_dedup_duplicates_detected_total",
        description: "Duplicates detected by fingerprint");
    
    /// <summary>Embedding metrics</summary>
    public static readonly Counter<long> EmbeddingsGenerated = Meter.CreateCounter<long>(
        "gabi_embed_generated_total",
        description: "Embeddings generated");
    
    public static readonly Histogram<double> EmbedBatchDuration = Meter.CreateHistogram<double>(
        "gabi_embed_batch_duration_seconds",
        description: "Embedding batch processing duration");
    
    // ═══════════════════════════════════════════════════════════════════════
    // COST ATTRIBUTION METRICS
    // ═══════════════════════════════════════════════════════════════════════
    
    /// <summary>API calls by source and endpoint</summary>
    public static readonly Counter<long> ApiCalls = Meter.CreateCounter<long>(
        "gabi_cost_api_calls_total",
        description: "API calls for cost tracking",
        unit: "{call}");
    
    /// <summary>Storage operations by source</summary>
    public static readonly Counter<long> StorageOperations = Meter.CreateCounter<long>(
        "gabi_cost_storage_ops_total",
        description: "Storage operations by type");
    
    /// <summary>Tokens processed (for embedding cost estimation)</summary>
    public static readonly Counter<long> TokensProcessed = Meter.CreateCounter<long>(
        "gabi_cost_tokens_total",
        description: "Tokens processed for LLM/embedding cost estimation",
        unit: "{token}");
}

// Instrumentation in code
public class PipelineOrchestrator
{
    public async Task ProcessDocument(Document doc)
    {
        var stopwatch = Stopwatch.StartNew();
        var tags = new TagList
        {
            { "source_id", doc.SourceId },
            { "stage", "fetch" }
        };
        
        try
        {
            // ... processing ...
            
            GabiMetrics.DocumentsProcessed.Add(1, tags);
            GabiMetrics.BytesDownloaded.Add(doc.SizeBytes, tags);
            GabiMetrics.StageDuration.Record(stopwatch.Elapsed.TotalSeconds, tags);
        }
        catch (Exception ex)
        {
            tags.Add("error_type", ex.GetType().Name);
            GabiMetrics.FetchErrors.Add(1, tags);
            throw;
        }
    }
}
```

### 3.3 Metric Labels (Dimensions)

| Metric | Required Labels | Optional Labels |
|--------|-----------------|-----------------|
| `gabi_pipeline_documents_processed_total` | `source_id`, `status` | `stage`, `document_type` |
| `gabi_memory_usage_bytes` | - | `app`, `instance` |
| `gabi_stage_duration_seconds` | `source_id`, `stage` | `document_type` |
| `gabi_fetch_errors_total` | `source_id`, `error_type` | `http_status`, `retry_count` |
| `gabi_cost_api_calls_total` | `source_id`, `endpoint` | `provider` |
| `gabi_dedup_duplicates_detected_total` | `source_id` | `fingerprint_method` |

---

## 4. Distributed Tracing (OpenTelemetry)

### 4.1 Configuration

```csharp
// Program.cs - Worker
builder.Services.AddOpenTelemetry()
    .WithTracing(tracing =>
    {
        tracing
            .AddSource("Gabi.Sync", "Gabi.Ingest", "Gabi.Discover")
            .SetResourceBuilder(ResourceBuilder.CreateDefault()
                .AddService("gabi-worker", serviceVersion: "2.1.0")
                .AddAttributes(new[]
                {
                    new KeyValuePair<string, object>("deployment.environment", 
                        Environment.GetEnvironmentVariable("GABI_ENVIRONMENT") ?? "unknown"),
                    new KeyValuePair<string, object>("host.name", 
                        Environment.MachineName)
                }))
            .AddHttpClientInstrumentation()
            .AddEntityFrameworkCoreInstrumentation()
            .AddOtlpExporter(opts =>
            {
                opts.Endpoint = new Uri(builder.Configuration["OTEL_EXPORTER_OTLP_ENDPOINT"] 
                    ?? "http://localhost:4317");
                opts.Protocol = OtlpExportProtocol.Grpc;
            });
        
        // Sampling: 100% in dev/staging, 10% in production
        if (builder.Environment.IsProduction())
        {
            tracing.SetSampler(new ParentBasedSampler(
                new TraceIdRatioBasedSampler(0.1)));
        }
    })
    .WithMetrics(metrics =>
    {
        metrics
            .AddMeter("Gabi")
            .AddPrometheusExporter();
    });

// Program.cs - API
builder.Services.AddOpenTelemetry()
    .WithTracing(tracing =>
    {
        tracing
            .AddAspNetCoreInstrumentation(opts =>
            {
                opts.Filter = ctx => !ctx.Request.Path.StartsWithSegments("/health");
            })
            .AddSource("Gabi.Api")
            // ... same OTLP config
    });
```

### 4.2 Span Structure

```
sync_execution (source: tcu_acordaos, execution_id: uuid)
├── discovery (3 URLs discovered)
│   ├── fetch_head_request
│   │   └── http.client (GET https://.../acordao-2024.csv)
│   ├── etag_comparison
│   └── change_detection_result
├── fetch (1.2GB downloaded)
│   ├── http_download_stream
│   │   └── http.client (streaming 64KB chunks)
│   └── decompress (if needed)
├── parse (34,567 documents)
│   ├── csv_parse_stream
│   ├── transform_normalize
│   └── document_created
├── fingerprint
│   └── sha256_compute
├── deduplicate
│   └── postgres.query (SELECT fingerprint...)
├── index
│   ├── postgres.insert (batch 50)
│   └── elasticsearch.bulk_index
└── chunk_embed
    ├── chunk_document (avg 12 chunks/doc)
    ├── embed_batch (batch_size: 32)
    │   └── http.client (POST /embed)
    └── cleanup_chunks
```

### 4.3 Custom Spans

```csharp
public class TracedPipelineStage : IPipelineStage
{
    private readonly IPipelineStage _inner;
    private readonly ILogger<TracedPipelineStage> _logger;
    private static readonly ActivitySource ActivitySource = new("Gabi.Sync");
    
    public async Task<Document> ExecuteAsync(Document input, CancellationToken ct)
    {
        using var activity = ActivitySource.StartActivity(
            $"stage.{StageName}", 
            ActivityKind.Internal,
            parentContext: default);
        
        activity?.SetTag("source.id", input.SourceId);
        activity?.SetTag("document.id", input.DocumentId);
        activity?.SetTag("stage.name", StageName);
        activity?.SetTag("document.size_bytes", input.SizeBytes);
        
        try
        {
            var stopwatch = Stopwatch.StartNew();
            var result = await _inner.ExecuteAsync(input, ct);
            
            activity?.SetTag("duration_ms", stopwatch.ElapsedMilliseconds);
            activity?.SetTag("success", true);
            activity?.SetStatus(ActivityStatusCode.Ok);
            
            return result;
        }
        catch (Exception ex)
        {
            activity?.SetTag("error", true);
            activity?.SetTag("error.type", ex.GetType().Name);
            activity?.SetTag("error.message", ex.Message);
            activity?.SetStatus(ActivityStatusCode.Error, ex.Message);
            throw;
        }
    }
}
```

---

## 5. Health Checks

### 5.1 Endpoint Design

```csharp
// HealthCheckEndpoints.cs
public static class HealthCheckEndpoints
{
    public static IEndpointRouteBuilder MapGabiHealthChecks(this IEndpointRouteBuilder app)
    {
        // Liveness: Is the process running?
        app.MapGet("/health/live", () => Results.Ok(new { status = "alive" }));
        
        // Readiness: Can it accept traffic/work?
        app.MapGet("/health/ready", async (HealthCheckService health, CancellationToken ct) =>
        {
            var report = await health.CheckHealthAsync(ct);
            var status = report.Status == HealthStatus.Healthy ? "ready" : "not_ready";
            var code = report.Status == HealthStatus.Healthy ? 200 : 503;
            
            return Results.Json(
                new 
                { 
                    status,
                    timestamp = DateTime.UtcNow,
                    checks = report.Entries.Select(e => new
                    {
                        name = e.Key,
                        status = e.Value.Status.ToString().ToLower(),
                        duration_ms = e.Value.Duration.TotalMilliseconds,
                        data = e.Value.Data
                    })
                },
                statusCode: code);
        });
        
        // Detailed health (authenticated in prod)
        app.MapGet("/health", async (HealthCheckService health, CancellationToken ct) =>
        {
            var report = await health.CheckHealthAsync(ct);
            
            return Results.Json(new HealthReportDto
            {
                Status = MapStatus(report.Status),
                Version = Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "unknown",
                Environment = Environment.GetEnvironmentVariable("GABI_ENVIRONMENT") ?? "unknown",
                Timestamp = DateTime.UtcNow,
                Uptime = GetUptime(),
                Services = report.Entries.ToDictionary(
                    e => e.Key,
                    e => new ServiceHealthDto
                    {
                        Status = MapStatus(e.Value.Status),
                        LatencyMs = e.Value.Duration.TotalMilliseconds,
                        LastCheck = DateTime.UtcNow - e.Value.Duration,
                        Metadata = e.Value.Data.ToDictionary(d => d.Key, d => d.Value?.ToString())
                    })
            });
        });
        
        return app;
    }
}

// Health check registrations
builder.Services.AddHealthChecks()
    // Self check (always available)
    .AddCheck("self", () => HealthCheckResult.Healthy(), tags: new[] { "live" })
    
    // PostgreSQL
    .AddNpgSql(
        connectionString: configuration.GetConnectionString("Default")!,
        name: "postgres",
        failureStatus: HealthStatus.Unhealthy,
        tags: new[] { "ready", "storage" })
    
    // Elasticsearch (optional for readiness)
    .AddElasticsearch(
        elasticsearchUri: configuration["GABI_ELASTICSEARCH_URL"] ?? "http://localhost:9200",
        name: "elasticsearch",
        failureStatus: HealthStatus.Degraded,
        tags: new[] { "ready", "search" })
    
    // TEI Service (optional)
    .AddCheck<TeiHealthCheck>("tei", tags: new[] { "ready", "embed" })
    
    // Memory pressure check
    .AddCheck<MemoryHealthCheck>("memory", tags: new[] { "ready" });
```

### 5.2 Memory Health Check

```csharp
public class MemoryHealthCheck : IHealthCheck
{
    private readonly IMemoryManager _memoryManager;
    
    public MemoryHealthCheck(IMemoryManager memoryManager)
    {
        _memoryManager = memoryManager;
    }
    
    public Task<HealthCheckResult> CheckHealthAsync(
        HealthCheckContext context, 
        CancellationToken ct)
    {
        var pressureRatio = (double)_memoryManager.CurrentUsage / _memoryManager.PressureThreshold;
        var data = new Dictionary<string, object>
        {
            ["current_mb"] = _memoryManager.CurrentUsage / 1024 / 1024,
            ["threshold_mb"] = _memoryManager.PressureThreshold / 1024 / 1024,
            ["pressure_ratio"] = pressureRatio,
            ["is_under_pressure"] = _memoryManager.IsUnderPressure
        };
        
        if (pressureRatio > 1.0)
            return Task.FromResult(HealthCheckResult.Unhealthy(
                "Memory pressure exceeded threshold", data: data));
        
        if (pressureRatio > 0.9)
            return Task.FromResult(HealthCheckResult.Degraded(
                "Memory pressure high (>90%)", data: data));
        
        return Task.FromResult(HealthCheckResult.Healthy(
            "Memory usage normal", data: data));
    }
}
```

### 5.3 Fly.io Health Check Integration

```toml
# fly.toml
[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = true
  auto_start_machines = true
  min_machines_running = 0
  
  [[http_service.checks]]
    interval = "30s"
    timeout = "5s"
    grace_period = "10s"
    method = "GET"
    path = "/health/ready"
    protocol = "http"
```

---

## 6. Alerting Rules

### 6.1 Fly.io Native Alerts

Configure via Fly.io dashboard or CLI:

```bash
# Create alert for high error rate
flyctl alerts create \
  --name "gabi-high-error-rate" \
  --condition "error_rate > 5" \
  --window "5m" \
  --webhook-url "https://hooks.slack.com/services/..."
```

### 6.2 Prometheus AlertManager Rules

```yaml
# prometheus/alerts.yml
groups:
  - name: gabi-pipeline
    interval: 30s
    rules:
      # CRITICAL: Sync failures
      - alert: GabiPipelineSyncFailures
        expr: |
          rate(gabi_fetch_errors_total[5m]) > 0.1
        for: 5m
        labels:
          severity: critical
          team: platform
          service: gabi
        annotations:
          summary: "High sync failure rate for {{ $labels.source_id }}"
          description: "Error rate is {{ $value | humanizePercentage }} for source {{ $labels.source_id }}"
          runbook_url: "https://wiki.internal/gabi/runbooks/sync-failures"
          
      # CRITICAL: Memory pressure
      - alert: GabiMemoryPressureCritical
        expr: |
          gabi_memory_pressure_ratio > 0.95
        for: 2m
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "Critical memory pressure in {{ $labels.app }}"
          description: "Memory pressure is {{ $value | humanizePercentage }} ({{ $labels.instance }})"
          
      # WARNING: Memory pressure rising
      - alert: GabiMemoryPressureWarning
        expr: |
          gabi_memory_pressure_ratio > 0.8
        for: 5m
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "High memory pressure in {{ $labels.app }}"
          description: "Memory pressure is {{ $value | humanizePercentage }}"
          
      # WARNING: Backpressure events
      - alert: GabiBackpressureFrequent
        expr: |
          rate(gabi_memory_backpressure_events_total[10m]) > 0.01
        for: 5m
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "Frequent backpressure events"
          description: "{{ $value | humanize }} backpressure events/minute"
          
      # CRITICAL: Document drops
      - alert: GabiDocumentsDropped
        expr: |
          rate(gabi_pipeline_documents_dropped_total[5m]) > 0
        for: 1m
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "Documents being dropped due to memory pressure"
          description: "{{ $value | humanize }} documents dropped/minute"
          
      # WARNING: Pipeline duration
      - alert: GabiPipelineSlow
        expr: |
          histogram_quantile(0.95, 
            rate(gabi_pipeline_duration_seconds_bucket[10m])
          ) > 300
        for: 10m
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "Pipeline execution unusually slow"
          description: "95th percentile duration is {{ $value | humanizeDuration }}"
          
      # INFO: Source completion
      - alert: GabiSourceCompleted
        expr: |
          gabi_pipeline_documents_processed_total > 0
        for: 0m
        labels:
          severity: info
          team: data
        annotations:
          summary: "Source {{ $labels.source_id }} completed processing"

  - name: gabi-infrastructure
    rules:
      # CRITICAL: PostgreSQL unavailable
      - alert: GabiPostgresDown
        expr: |
          up{job="postgres"} == 0
        for: 1m
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "PostgreSQL is down"
          
      # CRITICAL: Elasticsearch unavailable
      - alert: GabiElasticsearchDown
        expr: |
          up{job="elasticsearch"} == 0
        for: 2m
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "Elasticsearch is down"
          
      # WARNING: Disk space
      - alert: GabiPostgresDiskSpaceLow
        expr: |
          pg_database_size_bytes / pg_settings_max_wal_size > 0.8
        for: 5m
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "PostgreSQL disk space running low"

  - name: gabi-cost
    rules:
      # INFO: High API usage
      - alert: GabiHighApiUsage
        expr: |
          rate(gabi_cost_api_calls_total[1h]) > 1000
        for: 1h
        labels:
          severity: info
          team: data
        annotations:
          summary: "High API usage detected for {{ $labels.source_id }}"
          description: "{{ $value | humanize }} calls/hour"
```

### 6.3 Notification Routing

```yaml
# alertmanager.yml
global:
  pagerduty_url: 'https://events.pagerduty.com/v2/enqueue'
  
route:
  receiver: 'default'
  group_by: ['alertname', 'source_id', 'severity']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  
  routes:
    # Critical alerts go to PagerDuty + Slack
    - match:
        severity: critical
      receiver: 'pagerduty-critical'
      continue: true
      
    # Pipeline warnings to #gabi-alerts
    - match_re:
        severity: warning|info
      receiver: 'slack-alerts'
      
receivers:
  - name: 'default'
    slack_configs:
      - channel: '#gabi-monitoring'
        title: 'GABI Alert'
        
  - name: 'pagerduty-critical'
    pagerduty_configs:
      - service_key: '<GABI_SERVICE_KEY>'
        severity: critical
        description: '{{ .GroupLabels.alertname }}: {{ .Annotations.summary }}'
        
  - name: 'slack-alerts'
    slack_configs:
      - channel: '#gabi-alerts'
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}'
        color: '{{ if eq .GroupLabels.severity "critical" }}danger{{ else if eq .GroupLabels.severity "warning" }}warning{{ else }}good{{ end }}'
        fields:
          - title: Source
            value: '{{ .GroupLabels.source_id }}'
            short: true
          - title: Severity
            value: '{{ .GroupLabels.severity }}'
            short: true
          - title: Runbook
            value: '{{ .Annotations.runbook_url }}'
            short: false
```

---

## 7. Cost Attribution

### 7.1 Cost Tracking Design

```csharp
// CostTracker.cs
public class CostTracker : ICostTracker
{
    private readonly ILogger<CostTracker> _logger;
    
    public void TrackApiCall(string sourceId, string endpoint, string provider, int tokens = 0)
    {
        var tags = new TagList
        {
            { "source_id", sourceId },
            { "endpoint", endpoint },
            { "provider", provider }
        };
        
        GabiMetrics.ApiCalls.Add(1, tags);
        
        if (tokens > 0)
        {
            GabiMetrics.TokensProcessed.Add(tokens, tags);
        }
        
        _logger.LogDebug(
            "API call tracked: {SourceId} -> {Endpoint} ({Tokens} tokens)",
            sourceId, endpoint, tokens);
    }
    
    public void TrackStorageOp(string sourceId, string operation, long bytes)
    {
        var tags = new TagList
        {
            { "source_id", sourceId },
            { "operation", operation }  // insert, update, delete, query
        };
        
        GabiMetrics.StorageOperations.Add(1, tags);
        
        // Estimate storage cost (simplified)
        // PostgreSQL: ~$0.10/GB/month
        // Elasticsearch: ~$0.15/GB/month
    }
}
```

### 7.2 Cost Dashboard Queries

```promql
# Daily cost by source (API calls)
sum by (source_id) (
  increase(gabi_cost_api_calls_total[24h])
)

# Estimated embedding cost (assuming $0.10/1M tokens)
sum by (source_id) (
  increase(gabi_cost_tokens_total[24h]) * 0.0000001
)

# Storage growth by source
sum by (source_id) (
  increase(gabi_fetch_bytes_downloaded_total[24h])
)

# Most expensive sources (last 7 days)
topk(5,
  sum by (source_id) (
    increase(gabi_cost_api_calls_total[7d]) * 0.001 +  # API call cost
    increase(gabi_cost_tokens_total[7d]) * 0.0000001     # Token cost
  )
)
```

### 7.3 Monthly Cost Report (Automated)

```csharp
public class CostReportService : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            await GenerateMonthlyReport();
            await Task.Delay(TimeSpan.FromDays(30), ct);
        }
    }
    
    private async Task GenerateMonthlyReport()
    {
        var report = new CostReport
        {
            Period = DateTime.UtcNow.AddMonths(-1).ToString("yyyy-MM"),
            GeneratedAt = DateTime.UtcNow,
            Sources = await CalculateSourceCosts()
        };
        
        _logger.LogInformation(
            "Monthly cost report: Total=${Total:F2}, Sources={Count}",
            report.TotalCost,
            report.Sources.Count);
        
        // Store in PostgreSQL for historical tracking
        await _repository.SaveCostReport(report);
    }
}
```

---

## 8. Operations Dashboard

### 8.1 Grafana Dashboard (JSON Model)

```json
{
  "dashboard": {
    "title": "GABI Pipeline Overview",
    "panels": [
      {
        "title": "Pipeline Status",
        "type": "stat",
        "targets": [{
          "expr": "gabi_pipeline_state",
          "legendFormat": "{{source_id}}"
        }]
      },
      {
        "title": "Documents Processed (Rate)",
        "type": "graph",
        "targets": [{
          "expr": "rate(gabi_pipeline_documents_processed_total[5m])",
          "legendFormat": "{{source_id}} ({{status}})"
        }]
      },
      {
        "title": "Memory Usage",
        "type": "timeseries",
        "targets": [
          {
            "expr": "gabi_memory_usage_bytes / 1024 / 1024",
            "legendFormat": "Current (MB)"
          },
          {
            "expr": "gabi_memory_pressure_ratio",
            "legendFormat": "Pressure Ratio"
          }
        ],
        "alert": {
          "conditions": [{
            "evaluator": { "params": [0.9], "type": "gt" },
            "reducer": { "type": "last" },
            "query": { "params": ["A", "5m", "now"] }
          }]
        }
      },
      {
        "title": "Active Sources",
        "type": "table",
        "targets": [{
          "expr": "sum by (source_id) (gabi_pipeline_documents_processed_total)",
          "format": "table"
        }],
        "transformations": [
          {
            "id": "organize",
            "options": {
              "indexByName": { "source_id": 0, "Value": 1 },
              "renameByName": { "Value": "Total Documents" }
            }
          }
        ]
      },
      {
        "title": "Cost Breakdown (24h)",
        "type": "piechart",
        "targets": [{
          "expr": "sum by (source_id) (increase(gabi_cost_api_calls_total[24h]))",
          "legendFormat": "{{source_id}}"
        }]
      }
    ]
  }
}
```

### 8.2 Fly.io Dashboard Integration

```bash
# View metrics in Fly.io dashboard
flyctl dashboard --app gabi-worker

# Custom metrics endpoint (Prometheus format)
flyctl metrics --app gabi-worker
```

### 8.3 Operational Runbooks

```markdown
# Runbook: Memory Pressure Alert

## Symptoms
- Alert: `GabiMemoryPressureCritical` or `GabiMemoryPressureWarning`
- Memory pressure ratio > 0.9

## Initial Response (5 minutes)
1. Check current pipeline status: `GET /health/ready`
2. View active sources: Check dashboard "Active Sources" panel
3. Check if backpressure is active: `gabi_memory_backpressure_events_total`

## Escalation Path
- If pressure > 0.95 for > 5min: Scale VM to 2GB
- If documents being dropped: Pause non-critical sources

## Resolution
1. Identify source causing pressure (largest document/batch)
2. Reduce batch_size in source config
3. Enable more aggressive GC
4. Consider sequential processing only

## Prevention
- Set memory_threshold lower in sources_v2.yaml
- Monitor `gabi_memory_pressure_ratio` trend
```

---

## 9. Implementation Roadmap

### Phase 1: Foundation (Week 1)
- [ ] Add Serilog JSON logging to all projects
- [ ] Implement CorrelationId middleware/propagation
- [ ] Add basic health checks (/health, /ready, /live)
- [ ] Configure Fly.io metrics endpoint

### Phase 2: Metrics (Week 2)
- [ ] Instrument PipelineOrchestrator with metrics
- [ ] Add MemoryManager metrics export
- [ ] Create cost tracking infrastructure
- [ ] Deploy Grafana Cloud (free tier)

### Phase 3: Tracing (Week 3)
- [ ] Configure OpenTelemetry in Worker
- [ ] Configure OpenTelemetry in API
- [ ] Add custom spans to pipeline stages
- [ ] Setup Jaeger/Tempo (Grafana Cloud)

### Phase 4: Alerting (Week 4)
- [ ] Configure AlertManager rules
- [ ] Setup Slack notifications
- [ ] Setup PagerDuty integration (critical only)
- [ ] Create operational runbooks

### Phase 5: Dashboard (Week 5)
- [ ] Build Grafana dashboard
- [ ] Add cost attribution panels
- [ ] Create pipeline progress visualization
- [ ] Document operational procedures

---

## 10. Resource Budget

### Memory Usage (within 1GB constraint)

| Component | Memory | Notes |
|-----------|--------|-------|
| .NET Runtime | ~200MB | Fixed |
| Application Code | ~100MB | Worker + Pipeline |
| Active Processing | ~150MB | Streaming buffers |
| Serilog (buffer) | ~10MB | Async sink |
| Prometheus Metrics | ~20MB | Metric storage |
| OpenTelemetry | ~30MB | Traces buffer (limited) |
| **Total Observable** | **~510MB** | **Leaves ~490MB safety** |

### Sampling Strategy (Production)

| Data Type | Sampling Rate | Justification |
|-----------|---------------|---------------|
| Logs | 100% | Low volume, critical for debugging |
| Metrics | 100% | Aggregated, minimal overhead |
| Traces | 10% | Sufficient for error analysis |
| Health Checks | 100% | Required for load balancing |

---

## 11. Security Considerations

- Health check `/health` details require authentication in production
- Metrics endpoint `/metrics` should not be public
- Logs must not contain PII or sensitive document content
- Trace data retention: 7 days (Grafana Cloud free tier)
- Cost reports access limited to finance team

---

## 12. References

- [Fly.io Metrics](https://fly.io/docs/reference/metrics/)
- [OpenTelemetry .NET](https://opentelemetry.io/docs/instrumentation/net/)
- [Prometheus Alerting](https://prometheus.io/docs/alerting/latest/alertmanager/)
- [Grafana Cloud Free Tier](https://grafana.com/pricing/)
- Existing: `/docs/architecture/OBSERVABILITY.md`
- Existing: `/docs/architecture/MEMORY_ARCHITECTURE.md`
