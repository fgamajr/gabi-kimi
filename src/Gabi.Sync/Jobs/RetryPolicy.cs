namespace Gabi.Sync.Jobs;

/// <summary>
/// Retry policy with exponential backoff and jitter.
/// </summary>
public static class RetryPolicy
{
    private static readonly Random Random = new();
    
    /// <summary>
    /// Default base delay for retry calculations.
    /// </summary>
    public static readonly TimeSpan DefaultBaseDelay = TimeSpan.FromSeconds(30);
    
    /// <summary>
    /// Default maximum delay between retries.
    /// </summary>
    public static readonly TimeSpan DefaultMaxDelay = TimeSpan.FromMinutes(10);
    
    /// <summary>
    /// Default maximum number of retry attempts.
    /// </summary>
    public const int DefaultMaxRetries = 3;
    
    /// <summary>
    /// Calculates the delay for a retry attempt using exponential backoff with jitter.
    /// Formula: baseDelay * 2^retryCount + jitter(-25% to +25%)
    /// </summary>
    /// <param name="retryCount">Current retry attempt (0-based).</param>
    /// <param name="baseDelay">Base delay between retries.</param>
    /// <param name="maxDelay">Maximum delay cap.</param>
    /// <param name="addJitter">Whether to add random jitter.</param>
    /// <returns>The calculated delay.</returns>
    public static TimeSpan CalculateDelay(
        int retryCount,
        TimeSpan? baseDelay = null,
        TimeSpan? maxDelay = null,
        bool addJitter = true)
    {
        var baseValue = baseDelay ?? DefaultBaseDelay;
        var maxValue = maxDelay ?? DefaultMaxDelay;
        
        // Exponential: 30s, 60s, 120s, 240s...
        var delay = baseValue * Math.Pow(2, retryCount);
        
        // Cap at max delay
        if (delay > maxValue)
            delay = maxValue;
        
        // Add jitter (±25%) to prevent thundering herd
        if (addJitter)
        {
            var jitter = Random.NextDouble() * 0.5 - 0.25; // -25% to +25%
            delay = delay * (1 + jitter);
        }
        
        return TimeSpan.FromSeconds(Math.Max(1, delay.TotalSeconds));
    }
    
    /// <summary>
    /// Calculates the scheduled time for the next retry attempt.
    /// </summary>
    /// <param name="retryCount">Current retry attempt (0-based).</param>
    /// <param name="baseDelay">Base delay between retries.</param>
    /// <param name="maxDelay">Maximum delay cap.</param>
    /// <param name="addJitter">Whether to add random jitter.</param>
    /// <returns>The UTC time when the job should be retried.</returns>
    public static DateTime CalculateNextRetryTime(
        int retryCount,
        TimeSpan? baseDelay = null,
        TimeSpan? maxDelay = null,
        bool addJitter = true)
    {
        var delay = CalculateDelay(retryCount, baseDelay, maxDelay, addJitter);
        return DateTime.UtcNow.Add(delay);
    }
    
    /// <summary>
    /// Checks if a job should be retried based on its current retry count and max retries.
    /// </summary>
    /// <param name="currentRetryCount">Current retry count.</param>
    /// <param name="maxRetries">Maximum allowed retries.</param>
    /// <returns>True if the job should be retried.</returns>
    public static bool ShouldRetry(int currentRetryCount, int maxRetries = DefaultMaxRetries)
    {
        return currentRetryCount < maxRetries;
    }
}
