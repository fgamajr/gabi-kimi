using Gabi.Contracts.Errors;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Plans retry strategies based on error classification.
/// Uses exponential backoff with jitter for transient errors,
/// and immediate DLQ routing for permanent errors.
/// </summary>
public static class IntelligentRetryPlanner
{
    /// <summary>
    /// Determines the retry plan based on error classification and retry history.
    /// </summary>
    /// <param name="classification">The error classification</param>
    /// <param name="retryCount">Current retry count (0-based)</param>
    /// <param name="maxRetries">Maximum number of retry attempts</param>
    /// <param name="backoffOptions">Backoff configuration options</param>
    /// <returns>Retry plan with decision and delay</returns>
    public static RetryPlan Plan(
        ErrorClassification classification, 
        int retryCount, 
        int maxRetries,
        BackoffOptions? backoffOptions = null)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(retryCount);
        var normalizedMaxRetries = Math.Max(1, maxRetries);

        // Permanent errors and bugs go straight to DLQ - no point retrying
        if (classification.Category is ErrorCategory.Permanent or ErrorCategory.Bug)
        {
            return new RetryPlan(RetryDecision.MoveToDlq, TimeSpan.Zero);
        }

        // Non-recoverable auth errors go to DLQ (e.g., 403 Forbidden)
        if (classification.Category == ErrorCategory.Authentication && !classification.IsRecoverable)
        {
            return new RetryPlan(RetryDecision.MoveToDlq, TimeSpan.Zero);
        }

        // Max retries exhausted - move to DLQ for manual inspection
        if (retryCount >= normalizedMaxRetries)
        {
            return new RetryPlan(RetryDecision.MoveToDlq, TimeSpan.Zero);
        }

        // Calculate jittered backoff delay
        var delay = ExponentialBackoffCalculator.Calculate(
            retryCount, 
            classification.Category,
            backoffOptions);

        return new RetryPlan(RetryDecision.ScheduleRetry, delay);
    }

    /// <summary>
    /// Plans a retry with source-specific considerations (e.g., circuit breaker state).
    /// </summary>
    public static RetryPlan PlanWithCircuitBreaker(
        ErrorClassification classification,
        int retryCount,
        int maxRetries,
        ICircuitBreaker circuitBreaker,
        string sourceId,
        string? url = null,
        BackoffOptions? backoffOptions = null)
    {
        // Check circuit breaker first
        if (circuitBreaker.IsOpen(sourceId, url))
        {
            // Circuit is open - don't retry immediately
            // Return a delay that will push the retry past the circuit reset time
            var circuitState = circuitBreaker.GetState(sourceId, url);
            if (circuitState?.OpenUntil != null)
            {
                var waitUntil = circuitState.OpenUntil.Value.Add(TimeSpan.FromSeconds(30));
                var delay = waitUntil - DateTime.UtcNow;
                if (delay > TimeSpan.Zero)
                {
                    return new RetryPlan(RetryDecision.ScheduleRetry, delay);
                }
            }
        }

        return Plan(classification, retryCount, maxRetries, backoffOptions);
    }

    /// <summary>
    /// Gets a human-readable description of the retry plan.
    /// </summary>
    public static string Describe(RetryPlan plan, ErrorClassification classification)
    {
        if (plan.Decision == RetryDecision.MoveToDlq)
        {
            var reason = classification.Category switch
            {
                ErrorCategory.Permanent => "permanent error",
                ErrorCategory.Bug => "code defect",
                ErrorCategory.Authentication when !classification.IsRecoverable => "auth failure (non-recoverable)",
                _ => "max retries exceeded"
            };

            return $"Move to DLQ: {reason}. Action: {classification.SuggestedAction}";
        }

        var categoryDesc = classification.Category switch
        {
            ErrorCategory.Throttled => "rate limited",
            ErrorCategory.Authentication => "auth error (recoverable)",
            ErrorCategory.Transient => "transient failure",
            _ => "retryable error"
        };

        return $"Retry in {plan.Delay.TotalSeconds:F1}s: {categoryDesc}. Action: {classification.SuggestedAction}";
    }
}
