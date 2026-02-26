namespace Gabi.ReliabilityLab.Pipeline.Scenarios;

public sealed class ZeroKelvinConfig
{
    public int MaxDocs { get; init; } = 1000;
    public string? SourceId { get; init; }
    public IReadOnlyList<string> Phases { get; init; } = new[] { "seed", "discovery", "fetch", "ingest" };
    public int SampleSize { get; init; } = 50;
    public TimeSpan PhaseTimeout { get; init; } = TimeSpan.FromMinutes(5);
}
