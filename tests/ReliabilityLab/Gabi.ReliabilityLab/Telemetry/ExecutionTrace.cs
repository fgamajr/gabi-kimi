namespace Gabi.ReliabilityLab.Telemetry;

public sealed record TraceSpan
{
    public required string Name { get; init; }
    public required DateTimeOffset Start { get; init; }
    public required DateTimeOffset End { get; init; }
    public TimeSpan Duration => End - Start;
    public IReadOnlyDictionary<string, string> Tags { get; init; } = new Dictionary<string, string>();
}

public sealed record ExecutionTrace
{
    public required string CorrelationId { get; init; }
    public required IReadOnlyList<TraceSpan> Spans { get; init; }
}
