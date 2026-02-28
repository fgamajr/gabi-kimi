# Error Handling Implementation Guide

## Quick Start

This guide covers the improved error handling implementation for the GABI fetch system.

## What's New

### 1. Enhanced Error Classification

**Before:**
```csharp
// 4 categories: Transient, Throttled, Permanent, Bug
var classification = ErrorClassifier.Classify(exception);
```

**After:**
```csharp
// 5 categories: + Authentication
var context = new ErrorContext { Url = url, RetryCount = retryCount };
var classification = ErrorClassifier.Classify(exception, context);
// classification.IsRecoverable
// classification.SuggestedAction
```

### 2. Exponential Backoff with Jitter

**Before:**
```csharp
// Fixed exponential: 2, 4, 8, 16, 32 seconds
var delay = TimeSpan.FromSeconds(Math.Pow(2, retryCount));
```

**After:**
```csharp
// Jittered: random between base and 3x exponential, capped at max
var delay = ExponentialBackoffCalculator.Calculate(
    retryCount, 
    classification.Category,
    BackoffOptions.Default);
```

### 3. Circuit Breaker Pattern

New! Prevents hammering failing sources:

```csharp
// After 5 failures, circuit opens for 5 minutes
var cb = new FetchCircuitBreaker(failureThreshold: 5);

if (!cb.IsOpen(sourceId, url))
{
    await FetchAsync(url);
    cb.RecordSuccess(sourceId, url);
}
else
{
    // Skip, circuit is open
}
```

### 4. Enhanced DLQ

**Before:** Basic error message and stack trace

**After:** Rich context including:
- Error category and code
- Recovery suggestions
- Failure signatures for grouping
- Similar failure counts
- Structured error context (URL, headers, response snippet)

## File Structure

```
src/
├── Gabi.Contracts/
│   └── Errors/
│       ├── ErrorClassification.cs      # Enums and records
│       ├── ErrorClassifier.cs          # Classification logic
│       ├── ExponentialBackoffCalculator.cs
│       └── FetchException.cs           # Custom exception
├── Gabi.Worker/
│   └── Jobs/
│       ├── FetchCircuitBreaker.cs      # Circuit breaker implementation
│       ├── IntelligentRetryPlanner.cs  # Updated retry planning
│       ├── EnhancedDlqFilter.cs        # Hangfire filter with new features
│       └── FetchErrorMetrics.cs        # OpenTelemetry metrics
└── Gabi.Api/
    ├── Services/
    │   └── EnhancedDlqService.cs       # DLQ management API
    └── Endpoints/
        └── DlqEndpoints.cs             # REST API endpoints
```

## Migration Steps

### 1. Update Database Schema

```bash
# Run the migration SQL in docs/error-handling/DATABASE_MIGRATION.md
# Or use EF Core migrations:
dotnet ef migrations add EnhanceErrorHandling \
    --project src/Gabi.Postgres \
    --startup-project src/Gabi.Api

dotnet ef database update \
    --project src/Gabi.Postgres \
    --startup-project src/Gabi.Api
```

### 2. Update Entity Models

Add to `DlqEntryEntity`:
```csharp
public string ErrorCategory { get; set; } = "unknown";
public string ErrorCode { get; set; } = string.Empty;
public string? ErrorContext { get; set; }
public string? SuggestedAction { get; set; }
public bool IsRecoverable { get; set; } = true;
public string? FailureSignature { get; set; }
public int SimilarFailureCount { get; set; }
```

Add to `FetchItemEntity`:
```csharp
public int RetryCount { get; set; }
public DateTime? FirstFailedAt { get; set; }
public DateTime? LastFailedAt { get; set; }
public string? RetryHistory { get; set; }
public string? LastErrorCategory { get; set; }
public string? LastErrorCode { get; set; }
public int ConsecutiveFailures { get; set; }
public DateTime? CircuitBrokenUntil { get; set; }
```

### 3. Register Services

In `Program.cs`:

```csharp
// Add circuit breaker
builder.Services.AddSingleton<ICircuitBreaker>(sp => 
    new FetchCircuitBreaker(
        failureThreshold: 5,
        breakDuration: TimeSpan.FromMinutes(5),
        logger: sp.GetRequiredService<ILogger<FetchCircuitBreaker>>()));

// Add enhanced DLQ service
builder.Services.AddScoped<IEnhancedDlqService, EnhancedDlqService>();

// Add enhanced DLQ filter (replaces DlqFilter)
builder.Services.AddSingleton<EnhancedDlqFilter>();

// Add backoff options
builder.Services.Configure<BackoffOptions>(options =>
{
    options.BaseDelay = TimeSpan.FromSeconds(1);
    options.ThrottledBaseDelay = TimeSpan.FromMinutes(5);
    options.AuthBaseDelay = TimeSpan.FromMinutes(1);
    options.MaxDelay = TimeSpan.FromHours(1);
});
```

### 4. Update Hangfire Configuration

```csharp
// Replace DlqFilter with EnhancedDlqFilter
GlobalJobFilters.Filters.Add(serviceProvider.GetRequiredService<EnhancedDlqFilter>());
```

### 5. Map API Endpoints

```csharp
// In Program.cs
app.MapDlqEndpoints();
```

## Usage Examples

### Error Classification with Context

```csharp
try
{
    await FetchAsync(url);
}
catch (Exception ex)
{
    var context = new ErrorContext
    {
        Url = url,
        SourceId = sourceId,
        RetryCount = item.RetryCount,
        FirstFailedAt = item.FirstFailedAt,
        RequestDuration = stopwatch.Elapsed
    };
    
    var classification = ErrorClassifier.Classify(ex, context);
    
    _logger.LogWarning(
        "Fetch failed: {Category}/{Code}, Recoverable: {Recoverable}, Action: {Action}",
        classification.Category,
        classification.Code,
        classification.IsRecoverable,
        classification.SuggestedAction);
    
    // Update item tracking
    item.LastErrorCategory = classification.Category.ToString();
    item.LastErrorCode = classification.Code;
    item.ConsecutiveFailures++;
    
    // Throw with classification for DLQ
    throw new FetchException(
        $"Fetch failed: {classification.Code}", 
        ex, 
        classification, 
        context);
}
```

### Circuit Breaker in Fetch Executor

```csharp
public class FetchJobExecutor
{
    private readonly ICircuitBreaker _circuitBreaker;
    
    public async Task<JobResult> ExecuteAsync(IngestJob job, ...)
    {
        foreach (var item in items)
        {
            // Check circuit breaker
            if (_circuitBreaker.IsOpen(job.SourceId, item.Url))
            {
                _logger.LogWarning(
                    "Skipping {Url} - circuit is open until {Until}",
                    item.Url, 
                    _circuitBreaker.GetState(job.SourceId, item.Url)?.OpenUntil);
                
                item.Status = "circuit_open";
                item.LastError = "Circuit breaker is open";
                continue;
            }
            
            try
            {
                await FetchAndProcessAsync(item);
                _circuitBreaker.RecordSuccess(job.SourceId, item.Url);
            }
            catch (Exception ex)
            {
                _circuitBreaker.RecordFailure(job.SourceId, item.Url);
                throw;
            }
        }
    }
}
```

### DLQ Replay via API

```bash
# Get health report
curl /api/v1/dlq/health

# Get failure patterns
curl /api/v1/dlq/patterns

# Replay by pattern
curl -X POST /api/v1/dlq/patterns/abc123/replay \
  -d '{"notes": "Retry after source fix"}'

# Replay all auth failures
curl -X POST /api/v1/dlq/categories/authentication/replay

# Archive unrecoverable items
curl -X POST /api/v1/dlq/patterns/def456/archive \
  -d '{"reason": "Source permanently unavailable"}'
```

## Metrics & Monitoring

### Available Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `fetch.attempts.total` | Counter | Total fetch attempts |
| `fetch.failures.total` | Counter | Failures by category |
| `fetch.retries.total` | Counter | Retry attempts |
| `fetch.dlq.additions.total` | Counter | Items moved to DLQ |
| `fetch.dlq.pending` | UpDown | Current DLQ size |
| `fetch.retry.delay_seconds` | Histogram | Retry delay distribution |
| `fetch.circuit_breaker.open` | UpDown | Open circuits |

### Alert Examples (Prometheus)

```yaml
alerts:
  - alert: HighFetchFailureRate
    expr: |
      rate(fetch.failures.total[5m]) 
      / rate(fetch.attempts.total[5m]) > 0.1
    for: 2m
    labels:
      severity: warning

  - alert: AuthFailuresDetected
    expr: |
      fetch.dlq.additions.total{category="authentication"} > 0
    labels:
      severity: critical

  - alert: DLQGrowing
    expr: fetch.dlq.pending > 100
    for: 10m
    labels:
      severity: warning
```

## Testing

### Unit Tests

```csharp
[Fact]
public void Classify_AuthError_WithContext_ShouldBeRecoverable()
{
    var ex = new HttpRequestException("Unauthorized", null, HttpStatusCode.Unauthorized);
    var context = new ErrorContext { RetryCount = 0 };
    
    var result = ErrorClassifier.Classify(ex, context);
    
    Assert.Equal(ErrorCategory.Authentication, result.Category);
    Assert.True(result.IsRecoverable);
    Assert.Equal("HTTP_401", result.Code);
}

[Theory]
[InlineData(0, 1000, 3000)]
[InlineData(3, 1000, 24000)]
public void Calculate_WithJitter_ShouldStayWithinBounds(
    int retryCount, int minMs, int maxMs)
{
    var delay = ExponentialBackoffCalculator.Calculate(
        retryCount, ErrorCategory.Transient);
    
    Assert.InRange(delay.TotalMilliseconds, minMs, maxMs);
}

[Fact]
public void CircuitBreaker_AfterThreshold_ShouldOpen()
{
    var cb = new FetchCircuitBreaker(failureThreshold: 3);
    
    cb.RecordFailure("source1");
    cb.RecordFailure("source1");
    Assert.False(cb.IsOpen("source1"));
    
    cb.RecordFailure("source1");
    Assert.True(cb.IsOpen("source1"));
}
```

### Integration Tests

```csharp
[Fact]
public async Task FailedJob_ShouldMoveToDlq_WithClassification()
{
    // Arrange
    var job = CreateJobThatWillFail();
    
    // Act - Execute until max retries
    for (int i = 0; i < MaxRetries; i++)
    {
        await _runner.RunAsync(job);
    }
    
    // Assert
    var dlqEntry = await _dbContext.DlqEntries
        .FirstOrDefaultAsync(e => e.OriginalJobId == job.Id);
    
    Assert.NotNull(dlqEntry);
    Assert.NotEqual("unknown", dlqEntry.ErrorCategory);
    Assert.NotNull(dlqEntry.FailureSignature);
}
```

## Configuration

### Backoff Options

```json
{
  "BackoffOptions": {
    "BaseDelay": "00:00:01",
    "ThrottledBaseDelay": "00:05:00",
    "AuthBaseDelay": "00:01:00",
    "MaxDelay": "01:00:00"
  }
}
```

### Circuit Breaker Options

```csharp
builder.Services.AddSingleton<ICircuitBreaker>(sp => 
    new FetchCircuitBreaker(
        failureThreshold: 5,        // Open after 5 failures
        breakDuration: TimeSpan.FromMinutes(5),  // Stay open 5 min
        resetTimeout: TimeSpan.FromMinutes(30)   // Reset counter after 30 min of no failures
    ));
```

## Rollback Plan

If issues arise:

1. **Revert to original DlqFilter:**
   ```csharp
   // Remove EnhancedDlqFilter from services
   // Re-add original DlqFilter
   ```

2. **Database rollback:**
   ```bash
   dotnet ef database update <previous_migration>
   ```

3. **Code changes are additive** - existing functionality remains intact

## Performance Considerations

- **Circuit breaker:** In-memory state (fast, but not distributed)
- **Jitter calculation:** ThreadLocal Random (no contention)
- **DLQ queries:** Indexed columns for filtering
- **Metrics:** Zero-allocation counters where possible

## Next Steps

1. [ ] Run database migration
2. [ ] Deploy updated services
3. [ ] Configure monitoring dashboards
4. [ ] Set up alerts
5. [ ] Train ops team on new DLQ API
6. [ ] Document runbooks for common failure patterns
