# GABI Fetch Error Handling Strategy

> **Goal:** Make failures observable, recoverable, and actionable.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Fetch Operation                             │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  Error Occurs    │
                    └──────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
    ┌─────────────────┐ ┌──────────┐ ┌────────────────┐
    │ ErrorClassifier │ │  Jitter  │ │Circuit Breaker │
    │  + Auth errors  │ │ Backoff  │ │   Protection   │
    └─────────────────┘ └──────────┘ └────────────────┘
              │               │               │
              └───────────────┴───────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  Retry Decision  │
                    │ (Retry / DLQ)    │
                    └──────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
    ┌─────────────────────┐      ┌─────────────────────────┐
    │   Schedule Retry    │      │   Move to DLQ           │
    │   (with jitter)     │      │   + Rich context        │
    └─────────────────────┘      │   + Failure signature   │
                                 └─────────────────────────┘
                                             │
                                             ▼
                                 ┌─────────────────────────┐
                                 │   Enhanced DLQ API      │
                                 │   - Pattern replay      │
                                 │   - Health reports      │
                                 │   - Bulk operations     │
                                 └─────────────────────────┘
```

## Key Components

### 1. Error Classification (`ErrorClassifier`)

| Category | HTTP Codes | Retry? | Example |
|----------|-----------|--------|---------|
| `Transient` | 5xx, Timeout | Yes | Server temporarily unavailable |
| `Throttled` | 429 | Yes (slow) | Rate limit hit |
| `Permanent` | 404, 4xx | No | Resource not found |
| `Authentication` | 401, 403 | Maybe | Token expired vs. revoked |
| `Bug` | NRE, Argument | No | Code defect |

```csharp
var context = new ErrorContext { Url = url, RetryCount = count };
var classification = ErrorClassifier.Classify(exception, context);
// classification.IsRecoverable
// classification.SuggestedAction
```

### 2. Exponential Backoff with Jitter

Prevents thundering herd when multiple jobs fail simultaneously.

```csharp
// Before: All retries at 2, 4, 8, 16... seconds
// After:  Random between 1-6s, 1-12s, 1-24s...

var delay = ExponentialBackoffCalculator.Calculate(
    retryCount: 2,
    category: ErrorCategory.Transient);
// Result: Random between 1-24 seconds
```

### 3. Circuit Breaker

Stops hammering failing sources.

```csharp
var cb = new FetchCircuitBreaker(
    failureThreshold: 5,     // Open after 5 failures
    breakDuration: TimeSpan.FromMinutes(5));

if (cb.IsOpen(sourceId))
    return; // Skip fetch, circuit is open

// ... fetch ...

cb.RecordSuccess(sourceId);  // Reset on success
cb.RecordFailure(sourceId);  // Count failure
```

### 4. Enhanced Dead Letter Queue

Rich error context for faster debugging:

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "jobType": "fetch",
  "sourceId": "senado",
  "errorCategory": "authentication",
  "errorCode": "HTTP_401",
  "isRecoverable": true,
  "suggestedAction": "Check token expiration",
  "failureSignature": "a1b2c3d4e5f6",
  "similarFailureCount": 5,
  "errorContext": {
    "url": "https://api.example.com/data",
    "httpStatusCode": 401,
    "requestDuration": "00:00:02.345",
    "retryHistory": [
      {"attempt": 1, "error": "401 Unauthorized"},
      {"attempt": 2, "error": "401 Unauthorized"}
    ]
  }
}
```

### 5. DLQ Management API

```bash
# Health check
curl /api/v1/dlq/health

# List failures by category
curl "/api/v1/dlq/entries?category=authentication&isRecoverable=true"

# See failure patterns
curl /api/v1/dlq/patterns

# Replay all similar failures
curl -X POST /api/v1/dlq/patterns/a1b2c3d4/replay

# Archive unrecoverable items
curl -X POST /api/v1/dlq/patterns/e5f6g7h8/archive \
  -d '{"reason": "Source permanently down"}'
```

## Metrics & Alerting

| Metric | Type | Alert Threshold |
|--------|------|-----------------|
| `fetch.failures.total` | Counter | > 10% failure rate |
| `fetch.dlq.pending` | Gauge | > 100 items |
| `fetch.dlq.additions{category=authentication}` | Counter | > 0 (immediate) |
| `fetch.circuit_breaker.open` | Gauge | > 0 |

## Quick Reference

### Error Handling Flow

```
Fetch Error
    │
    ├── Classify Error
    │   ├── Transient → Retry with jitter
    │   ├── Throttled → Retry with long delay
    │   ├── Auth → Retry if recoverable, else DLQ
    │   ├── Permanent → DLQ immediately
    │   └── Bug → DLQ immediately
    │
    ├── Check Circuit Breaker
    │   ├── Open → Skip, mark as blocked
    │   └── Closed → Proceed
    │
    └── Update DLQ
        ├── Set category/code
        ├── Store context
        ├── Compute signature
        └── Update similar count
```

### Configuration

```csharp
// Program.cs
builder.Services.AddSingleton<ICircuitBreaker>(sp => 
    new FetchCircuitBreaker(
        failureThreshold: 5,
        breakDuration: TimeSpan.FromMinutes(5)));

builder.Services.Configure<BackoffOptions>(options =>
{
    options.BaseDelay = TimeSpan.FromSeconds(1);
    options.ThrottledBaseDelay = TimeSpan.FromMinutes(5);
    options.MaxDelay = TimeSpan.FromHours(1);
});

// Add enhanced DLQ filter
GlobalJobFilters.Filters.Add(
    serviceProvider.GetRequiredService<EnhancedDlqFilter>());
```

### Database Migration

```bash
# Run migration
dotnet ef migrations add EnhanceErrorHandling \
    --project src/Gabi.Postgres

dotnet ef database update \
    --project src/Gabi.Postgres
```

## File Index

| File | Purpose |
|------|---------|
| `ErrorClassification.cs` | Enums and data structures |
| `ErrorClassifier.cs` | Classification logic |
| `ExponentialBackoffCalculator.cs` | Jittered backoff |
| `FetchException.cs` | Rich exception type |
| `FetchCircuitBreaker.cs` | Circuit breaker implementation |
| `IntelligentRetryPlanner.cs` | Retry decision logic |
| `EnhancedDlqFilter.cs` | Hangfire integration |
| `EnhancedDlqService.cs` | DLQ management API |
| `FetchErrorMetrics.cs` | Metrics instrumentation |
| `DlqEndpoints.cs` | REST API endpoints |

## See Also

- [Full Strategy Document](IMPROVED_ERROR_HANDLING_STRATEGY.md)
- [Implementation Guide](IMPLEMENTATION_GUIDE.md)
- [Database Migration](DATABASE_MIGRATION.md)
