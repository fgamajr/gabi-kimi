namespace Gabi.Worker.Jobs;

public sealed class HangfireRetryPolicyOptions
{
    public const string SectionName = "Hangfire:RetryPolicy";

    public int Attempts { get; set; } = 3;

    public int[] DelaysInSeconds { get; set; } = [2, 8, 30];

    public (int Attempts, int[] DelaysInSeconds) Normalize()
    {
        var attempts = Attempts < 0 ? 0 : Attempts;
        var delays = DelaysInSeconds?.Where(d => d >= 0).ToArray() ?? [];
        return (attempts, delays);
    }
}
