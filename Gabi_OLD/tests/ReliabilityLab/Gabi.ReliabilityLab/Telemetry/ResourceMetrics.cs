namespace Gabi.ReliabilityLab.Telemetry;

public sealed record ResourceMetrics
{
    public double PeakMemoryMb { get; init; }
    public int Gen0Collections { get; init; }
    public int Gen1Collections { get; init; }
    public int Gen2Collections { get; init; }
}
