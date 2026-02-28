namespace Gabi.Contracts.Errors;

/// <summary>
/// Categories of errors for retry and handling decisions.
/// </summary>
public enum ErrorCategory
{
    /// <summary>Network issues, 5xx errors, timeouts - retryable</summary>
    Transient,
    
    /// <summary>Rate limiting (429) - retryable with longer delay</summary>
    Throttled,
    
    /// <summary>Permanent failures (404, malformed data) - don't retry</summary>
    Permanent,
    
    /// <summary>Authentication errors (401, 403) - may require manual intervention</summary>
    Authentication,
    
    /// <summary>Code defects - don't retry, needs bug fix</summary>
    Bug
}

/// <summary>
/// Structured error classification result with recovery guidance.
/// </summary>
public readonly record struct ErrorClassification(
    ErrorCategory Category, 
    string Code, 
    string Message,
    bool IsRecoverable = true,
    string? SuggestedAction = null);

/// <summary>
/// Context for error classification to enable smarter decisions.
/// </summary>
public record ErrorContext
{
    public string? Url { get; init; }
    public string? SourceId { get; init; }
    public int RetryCount { get; init; }
    public TimeSpan? RequestDuration { get; init; }
    public DateTime? FirstFailedAt { get; init; }
    public TimeSpan? TotalRetryDuration { get; init; }
}

/// <summary>
/// Retry decision types.
/// </summary>
public enum RetryDecision
{
    ScheduleRetry,
    MoveToDlq
}

/// <summary>
/// Retry plan with decision and delay.
/// </summary>
public readonly record struct RetryPlan(RetryDecision Decision, TimeSpan Delay);

/// <summary>
/// Configuration options for exponential backoff calculation.
/// </summary>
public sealed class BackoffOptions
{
    public TimeSpan BaseDelay { get; init; } = TimeSpan.FromSeconds(1);
    public TimeSpan ThrottledBaseDelay { get; init; } = TimeSpan.FromMinutes(5);
    public TimeSpan AuthBaseDelay { get; init; } = TimeSpan.FromMinutes(1);
    public TimeSpan MaxDelay { get; init; } = TimeSpan.FromHours(1);

    public static BackoffOptions Default { get; } = new();
}
