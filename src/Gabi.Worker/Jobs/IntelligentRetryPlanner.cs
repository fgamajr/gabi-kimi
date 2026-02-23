using Gabi.Contracts.Common;

namespace Gabi.Worker.Jobs;

public enum RetryDecision
{
    ScheduleRetry,
    MoveToDlq
}

public readonly record struct RetryPlan(RetryDecision Decision, TimeSpan Delay);

public static class IntelligentRetryPlanner
{
    public static RetryPlan Plan(ErrorClassification classification, int retryCount, int maxRetries)
    {
        var normalizedMaxRetries = Math.Max(1, maxRetries);

        if (classification.Category is ErrorCategory.Permanent or ErrorCategory.Bug)
            return new RetryPlan(RetryDecision.MoveToDlq, TimeSpan.Zero);

        if (retryCount >= normalizedMaxRetries)
            return new RetryPlan(RetryDecision.MoveToDlq, TimeSpan.Zero);

        if (classification.Category == ErrorCategory.Throttled)
            return new RetryPlan(RetryDecision.ScheduleRetry, TimeSpan.FromMinutes(15));

        var exponent = Math.Max(0, retryCount);
        var seconds = (int)Math.Pow(2, exponent);
        seconds = Math.Clamp(seconds, 1, 60);

        return new RetryPlan(RetryDecision.ScheduleRetry, TimeSpan.FromSeconds(seconds));
    }
}
