using Gabi.Contracts.Common;
using Gabi.Worker.Jobs;

namespace Gabi.Postgres.Tests;

public class IntelligentRetryPlannerTests
{
    [Fact]
    public void Plan_ForPermanent_ShouldMoveToDlqImmediately()
    {
        var classification = new ErrorClassification(ErrorCategory.Permanent, "HTTP_404", "not found");

        var plan = IntelligentRetryPlanner.Plan(classification, retryCount: 0, maxRetries: 3);

        Assert.Equal(RetryDecision.MoveToDlq, plan.Decision);
        Assert.Equal(TimeSpan.Zero, plan.Delay);
    }

    [Fact]
    public void Plan_ForThrottled_ShouldUse15MinutesDelay()
    {
        var classification = new ErrorClassification(ErrorCategory.Throttled, "HTTP_429", "rate limited");

        var plan = IntelligentRetryPlanner.Plan(classification, retryCount: 1, maxRetries: 3);

        Assert.Equal(RetryDecision.ScheduleRetry, plan.Decision);
        Assert.Equal(TimeSpan.FromMinutes(15), plan.Delay);
    }

    [Fact]
    public void Plan_ForTransient_ShouldUseExponentialBackoff()
    {
        var classification = new ErrorClassification(ErrorCategory.Transient, "TIMEOUT", "timeout");

        var plan = IntelligentRetryPlanner.Plan(classification, retryCount: 2, maxRetries: 3);

        Assert.Equal(RetryDecision.ScheduleRetry, plan.Decision);
        Assert.Equal(TimeSpan.FromSeconds(4), plan.Delay);
    }

    [Fact]
    public void Plan_ForBug_ShouldMoveToDlqImmediately()
    {
        var classification = new ErrorClassification(ErrorCategory.Bug, "NULL_REFERENCE", "boom");

        var plan = IntelligentRetryPlanner.Plan(classification, retryCount: 0, maxRetries: 3);

        Assert.Equal(RetryDecision.MoveToDlq, plan.Decision);
    }
}
