# GABI - Resiliency Patterns Design

> **Status:** Design Document  
> **Target:** Gabi.Sync, Gabi.Worker, Gabi.Ingest  
> **Environment:** Fly.io, 1GB RAM, No Disk  

---

## 1. Executive Summary

This document defines comprehensive resiliency patterns for the GABI pipeline to handle:

| Challenge | Impact | Pattern |
|-----------|--------|---------|
| Network failures | Downloads fail | Retry + Circuit Breaker |
| API rate limiting (429) | Throttling | Exponential backoff + Jitter |
| Database drops | Data loss | Retry + Connection pooling |
| Out of memory (1GB) | Process crash | Backpressure + Graceful degradation |
| Partial failures | Incomplete sync | Dead Letter Queue (DLQ) |

**Design Principles:**
- Fail fast, retry smart
- Isolate failures (bulkhead)
- Never lose data (DLQ)
- Self-healing where possible
- Observable at all times

---

## 2. Circuit Breaker Pattern

### 2.1 Overview

Prevents cascade failures by temporarily rejecting operations when a service is unhealthy.

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   CLOSED    │────▶│    OPEN     │────▶│  HALF_OPEN  │
│  (normal)   │     │  (failing)  │     │  (testing)  │
└─────────────┘     └─────────────┘     └─────────────┘
       ▲                                      │
       └──────────────────────────────────────┘
              (success threshold met)
```

### 2.2 Implementation

```csharp
namespace Gabi.Sync.Resiliency;

/// <summary>
/// Circuit breaker states.
/// </summary>
public enum CircuitState
{
    Closed,     // Normal operation
    Open,       // Failing, reject requests
    HalfOpen    // Testing if recovered
}

/// <summary>
/// Circuit breaker for external service calls.
/// Thread-safe for concurrent access.
/// </summary>
public interface ICircuitBreaker
{
    string Name { get; }
    CircuitState State { get; }
    
    /// <summary>
    /// Execute action with circuit breaker protection.
    /// Throws CircuitOpenException if circuit is open.
    /// </summary>
    Task<T> ExecuteAsync<T>(Func<CancellationToken, Task<T>> action, CancellationToken ct = default);
    
    /// <summary>
    /// Current metrics.
    /// </summary>
    CircuitMetrics GetMetrics();
}

/// <summary>
/// Configuration for circuit breaker.
/// </summary>
public record CircuitBreakerConfig
{
    /// <summary>
    /// Failure threshold to open circuit (count).
    /// </summary>
    public int FailureThreshold { get; init; } = 5;
    
    /// <summary>
    /// Time window for counting failures.
    /// </summary>
    public TimeSpan SamplingWindow { get; init; } = TimeSpan.FromMinutes(1);
    
    /// <summary>
    /// Duration to stay open before half-open.
    /// </summary>
    public TimeSpan OpenDuration { get; init; } = TimeSpan.FromSeconds(30);
    
    /// <summary>
    /// Success threshold to close from half-open.
    /// </summary>
    public int SuccessThreshold { get; init; } = 3;
    
    /// <summary>
    /// Exceptions that should NOT count as failures (e.g., 404).
    /// </summary>
    public HashSet<Type> IgnoredExceptions { get; init; } = new();
}

/// <summary>
/// Metrics for circuit breaker.
/// </summary>
public record CircuitMetrics
{
    public CircuitState State { get; init; }
    public int ConsecutiveFailures { get; init; }
    public int ConsecutiveSuccesses { get; init; }
    public DateTime? LastFailureAt { get; init; }
    public DateTime? LastSuccessAt { get; init; }
    public long TotalSuccesses { get; init; }
    public long TotalFailures { get; init; }
    public long RejectedCount { get; init; }
}

/// <summary>
/// Exception thrown when circuit is open.
/// </summary>
public class CircuitOpenException : Exception
{
    public string CircuitName { get; }
    public TimeSpan RetryAfter { get; }
    
    public CircuitOpenException(string circuitName, TimeSpan retryAfter) 
        : base($"Circuit '{circuitName}' is open. Retry after {retryAfter.TotalSeconds}s")
    {
        CircuitName = circuitName;
        RetryAfter = retryAfter;
    }
}
```

### 2.3 Circuit Breaker Registry

```csharp
/// <summary>
/// Factory and registry for circuit breakers.
/// Creates one CB per external service (bulkhead isolation).
/// </summary>
public interface ICircuitBreakerRegistry
{
    /// <summary>
    /// Get or create circuit breaker for a service.
    /// </summary>
    ICircuitBreaker GetOrCreate(string serviceName, CircuitBreakerConfig? config = null);
    
    /// <summary>
    /// Get all registered circuit breakers.
    /// </summary>
    IReadOnlyDictionary<string, ICircuitBreaker> GetAll();
    
    /// <summary>
    /// Force open a circuit (for maintenance).
    /// </summary>
    void ForceOpen(string serviceName);
    
    /// <summary>
    /// Force close a circuit (after recovery).
    /// </summary>
    void ForceClose(string serviceName);
}

/// <summary>
/// Pre-defined circuit breakers for GABI services.
/// </summary>
public static class CircuitBreakers
{
    // External APIs
    public const string TcuHttp = "tcu_http";
    public const string CamaraApi = "camara_api";
    public const string StfApi = "stf_api";
    public const string StjApi = "stj_api";
    
    // Internal services
    public const string PostgreSQL = "postgresql";
    public const string Elasticsearch = "elasticsearch";
    public const string TeiEmbedding = "tei_embedding";
    public const string Redis = "redis";
    
    // Default configurations per service type
    public static CircuitBreakerConfig HttpConfig => new()
    {
        FailureThreshold = 5,
        SamplingWindow = TimeSpan.FromMinutes(1),
        OpenDuration = TimeSpan.FromSeconds(30),
        SuccessThreshold = 3,
        IgnoredExceptions = { typeof(NotFoundException) }
    };
    
    public static CircuitBreakerConfig DatabaseConfig => new()
    {
        FailureThreshold = 3,        // More sensitive
        SamplingWindow = TimeSpan.FromSeconds(30),
        OpenDuration = TimeSpan.FromSeconds(10), // Faster recovery
        SuccessThreshold = 2
    };
    
    public static CircuitBreakerConfig EmbeddingConfig => new()
    {
        FailureThreshold = 10,       // Embedding service can be slow
        SamplingWindow = TimeSpan.FromMinutes(2),
        OpenDuration = TimeSpan.FromSeconds(60),
        SuccessThreshold = 5
    };
}
```

### 2.4 Usage Examples

```csharp
public class ContentFetcher
{
    private readonly ICircuitBreaker _circuitBreaker;
    private readonly HttpClient _httpClient;
    
    public ContentFetcher(ICircuitBreakerRegistry cbRegistry, HttpClient httpClient)
    {
        _circuitBreaker = cbRegistry.GetOrCreate(CircuitBreakers.TcuHttp, CircuitBreakers.HttpConfig);
        _httpClient = httpClient;
    }
    
    public async Task<Stream> FetchAsync(string url, CancellationToken ct = default)
    {
        return await _circuitBreaker.ExecuteAsync(async token =>
        {
            var response = await _httpClient.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, token);
            response.EnsureSuccessStatusCode();
            return await response.Content.ReadAsStreamAsync(token);
        }, ct);
    }
}

public class DocumentIndexer
{
    private readonly ICircuitBreaker _circuitBreaker;
    private readonly IDocumentRepository _repository;
    
    public DocumentIndexer(ICircuitBreakerRegistry cbRegistry, IDocumentRepository repository)
    {
        _circuitBreaker = cbRegistry.GetOrCreate(CircuitBreakers.PostgreSQL, CircuitBreakers.DatabaseConfig);
        _repository = repository;
    }
    
    public async Task IndexAsync(Document document, CancellationToken ct = default)
    {
        await _circuitBreaker.ExecuteAsync(async token =>
        {
            await _repository.SaveAsync(document, token);
            return true;
        }, ct);
    }
}
```

---

## 3. Retry with Exponential Backoff + Jitter

### 3.1 Overview

Intelligent retry strategy that prevents thundering herd and respects rate limits.

### 3.2 Implementation

```csharp
namespace Gabi.Sync.Resiliency;

/// <summary>
/// Retry policy configuration.
/// </summary>
public record RetryPolicyConfig
{
    /// <summary>
    /// Maximum number of retry attempts.
    /// </summary>
    public int MaxAttempts { get; init; } = 3;
    
    /// <summary>
    /// Initial delay between retries.
    /// </summary>
    public TimeSpan InitialDelay { get; init; } = TimeSpan.FromSeconds(1);
    
    /// <summary>
    /// Maximum delay between retries.
    /// </summary>
    public TimeSpan MaxDelay { get; init; } = TimeSpan.FromSeconds(60);
    
    /// <summary>
    /// Backoff strategy.
    /// </summary>
    public BackoffStrategy Strategy { get; init; } = BackoffStrategy.Exponential;
    
    /// <summary>
    /// Jitter factor (0.0 - 1.0) to add randomness.
    /// </summary>
    public double JitterFactor { get; init; } = 0.1;
    
    /// <summary>
    /// Exceptions that should NOT be retried.
    /// </summary>
    public HashSet<Type> NonRetryableExceptions { get; init; } = new();
    
    /// <summary>
    /// HTTP status codes that should be retried.
    /// </summary>
    public HashSet<HttpStatusCode> RetryableStatusCodes { get; init; } = new()
    {
        HttpStatusCode.RequestTimeout,      // 408
        HttpStatusCode.TooManyRequests,     // 429
        HttpStatusCode.InternalServerError, // 500
        HttpStatusCode.BadGateway,          // 502
        HttpStatusCode.ServiceUnavailable,  // 503
        HttpStatusCode.GatewayTimeout       // 504
    };
}

/// <summary>
/// Backoff calculation strategies.
/// </summary>
public enum BackoffStrategy
{
    /// <summary>
    /// Fixed delay between retries.
    /// </summary>
    Fixed,
    
    /// <summary>
    /// Linear increase: delay * attempt.
    /// </summary>
    Linear,
    
    /// <summary>
    /// Exponential: delay * 2^attempt.
    /// </summary>
    Exponential,
    
    /// <summary>
    /// Decorrelated jitter (AWS recommended).
    /// </summary>
    DecorrelatedJitter
}

/// <summary>
/// Retry context for each attempt.
    /// </summary>
public record RetryContext
{
    public int AttemptNumber { get; init; }
    public int MaxAttempts { get; init; }
    public TimeSpan DelayBeforeRetry { get; init; }
    public Exception? LastException { get; init; }
    public TimeSpan TotalElapsed { get; init; }
    public bool IsLastAttempt => AttemptNumber >= MaxAttempts;
}

/// <summary>
/// Result of retry operation.
    /// </summary>
public record RetryResult<T>
{
    public bool Success { get; init; }
    public T? Value { get; init; }
    public Exception? LastException { get; init; }
    public int AttemptsMade { get; init; }
    public TimeSpan TotalDuration { get; init; }
    public IReadOnlyList<RetryAttempt> AttemptHistory { get; init; } = new List<RetryAttempt>();
}

public record RetryAttempt
{
    public int Number { get; init; }
    public TimeSpan Delay { get; init; }
    public Exception? Exception { get; init; }
    public DateTime Timestamp { get; init; }
}

/// <summary>
/// Retry executor with circuit breaker integration.
/// </summary>
public interface IRetryExecutor
{
    /// <summary>
    /// Execute with retry policy.
    /// </summary>
    Task<T> ExecuteAsync<T>(
        Func<CancellationToken, Task<T>> action,
        RetryPolicyConfig config,
        Action<RetryContext>? onRetry = null,
        CancellationToken ct = default);
    
    /// <summary>
    /// Execute with retry and circuit breaker.
    /// </summary>
    Task<T> ExecuteWithCircuitBreakerAsync<T>(
        Func<CancellationToken, Task<T>> action,
        RetryPolicyConfig retryConfig,
        ICircuitBreaker circuitBreaker,
        CancellationToken ct = default);
}

/// <summary>
/// Implements retry with various backoff strategies.
/// </summary>
public class RetryExecutor : IRetryExecutor
{
    private readonly ILogger<RetryExecutor> _logger;
    private readonly Random _random = new();
    
    public RetryExecutor(ILogger<RetryExecutor> logger)
    {
        _logger = logger;
    }
    
    public async Task<T> ExecuteAsync<T>(
        Func<CancellationToken, Task<T>> action,
        RetryPolicyConfig config,
        Action<RetryContext>? onRetry = null,
        CancellationToken ct = default)
    {
        var startTime = DateTime.UtcNow;
        var attempts = new List<RetryAttempt>();
        Exception? lastException = null;
        
        for (int attempt = 1; attempt <= config.MaxAttempts; attempt++)
        {
            try
            {
                var result = await action(ct);
                
                if (attempt > 1)
                {
                    _logger.LogInformation(
                        "Operation succeeded after {Attempts} attempts in {Duration}ms",
                        attempt,
                        (DateTime.UtcNow - startTime).TotalMilliseconds);
                }
                
                return result;
            }
            catch (Exception ex) when (ShouldRetry(ex, config, attempt))
            {
                lastException = ex;
                var delay = CalculateDelay(attempt, config);
                
                attempts.Add(new RetryAttempt
                {
                    Number = attempt,
                    Delay = delay,
                    Exception = ex,
                    Timestamp = DateTime.UtcNow
                });
                
                var context = new RetryContext
                {
                    AttemptNumber = attempt,
                    MaxAttempts = config.MaxAttempts,
                    DelayBeforeRetry = delay,
                    LastException = ex,
                    TotalElapsed = DateTime.UtcNow - startTime
                };
                
                onRetry?.Invoke(context);
                
                _logger.LogWarning(
                    ex,
                    "Attempt {Attempt}/{MaxAttempts} failed. Retrying in {Delay}ms...",
                    attempt,
                    config.MaxAttempts,
                    delay.TotalMilliseconds);
                
                if (attempt < config.MaxAttempts)
                {
                    await Task.Delay(delay, ct);
                }
            }
        }
        
        throw new RetryExhaustedException(
            $"All {config.MaxAttempts} attempts failed. Last error: {lastException?.Message}",
            lastException!,
            attempts);
    }
    
    public async Task<T> ExecuteWithCircuitBreakerAsync<T>(
        Func<CancellationToken, Task<T>> action,
        RetryPolicyConfig retryConfig,
        ICircuitBreaker circuitBreaker,
        CancellationToken ct = default)
    {
        return await circuitBreaker.ExecuteAsync(
            async token => await ExecuteAsync(action, retryConfig, null, token),
            ct);
    }
    
    private TimeSpan CalculateDelay(int attempt, RetryPolicyConfig config)
    {
        var baseDelay = config.Strategy switch
        {
            BackoffStrategy.Fixed => config.InitialDelay,
            BackoffStrategy.Linear => TimeSpan.FromTicks(config.InitialDelay.Ticks * attempt),
            BackoffStrategy.Exponential => TimeSpan.FromTicks(
                (long)(config.InitialDelay.Ticks * Math.Pow(2, attempt - 1))),
            BackoffStrategy.DecorrelatedJitter => CalculateDecorrelatedJitter(attempt, config),
            _ => config.InitialDelay
        };
        
        // Add jitter to prevent thundering herd
        if (config.JitterFactor > 0)
        {
            var jitter = baseDelay.TotalMilliseconds * config.JitterFactor * (_random.NextDouble() * 2 - 1);
            baseDelay = TimeSpan.FromMilliseconds(Math.Max(0, baseDelay.TotalMilliseconds + jitter));
        }
        
        return TimeSpan.FromMilliseconds(Math.Min(baseDelay.TotalMilliseconds, config.MaxDelay.TotalMilliseconds));
    }
    
    private TimeSpan CalculateDecorrelatedJitter(int attempt, RetryPolicyConfig config)
    {
        // AWS recommended: min(cap, random * sleep * 3^(attempt-1))
        var sleep = config.InitialDelay.TotalMilliseconds;
        var cap = config.MaxDelay.TotalMilliseconds;
        var randomFactor = _random.NextDouble();
        var delay = Math.Min(cap, randomFactor * sleep * Math.Pow(3, attempt - 1));
        return TimeSpan.FromMilliseconds(delay);
    }
    
    private bool ShouldRetry(Exception ex, RetryPolicyConfig config, int attempt)
    {
        if (attempt >= config.MaxAttempts)
            return false;
            
        // Check non-retryable exceptions
        foreach (var nonRetryable in config.NonRetryableExceptions)
        {
            if (nonRetryable.IsInstanceOfType(ex))
                return false;
        }
        
        // Check HTTP status codes
        if (ex is HttpRequestException httpEx && httpEx.StatusCode.HasValue)
        {
            return config.RetryableStatusCodes.Contains(httpEx.StatusCode.Value);
        }
        
        // Check for specific exception types
        return ex is TimeoutException 
            or IOException 
            or TaskCanceledException
            or HttpRequestException;
    }
}

/// <summary>
/// Exception thrown when all retries are exhausted.
/// </summary>
public class RetryExhaustedException : Exception
{
    public IReadOnlyList<RetryAttempt> AttemptHistory { get; }
    
    public RetryExhaustedException(string message, Exception innerException, IReadOnlyList<RetryAttempt> attempts)
        : base(message, innerException)
    {
        AttemptHistory = attempts;
    }
}
```

### 3.3 Rate Limit Handling (429)

```csharp
/// <summary>
/// Special handling for rate limit responses.
/// </summary>
public class RateLimitHandler
{
    private readonly ILogger<RateLimitHandler> _logger;
    private readonly Dictionary<string, RateLimitState> _states = new();
    
    public async Task<HttpResponseMessage> SendWithRateLimitHandlingAsync(
        HttpClient client,
        HttpRequestMessage request,
        CancellationToken ct = default)
    {
        var serviceKey = request.RequestUri?.Host ?? "unknown";
        
        // Check if we're rate limited
        if (_states.TryGetValue(serviceKey, out var state) && state.RetryAfter > DateTime.UtcNow)
        {
            var waitTime = state.RetryAfter - DateTime.UtcNow;
            _logger.LogWarning("Rate limited for {Service}. Waiting {WaitTime}s", serviceKey, waitTime.TotalSeconds);
            await Task.Delay(waitTime, ct);
        }
        
        var response = await client.SendAsync(request, ct);
        
        if (response.StatusCode == HttpStatusCode.TooManyRequests)
        {
            var retryAfter = ParseRetryAfter(response);
            _states[serviceKey] = new RateLimitState { RetryAfter = DateTime.UtcNow + retryAfter };
            
            _logger.LogWarning("Received 429. Retry-After: {RetryAfter}s", retryAfter.TotalSeconds);
            
            // Re-throw for retry logic to handle
            throw new HttpRequestException("Rate limited", null, HttpStatusCode.TooManyRequests);
        }
        
        return response;
    }
    
    private TimeSpan ParseRetryAfter(HttpResponseMessage response)
    {
        // Try Retry-After header (seconds or HTTP-date)
        if (response.Headers.TryGetValues("Retry-After", out var values))
        {
            var value = values.FirstOrDefault();
            if (int.TryParse(value, out var seconds))
            {
                return TimeSpan.FromSeconds(seconds);
            }
            if (DateTime.TryParse(value, out var date))
            {
                return date - DateTime.UtcNow;
            }
        }
        
        // X-RateLimit-Reset (Unix timestamp)
        if (response.Headers.TryGetValues("X-RateLimit-Reset", out var resetValues))
        {
            if (long.TryParse(resetValues.FirstOrDefault(), out var unixTime))
            {
                var resetTime = DateTimeOffset.FromUnixTimeSeconds(unixTime);
                return resetTime - DateTimeOffset.UtcNow;
            }
        }
        
        // Default fallback
        return TimeSpan.FromSeconds(60);
    }
    
    private class RateLimitState
    {
        public DateTime RetryAfter { get; set; }
    }
}
```

### 3.4 Pre-configured Retry Policies

```csharp
/// <summary>
/// Pre-configured retry policies for different scenarios.
/// </summary>
public static class RetryPolicies
{
    /// <summary>
    /// For TCU HTTP downloads (reliable source).
    /// </summary>
    public static RetryPolicyConfig HttpDownload => new()
    {
        MaxAttempts = 3,
        InitialDelay = TimeSpan.FromSeconds(2),
        MaxDelay = TimeSpan.FromSeconds(30),
        Strategy = BackoffStrategy.Exponential,
        JitterFactor = 0.1,
        RetryableStatusCodes = { HttpStatusCode.RequestTimeout, HttpStatusCode.BadGateway, 
                                  HttpStatusCode.ServiceUnavailable, HttpStatusCode.GatewayTimeout }
    };
    
    /// <summary>
    /// For external APIs with rate limiting.
    /// </summary>
    public static RetryPolicyConfig ExternalApi => new()
    {
        MaxAttempts = 5,
        InitialDelay = TimeSpan.FromSeconds(1),
        MaxDelay = TimeSpan.FromSeconds(60),
        Strategy = BackoffStrategy.DecorrelatedJitter,
        JitterFactor = 0.2,
        RetryableStatusCodes = { HttpStatusCode.TooManyRequests, HttpStatusCode.RequestTimeout,
                                  HttpStatusCode.BadGateway, HttpStatusCode.ServiceUnavailable }
    };
    
    /// <summary>
    /// For database operations (fast retry).
    /// </summary>
    public static RetryPolicyConfig Database => new()
    {
        MaxAttempts = 3,
        InitialDelay = TimeSpan.FromMilliseconds(100),
        MaxDelay = TimeSpan.FromSeconds(5),
        Strategy = BackoffStrategy.Linear,
        JitterFactor = 0.05,
        NonRetryableExceptions = { typeof(ArgumentException), typeof(InvalidOperationException) }
    };
    
    /// <summary>
    /// For embedding service (TEI) - more patience.
    /// </summary>
    public static RetryPolicyConfig Embedding => new()
    {
        MaxAttempts = 5,
        InitialDelay = TimeSpan.FromSeconds(2),
        MaxDelay = TimeSpan.FromSeconds(120),
        Strategy = BackoffStrategy.Exponential,
        JitterFactor = 0.15
    };
    
    /// <summary>
    /// For Elasticsearch bulk operations.
    /// </summary>
    public static RetryPolicyConfig Elasticsearch => new()
    {
        MaxAttempts = 3,
        InitialDelay = TimeSpan.FromMilliseconds(500),
        MaxDelay = TimeSpan.FromSeconds(10),
        Strategy = BackoffStrategy.Linear,
        JitterFactor = 0.1
    };
}
```

---

## 4. Bulkhead Isolation

### 4.1 Overview

Isolates failures by limiting resources per source/service, preventing one failure from affecting others.

```
┌─────────────────────────────────────────────────────────┐
│                    BULKHEAD POOL                         │
├─────────────┬─────────────┬─────────────┬───────────────┤
│  TCU Source │Camara Source│  PDF Parser │  TEI Embedder │
│  Max: 3     │  Max: 2     │  Max: 2     │  Max: 4       │
│  Used: 1    │  Used: 0    │  Used: 0    │  Used: 0      │
├─────────────┴─────────────┴─────────────┴───────────────┤
│  WAITING QUEUE (max 100 per source)                     │
│  [tcu_2024.csv, tcu_2023.csv, ...]                      │
└─────────────────────────────────────────────────────────┘
```

### 4.2 Implementation

```csharp
namespace Gabi.Sync.Resiliency;

/// <summary>
/// Bulkhead isolation for resource management.
/// Limits concurrent operations per source/service.
/// </summary>
public interface IBulkhead
{
    string Name { get; }
    int MaxConcurrent { get; }
    int AvailableSlots { get; }
    int WaitingCount { get; }
    
    /// <summary>
    /// Execute with bulkhead isolation.
    /// Blocks if no slots available (up to timeout).
    /// </summary>
    Task<T> ExecuteAsync<T>(Func<CancellationToken, Task<T>> action, CancellationToken ct = default);
    
    /// <summary>
    /// Try to execute immediately without waiting.
    /// </summary>
    Task<(bool Success, T? Result)> TryExecuteAsync<T>(Func<CancellationToken, Task<T>> action, CancellationToken ct = default);
    
    /// <summary>
    /// Current metrics.
    /// </summary>
    BulkheadMetrics GetMetrics();
}

/// <summary>
/// Bulkhead configuration.
/// </summary>
public record BulkheadConfig
{
    /// <summary>
    /// Maximum concurrent operations.
    /// </summary>
    public int MaxConcurrent { get; init; } = 3;
    
    /// <summary>
    /// Maximum waiting queue size.
    /// </summary>
    public int MaxQueueSize { get; init; } = 100;
    
    /// <summary>
    /// Timeout to wait for slot.
    /// </summary>
    public TimeSpan WaitTimeout { get; init; } = TimeSpan.FromMinutes(5);
}

/// <summary>
/// Bulkhead metrics.
/// </summary>
public record BulkheadMetrics
{
    public string Name { get; init; } = string.Empty;
    public int MaxConcurrent { get; init; }
    public int AvailableSlots { get; init; }
    public int ActiveOperations { get; init; }
    public int WaitingCount { get; init; }
    public int MaxQueueSize { get; init; }
    public long TotalExecuted { get; init; }
    public long TotalRejected { get; init; }
    public long TotalTimedOut { get; init; }
    public TimeSpan AverageWaitTime { get; init; }
}

/// <summary>
/// Factory and registry for bulkheads.
/// </summary>
public interface IBulkheadRegistry
{
    /// <summary>
    /// Get or create bulkhead for a source.
    /// </summary>
    IBulkhead GetOrCreate(string sourceId, BulkheadConfig? config = null);
    
    /// <summary>
    /// Get all bulkheads.
    /// </summary>
    IReadOnlyDictionary<string, IBulkhead> GetAll();
}

/// <summary>
/// Implementation using SemaphoreSlim.
/// </summary>
public class Bulkhead : IBulkhead
{
    private readonly SemaphoreSlim _semaphore;
    private readonly SemaphoreSlim _queueSemaphore;
    private readonly ILogger<Bulkhead> _logger;
    private long _totalExecuted;
    private long _totalRejected;
    private long _totalTimedOut;
    
    public string Name { get; }
    public int MaxConcurrent { get; }
    public int MaxQueueSize { get; }
    
    public int AvailableSlots => _semaphore.CurrentCount;
    public int WaitingCount => MaxQueueSize - _queueSemaphore.CurrentCount;
    
    public Bulkhead(string name, BulkheadConfig config, ILogger<Bulkhead> logger)
    {
        Name = name;
        MaxConcurrent = config.MaxConcurrent;
        MaxQueueSize = config.MaxQueueSize;
        _logger = logger;
        _semaphore = new SemaphoreSlim(config.MaxConcurrent, config.MaxConcurrent);
        _queueSemaphore = new SemaphoreSlim(config.MaxQueueSize, config.MaxQueueSize);
    }
    
    public async Task<T> ExecuteAsync<T>(Func<CancellationToken, Task<T>> action, CancellationToken ct = default)
    {
        // First, acquire queue slot
        if (!await _queueSemaphore.WaitAsync(TimeSpan.FromSeconds(1), ct))
        {
            Interlocked.Increment(ref _totalRejected);
            throw new BulkheadRejectedException($"Bulkhead '{Name}' queue full ({MaxQueueSize})");
        }
        
        try
        {
            // Wait for execution slot
            if (!await _semaphore.WaitAsync(TimeSpan.FromMinutes(5), ct))
            {
                Interlocked.Increment(ref _totalTimedOut);
                throw new BulkheadTimeoutException($"Timeout waiting for bulkhead '{Name}' slot");
            }
            
            try
            {
                Interlocked.Increment(ref _totalExecuted);
                _logger.LogDebug("Bulkhead '{Bulkhead}' executing. Slots available: {Available}/{Max}",
                    Name, _semaphore.CurrentCount, MaxConcurrent);
                
                return await action(ct);
            }
            finally
            {
                _semaphore.Release();
            }
        }
        finally
        {
            _queueSemaphore.Release();
        }
    }
    
    public async Task<(bool Success, T? Result)> TryExecuteAsync<T>(Func<CancellationToken, Task<T>> action, CancellationToken ct = default)
    {
        // Quick check without blocking
        if (_semaphore.CurrentCount == 0 || _queueSemaphore.CurrentCount == 0)
        {
            return (false, default);
        }
        
        try
        {
            var result = await ExecuteAsync(action, ct);
            return (true, result);
        }
        catch (BulkheadRejectedException)
        {
            return (false, default);
        }
    }
    
    public BulkheadMetrics GetMetrics() => new()
    {
        Name = Name,
        MaxConcurrent = MaxConcurrent,
        AvailableSlots = AvailableSlots,
        ActiveOperations = MaxConcurrent - AvailableSlots,
        WaitingCount = WaitingCount,
        MaxQueueSize = MaxQueueSize,
        TotalExecuted = Interlocked.Read(ref _totalExecuted),
        TotalRejected = Interlocked.Read(ref _totalRejected),
        TotalTimedOut = Interlocked.Read(ref _totalTimedOut)
    };
}

/// <summary>
/// Exception when bulkhead rejects operation.
/// </summary>
public class BulkheadRejectedException : Exception
{
    public BulkheadRejectedException(string message) : base(message) { }
}

/// <summary>
/// Exception when bulkhead wait times out.
/// </summary>
public class BulkheadTimeoutException : Exception
{
    public BulkheadTimeoutException(string message) : base(message) { }
}
```

### 4.3 Source-Specific Bulkhead Configuration

```csharp
/// <summary>
/// Pre-configured bulkheads for GABI sources.
/// </summary>
public static class BulkheadConfigs
{
    /// <summary>
    /// TCU sources - largest files, single-threaded per source.
    /// </summary>
    public static BulkheadConfig TcuSource => new()
    {
        MaxConcurrent = 1,      // Sequential processing for memory
        MaxQueueSize = 5,       // Years of data
        WaitTimeout = TimeSpan.FromMinutes(10)
    };
    
    /// <summary>
    /// External APIs with rate limits.
    /// </summary>
    public static BulkheadConfig ExternalApi => new()
    {
        MaxConcurrent = 2,
        MaxQueueSize = 20,
        WaitTimeout = TimeSpan.FromMinutes(5)
    };
    
    /// <summary>
    /// PDF processing - CPU intensive.
    /// </summary>
    public static BulkheadConfig PdfProcessing => new()
    {
        MaxConcurrent = 1,      // Memory intensive
        MaxQueueSize = 10,
        WaitTimeout = TimeSpan.FromMinutes(5)
    };
    
    /// <summary>
    /// TEI embedding service.
    /// </summary>
    public static BulkheadConfig EmbeddingService => new()
    {
        MaxConcurrent = 2,
        MaxQueueSize = 50,
        WaitTimeout = TimeSpan.FromMinutes(10)
    };
    
    /// <summary>
    /// Database operations.
    /// </summary>
    public static BulkheadConfig Database => new()
    {
        MaxConcurrent = 5,
        MaxQueueSize = 100,
        WaitTimeout = TimeSpan.FromMinutes(2)
    };
}
```

### 4.4 Usage in Pipeline

```csharp
public class PipelineExecutor
{
    private readonly IBulkheadRegistry _bulkheadRegistry;
    private readonly IRetryExecutor _retryExecutor;
    private readonly ICircuitBreakerRegistry _circuitBreakerRegistry;
    
    public async Task ProcessSourceAsync(string sourceId, SourceConfig config, CancellationToken ct)
    {
        // Get source-specific bulkhead
        var bulkhead = _bulkheadRegistry.GetOrCreate(
            $"source:{sourceId}", 
            GetBulkheadConfig(config));
        
        // Execute within bulkhead isolation
        await bulkhead.ExecuteAsync(async token =>
        {
            await ProcessDocumentsAsync(sourceId, config, token);
            return true;
        }, ct);
    }
    
    private BulkheadConfig GetBulkheadConfig(SourceConfig config)
    {
        return config.Provider switch
        {
            "TCU" => BulkheadConfigs.TcuSource,
            "CAMARA" => BulkheadConfigs.ExternalApi,
            "STF" => BulkheadConfigs.ExternalApi,
            "STJ" => BulkheadConfigs.ExternalApi,
            _ => new BulkheadConfig { MaxConcurrent = 1, MaxQueueSize = 5 }
        };
    }
}
```

---

## 5. Timeout Strategies

### 5.1 Overview

Hierarchical timeouts to prevent hanging operations and resource exhaustion.

```
Pipeline Timeout: 2 hours
├── Discovery: 10 minutes
├── Fetch per file: 5 minutes
│   ├── Connect: 30 seconds
│   └── Read (streaming): 4 minutes
├── Parse: 10 minutes
├── Chunk: 5 minutes
├── Embed: 30 minutes
└── Index: 10 minutes
```

### 5.2 Implementation

```csharp
namespace Gabi.Sync.Resiliency;

/// <summary>
/// Hierarchical timeout configuration.
/// </summary>
public record TimeoutConfig
{
    /// <summary>
    /// Total timeout for operation.
    /// </summary>
    public TimeSpan TotalTimeout { get; init; }
    
    /// <summary>
    /// Connect/establishment timeout.
    /// </summary>
    public TimeSpan ConnectTimeout { get; init; }
    
    /// <summary>
    /// Read/operation timeout.
    /// </summary>
    public TimeSpan? ReadTimeout { get; init; }
    
    /// <summary>
    /// Idle timeout (no data received).
    /// </summary>
    public TimeSpan? IdleTimeout { get; init; }
    
    /// <summary>
    /// Grace period for cleanup after cancellation.
    /// </summary>
    public TimeSpan CleanupGracePeriod { get; init; } = TimeSpan.FromSeconds(5);
}

/// <summary>
/// Pre-configured timeouts.
/// </summary>
public static class TimeoutConfigs
{
    public static TimeoutConfig HttpDownload => new()
    {
        TotalTimeout = TimeSpan.FromMinutes(5),
        ConnectTimeout = TimeSpan.FromSeconds(30),
        ReadTimeout = null,  // Streaming - no timeout
        IdleTimeout = TimeSpan.FromSeconds(60)
    };
    
    public static TimeoutConfig HttpApi => new()
    {
        TotalTimeout = TimeSpan.FromMinutes(2),
        ConnectTimeout = TimeSpan.FromSeconds(10),
        ReadTimeout = TimeSpan.FromSeconds(90),
        IdleTimeout = TimeSpan.FromSeconds(30)
    };
    
    public static TimeoutConfig DatabaseQuery => new()
    {
        TotalTimeout = TimeSpan.FromSeconds(30),
        ConnectTimeout = TimeSpan.FromSeconds(5),
        ReadTimeout = TimeSpan.FromSeconds(25)
    };
    
    public static TimeoutConfig DatabaseCommand => new()
    {
        TotalTimeout = TimeSpan.FromMinutes(2),
        ConnectTimeout = TimeSpan.FromSeconds(5),
        ReadTimeout = TimeSpan.FromMinutes(1)
    };
    
    public static TimeoutConfig Embedding => new()
    {
        TotalTimeout = TimeSpan.FromMinutes(5),
        ConnectTimeout = TimeSpan.FromSeconds(10),
        ReadTimeout = TimeSpan.FromMinutes(4)
    };
    
    public static TimeoutConfig Pipeline => new()
    {
        TotalTimeout = TimeSpan.FromHours(2),
        ConnectTimeout = TimeSpan.FromMinutes(1),
        IdleTimeout = TimeSpan.FromMinutes(10)
    };
}

/// <summary>
/// Timeout executor with proper cleanup.
/// </summary>
public interface ITimeoutExecutor
{
    /// <summary>
    /// Execute with timeout enforcement.
    /// </summary>
    Task<T> ExecuteAsync<T>(
        Func<CancellationToken, Task<T>> action,
        TimeoutConfig config,
        CancellationToken ct = default);
}

/// <summary>
/// Implementation with cooperative cancellation.
/// </summary>
public class TimeoutExecutor : ITimeoutExecutor
{
    private readonly ILogger<TimeoutExecutor> _logger;
    
    public TimeoutExecutor(ILogger<TimeoutExecutor> logger)
    {
        _logger = logger;
    }
    
    public async Task<T> ExecuteAsync<T>(
        Func<CancellationToken, Task<T>> action,
        TimeoutConfig config,
        CancellationToken ct = default)
    {
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(config.TotalTimeout);
        
        try
        {
            return await action(cts.Token);
        }
        catch (OperationCanceledException) when (cts.Token.IsCancellationRequested && !ct.IsCancellationRequested)
        {
            _logger.LogError("Operation timed out after {Timeout}", config.TotalTimeout);
            throw new TimeoutException($"Operation timed out after {config.TotalTimeout}");
        }
    }
}

/// <summary>
/// HttpClient with timeout per operation type.
/// </summary>
public class ResilientHttpClient
{
    private readonly HttpClient _httpClient;
    private readonly ILogger<ResilientHttpClient> _logger;
    
    public ResilientHttpClient(HttpClient httpClient, ILogger<ResilientHttpClient> logger)
    {
        _httpClient = httpClient;
        _logger = logger;
    }
    
    public async Task<HttpResponseMessage> GetWithTimeoutAsync(
        string url, 
        TimeoutConfig config,
        CancellationToken ct = default)
    {
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(config.TotalTimeout);
        
        try
        {
            _httpClient.Timeout = config.ConnectTimeout;
            var response = await _httpClient.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, cts.Token);
            
            // For streaming, read without timeout
            if (config.ReadTimeout == null)
            {
                return response;
            }
            
            // For non-streaming, apply read timeout
            cts.CancelAfter(config.ReadTimeout.Value);
            var content = await response.Content.ReadAsByteArrayAsync(cts.Token);
            
            // Replace content with buffered version
            response.Content = new ByteArrayContent(content);
            foreach (var header in response.Content.Headers)
            {
                response.Content.Headers.TryAddWithoutValidation(header.Key, header.Value);
            }
            
            return response;
        }
        catch (OperationCanceledException) when (cts.Token.IsCancellationRequested && !ct.IsCancellationRequested)
        {
            _logger.LogError("HTTP request to {Url} timed out", url);
            throw new TimeoutException($"HTTP request to {url} timed out");
        }
    }
}
```

---

## 6. Graceful Degradation

### 6.1 Overview

When full processing is not possible, continue with reduced functionality.

```
Normal Mode:
  Download → Parse → Chunk → Embed → Index

Degraded Mode (embedding unavailable):
  Download → Parse → Chunk → [SKIP EMBED] → Index (no vectors)

Emergency Mode (memory pressure):
  Download → Parse → [SKIP CHUNK/EMBED] → Index (metadata only)
```

### 6.2 Implementation

```csharp
namespace Gabi.Sync.Resiliency;

/// <summary>
/// Degradation levels for pipeline processing.
/// </summary>
public enum DegradationLevel
{
    /// <summary>
    /// Full functionality.
    /// </summary>
    Normal,
    
    /// <summary>
    /// Skip optional phases (embeddings).
    /// </summary>
    SkipOptional,
    
    /// <summary>
    /// Skip heavy processing (chunk + embed).
    /// </summary>
    MinimalProcessing,
    
    /// <summary>
    /// Metadata only, no content indexing.
    /// </summary>
    MetadataOnly,
    
    /// <summary>
    /// Circuit breaker open - skip entirely.
    /// </summary>
    CircuitOpen
}

/// <summary>
/// Degradation decision context.
/// </summary>
public record DegradationContext
{
    public string SourceId { get; init; } = string.Empty;
    public DegradationLevel CurrentLevel { get; init; }
    public MemoryPressureEventArgs? MemoryPressure { get; init; }
    public CircuitState? CircuitState { get; init; }
    public IReadOnlyList<string> FailedServices { get; init; } = new List<string>();
    public DateTime DecisionTime { get; init; } = DateTime.UtcNow;
}

/// <summary>
/// Strategy for graceful degradation.
/// </summary>
public interface IDegradationStrategy
{
    /// <summary>
    /// Determine degradation level based on context.
    /// </summary>
    DegradationLevel DetermineLevel(DegradationContext context);
    
    /// <summary>
    /// Get enabled phases for degradation level.
    /// </summary>
    PipelinePhases GetEnabledPhases(DegradationLevel level);
    
    /// <summary>
    /// Check if can upgrade to higher level.
    /// </summary>
    bool CanUpgrade(DegradationContext current, DegradationLevel proposed);
}

/// <summary>
/// Pipeline phases configuration.
/// </summary>
public record PipelinePhases
{
    public bool Fetch { get; init; } = true;
    public bool Parse { get; init; } = true;
    public bool Transform { get; init; } = true;
    public bool Deduplicate { get; init; } = true;
    public bool Chunk { get; init; } = true;
    public bool Embed { get; init; } = true;
    public bool IndexPg { get; init; } = true;
    public bool IndexEs { get; init; } = true;
    public bool Graph { get; init; } = false;
}

/// <summary>
/// Default degradation strategy.
/// </summary>
public class DefaultDegradationStrategy : IDegradationStrategy
{
    public DegradationLevel DetermineLevel(DegradationContext context)
    {
        // Circuit breaker open for critical service
        if (context.CircuitState == CircuitState.Open && 
            context.FailedServices.Contains("postgresql"))
        {
            return DegradationLevel.CircuitOpen;
        }
        
        // Memory pressure > 90%
        if (context.MemoryPressure?.PressureRatio > 0.9)
        {
            return DegradationLevel.MetadataOnly;
        }
        
        // Memory pressure > 80%
        if (context.MemoryPressure?.PressureRatio > 0.8)
        {
            return DegradationLevel.MinimalProcessing;
        }
        
        // Circuit breaker open for embedding
        if (context.CircuitState == CircuitState.Open &&
            context.FailedServices.Contains("tei_embedding"))
        {
            return DegradationLevel.SkipOptional;
        }
        
        return DegradationLevel.Normal;
    }
    
    public PipelinePhases GetEnabledPhases(DegradationLevel level) => level switch
    {
        DegradationLevel.Normal => new PipelinePhases 
        { 
            Fetch = true, Parse = true, Transform = true, 
            Deduplicate = true, Chunk = true, Embed = true,
            IndexPg = true, IndexEs = true 
        },
        DegradationLevel.SkipOptional => new PipelinePhases 
        { 
            Fetch = true, Parse = true, Transform = true,
            Deduplicate = true, Chunk = true, Embed = false,  // Skip embeddings
            IndexPg = true, IndexEs = true 
        },
        DegradationLevel.MinimalProcessing => new PipelinePhases 
        { 
            Fetch = true, Parse = true, Transform = true,
            Deduplicate = true, Chunk = false, Embed = false, // Skip chunk+embed
            IndexPg = true, IndexEs = true 
        },
        DegradationLevel.MetadataOnly => new PipelinePhases 
        { 
            Fetch = true, Parse = true, Transform = false,
            Deduplicate = false, Chunk = false, Embed = false,
            IndexPg = true, IndexEs = false  // Only PG metadata
        },
        DegradationLevel.CircuitOpen => new PipelinePhases(), // Nothing
        _ => new PipelinePhases()
    };
    
    public bool CanUpgrade(DegradationContext current, DegradationLevel proposed)
    {
        // Only upgrade if memory pressure reduced
        if (current.MemoryPressure?.PressureRatio > 0.75)
            return false;
            
        // Only upgrade if circuits are closed
        if (current.CircuitState == CircuitState.Open)
            return false;
            
        return proposed < current.CurrentLevel;
    }
}

/// <summary>
/// Degraded pipeline executor.
/// </summary>
public class DegradedPipelineExecutor
{
    private readonly IDegradationStrategy _strategy;
    private readonly ILogger<DegradedPipelineExecutor> _logger;
    private readonly IMemoryManager _memoryManager;
    private readonly ICircuitBreakerRegistry _circuitBreakerRegistry;
    
    public async Task<PipelineResult> ExecuteAsync(
        string sourceId,
        IAsyncEnumerable<Document> documents,
        PipelineOptions options,
        CancellationToken ct = default)
    {
        var context = BuildContext(sourceId);
        var level = _strategy.DetermineLevel(context);
        var phases = _strategy.GetEnabledPhases(level);
        
        if (level == DegradationLevel.CircuitOpen)
        {
            _logger.LogError("Cannot process {SourceId}: critical circuits open", sourceId);
            return new PipelineResult 
            { 
                Success = false, 
                ErrorMessage = "Critical services unavailable" 
            };
        }
        
        if (level != DegradationLevel.Normal)
        {
            _logger.LogWarning(
                "Processing {SourceId} in DEGRADED mode: {Level}. Phases: {Phases}",
                sourceId, level, FormatPhases(phases));
        }
        
        // Execute with enabled phases only
        return await ExecuteWithPhasesAsync(documents, phases, options, ct);
    }
    
    private DegradationContext BuildContext(string sourceId)
    {
        var failedServices = new List<string>();
        CircuitState? worstState = null;
        
        foreach (var cb in _circuitBreakerRegistry.GetAll())
        {
            if (cb.Value.State != CircuitState.Closed)
            {
                failedServices.Add(cb.Key);
                if (worstState == null || cb.Value.State > worstState)
                {
                    worstState = cb.Value.State;
                }
            }
        }
        
        return new DegradationContext
        {
            SourceId = sourceId,
            CurrentLevel = DegradationLevel.Normal, // Will be determined
            MemoryPressure = _memoryManager.IsUnderPressure ? new MemoryPressureEventArgs 
            { 
                CurrentUsage = _memoryManager.CurrentUsage,
                Threshold = _memoryManager.PressureThreshold,
                PressureRatio = (double)_memoryManager.CurrentUsage / _memoryManager.TotalMemory
            } : null,
            CircuitState = worstState,
            FailedServices = failedServices
        };
    }
    
    private string FormatPhases(PipelinePhases phases)
    {
        var enabled = new List<string>();
        if (phases.Fetch) enabled.Add("fetch");
        if (phases.Parse) enabled.Add("parse");
        if (phases.Transform) enabled.Add("transform");
        if (phases.Deduplicate) enabled.Add("dedup");
        if (phases.Chunk) enabled.Add("chunk");
        if (phases.Embed) enabled.Add("embed");
        if (phases.IndexPg) enabled.Add("index-pg");
        if (phases.IndexEs) enabled.Add("index-es");
        return string.Join(",", enabled);
    }
}
```

---

## 7. Health Checks and Self-Healing

### 7.1 Overview

Continuous monitoring with automatic recovery actions.

### 7.2 Implementation

```csharp
namespace Gabi.Sync.Resiliency;

/// <summary>
/// Health status levels.
/// </summary>
public enum HealthStatus
{
    Healthy,
    Degraded,
    Unhealthy
}

/// <summary>
/// Health check result.
/// </summary>
public record HealthCheckResult
{
    public string ComponentName { get; init; } = string.Empty;
    public HealthStatus Status { get; init; }
    public string? Message { get; init; }
    public TimeSpan ResponseTime { get; init; }
    public Exception? Exception { get; init; }
    public Dictionary<string, object> Metadata { get; init; } = new();
    public DateTime CheckedAt { get; init; } = DateTime.UtcNow;
}

/// <summary>
/// Individual health check.
/// </summary>
public interface IHealthCheck
{
    string Name { get; }
    Task<HealthCheckResult> CheckAsync(CancellationToken ct = default);
}

/// <summary>
/// Health check registry.
/// </summary>
public interface IHealthCheckRegistry
{
    void Register(IHealthCheck check);
    Task<IReadOnlyDictionary<string, HealthCheckResult>> CheckAllAsync(CancellationToken ct = default);
    HealthCheckResult? GetLastResult(string componentName);
}

/// <summary>
/// PostgreSQL health check.
/// </summary>
public class PostgreSqlHealthCheck : IHealthCheck
{
    private readonly GabiDbContext _dbContext;
    private readonly ILogger<PostgreSqlHealthCheck> _logger;
    
    public string Name => "postgresql";
    
    public async Task<HealthCheckResult> CheckAsync(CancellationToken ct = default)
    {
        var sw = Stopwatch.StartNew();
        try
        {
            await _dbContext.Database.ExecuteSqlRawAsync("SELECT 1", ct);
            sw.Stop();
            
            // Check connection count
            var connCount = await _dbContext.Database
                .SqlQuery<int>($"SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
                .FirstAsync(ct);
            
            var status = connCount > 80 ? HealthStatus.Degraded : HealthStatus.Healthy;
            
            return new HealthCheckResult
            {
                ComponentName = Name,
                Status = status,
                ResponseTime = sw.Elapsed,
                Metadata = { ["connections"] = connCount }
            };
        }
        catch (Exception ex)
        {
            return new HealthCheckResult
            {
                ComponentName = Name,
                Status = HealthStatus.Unhealthy,
                ResponseTime = sw.Elapsed,
                Exception = ex,
                Message = ex.Message
            };
        }
    }
}

/// <summary>
/// Elasticsearch health check.
/// </summary>
public class ElasticsearchHealthCheck : IHealthCheck
{
    private readonly HttpClient _httpClient;
    private readonly ILogger<ElasticsearchHealthCheck> _logger;
    
    public string Name => "elasticsearch";
    
    public async Task<HealthCheckResult> CheckAsync(CancellationToken ct = default)
    {
        var sw = Stopwatch.StartNew();
        try
        {
            var response = await _httpClient.GetAsync("_cluster/health", ct);
            response.EnsureSuccessStatusCode();
            
            var content = await response.Content.ReadFromJsonAsync<EsHealthResponse>(ct);
            sw.Stop();
            
            var status = content?.Status switch
            {
                "green" => HealthStatus.Healthy,
                "yellow" => HealthStatus.Degraded,
                _ => HealthStatus.Unhealthy
            };
            
            return new HealthCheckResult
            {
                ComponentName = Name,
                Status = status,
                ResponseTime = sw.Elapsed,
                Metadata = 
                { 
                    ["cluster_status"] = content?.Status,
                    ["active_shards"] = content?.ActiveShards 
                }
            };
        }
        catch (Exception ex)
        {
            return new HealthCheckResult
            {
                ComponentName = Name,
                Status = HealthStatus.Unhealthy,
                ResponseTime = sw.Elapsed,
                Exception = ex
            };
        }
    }
    
    private record EsHealthResponse(string Status, int ActiveShards);
}

/// <summary>
/// TEI embedding service health check.
/// </summary>
public class TeiHealthCheck : IHealthCheck
{
    private readonly HttpClient _httpClient;
    
    public string Name => "tei";
    
    public async Task<HealthCheckResult> CheckAsync(CancellationToken ct = default)
    {
        var sw = Stopwatch.StartNew();
        try
        {
            var response = await _httpClient.GetAsync("health", ct);
            sw.Stop();
            
            return new HealthCheckResult
            {
                ComponentName = Name,
                Status = response.IsSuccessStatusCode ? HealthStatus.Healthy : HealthStatus.Unhealthy,
                ResponseTime = sw.Elapsed
            };
        }
        catch (Exception ex)
        {
            return new HealthCheckResult
            {
                ComponentName = Name,
                Status = HealthStatus.Unhealthy,
                ResponseTime = sw.Elapsed,
                Exception = ex
            };
        }
    }
}

/// <summary>
/// Memory health check.
/// </summary>
public class MemoryHealthCheck : IHealthCheck
{
    private readonly IMemoryManager _memoryManager;
    
    public string Name => "memory";
    
    public Task<HealthCheckResult> CheckAsync(CancellationToken ct = default)
    {
        var usage = _memoryManager.CurrentUsage;
        var total = _memoryManager.TotalMemory;
        var ratio = (double)usage / total;
        
        var status = ratio switch
        {
            > 0.95 => HealthStatus.Unhealthy,
            > 0.80 => HealthStatus.Degraded,
            _ => HealthStatus.Healthy
        };
        
        return Task.FromResult(new HealthCheckResult
        {
            ComponentName = Name,
            Status = status,
            ResponseTime = TimeSpan.Zero,
            Metadata =
            {
                ["usage_bytes"] = usage,
                ["total_bytes"] = total,
                ["usage_percent"] = ratio * 100
            }
        });
    }
}

/// <summary>
/// Self-healing orchestrator.
/// </summary>
public interface ISelfHealingOrchestrator
{
    /// <summary>
    /// Start monitoring loop.
    /// </summary>
    Task StartAsync(CancellationToken ct);
    
    /// <summary>
    /// Stop monitoring.
    /// </summary>
    Task StopAsync(CancellationToken ct);
}

/// <summary>
/// Implements self-healing actions based on health checks.
/// </summary>
public class SelfHealingOrchestrator : ISelfHealingOrchestrator
{
    private readonly IHealthCheckRegistry _healthCheckRegistry;
    private readonly ICircuitBreakerRegistry _circuitBreakerRegistry;
    private readonly IMemoryManager _memoryManager;
    private readonly ILogger<SelfHealingOrchestrator> _logger;
    private Timer? _timer;
    
    public SelfHealingOrchestrator(
        IHealthCheckRegistry healthCheckRegistry,
        ICircuitBreakerRegistry circuitBreakerRegistry,
        IMemoryManager memoryManager,
        ILogger<SelfHealingOrchestrator> logger)
    {
        _healthCheckRegistry = healthCheckRegistry;
        _circuitBreakerRegistry = circuitBreakerRegistry;
        _memoryManager = memoryManager;
        _logger = logger;
    }
    
    public Task StartAsync(CancellationToken ct)
    {
        _timer = new Timer(async _ => await RunHealthCheckAsync(ct), null, TimeSpan.Zero, TimeSpan.FromSeconds(30));
        return Task.CompletedTask;
    }
    
    public Task StopAsync(CancellationToken ct)
    {
        _timer?.Change(Timeout.Infinite, 0);
        return Task.CompletedTask;
    }
    
    private async Task RunHealthCheckAsync(CancellationToken ct)
    {
        try
        {
            var results = await _healthCheckRegistry.CheckAllAsync(ct);
            
            foreach (var (name, result) in results)
            {
                await HandleHealthResultAsync(name, result, ct);
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Health check loop failed");
        }
    }
    
    private async Task HandleHealthResultAsync(string name, HealthCheckResult result, CancellationToken ct)
    {
        switch (result.Status)
        {
            case HealthStatus.Healthy:
                await HandleHealthyAsync(name, result, ct);
                break;
                
            case HealthStatus.Degraded:
                await HandleDegradedAsync(name, result, ct);
                break;
                
            case HealthStatus.Unhealthy:
                await HandleUnhealthyAsync(name, result, ct);
                break;
        }
    }
    
    private Task HandleHealthyAsync(string name, HealthCheckResult result, CancellationToken ct)
    {
        // Check if we should close any open circuits
        var cb = _circuitBreakerRegistry.GetAll().GetValueOrDefault(name);
        if (cb?.State == CircuitState.Open)
        {
            _logger.LogInformation("Service {Service} is healthy, attempting circuit close", name);
            _circuitBreakerRegistry.ForceClose(name);
        }
        
        return Task.CompletedTask;
    }
    
    private Task HandleDegradedAsync(string name, HealthCheckResult result, CancellationToken ct)
    {
        _logger.LogWarning("Service {Service} is DEGRADED: {Message}", name, result.Message);
        
        // Memory pressure - trigger GC
        if (name == "memory" && _memoryManager.IsUnderPressure)
        {
            _logger.LogWarning("Memory pressure detected, triggering GC");
            _memoryManager.CollectIfUnderPressure();
        }
        
        return Task.CompletedTask;
    }
    
    private Task HandleUnhealthyAsync(string name, HealthCheckResult result, CancellationToken ct)
    {
        _logger.LogError("Service {Service} is UNHEALTHY: {Message}", name, result.Message);
        
        // Open circuit breaker if not already open
        var cb = _circuitBreakerRegistry.GetAll().GetValueOrDefault(name);
        if (cb?.State == CircuitState.Closed)
        {
            _logger.LogWarning("Opening circuit for {Service} due to health check failure", name);
            _circuitBreakerRegistry.ForceOpen(name);
        }
        
        return Task.CompletedTask;
    }
}
```

---

## 8. Dead Letter Queue (DLQ)

### 8.1 Overview

Captures failed items with retry count for later reprocessing.

```
┌─────────────┐    ┌─────────────┐    ┌─────────────────┐
│   Pipeline  │───▶│   Failure   │───▶│      DLQ        │
│   Stage     │    │   Handler   │    │  (PostgreSQL)   │
└─────────────┘    └─────────────┘    └─────────────────┘
                                             │
                                             ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────────┐
│  Reprocess  │◀───│   Retry     │◀───│  DLQ Worker     │
│   Success   │    │   Logic     │    │  (scheduled)    │
└─────────────┘    └─────────────┘    └─────────────────┘
```

### 8.2 Implementation

```csharp
namespace Gabi.Sync.Resiliency;

/// <summary>
/// DLQ entry status.
/// </summary>
public enum DlqStatus
{
    /// <summary>
    /// New entry, not yet processed.
    /// </summary>
    Pending,
    
    /// <summary>
    /// Currently being retried.
    /// </summary>
    Processing,
    
    /// <summary>
    /// Successfully reprocessed.
    /// </summary>
    Resolved,
    
    /// <summary>
    /// Max retries exceeded.
    /// </summary>
    Dead,
    
    /// <summary>
    /// Manually reviewed and resolved.
    /// </summary>
    ManualResolved,
    
    /// <summary>
    /// Will not be retried.
    /// </summary>
    Discarded
}

/// <summary>
/// DLQ entry for failed items.
/// </summary>
public record DlqEntry
{
    public Guid Id { get; init; } = Guid.NewGuid();
    public string SourceId { get; init; } = string.Empty;
    public string DocumentId { get; init; } = string.Empty;
    public string PipelineStage { get; init; } = string.Empty;
    
    /// <summary>
    /// Serialized document at time of failure.
    /// </summary>
    public string DocumentPayload { get; init; } = string.Empty;
    
    /// <summary>
    /// Error details.
    /// </summary>
    public string ErrorMessage { get; init; } = string.Empty;
    public string? ErrorStackTrace { get; init; }
    public string? ErrorType { get; init; }
    
    /// <summary>
    /// Retry tracking.
    /// </summary>
    public int RetryCount { get; set; }
    public int MaxRetries { get; init; } = 3;
    public DateTime? LastRetryAt { get; set; }
    public DateTime? NextRetryAt { get; set; }
    
    /// <summary>
    /// Current status.
    /// </summary>
    public DlqStatus Status { get; set; } = DlqStatus.Pending;
    
    /// <summary>
    /// Metadata for debugging.
    /// </summary>
    public Dictionary<string, object> Metadata { get; init; } = new();
    
    /// <summary>
    /// When first added to DLQ.
    /// </summary>
    public DateTime CreatedAt { get; init; } = DateTime.UtcNow;
    
    /// <summary>
    /// Last update timestamp.
    /// </summary>
    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;
}

/// <summary>
/// DLQ operations.
/// </summary>
public interface IDeadLetterQueue
{
    /// <summary>
    /// Add failed item to DLQ.
    /// </summary>
    Task<DlqEntry> EnqueueAsync(DlqEntry entry, CancellationToken ct = default);
    
    /// <summary>
    /// Get pending entries for retry.
    /// </summary>
    Task<IReadOnlyList<DlqEntry>> GetPendingAsync(int batchSize = 100, CancellationToken ct = default);
    
    /// <summary>
    /// Get entries for specific source.
    /// </summary>
    Task<IReadOnlyList<DlqEntry>> GetBySourceAsync(string sourceId, CancellationToken ct = default);
    
    /// <summary>
    /// Update entry after retry attempt.
    /// </summary>
    Task UpdateAsync(DlqEntry entry, CancellationToken ct = default);
    
    /// <summary>
    /// Mark entry as resolved.
    /// </summary>
    Task ResolveAsync(Guid entryId, DlqStatus resolution, string? notes = null, CancellationToken ct = default);
    
    /// <summary>
    /// Get DLQ statistics.
    /// </summary>
    Task<DlqStatistics> GetStatisticsAsync(CancellationToken ct = default);
}

/// <summary>
/// DLQ statistics.
/// </summary>
public record DlqStatistics
{
    public int TotalEntries { get; init; }
    public int PendingCount { get; init; }
    public int ProcessingCount { get; init; }
    public int ResolvedCount { get; init; }
    public int DeadCount { get; init; }
    public int ManualResolvedCount { get; init; }
    public IReadOnlyDictionary<string, int> BySource { get; init; } = new Dictionary<string, int>();
    public IReadOnlyDictionary<string, int> ByStage { get; init; } = new Dictionary<string, int>();
}

/// <summary>
/// DLQ retry policy.
/// </summary>
public record DlqRetryPolicy
{
    /// <summary>
    /// Delay between retries (increases with each attempt).
    /// </summary>
    public TimeSpan[] RetryDelays { get; init; } = new[]
    {
        TimeSpan.FromMinutes(5),
        TimeSpan.FromMinutes(15),
        TimeSpan.FromHours(1),
        TimeSpan.FromHours(4),
        TimeSpan.FromHours(12)
    };
    
    /// <summary>
    /// Max age before marking as dead.
    /// </summary>
    public TimeSpan MaxAge { get; init; } = TimeSpan.FromDays(7);
    
    /// <summary>
    /// Whether to auto-retry on schedule.
    /// </summary>
    public bool AutoRetryEnabled { get; init; } = true;
    
    /// <summary>
    /// Schedule for DLQ worker (cron expression).
    /// </summary>
    public string RetrySchedule { get; init; } = "*/15 * * * *"; // Every 15 minutes
}

/// <summary>
/// DLQ worker for background retry processing.
/// </summary>
public interface IDlqWorker
{
    Task StartAsync(CancellationToken ct);
    Task StopAsync(CancellationToken ct);
}

/// <summary>
/// Implementation using PostgreSQL.
/// </summary>
public class DlqWorker : BackgroundService, IDlqWorker
{
    private readonly IDeadLetterQueue _dlq;
    private readonly IRetryExecutor _retryExecutor;
    private readonly IPipelineExecutor _pipelineExecutor;
    private readonly DlqRetryPolicy _policy;
    private readonly ILogger<DlqWorker> _logger;
    
    public DlqWorker(
        IDeadLetterQueue dlq,
        IRetryExecutor retryExecutor,
        IPipelineExecutor pipelineExecutor,
        DlqRetryPolicy policy,
        ILogger<DlqWorker> logger)
    {
        _dlq = dlq;
        _retryExecutor = retryExecutor;
        _pipelineExecutor = pipelineExecutor;
        _policy = policy;
        _logger = logger;
    }
    
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await ProcessDlqAsync(stoppingToken);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "DLQ processing failed");
            }
            
            await Task.Delay(TimeSpan.FromMinutes(15), stoppingToken);
        }
    }
    
    private async Task ProcessDlqAsync(CancellationToken ct)
    {
        var pending = await _dlq.GetPendingAsync(batchSize: 50, ct);
        
        _logger.LogInformation("Processing {Count} DLQ entries", pending.Count);
        
        foreach (var entry in pending)
        {
            // Check if it's time to retry
            if (entry.NextRetryAt > DateTime.UtcNow)
            {
                continue;
            }
            
            // Check max age
            if (DateTime.UtcNow - entry.CreatedAt > _policy.MaxAge)
            {
                await _dlq.ResolveAsync(entry.Id, DlqStatus.Dead, "Max age exceeded", ct);
                continue;
            }
            
            await ProcessEntryAsync(entry, ct);
        }
    }
    
    private async Task ProcessEntryAsync(DlqEntry entry, CancellationToken ct)
    {
        entry.Status = DlqStatus.Processing;
        entry.LastRetryAt = DateTime.UtcNow;
        await _dlq.UpdateAsync(entry, ct);
        
        try
        {
            // Deserialize and retry
            var document = JsonSerializer.Deserialize<Document>(entry.DocumentPayload);
            if (document == null)
            {
                await _dlq.ResolveAsync(entry.Id, DlqStatus.Dead, "Failed to deserialize document", ct);
                return;
            }
            
            // Retry the specific stage
            await _retryExecutor.ExecuteAsync(
                async token => await RetryStageAsync(entry.PipelineStage, document, token),
                RetryPolicies.HttpDownload,
                onRetry: ctx => _logger.LogWarning(
                    "DLQ retry {Attempt} for {DocumentId}",
                    ctx.AttemptNumber, entry.DocumentId),
                ct);
            
            // Success!
            entry.Status = DlqStatus.Resolved;
            entry.RetryCount++;
            await _dlq.UpdateAsync(entry, ct);
            
            _logger.LogInformation("DLQ entry {EntryId} resolved after {Retries} retries", 
                entry.Id, entry.RetryCount);
        }
        catch (Exception ex)
        {
            entry.RetryCount++;
            
            if (entry.RetryCount >= entry.MaxRetries)
            {
                entry.Status = DlqStatus.Dead;
                _logger.LogError(ex, "DLQ entry {EntryId} marked as DEAD after {Retries} attempts",
                    entry.Id, entry.RetryCount);
            }
            else
            {
                entry.Status = DlqStatus.Pending;
                var delayIndex = Math.Min(entry.RetryCount - 1, _policy.RetryDelays.Length - 1);
                entry.NextRetryAt = DateTime.UtcNow + _policy.RetryDelays[delayIndex];
                _logger.LogWarning("DLQ entry {EntryId} will retry at {NextRetry}",
                    entry.Id, entry.NextRetryAt);
            }
            
            await _dlq.UpdateAsync(entry, ct);
        }
    }
    
    private Task RetryStageAsync(string stage, Document document, CancellationToken ct)
    {
        // Route to appropriate stage retry logic
        return stage switch
        {
            "fetch" => _pipelineExecutor.RetryFetchAsync(document, ct),
            "parse" => _pipelineExecutor.RetryParseAsync(document, ct),
            "chunk" => _pipelineExecutor.RetryChunkAsync(document, ct),
            "embed" => _pipelineExecutor.RetryEmbedAsync(document, ct),
            "index" => _pipelineExecutor.RetryIndexAsync(document, ct),
            _ => throw new NotSupportedException($"Stage {stage} not supported for retry")
        };
    }
}

/// <summary>
/// Handler for pipeline stage failures.
/// </summary>
public class DlqFailureHandler
{
    private readonly IDeadLetterQueue _dlq;
    private readonly ILogger<DlqFailureHandler> _logger;
    
    public async Task HandleFailureAsync(
        Document document,
        string stage,
        Exception exception,
        CancellationToken ct = default)
    {
        _logger.LogError(exception, 
            "Pipeline failure at stage {Stage} for document {DocumentId}",
            stage, document.Id);
        
        var entry = new DlqEntry
        {
            SourceId = document.SourceId,
            DocumentId = document.Id,
            PipelineStage = stage,
            DocumentPayload = JsonSerializer.Serialize(document),
            ErrorMessage = exception.Message,
            ErrorStackTrace = exception.StackTrace,
            ErrorType = exception.GetType().FullName,
            Metadata =
            {
                ["document_size"] = document.EstimatedMemory,
                ["stage_duration_ms"] = document.Metadata.GetValueOrDefault("stage_duration_ms", 0)
            }
        };
        
        await _dlq.EnqueueAsync(entry, ct);
    }
}
```

### 8.3 Database Schema

```sql
-- DLQ table
CREATE TABLE dlq_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id VARCHAR(100) NOT NULL,
    document_id VARCHAR(255) NOT NULL,
    pipeline_stage VARCHAR(50) NOT NULL,
    document_payload JSONB NOT NULL,
    error_message TEXT NOT NULL,
    error_stack_trace TEXT,
    error_type VARCHAR(255),
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    last_retry_at TIMESTAMP WITH TIME ZONE,
    next_retry_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR(20) DEFAULT 'Pending',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_dlq_status ON dlq_entries(status);
CREATE INDEX idx_dlq_next_retry ON dlq_entries(next_retry_at) WHERE status = 'Pending';
CREATE INDEX idx_dlq_source ON dlq_entries(source_id);
CREATE INDEX idx_dlq_stage ON dlq_entries(pipeline_stage);
CREATE INDEX idx_dlq_created ON dlq_entries(created_at);

-- Statistics view
CREATE VIEW dlq_statistics AS
SELECT
    status,
    COUNT(*) as count,
    source_id,
    pipeline_stage
FROM dlq_entries
GROUP BY status, source_id, pipeline_stage;
```

---

## 9. Integration Architecture

### 9.1 Complete Pipeline with Resiliency

```csharp
namespace Gabi.Sync.Pipeline;

/// <summary>
/// Resilient pipeline stage wrapper.
/// </summary>
public class ResilientPipelineStage<TInput, TOutput>
{
    private readonly string _stageName;
    private readonly Func<TInput, CancellationToken, Task<TOutput>> _processor;
    private readonly ICircuitBreaker _circuitBreaker;
    private readonly IBulkhead _bulkhead;
    private readonly IRetryExecutor _retryExecutor;
    private readonly DlqFailureHandler _dlqHandler;
    private readonly ILogger _logger;
    
    public ResilientPipelineStage(
        string stageName,
        Func<TInput, CancellationToken, Task<TOutput>> processor,
        ICircuitBreakerRegistry cbRegistry,
        IBulkheadRegistry bulkheadRegistry,
        IRetryExecutor retryExecutor,
        DlqFailureHandler dlqHandler,
        RetryPolicyConfig retryPolicy,
        BulkheadConfig bulkheadConfig,
        ILogger logger)
    {
        _stageName = stageName;
        _processor = processor;
        _circuitBreaker = cbRegistry.GetOrCreate(stageName);
        _bulkhead = bulkheadRegistry.GetOrCreate(stageName, bulkheadConfig);
        _retryExecutor = retryExecutor;
        _dlqHandler = dlqHandler;
        _logger = logger;
    }
    
    public async Task<TOutput> ExecuteAsync(TInput input, CancellationToken ct = default)
    {
        return await _bulkhead.ExecuteAsync(async token =>
        {
            return await _circuitBreaker.ExecuteAsync(async cbToken =>
            {
                return await _retryExecutor.ExecuteAsync(
                    async retryToken => await _processor(input, retryToken),
                    RetryPolicies.HttpDownload,
                    onRetry: ctx => _logger.LogWarning(
                        "Stage {Stage} retry {Attempt}/{Max}",
                        _stageName, ctx.AttemptNumber, ctx.MaxAttempts),
                    cbToken);
            }, token);
        }, ct);
    }
}

/// <summary>
/// Complete resilient pipeline orchestrator.
/// </summary>
public class ResilientPipelineOrchestrator
{
    private readonly IResiliencyInfrastructure _resiliency;
    private readonly IPipelineStageExecutor _stageExecutor;
    private readonly ILogger<ResilientPipelineOrchestrator> _logger;
    
    public async Task<PipelineResult> ExecuteAsync(
        string sourceId,
        IAsyncEnumerable<Document> documents,
        PipelineOptions options,
        CancellationToken ct = default)
    {
        var metrics = new PipelineMetrics
        {
            SourceId = sourceId,
            StartedAt = DateTime.UtcNow
        };
        
        var processed = 0;
        var failed = 0;
        
        await foreach (var document in documents.WithCancellation(ct))
        {
            try
            {
                await ProcessDocumentWithResiliencyAsync(sourceId, document, options, ct);
                processed++;
            }
            catch (Exception ex) when (IsRecoverable(ex))
            {
                // DLQ handled
                failed++;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Unrecoverable error for document {DocumentId}", document.Id);
                throw;
            }
            
            // Periodic metrics update
            if (processed % 100 == 0)
            {
                _logger.LogInformation(
                    "Progress: {Processed} processed, {Failed} failed for {SourceId}",
                    processed, failed, sourceId);
            }
        }
        
        metrics.DocumentsProcessed = processed;
        metrics.DocumentsFailed = failed;
        metrics.CompletedAt = DateTime.UtcNow;
        
        return new PipelineResult
        {
            Success = true,
            Metrics = metrics
        };
    }
    
    private async Task ProcessDocumentWithResiliencyAsync(
        string sourceId,
        Document document,
        PipelineOptions options,
        CancellationToken ct)
    {
        // Fetch with resiliency
        var fetched = await ExecuteStageAsync(
            "fetch",
            async () => await _stageExecutor.FetchAsync(document, ct),
            document,
            ct);
        
        // Parse with resiliency
        var parsed = await ExecuteStageAsync(
            "parse",
            async () => await _stageExecutor.ParseAsync(fetched, ct),
            document,
            ct);
        
        // Continue with other stages...
        // Each stage is wrapped with CB, Retry, and Bulkhead
    }
    
    private async Task<T> ExecuteStageAsync<T>(
        string stageName,
        Func<Task<T>> action,
        Document document,
        CancellationToken ct)
    {
        try
        {
            return await action();
        }
        catch (Exception ex) when (ShouldDlq(ex))
        {
            await _resiliency.DlqHandler.HandleFailureAsync(document, stageName, ex, ct);
            throw;
        }
    }
    
    private bool IsRecoverable(Exception ex) => ex is
        HttpRequestException or
        TimeoutException or
        IOException or
        RetryExhaustedException;
    
    private bool ShouldDlq(Exception ex) => IsRecoverable(ex);
}
```

### 9.2 Dependency Injection Setup

```csharp
public static class ResiliencyServiceExtensions
{
    public static IServiceCollection AddResiliency(
        this IServiceCollection services)
    {
        // Circuit breakers
        services.AddSingleton<ICircuitBreakerRegistry, CircuitBreakerRegistry>();
        
        // Retry executor
        services.AddSingleton<IRetryExecutor, RetryExecutor>();
        
        // Bulkheads
        services.AddSingleton<IBulkheadRegistry, BulkheadRegistry>();
        
        // Timeouts
        services.AddSingleton<ITimeoutExecutor, TimeoutExecutor>();
        
        // Health checks
        services.AddSingleton<IHealthCheckRegistry, HealthCheckRegistry>();
        services.AddSingleton<IHealthCheck, PostgreSqlHealthCheck>();
        services.AddSingleton<IHealthCheck, ElasticsearchHealthCheck>();
        services.AddSingleton<IHealthCheck, TeiHealthCheck>();
        services.AddSingleton<IHealthCheck, MemoryHealthCheck>();
        
        // Self-healing
        services.AddSingleton<ISelfHealingOrchestrator, SelfHealingOrchestrator>();
        
        // DLQ
        services.AddSingleton<IDeadLetterQueue, PostgreSqlDeadLetterQueue>();
        services.AddSingleton<DlqFailureHandler>();
        services.AddSingleton<DlqRetryPolicy>();
        services.AddHostedService<DlqWorker>();
        
        // Rate limit handler
        services.AddSingleton<RateLimitHandler>();
        
        return services;
    }
}
```

---

## 10. Monitoring and Alerting

### 10.1 Metrics

```csharp
// Prometheus metrics
public static class ResiliencyMetrics
{
    public static readonly Counter CircuitBreakerTransitions = Metrics.CreateCounter(
        "gabi_circuit_breaker_transitions_total",
        "Circuit breaker state transitions",
        new CounterConfiguration { LabelNames = new[] { "circuit", "from_state", "to_state" } });
    
    public static readonly Gauge CircuitBreakerState = Metrics.CreateGauge(
        "gabi_circuit_breaker_state",
        "Current circuit breaker state (0=closed, 1=half-open, 2=open)",
        new GaugeConfiguration { LabelNames = new[] { "circuit" } });
    
    public static readonly Counter RetryAttempts = Metrics.CreateCounter(
        "gabi_retry_attempts_total",
        "Retry attempts by result",
        new CounterConfiguration { LabelNames = new[] { "operation", "result" } });
    
    public static readonly Histogram RetryDuration = Metrics.CreateHistogram(
        "gabi_retry_duration_seconds",
        "Total duration including retries",
        new HistogramConfiguration { LabelNames = new[] { "operation" } });
    
    public static readonly Gauge BulkheadUsage = Metrics.CreateGauge(
        "gabi_bulkhead_usage",
        "Current bulkhead utilization",
        new GaugeConfiguration { LabelNames = new[] { "bulkhead", "type" } });
    
    public static readonly Counter DlqEntries = Metrics.CreateCounter(
        "gabi_dlq_entries_total",
        "DLQ entries by status",
        new CounterConfiguration { LabelNames = new[] { "source", "stage", "status" } });
    
    public static readonly Gauge DlqPending = Metrics.CreateGauge(
        "gabi_dlq_pending",
        "Current pending DLQ entries");
}
```

### 10.2 Alerts

```yaml
# prometheus/alerts.yml
groups:
  - name: gabi_resiliency
    rules:
      - alert: GabiCircuitBreakerOpen
        expr: gabi_circuit_breaker_state == 2
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Circuit breaker {{ $labels.circuit }} is open"
          
      - alert: GabiHighRetryRate
        expr: rate(gabi_retry_attempts_total{result="failure"}[5m]) > 0.5
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "High retry failure rate for {{ $labels.operation }}"
          
      - alert: GabiBulkheadRejection
        expr: rate(gabi_bulkhead_usage{bulkhead="rejected"}[1m]) > 0
        for: 30s
        labels:
          severity: critical
        annotations:
          summary: "Bulkhead {{ $labels.bulkhead }} rejecting requests"
          
      - alert: GabiDlqGrowing
        expr: gabi_dlq_pending > 1000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "DLQ has {{ $value }} pending entries"
          
      - alert: GabiDlqDeadEntries
        expr: rate(gabi_dlq_entries_total{status="dead"}[1h]) > 10
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High rate of DLQ entries becoming dead"
```

---

## 11. Configuration Reference

### 11.1 appsettings.json

```json
{
  "Resiliency": {
    "CircuitBreaker": {
      "Default": {
        "FailureThreshold": 5,
        "SamplingWindow": "00:01:00",
        "OpenDuration": "00:00:30",
        "SuccessThreshold": 3
      },
      "Database": {
        "FailureThreshold": 3,
        "SamplingWindow": "00:00:30",
        "OpenDuration": "00:00:10",
        "SuccessThreshold": 2
      }
    },
    "Retry": {
      "HttpDownload": {
        "MaxAttempts": 3,
        "InitialDelay": "00:00:02",
        "MaxDelay": "00:00:30",
        "Strategy": "Exponential",
        "JitterFactor": 0.1
      },
      "ExternalApi": {
        "MaxAttempts": 5,
        "InitialDelay": "00:00:01",
        "MaxDelay": "00:01:00",
        "Strategy": "DecorrelatedJitter",
        "JitterFactor": 0.2
      }
    },
    "Bulkhead": {
      "TcuSource": {
        "MaxConcurrent": 1,
        "MaxQueueSize": 5,
        "WaitTimeout": "00:10:00"
      },
      "Embedding": {
        "MaxConcurrent": 2,
        "MaxQueueSize": 50,
        "WaitTimeout": "00:10:00"
      }
    },
    "DLQ": {
      "MaxRetries": 5,
      "RetryDelays": ["00:05:00", "00:15:00", "00:01:00:00", "00:04:00:00", "00:12:00:00"],
      "MaxAge": "7.00:00:00",
      "AutoRetryEnabled": true,
      "RetrySchedule": "*/15 * * * *"
    },
    "HealthCheck": {
      "IntervalSeconds": 30,
      "TimeoutSeconds": 10
    }
  }
}
```

---

## 12. Implementation Checklist

### Phase 1: Core Patterns
- [ ] Circuit Breaker base implementation
- [ ] Retry executor with exponential backoff
- [ ] Bulkhead isolation per source
- [ ] Timeout strategies

### Phase 2: Integration
- [ ] Integrate with PipelineOrchestrator
- [ ] DLQ PostgreSQL schema and repository
- [ ] Health checks for all services
- [ ] Self-healing orchestrator

### Phase 3: Observability
- [ ] Prometheus metrics export
- [ ] Structured logging for all patterns
- [ ] Alerting rules
- [ ] Dashboard (Grafana)

### Phase 4: Testing
- [ ] Chaos engineering tests
- [ ] Circuit breaker state transitions
- [ ] Retry exhaustion scenarios
- [ ] Bulkhead saturation
- [ ] DLQ end-to-end flow

---

## 13. Summary

| Pattern | Challenge | Implementation | Monitoring |
|---------|-----------|----------------|------------|
| Circuit Breaker | Cascade failures | Per-service CB with state machine | CB transitions, state gauge |
| Retry + Backoff | Network/API failures | Exponential + decorrelated jitter | Retry attempts, duration |
| Bulkhead | Resource exhaustion | Semaphore per source | Usage, queue depth |
| Timeout | Hanging operations | Hierarchical timeouts | Timeout events |
| Graceful Degradation | Memory pressure | Skip optional phases | Degradation level |
| Health Checks | Service availability | Periodic checks | Status, latency |
| Self-Healing | Auto-recovery | Circuit manipulation | Recovery events |
| DLQ | Partial failures | PostgreSQL + worker | Pending, dead counts |

**Key Metrics to Watch:**
1. `gabi_circuit_breaker_state > 0` → Service issues
2. `gabi_retry_attempts_total` increasing → Network problems
3. `gabi_dlq_pending` growing → Pipeline failures
4. `gabi_bulkhead_usage` at max → Need more resources
