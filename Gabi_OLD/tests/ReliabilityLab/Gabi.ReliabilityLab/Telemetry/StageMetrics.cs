namespace Gabi.ReliabilityLab.Telemetry;

public sealed record StageMetrics
{
    public required string StageName { get; init; }
    public required TimeSpan Duration { get; init; }
    public int ItemCount { get; init; }
    public double ThroughputPerSecond { get; init; }
}
