namespace Gabi.Contracts.Errors;

/// <summary>
/// Calculates retry delays using exponential backoff with decorrelated jitter.
/// 
/// Uses the "full jitter" algorithm to prevent thundering herd:
/// delay = random(base_delay, min(max_delay, base_delay * 2^retryCount * 3))
/// 
/// Reference: AWS Architecture Blog - Exponential Backoff and Jitter
/// </summary>
public static class ExponentialBackoffCalculator
{
    // ThreadLocal Random to avoid contention in concurrent scenarios
    private static readonly ThreadLocal<Random> Random = new(() => new Random());

    /// <summary>
    /// Calculates the backoff delay for a retry attempt.
    /// </summary>
    /// <param name="retryCount">Zero-based retry count (0 = first retry)</param>
    /// <param name="category">Error category for category-specific delays</param>
    /// <param name="options">Backoff options, or default if null</param>
    /// <returns>Jittered delay duration</returns>
    public static TimeSpan Calculate(
        int retryCount, 
        ErrorCategory category,
        BackoffOptions? options = null)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(retryCount);

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
        var maxForAttempt = baseDelay * exponential;
        
        // Apply full jitter: random value between base and maxForAttempt * 3
        // The 3x multiplier provides decorrelation between clients
        var minMs = baseDelay.TotalMilliseconds;
        var maxMs = Math.Min(maxForAttempt.TotalMilliseconds * 3, opts.MaxDelay.TotalMilliseconds);
        
        var jitteredMs = minMs + (Random.Value!.NextDouble() * (maxMs - minMs));
        
        return TimeSpan.FromMilliseconds(jitteredMs);
    }

    /// <summary>
    /// Calculates multiple backoff delays for planning purposes.
    /// </summary>
    public static IReadOnlyList<TimeSpan> CalculateSchedule(
        int maxRetries,
        ErrorCategory category,
        BackoffOptions? options = null)
    {
        var schedule = new List<TimeSpan>(maxRetries);
        for (int i = 0; i < maxRetries; i++)
        {
            schedule.Add(Calculate(i, category, options));
        }
        return schedule;
    }
}
