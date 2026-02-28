using System.Collections.Concurrent;
using Gabi.Contracts.Observability;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Circuit breaker pattern implementation for fetch operations.
/// Prevents hammering failing sources by temporarily blocking requests
/// after a threshold of consecutive failures.
/// </summary>
public interface ICircuitBreaker
{
    /// <summary>
    /// Checks if the circuit is open (blocking) for the given source/URL.
    /// </summary>
    bool IsOpen(string sourceId, string? url = null);
    
    /// <summary>
    /// Records a successful request, resetting the circuit.
    /// </summary>
    void RecordSuccess(string sourceId, string? url = null);
    
    /// <summary>
    /// Records a failed request, potentially opening the circuit.
    /// </summary>
    void RecordFailure(string sourceId, string? url = null);
    
    /// <summary>
    /// Gets the current state of a circuit for debugging.
    /// </summary>
    CircuitState? GetState(string sourceId, string? url = null);
}

/// <summary>
/// State of a circuit breaker.
/// </summary>
public record CircuitState
{
    public bool IsOpen { get; init; }
    public int FailureCount { get; init; }
    public DateTime? OpenedAt { get; init; }
    public DateTime? OpenUntil { get; init; }
    public DateTime? LastFailureAt { get; init; }
}

/// <summary>
/// Thread-safe circuit breaker implementation with per-source and per-URL granularity.
/// </summary>
public class FetchCircuitBreaker : ICircuitBreaker
{
    private readonly int _failureThreshold;
    private readonly TimeSpan _breakDuration;
    private readonly TimeSpan _resetTimeout;
    private readonly ILogger<FetchCircuitBreaker> _logger;

    // In-memory state - consider Redis for distributed workers
    private readonly ConcurrentDictionary<string, CircuitData> _states = new();

    public FetchCircuitBreaker(
        int failureThreshold = 5, 
        TimeSpan? breakDuration = null,
        TimeSpan? resetTimeout = null,
        ILogger<FetchCircuitBreaker>? logger = null)
    {
        _failureThreshold = Math.Max(1, failureThreshold);
        _breakDuration = breakDuration ?? TimeSpan.FromMinutes(5);
        _resetTimeout = resetTimeout ?? TimeSpan.FromMinutes(30);
        _logger = logger ?? NullLogger<FetchCircuitBreaker>.Instance;
    }

    /// <inheritdoc />
    public bool IsOpen(string sourceId, string? url = null)
    {
        var key = BuildKey(sourceId, url);
        
        if (!_states.TryGetValue(key, out var data))
            return false;

        // Auto-reset if the break duration has passed
        if (data.IsOpen && DateTime.UtcNow >= data.OpenUntil)
        {
            if (_states.TryRemove(key, out _))
            {
                _logger.LogInformation(
                    "Circuit breaker auto-reset for {SourceId} (URL: {Url})",
                    sourceId, url ?? "N/A");
            }
            return false;
        }

        return data.IsOpen;
    }

    /// <inheritdoc />
    public void RecordFailure(string sourceId, string? url = null)
    {
        var key = BuildKey(sourceId, url);
        var now = DateTime.UtcNow;
        
        var data = _states.AddOrUpdate(key,
            _ => new CircuitData 
            { 
                FailureCount = 1, 
                LastFailureAt = now 
            },
            (_, existing) =>
            {
                // Check if we should reset the counter (failures are too spread out)
                if (existing.LastFailureAt.HasValue &&
                    (now - existing.LastFailureAt.Value) > _resetTimeout)
                {
                    _logger.LogDebug(
                        "Resetting failure counter for {SourceId} - last failure was {Minutes:F0} minutes ago",
                        sourceId, (now - existing.LastFailureAt.Value).TotalMinutes);
                    
                    return new CircuitData 
                    { 
                        FailureCount = 1, 
                        LastFailureAt = now 
                    };
                }

                return existing with 
                { 
                    FailureCount = existing.FailureCount + 1,
                    LastFailureAt = now
                };
            });

        // Open circuit if threshold reached
        if (!data.IsOpen && data.FailureCount >= _failureThreshold)
        {
            var openUntil = now.Add(_breakDuration);
            var newData = data with 
            { 
                IsOpen = true, 
                OpenedAt = now,
                OpenUntil = openUntil
            };
            
            _states[key] = newData;
            
            _logger.LogWarning(
                "Circuit breaker OPEN for {SourceId} (URL: {Url}) after {Count} failures. " +
                "Open until {OpenUntil:HH:mm:ss} ({Duration} minutes)",
                sourceId, url ?? "N/A", data.FailureCount, openUntil, _breakDuration.TotalMinutes);

            // Emit metric
            PipelineTelemetry.RecordCounter("fetch.circuit_breaker.open", 1,
                new KeyValuePair<string, object?>("source_id", sourceId));
        }
    }

    /// <inheritdoc />
    public void RecordSuccess(string sourceId, string? url = null)
    {
        var key = BuildKey(sourceId, url);
        
        if (_states.TryRemove(key, out var data) && data.FailureCount > 0)
        {
            _logger.LogDebug(
                "Circuit breaker reset for {SourceId} (URL: {Url}) after success. " +
                "Previous failures: {Count}",
                sourceId, url ?? "N/A", data.FailureCount);
        }
    }

    /// <inheritdoc />
    public CircuitState? GetState(string sourceId, string? url = null)
    {
        var key = BuildKey(sourceId, url);
        
        if (!_states.TryGetValue(key, out var data))
            return null;

        return new CircuitState
        {
            IsOpen = data.IsOpen,
            FailureCount = data.FailureCount,
            OpenedAt = data.OpenedAt,
            OpenUntil = data.OpenUntil,
            LastFailureAt = data.LastFailureAt
        };
    }

    /// <summary>
    /// Gets statistics for all tracked circuits.
    /// </summary>
    public CircuitStats GetStats()
    {
        var states = _states.Values.ToList();
        
        return new CircuitStats
        {
            TotalTracked = states.Count,
            OpenCircuits = states.Count(s => s.IsOpen),
            TotalFailures = states.Sum(s => s.FailureCount),
            BySource = _states
                .GroupBy(kvp => kvp.Key.Split(':')[0])
                .ToDictionary(
                    g => g.Key, 
                    g => new SourceCircuitStats
                    {
                        Circuits = g.Count(),
                        OpenCircuits = g.Count(x => x.Value.IsOpen),
                        TotalFailures = g.Sum(x => x.Value.FailureCount)
                    })
        };
    }

    private static string BuildKey(string sourceId, string? url)
    {
        if (string.IsNullOrEmpty(url))
            return sourceId;
        
        // Use hash of URL to keep key size reasonable
        var urlHash = url.GetHashCode().ToString("x8");
        return $"{sourceId}:{urlHash}";
    }

    private record CircuitData
    {
        public int FailureCount { get; init; }
        public bool IsOpen { get; init; }
        public DateTime? OpenedAt { get; init; }
        public DateTime? OpenUntil { get; init; }
        public DateTime? LastFailureAt { get; init; }
    }
}

/// <summary>
/// Statistics for circuit breakers.
/// </summary>
public class CircuitStats
{
    public int TotalTracked { get; init; }
    public int OpenCircuits { get; init; }
    public int TotalFailures { get; init; }
    public Dictionary<string, SourceCircuitStats> BySource { get; init; } = new();
}

public class SourceCircuitStats
{
    public int Circuits { get; init; }
    public int OpenCircuits { get; init; }
    public int TotalFailures { get; init; }
}
