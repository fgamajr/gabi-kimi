# Improved Error Handling Strategy for GABI Fetch System

## Executive Summary

This document outlines improvements to the fetch error handling to make failures **observable**, **recoverable**, and **actionable**. The focus is on eliminating silent failures and providing clear paths to resolution.

---

## 1. Error Classification Enhancement

### Current State
The system already has `ErrorClassifier` with categories:
- `Transient` - Retryable (timeouts, 5xx)
- `Throttled` - Rate limited (429)
- `Permanent` - Don't retry (404, 4xx)
- `Bug` - Code issues (NullReference, ArgumentException)

### Proposed Addition: `Authentication` Category

Authentication errors (401, 403) need special handling:
- They may be transient (expired token) or permanent (revoked credentials)
- Require different alerting (notify ops team)
- May need manual intervention

```csharp
public enum ErrorCategory
{
    Transient,      // Network issues, 5xx, timeouts
    Throttled,      // 429 Too Many Requests
    Permanent,      // 404, malformed data
    Authentication, // 401, 403 - requires credential check
    Bug             // Code defects
}
```

### Enhanced Classification with Context

```csharp
public readonly record struct ErrorClassification(
    ErrorCategory Category, 
    string Code, 
    string Message,
    bool IsRecoverable = true,
    string? SuggestedAction = null);

public record ErrorContext
{
    public string? Url { get; init; }
    public string? SourceId { get; init; }
    public int RetryCount { get; init; }
    public TimeSpan? RequestDuration { get; init; }
    public DateTime? FirstFailedAt { get; init; }
}

public static class ErrorClassifier
{
    public static ErrorClassification Classify(Exception exception, ErrorContext? context = null)
    {
        ArgumentNullException.ThrowIfNull(exception);

        if (exception is HttpRequestException http)
        {
            var classification = ClassifyHttpStatus(http.StatusCode, exception.Message);
            
            // Add context-aware classification for auth errors
            if (classification.Category == ErrorCategory.Authentication && context != null)
            {
                var isRecoverable = IsPotentiallyRecoverableAuthError(context);
                return classification with { 
                    IsRecoverable = isRecoverable,
                    SuggestedAction = isRecoverable 
                        ? "Check token expiration and retry" 
                        : "Verify credentials with source owner"
                };
            }
            
            return classification;
        }

        // Existing classification logic...
        if (exception is NullReferenceException)
            return new ErrorClassification(ErrorCategory.Bug, "NULL_REFERENCE", exception.Message, false);

        if (exception is ArgumentException)
            return new ErrorClassification(ErrorCategory.Bug, "ARGUMENT_ERROR", exception.Message, false);

        if (exception is TimeoutException or TaskCanceledException)
            return new ErrorClassification(ErrorCategory.Transient, "TIMEOUT", exception.Message);

        if (exception is FormatException)
            return new ErrorClassification(ErrorCategory.Permanent, "FORMAT_ERROR", exception.Message, false);

        // Unwrap custom wrapper exceptions
        if (exception.InnerException is HttpRequestException innerHttp)
            return ClassifyHttpStatus(innerHttp.StatusCode, exception.Message);

        return new ErrorClassification(ErrorCategory.Transient, "UNCLASSIFIED", exception.Message);
    }

    private static ErrorClassification ClassifyHttpStatus(HttpStatusCode? statusCode, string message)
    {
        if (!statusCode.HasValue)
            return new ErrorClassification(ErrorCategory.Transient, "HTTP_UNKNOWN", message);

        var code = (int)statusCode.Value;

        return code switch
        {
            401 => new ErrorClassification(
                ErrorCategory.Authentication, 
                "HTTP_401", 
                "Unauthorized - check credentials",
                true,
                "Verify authentication token/credentials"),
            403 => new ErrorClassification(
                ErrorCategory.Authentication, 
                "HTTP_403", 
                "Forbidden - verify access rights",
                false,
                "Check source access permissions"),
            404 => new ErrorClassification(
                ErrorCategory.Permanent, 
                "HTTP_404", 
                "Not found",
                false,
                "URL may be invalid or resource removed"),
            429 => new ErrorClassification(
                ErrorCategory.Throttled, 
                "HTTP_429", 
                "Rate limited",
                true,
                "Wait before retrying"),
            >= 500 => new ErrorClassification(
                ErrorCategory.Transient, 
                $"HTTP_{code}", 
                message,
                true,
                "Server error - will retry"),
            >= 400 => new ErrorClassification(
                ErrorCategory.Permanent, 
                $"HTTP_{code}", 
                message,
                false),
            _ => new ErrorClassification(
                ErrorCategory.Transient, 
                $"HTTP_{code}", 
                message)
        };
    }

    private static bool IsPotentiallyRecoverableAuthError(ErrorContext context)
    {
        // Auth errors are potentially recoverable if:
        // - It's the first failure for this item
        // - The error happened recently (token might just be expired)
        if (context.RetryCount == 0) return true;
        if (context.FirstFailedAt == null) return true;
        
        var timeSinceFirstFailure = DateTime.UtcNow - context.FirstFailedAt.Value;
        return timeSinceFirstFailure < TimeSpan.FromHours(1);
    }
}
```

---

## 2. Exponential Backoff with Jitter

### Current State
Simple exponential: `delay = 2^retryCount` seconds (max 60s)

### Problem
Multiple failing jobs retry at the same time, causing thundering herd.

### Solution: Decorrelated Jitter

```csharp
public static class ExponentialBackoffCalculator
{
    private static readonly ThreadLocal<Random> Random = new(() => new Random());

    /// <summary>
    /// Calculates backoff with decorrelated jitter.
    /// Formula: min(cap, random(base, retryDelay * 3))
    /// </summary>
    public static TimeSpan Calculate(
        int retryCount, 
        ErrorCategory category,
        BackoffOptions? options = null)
    {
        var opts = options ?? BackoffOptions.Default;
        
        // Category-specific base delays
        var baseDelay = category switch
        {
            ErrorCategory.Throttled => opts.ThrottledBaseDelay,
            ErrorCategory.Authentication => opts.AuthBaseDelay,
            _ => opts.BaseDelay
        };

        // Exponential component: 2^retryCount
        var exponential = Math.Pow(2, retryCount);
        var retryDelay = baseDelay * exponential;
        
        // Apply full jitter: random value between base and retryDelay * 3
        // This spreads retries across a wide window
        var min = baseDelay.TotalMilliseconds;
        var max = Math.Min(retryDelay.TotalMilliseconds * 3, opts.MaxDelay.TotalMilliseconds);
        
        var jitteredMs = min + (Random.Value!.NextDouble() * (max - min));
        
        return TimeSpan.FromMilliseconds(jitteredMs);
    }
}

public sealed class BackoffOptions
{
    public TimeSpan BaseDelay { get; init; } = TimeSpan.FromSeconds(1);
    public TimeSpan ThrottledBaseDelay { get; init; } = TimeSpan.FromMinutes(5);
    public TimeSpan AuthBaseDelay { get; init; } = TimeSpan.FromMinutes(1);
    public TimeSpan MaxDelay { get; init; } = TimeSpan.FromHours(1);

    public static BackoffOptions Default { get; } = new();
}
```

### Updated IntelligentRetryPlanner

```csharp
public static class IntelligentRetryPlanner
{
    public static RetryPlan Plan(
        ErrorClassification classification, 
        int retryCount, 
        int maxRetries,
        BackoffOptions? backoffOptions = null)
    {
        var normalizedMaxRetries = Math.Max(1, maxRetries);

        // Permanent errors and bugs go straight to DLQ
        if (classification.Category is ErrorCategory.Permanent or ErrorCategory.Bug)
            return new RetryPlan(RetryDecision.MoveToDlq, TimeSpan.Zero);

        // Non-recoverable auth errors go to DLQ
        if (classification.Category == ErrorCategory.Authentication && !classification.IsRecoverable)
            return new RetryPlan(RetryDecision.MoveToDlq, TimeSpan.Zero);

        // Max retries exhausted
        if (retryCount >= normalizedMaxRetries)
            return new RetryPlan(RetryDecision.MoveToDlq, TimeSpan.Zero);

        // Calculate jittered backoff
        var delay = ExponentialBackoffCalculator.Calculate(
            retryCount, 
            classification.Category,
            backoffOptions);

        return new RetryPlan(RetryDecision.ScheduleRetry, delay);
    }
}
```

### Retry Schedule Examples

| Retry | Transient (no jitter) | Transient (with jitter) | Throttled |
|-------|----------------------|-------------------------|-----------|
| 1     | 2s                   | 1-6s                    | 5-15min   |
| 2     | 4s                   | 1-12s                   | 5-30min   |
| 3     | 8s                   | 1-24s                   | 5-60min   |
| 4     | 16s                  | 1-48s                   | 5-60min   |
| 5     | 32s                  | 1-60s                   | 5-60min   |

---

## 3. Enhanced Dead Letter Queue

### Enhanced DLQ Entity

```csharp
public class DlqEntryEntity
{
    // Existing fields...
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    [Required]
    [MaxLength(50)]
    public string JobType { get; set; } = string.Empty;

    [MaxLength(100)]
    public string? SourceId { get; set; }

    public Guid? OriginalJobId { get; set; }

    [MaxLength(100)]
    public string? HangfireJobId { get; set; }

    [Column(TypeName = "jsonb")]
    public string? Payload { get; set; }

    [MaxLength(4000)]
    public string? ErrorMessage { get; set; }

    [MaxLength(200)]
    public string? ErrorType { get; set; }

    [Column(TypeName = "jsonb")]
    public string? StackTrace { get; set; }

    public int RetryCount { get; set; }

    public DateTime FailedAt { get; set; } = DateTime.UtcNow;

    public DateTime? ReplayedAt { get; set; }

    [MaxLength(100)]
    public string? ReplayedBy { get; set; }

    public Guid? ReplayedAsJobId { get; set; }

    [Required]
    [MaxLength(20)]
    public string Status { get; set; } = "pending";

    [MaxLength(500)]
    public string? Notes { get; set; }

    // NEW: Structured error classification
    [MaxLength(20)]
    public string ErrorCategory { get; set; } = "unknown";

    [MaxLength(50)]
    public string ErrorCode { get; set; } = string.Empty;

    // NEW: Rich error context
    [Column(TypeName = "jsonb")]
    public string? ErrorContext { get; set; }

    // NEW: Recovery metadata
    [MaxLength(500)]
    public string? SuggestedAction { get; set; }

    public bool IsRecoverable { get; set; } = true;
    public DateTime? FirstFailedAt { get; set; }
    public TimeSpan TotalRetryDuration { get; set; }

    // NEW: Grouping for bulk operations
    [MaxLength(64)]
    public string? FailureSignature { get; set; }

    public int SimilarFailureCount { get; set; }
}
```

### Structured Error Context

```csharp
/// <summary>
/// Structured error context for debugging fetch failures
/// </summary>
public record FetchErrorContext
{
    public string? Url { get; init; }
    public int? HttpStatusCode { get; init; }
    public string? HttpMethod { get; init; }
    public Dictionary<string, string>? RequestHeaders { get; init; }
    public string? ResponseBodySnippet { get; init; }
    public string? ResponseContentType { get; init; }
    public long? ResponseContentLength { get; init; }
    public TimeSpan? RequestDuration { get; init; }
    public string? UserAgent { get; init; }
    public DateTime? FirstFailedAt { get; init; }
    public TimeSpan? TotalRetryDuration { get; init; }
    public List<RetryAttempt>? RetryHistory { get; init; }
}

public record RetryAttempt
{
    public int AttemptNumber { get; init; }
    public DateTime AttemptedAt { get; init; }
    public TimeSpan DelayBefore { get; init; }
    public string? ErrorMessage { get; init; }
    public string? ErrorCode { get; init; }
}
```

---

## 4. Per-Item Retry State Tracking

Currently, retries are tracked at the job level. We need per-fetch-item retry tracking:

```csharp
public class FetchItemEntity
{
    // Existing fields...
    public Guid Id { get; set; }
    public string Url { get; set; } = string.Empty;
    public string Status { get; set; } = "pending";
    public string? LastError { get; set; }
    public Guid? FetchRunId { get; set; }
    public DateTime? CompletedAt { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime? UpdatedAt { get; set; }

    // NEW: Detailed retry tracking
    public int RetryCount { get; set; }
    public DateTime? FirstFailedAt { get; set; }
    public DateTime? LastFailedAt { get; set; }

    [Column(TypeName = "jsonb")]
    public string? RetryHistory { get; set; }

    // NEW: Error classification cache
    [MaxLength(20)]
    public string? LastErrorCategory { get; set; }

    [MaxLength(50)]
    public string? LastErrorCode { get; set; }

    // NEW: Circuit breaker pattern
    public int ConsecutiveFailures { get; set; }
    public DateTime? CircuitBrokenUntil { get; set; }
}
```

---

## 5. Circuit Breaker Pattern

Prevent hammering failing sources:

```csharp
public interface ICircuitBreaker
{
    bool IsOpen(string sourceId, string? url = null);
    void RecordSuccess(string sourceId, string? url = null);
    void RecordFailure(string sourceId, string? url = null);
}

public class FetchCircuitBreaker : ICircuitBreaker
{
    private readonly int _failureThreshold;
    private readonly TimeSpan _breakDuration;
    private readonly ILogger<FetchCircuitBreaker> _logger;

    // In-memory state - consider Redis for distributed workers
    private readonly ConcurrentDictionary<string, CircuitState> _states = new();

    public FetchCircuitBreaker(
        int failureThreshold = 5, 
        TimeSpan? breakDuration = null,
        ILogger<FetchCircuitBreaker>? logger = null)
    {
        _failureThreshold = failureThreshold;
        _breakDuration = breakDuration ?? TimeSpan.FromMinutes(5);
        _logger = logger ?? NullLogger<FetchCircuitBreaker>.Instance;
    }

    public bool IsOpen(string sourceId, string? url = null)
    {
        var key = BuildKey(sourceId, url);
        
        if (!_states.TryGetValue(key, out var state))
            return false;

        if (DateTime.UtcNow >= state.OpenUntil)
        {
            // Auto-reset circuit
            _states.TryRemove(key, out _);
            _logger.LogInformation("Circuit breaker auto-reset for {Key}", key);
            return false;
        }

        return true;
    }

    public void RecordFailure(string sourceId, string? url = null)
    {
        var key = BuildKey(sourceId, url);
        
        var state = _states.AddOrUpdate(key,
            _ => new CircuitState { FailureCount = 1 },
            (_, existing) => existing with { FailureCount = existing.FailureCount + 1 });

        if (state.FailureCount >= _failureThreshold)
        {
            var newState = state with 
            { 
                IsOpen = true, 
                OpenUntil = DateTime.UtcNow.Add(_breakDuration) 
            };
            _states[key] = newState;
            
            _logger.LogWarning(
                "Circuit breaker OPEN for {Key} after {Count} failures. Open until {OpenUntil}",
                key, state.FailureCount, newState.OpenUntil);
        }
    }

    public void RecordSuccess(string sourceId, string? url = null)
    {
        var key = BuildKey(sourceId, url);
        _states.TryRemove(key, out _);
    }

    private static string BuildKey(string sourceId, string? url)
    {
        return url != null ? $"{sourceId}:{url.GetHashCode()}" : sourceId;
    }

    private record CircuitState
    {
        public int FailureCount { get; init; }
        public bool IsOpen { get; init; }
        public DateTime OpenUntil { get; init; }
    }
}
```

---

## 6. Enhanced DLQ Service

```csharp
public interface IEnhancedDlqService : IDlqService
{
    // New query operations
    Task<DlqFailurePatternsResponse> GetFailurePatternsAsync(CancellationToken ct = default);
    Task<DlqHealthReport> GetHealthReportAsync(CancellationToken ct = default);
    
    // Bulk operations
    Task<DlqBulkReplayResponse> ReplayByPatternAsync(string failureSignature, string? notes, CancellationToken ct = default);
    Task<DlqBulkArchiveResponse> ArchiveByPatternAsync(string failureSignature, string reason, CancellationToken ct = default);
    
    // Analysis
    Task<List<DlqAlert>> GetActiveAlertsAsync(CancellationToken ct = default);
}

public record DlqFailurePatternsResponse
{
    public IReadOnlyList<FailurePattern> Patterns { get; init; } = Array.Empty<FailurePattern>();
}

public record FailurePattern
{
    public string Signature { get; init; } = string.Empty;
    public string ErrorCategory { get; init; } = string.Empty;
    public string ErrorCode { get; init; } = string.Empty;
    public int Count { get; init; }
    public DateTime FirstSeen { get; init; }
    public DateTime LastSeen { get; init; }
    public bool IsRecoverable { get; init; }
    public string? SuggestedAction { get; init; }
}

public record DlqHealthReport
{
    public int TotalPending { get; init; }
    public int AuthFailures { get; init; }
    public int NewInLastHour { get; init; }
    public IReadOnlyList<DlqAlert> ActiveAlerts { get; init; } = Array.Empty<DlqAlert>();
    public Dictionary<string, int> Trends { get; init; } = new();
}

public record DlqAlert
{
    public string Severity { get; init; } = "warning";
    public string Message { get; init; } = string.Empty;
    public string? Category { get; init; }
    public int AffectedEntries { get; init; }
    public string? SuggestedAction { get; init; }
}

public record DlqBulkReplayResponse(int ReplayCount, string Message);
public record DlqBulkArchiveResponse(int ArchiveCount, string Message);
```

---

## 7. Implementation: Updated DlqFilter

```csharp
public class DlqFilter : JobFilterAttribute, IElectStateFilter
{
    private readonly IServiceProvider _serviceProvider;
    private readonly ILogger<DlqFilter> _logger;
    private readonly int _maxRetries;

    public DlqFilter(
        IServiceProvider serviceProvider,
        ILogger<DlqFilter> logger,
        IOptions<HangfireRetryPolicyOptions> retryOptions)
    {
        _serviceProvider = serviceProvider;
        _logger = logger;
        _maxRetries = retryOptions.Value.Normalize().Attempts;
    }

    public void OnStateElection(ElectStateContext context)
    {
        if (context.CandidateState is not FailedState failedState)
            return;

        var jobId = context.BackgroundJob?.Id;
        if (string.IsNullOrEmpty(jobId))
            return;

        var retryCount = GetRetryCount(context, jobId);
        var observedAttempts = DlqRetryDecision.ToObservedAttempts(retryCount);
        
        // Build error context for better classification
        var errorContext = BuildErrorContext(failedState.Exception, context);
        var classification = ErrorClassifier.Classify(failedState.Exception, errorContext);
        
        var plan = IntelligentRetryPlanner.Plan(classification, retryCount, _maxRetries);

        _logger.LogWarning(
            "Retry classification for job {JobId}: Category={Category}, Code={Code}, IsRecoverable={IsRecoverable}, RetryCount={RetryCount}, MaxRetries={MaxRetries}",
            jobId,
            classification.Category,
            classification.Code,
            classification.IsRecoverable,
            retryCount,
            _maxRetries);

        if (plan.Decision == RetryDecision.ScheduleRetry)
        {
            _logger.LogDebug(
                "Job {JobId} failed (attempt {RetryCount}/{MaxRetries}), scheduling retry in {Delay}. Action: {Action}",
                jobId, observedAttempts, _maxRetries, plan.Delay, classification.SuggestedAction);

            context.SetJobParameter("RetryCount", retryCount + 1);
            context.CandidateState = new ScheduledState(plan.Delay)
            {
                Reason = $"Retry ({classification.Category}/{classification.Code}) in {plan.Delay}"
            };
            return;
        }

        _logger.LogWarning(
            "Job {JobId} failed after retryCount={RetryCount} (attempt {Attempt}), moving to Dead Letter Queue. Category={Category}, Code={Code}, SuggestedAction={Action}",
            jobId, retryCount, observedAttempts, classification.Category, classification.Code, classification.SuggestedAction);

        context.SetJobParameter("RetryCount", Math.Max(retryCount, _maxRetries));
        context.CandidateState = new FailedState(failedState.Exception)
        {
            Reason = $"{classification.Category} ({classification.Code})"
        };

        try
        {
            MoveToDlq(context, failedState, retryCount, classification, errorContext);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to move job {JobId} to DLQ", jobId);
        }
    }

    private static ErrorContext? BuildErrorContext(Exception exception, ElectStateContext context)
    {
        // Extract context from exception if it's our custom exception type
        if (exception is FetchException fetchEx)
        {
            return fetchEx.Context;
        }

        return null;
    }

    private void MoveToDlq(
        ElectStateContext context,
        FailedState failedState,
        int retryCount,
        ErrorClassification classification,
        ErrorContext? errorContext)
    {
        using var scope = _serviceProvider.CreateScope();
        var dbContext = scope.ServiceProvider.GetRequiredService<GabiDbContext>();

        var job = context.BackgroundJob?.Job;
        var jobId = context.BackgroundJob?.Id ?? "";

        var extracted = DlqJobContextExtractor.Extract(job?.Args);
        var failureSignature = ComputeFailureSignature(classification, errorContext);

        var dlqEntry = new DlqEntryEntity
        {
            Id = Guid.NewGuid(),
            JobType = job?.Method?.Name ?? "unknown",
            SourceId = extracted.SourceId,
            OriginalJobId = extracted.OriginalJobId,
            HangfireJobId = jobId,
            Payload = extracted.Payload,
            
            // Error details
            ErrorMessage = failedState.Exception?.Message?.Truncate(4000),
            ErrorType = failedState.Exception?.GetType().Name,
            StackTrace = DlqJsonSerializer.SerializeStackTrace(failedState.Exception?.StackTrace),
            
            // Classification
            ErrorCategory = classification.Category.ToString().ToLowerInvariant(),
            ErrorCode = classification.Code,
            ErrorContext = SerializeErrorContext(errorContext),
            
            // Recovery metadata
            SuggestedAction = classification.SuggestedAction?.Truncate(500),
            IsRecoverable = classification.IsRecoverable,
            FirstFailedAt = errorContext?.FirstFailedAt ?? DateTime.UtcNow,
            TotalRetryDuration = errorContext?.TotalRetryDuration ?? TimeSpan.Zero,
            
            // Grouping
            FailureSignature = failureSignature,
            SimilarFailureCount = 0, // Will be updated
            
            RetryCount = retryCount,
            FailedAt = DateTime.UtcNow,
            Status = "pending"
        };

        // Update similar failure count
        UpdateSimilarFailureCount(dbContext, failureSignature);

        dbContext.DlqEntries.Add(dlqEntry);
        dbContext.SaveChanges();

        _logger.LogInformation(
            "Job {JobId} moved to DLQ as {DlqId}. JobType={JobType}, SourceId={SourceId}, Category={Category}, Signature={Signature}",
            jobId, dlqEntry.Id, dlqEntry.JobType, dlqEntry.SourceId, classification.Category, failureSignature);
    }

    private static string ComputeFailureSignature(ErrorClassification classification, ErrorContext? context)
    {
        // Create a hash of error pattern for grouping similar failures
        var signature = $"{classification.Category}:{classification.Code}:{context?.Url?.GetHashCode()}";
        using var sha = SHA256.Create();
        var hash = sha.ComputeHash(Encoding.UTF8.GetBytes(signature));
        return Convert.ToHexString(hash)[..16].ToLowerInvariant();
    }

    private static void UpdateSimilarFailureCount(GabiDbContext dbContext, string? failureSignature)
    {
        if (string.IsNullOrEmpty(failureSignature))
            return;

        // Update count for all entries with this signature
        var entries = dbContext.DlqEntries
            .Where(e => e.FailureSignature == failureSignature)
            .ToList();

        var count = entries.Count + 1; // +1 for the new entry
        foreach (var entry in entries)
        {
            entry.SimilarFailureCount = count;
        }
    }

    private static string? SerializeErrorContext(ErrorContext? context)
    {
        if (context == null)
            return null;

        try
        {
            return JsonSerializer.Serialize(context, new JsonSerializerOptions
            {
                PropertyNamingPolicy = JsonNamingPolicy.CamelCase
            });
        }
        catch
        {
            return null;
        }
    }

    private static int GetRetryCount(ElectStateContext context, string jobId)
    {
        try
        {
            var fromParameter = context.GetJobParameter<int>("RetryCount");
            if (fromParameter >= 0)
                return fromParameter;

            var monitoring = JobStorage.Current.GetMonitoringApi();
            var details = monitoring.JobDetails(jobId);
            var failedHistoryCount = details?.History?.Count(h => h.StateName == "Failed") ?? 0;
            return Math.Max(0, failedHistoryCount - 1);
        }
        catch
        {
            return 0;
        }
    }
}
```

---

## 8. Observability & Metrics

### Metrics to Track

```csharp
public static class FetchErrorMetrics
{
    private static readonly Meter Meter = new("Gabi.Fetch");

    // Counters
    public static readonly Counter<long> FetchAttempts = 
        Meter.CreateCounter<long>("fetch.attempts_total", description: "Total fetch attempts");
    
    public static readonly Counter<long> FetchFailures = 
        Meter.CreateCounter<long>("fetch.failures_total", description: "Total fetch failures");
    
    public static readonly Counter<long> FetchRetries = 
        Meter.CreateCounter<long>("fetch.retries_total", description: "Total fetch retries");
    
    public static readonly Counter<long> FetchDlqAdditions = 
        Meter.CreateCounter<long>("fetch.dlq.additions_total", description: "Items moved to DLQ");
    
    public static readonly Counter<long> FetchDlqReplays = 
        Meter.CreateCounter<long>("fetch.dlq.replays_total", description: "DLQ items replayed");
    
    public static readonly Counter<long> CircuitBreakerOpen = 
        Meter.CreateCounter<long>("fetch.circuit_breaker.open_total", description: "Circuit breaker opened");

    // Histograms
    public static readonly Histogram<double> FetchRetryDelay = 
        Meter.CreateHistogram<double>("fetch.retry.delay_seconds", description: "Retry delay duration");
    
    public static readonly Histogram<int> FetchRetryCount = 
        Meter.CreateHistogram<int>("fetch.retry.count", description: "Number of retries before success/failure");

    // UpDownCounters
    public static readonly UpDownCounter<int> FetchDlqPending = 
        Meter.CreateUpDownCounter<int>("fetch.dlq.pending", description: "Current pending DLQ items");

    public static void RecordFailure(ErrorCategory category, string sourceId)
    {
        FetchFailures.Add(1, 
            new KeyValuePair<string, object?>("category", category.ToString()),
            new KeyValuePair<string, object?>("source_id", sourceId));
    }

    public static void RecordDlqAddition(ErrorClassification classification)
    {
        FetchDlqAdditions.Add(1,
            new KeyValuePair<string, object?>("category", classification.Category.ToString()),
            new KeyValuePair<string, object?>("code", classification.Code),
            new KeyValuePair<string, object?>("recoverable", classification.IsRecoverable));
        
        FetchDlqPending.Up(1);
    }
}
```

### Alert Rules (Prometheus-style)

```yaml
groups:
  - name: fetch_errors
    rules:
      - alert: HighFetchFailureRate
        expr: rate(fetch.failures_total[5m]) / rate(fetch.attempts_total[5m]) > 0.1
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "High fetch failure rate"
          description: "Fetch failure rate is above 10% for more than 2 minutes"

      - alert: AuthFailuresSpike
        expr: increase(fetch.failures_total{category="Authentication"}[1h]) > 5
        labels:
          severity: critical
        annotations:
          summary: "Authentication failures detected"
          description: "Multiple authentication failures - check credentials"

      - alert: DLQGrowing
        expr: fetch.dlq.pending > 100
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "DLQ has many pending items"
          description: "{{ $value }} items in DLQ awaiting manual intervention"

      - alert: CircuitBreakerTriggered
        expr: increase(fetch.circuit_breaker.open_total[5m]) > 0
        labels:
          severity: warning
        annotations:
          summary: "Circuit breaker opened"
          description: "A source is experiencing repeated failures"
```

---

## 9. Implementation Roadmap

### Phase 1: Enhanced Error Classification (Week 1)
- [ ] Add `Authentication` category to `ErrorCategory`
- [ ] Update `ErrorClassifier` for 401/403 detection with context
- [ ] Add `IsRecoverable` and `SuggestedAction` to classification

### Phase 2: Backoff with Jitter (Week 1)
- [ ] Implement `ExponentialBackoffCalculator`
- [ ] Update `IntelligentRetryPlanner`
- [ ] Add `BackoffOptions` configuration

### Phase 3: Enhanced DLQ Schema (Week 2)
- [ ] Add new columns to `DlqEntryEntity`
- [ ] Create EF Core migration
- [ ] Update `DlqFilter` to populate new fields

### Phase 4: Per-Item Tracking (Week 2)
- [ ] Add retry fields to `FetchItemEntity`
- [ ] Update `FetchJobExecutor` to track per-item retries
- [ ] Implement circuit breaker logic

### Phase 5: Enhanced DLQ Service (Week 3)
- [ ] Extend `DlqService` with new operations
- [ ] Implement failure pattern analysis
- [ ] Add health report generation

### Phase 6: Observability (Week 3)
- [ ] Add metrics instrumentation
- [ ] Create Grafana dashboards
- [ ] Configure alert rules

---

## 10. Testing Strategy

### Unit Tests

```csharp
public class ExponentialBackoffCalculatorTests
{
    [Theory]
    [InlineData(0, ErrorCategory.Transient, 1000, 3000)]
    [InlineData(3, ErrorCategory.Transient, 1000, 24000)]
    [InlineData(0, ErrorCategory.Throttled, 300000, 900000)]
    public void Calculate_ShouldStayWithinBounds(
        int retryCount, ErrorCategory category, 
        int minExpectedMs, int maxExpectedMs)
    {
        var delay = ExponentialBackoffCalculator.Calculate(retryCount, category);
        Assert.InRange(delay.TotalMilliseconds, minExpectedMs, maxExpectedMs);
    }

    [Fact]
    public void Calculate_ShouldApplyJitter()
    {
        var delays = Enumerable.Range(0, 100)
            .Select(_ => ExponentialBackoffCalculator.Calculate(2, ErrorCategory.Transient))
            .Distinct()
            .Count();
        
        Assert.True(delays > 50, "Jitter should produce varied delays");
    }
}

public class ErrorClassifierTests
{
    [Theory]
    [InlineData(401, ErrorCategory.Authentication, true)]
    [InlineData(403, ErrorCategory.Authentication, false)]
    [InlineData(404, ErrorCategory.Permanent, false)]
    [InlineData(429, ErrorCategory.Throttled, true)]
    [InlineData(500, ErrorCategory.Transient, true)]
    public void ClassifyHttpStatus_ShouldReturnExpectedCategory(
        int statusCode, ErrorCategory expectedCategory, bool expectedRecoverable)
    {
        var ex = new HttpRequestException("test", null, (HttpStatusCode)statusCode);
        var result = ErrorClassifier.Classify(ex);
        
        Assert.Equal(expectedCategory, result.Category);
        Assert.Equal(expectedRecoverable, result.IsRecoverable);
    }
}
```

### Integration Tests

```csharp
public class DlqIntegrationTests : IClassFixture<DatabaseFixture>
{
    [Fact]
    public async Task FailedJob_WithMaxRetries_ShouldMoveToDlqWithContext()
    {
        // Arrange
        var job = CreateFailingJob();
        
        // Act
        for (int i = 0; i < MaxRetries; i++)
        {
            await _runner.RunAsync(job.Id, job.JobType, job.SourceId, "{}");
        }
        
        // Assert
        var dlqEntry = await _dbContext.DlqEntries
            .FirstOrDefaultAsync(e => e.OriginalJobId == job.Id);
        
        Assert.NotNull(dlqEntry);
        Assert.Equal("fetch", dlqEntry.JobType);
        Assert.Equal(ErrorCategory.Transient.ToString().ToLowerInvariant(), dlqEntry.ErrorCategory);
        Assert.NotNull(dlqEntry.ErrorContext);
        Assert.NotNull(dlqEntry.FailureSignature);
    }

    [Fact]
    public async Task ReplayByPattern_ShouldReplayMatchingEntries()
    {
        // Arrange: Create multiple entries with same pattern
        var signature = "abc123";
        await CreateDlqEntriesAsync(signature, count: 5);
        
        // Act
        var result = await _dlqService.ReplayByPatternAsync(signature, "bulk replay test");
        
        // Assert
        Assert.Equal(5, result.ReplayCount);
        
        var replayed = await _dbContext.DlqEntries
            .Where(e => e.FailureSignature == signature && e.Status == "replayed")
            .CountAsync();
        Assert.Equal(5, replayed);
    }
}
```

---

## Summary

This improved error handling strategy provides:

| Aspect | Before | After |
|--------|--------|-------|
| **Classification** | 4 categories | 5 categories (added Auth) |
| **Backoff** | Fixed exponential | Exponential + jitter |
| **DLQ Context** | Basic message | Rich structured context |
| **Per-Item Tracking** | None | Retry history, circuit breaker |
| **Bulk Operations** | Single replay | Pattern-based bulk replay |
| **Observability** | Limited | Full metrics + alerts |

The key principle: **Make failures observable and recoverable**, never silent.
