using System.Diagnostics.Metrics;
using Gabi.Contracts.Errors;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Metrics for fetch error handling and DLQ operations.
/// </summary>
public static class FetchErrorMetrics
{
    private static readonly Meter Meter = new("Gabi.Fetch", "1.0.0");

    // Counters
    public static readonly Counter<long> FetchAttempts = 
        Meter.CreateCounter<long>(
            "fetch.attempts.total", 
            description: "Total number of fetch attempts");
    
    public static readonly Counter<long> FetchFailures = 
        Meter.CreateCounter<long>(
            "fetch.failures.total", 
            description: "Total number of fetch failures");
    
    public static readonly Counter<long> FetchRetries = 
        Meter.CreateCounter<long>(
            "fetch.retries.total", 
            description: "Total number of fetch retry attempts");
    
    public static readonly Counter<long> FetchSuccesses = 
        Meter.CreateCounter<long>(
            "fetch.successes.total", 
            description: "Total number of successful fetches");
    
    public static readonly Counter<long> DlqAdditions = 
        Meter.CreateCounter<long>(
            "fetch.dlq.additions.total", 
            description: "Number of items moved to DLQ");
    
    public static readonly Counter<long> DlqReplays = 
        Meter.CreateCounter<long>(
            "fetch.dlq.replays.total", 
            description: "Number of DLQ items replayed");
    
    public static readonly Counter<long> DlqArchives = 
        Meter.CreateCounter<long>(
            "fetch.dlq.archives.total", 
            description: "Number of DLQ items archived");
    
    public static readonly Counter<long> CircuitBreakerOpen = 
        Meter.CreateCounter<long>(
            "fetch.circuit_breaker.open.total", 
            description: "Number of times circuit breaker opened");
    
    public static readonly Counter<long> CircuitBreakerClose = 
        Meter.CreateCounter<long>(
            "fetch.circuit_breaker.close.total", 
            description: "Number of times circuit breaker closed");

    // Histograms
    public static readonly Histogram<double> RetryDelay = 
        Meter.CreateHistogram<double>(
            "fetch.retry.delay_seconds", 
            unit: "s",
            description: "Delay before retry attempts");
    
    public static readonly Histogram<int> RetryCount = 
        Meter.CreateHistogram<int>(
            "fetch.retry.count", 
            description: "Number of retries before success or DLQ");
    
    public static readonly Histogram<double> RequestDuration = 
        Meter.CreateHistogram<double>(
            "fetch.request.duration_seconds",
            unit: "s", 
            description: "Duration of fetch requests");

    // UpDownCounters (gauges)
    public static readonly UpDownCounter<int> DlqPending = 
        Meter.CreateUpDownCounter<int>(
            "fetch.dlq.pending", 
            description: "Current number of pending DLQ items");
    
    public static readonly UpDownCounter<int> OpenCircuits = 
        Meter.CreateUpDownCounter<int>(
            "fetch.circuit_breaker.open", 
            description: "Number of currently open circuits");

    /// <summary>
    /// Records a fetch failure with categorization.
    /// </summary>
    public static void RecordFailure(ErrorClassification classification, string sourceId, string? url = null)
    {
        var tags = new List<KeyValuePair<string, object?>>
        {
            new("category", classification.Category.ToString().ToLowerInvariant()),
            new("code", classification.Code),
            new("source_id", sourceId),
            new("is_recoverable", classification.IsRecoverable)
        };

        if (!string.IsNullOrEmpty(url))
        {
            // Hash URL to avoid high cardinality
            tags.Add(new KeyValuePair<string, object?>("url_hash", url.GetHashCode().ToString("x8")));
        }

        FetchFailures.Add(1, tags.ToArray());
    }

    /// <summary>
    /// Records a DLQ addition.
    /// </summary>
    public static void RecordDlqAddition(ErrorClassification classification, string sourceId)
    {
        DlqAdditions.Add(1,
            new KeyValuePair<string, object?>("category", classification.Category.ToString().ToLowerInvariant()),
            new KeyValuePair<string, object?>("code", classification.Code),
            new KeyValuePair<string, object?>("recoverable", classification.IsRecoverable),
            new KeyValuePair<string, object?>("source_id", sourceId));
        
        DlqPending.Up(1,
            new KeyValuePair<string, object?>("category", classification.Category.ToString().ToLowerInvariant()));
    }

    /// <summary>
    /// Records a DLQ replay.
    /// </summary>
    public static void RecordDlqReplay(string category, bool success)
    {
        DlqReplays.Add(1,
            new KeyValuePair<string, object?>("category", category),
            new KeyValuePair<string, object?>("success", success));
        
        DlqPending.Down(1,
            new KeyValuePair<string, object?>("category", category));
    }

    /// <summary>
    /// Records a circuit breaker opening.
    /// </summary>
    public static void RecordCircuitOpen(string sourceId)
    {
        CircuitBreakerOpen.Add(1,
            new KeyValuePair<string, object?>("source_id", sourceId));
        
        OpenCircuits.Up(1,
            new KeyValuePair<string, object?>("source_id", sourceId));
    }

    /// <summary>
    /// Records a circuit breaker closing.
    /// </summary>
    public static void RecordCircuitClose(string sourceId)
    {
        CircuitBreakerClose.Add(1,
            new KeyValuePair<string, object?>("source_id", sourceId));
        
        OpenCircuits.Down(1,
            new KeyValuePair<string, object?>("source_id", sourceId));
    }

    /// <summary>
    /// Records retry delay.
    /// </summary>
    public static void RecordRetryDelay(TimeSpan delay, ErrorCategory category)
    {
        RetryDelay.Record(delay.TotalSeconds,
            new KeyValuePair<string, object?>("category", category.ToString().ToLowerInvariant()));
    }

    /// <summary>
    /// Records the final retry count for an operation.
    /// </summary>
    public static void RecordRetryCount(int count, ErrorCategory category, bool success)
    {
        RetryCount.Record(count,
            new KeyValuePair<string, object?>("category", category.ToString().ToLowerInvariant()),
            new KeyValuePair<string, object?>("success", success));
    }
}
