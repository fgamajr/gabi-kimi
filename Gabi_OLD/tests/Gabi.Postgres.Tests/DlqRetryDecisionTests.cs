using Gabi.Worker.Jobs;
using Xunit;

namespace Gabi.Postgres.Tests;

public class DlqRetryDecisionTests
{
    [Theory]
    [InlineData(0, 3, false)]
    [InlineData(1, 3, false)]
    [InlineData(2, 3, false)]
    [InlineData(3, 3, true)]
    public void ShouldMoveToDlq_ShouldMoveOnlyWhenHangfireRetriesAreExhausted(int retryCount, int maxRetries, bool expected)
    {
        var actual = DlqRetryDecision.ShouldMoveToDlq(retryCount, maxRetries);
        Assert.Equal(expected, actual);
    }
}
