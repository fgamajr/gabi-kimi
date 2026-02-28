# Observabilidade

## Visão Geral

O sistema GabiSync expõe métricas Prometheus, logs estruturados JSON e tracing distribuído.

---

## Métricas (Prometheus)

### Documentos

```csharp
// Counter
var documentsIngestedTotal = Metrics.CreateCounter(
    "gabi_documents_ingested_total",
    "Total de documentos ingeridos",
    new CounterConfiguration { LabelNames = new[] { "source_id", "status" } }
);

// Uso
documentsIngestedTotal.WithLabels("tcu_sumulas", "success").Inc();
```

| Métrica | Tipo | Labels | Descrição |
|---------|------|--------|-----------|
| `gabi_documents_ingested_total` | Counter | `source_id`, `status` | Documentos processados |
| `gabi_documents_deduplicated_total` | Counter | `source_id` | Duplicatas detectadas |
| `gabi_fetch_skipped_total` | Counter | `source_id` | Downloads evitados (cache) |
| `gabi_fetch_failed_total` | Counter | `source_id`, `error_type` | Falhas de download |
| `gabi_embeddings_generated_total` | Counter | `source_id`, `model` | Embeddings criados |
| `gabi_sync_duration_seconds` | Histogram | `source_id` | Duração do sync |
| `gabi_active_documents` | Gauge | `source_id` | Documentos ativos |
| `gabi_dlq_messages` | Gauge | `source_id`, `status` | Mensagens na DLQ |

### Infraestrutura

```csharp
// Gauge
var dbConnections = Metrics.CreateGauge(
    "gabi_postgres_connections",
    "Conexões abertas no PostgreSQL"
);
```

---

## Logs Estruturados (JSON)

### Configuração

```csharp
// appsettings.json
{
  "Logging": {
    "LogLevel": {
      "Default": "Information",
      "Gabi": "Debug"
    },
    "Console": {
      "FormatterName": "json",
      "FormatterOptions": {
        "SingleLine": true,
        "IncludeScopes": true,
        "TimestampFormat": "yyyy-MM-ddTHH:mm:ss.fffZ"
      }
    }
  }
}
```

### Estrutura do Log

```json
{
  "Timestamp": "2025-01-15T14:30:00.123Z",
  "Level": "Information",
  "Message": "Document ingested successfully",
  "TraceId": "abc123def456",
  "SpanId": "span789",
  "Properties": {
    "CorrelationId": "exec-manifest-uuid",
    "SourceId": "tcu_sumulas",
    "DocumentId": "SUM-274/2012",
    "DurationMs": 1234,
    "EventType": "document_ingested"
  }
}
```

### Correlation ID

Cada execução de sync possui um `CorrelationId` único (do Execution Manifest):

```csharp
public async Task ExecuteSyncAsync(SyncContext context)
{
    using var scope = _logger.BeginScope(new Dictionary<string, object>
    {
        ["CorrelationId"] = context.ExecutionId,
        ["SourceId"] = context.SourceId
    });
    
    _logger.LogInformation("Starting sync for source {SourceId}", context.SourceId);
    // Todos os logs dentro do scope incluem CorrelationId
}
```

---

## Tracing (OpenTelemetry)

### Spans Principais

```
sync_execution
├── discovery
│   └── fetch_head_request
├── fetch
│   └── http_download
├── parse
│   ├── csv_parse
│   └── transform_apply
├── fingerprint
├── deduplicate
│   └── db_query
├── index
│   ├── pg_insert
│   └── es_index
└── chunk_embed
    ├── chunk
    └── embed_batch
```

### Implementação

```csharp
// Program.cs
builder.Services.AddOpenTelemetry()
    .WithTracing(tracing =>
    {
        tracing.AddAspNetCoreInstrumentation()
               .AddSource("Gabi.Discovery", "Gabi.Ingest", "Gabi.Sync")
               .AddOtlpExporter();
    });

// Uso
public class IngestionPipeline
{
    private readonly ActivitySource _activitySource = new("Gabi.Ingest");
    
    public async Task IngestAsync(Document doc)
    {
        using var activity = _activitySource.StartActivity("ingest_document");
        activity?.SetTag("document.id", doc.DocumentId);
        activity?.SetTag("source.id", doc.SourceId);
        
        // ... processamento
        
        activity?.SetStatus(ActivityStatusCode.Ok);
    }
}
```

---

## Lineage (Rastreamento de Linhagem)

Toda transformação é registrada em `lineage_nodes` / `lineage_edges`:

```sql
-- lineage_nodes
id: uuid
type: source | transform | document | api
data: jsonb
created_at: timestamp

-- lineage_edges  
from_node: uuid
to_node: uuid
transform_type: string
metadata: jsonb
```

### Exemplo de Linhagem

```
[source:tcu_csv] 
    ↓ (fetch)
[transform:csv_parse]
    ↓ (normalize)
[transform:strip_quotes]
    ↓ (fingerprint)
[document:SUM-274/2012]
    ↓ (chunk)
[chunk:0]
[chunk:1]
    ↓ (embed)
[embedding:0]
[embedding:1]
```

---

## Health Checks

### Endpoint

```csharp
// GET /health
{
  "status": "healthy",  // healthy | degraded | unhealthy
  "version": "2.1.0",
  "environment": "production",
  "services": {
    "postgres": { "status": "healthy", "latency_ms": 5 },
    "elasticsearch": { "status": "healthy", "latency_ms": 12 },
    "tei": { "status": "healthy", "latency_ms": 45 }
  }
}
```

### Implementação

```csharp
builder.Services.AddHealthChecks()
    .AddDbContextCheck<AppDbContext>("postgres")
    .AddElasticsearch("elasticsearch")
    .AddCheck<TeiHealthCheck>("tei");
```

---

## Alertas

### Condições de Alerta

| Alerta | Condição | Severidade |
|--------|----------|------------|
| Sync Failures | `gabi_fetch_failed_total > 10` em 5m | Critical |
| DLQ Growth | `gabi_dlq_messages > 100` | Warning |
| High Latency | `gabi_sync_duration_seconds > 300` | Warning |
| DB Connections | `gabi_postgres_connections > 80` | Critical |
| ES Unavailable | `up{job="elasticsearch"} == 0` | Critical |

### Integração

```yaml
# prometheus/alerts.yml
groups:
  - name: gabi
    rules:
      - alert: GabiSyncFailures
        expr: rate(gabi_fetch_failed_total[5m]) > 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High sync failure rate"
```
