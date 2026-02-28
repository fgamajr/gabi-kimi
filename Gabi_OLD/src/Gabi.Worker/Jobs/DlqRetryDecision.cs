namespace Gabi.Worker.Jobs;

public static class DlqRetryDecision
{
    public static bool ShouldMoveToDlq(int retryCount, int maxRetries)
    {
        var normalizedMaxRetries = Math.Max(1, maxRetries);
        return retryCount >= normalizedMaxRetries;
    }

    public static int ToObservedAttempts(int retryCount)
        => retryCount + 1;
}
