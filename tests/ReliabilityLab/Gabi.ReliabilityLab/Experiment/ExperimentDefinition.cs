namespace Gabi.ReliabilityLab.Experiment;

public sealed record ExperimentDefinition
{
    public required string Name { get; init; }
    public string Version { get; init; } = "1.0.0";
    public int RandomSeed { get; init; } = 42;
    public TimeSpan Timeout { get; init; } = TimeSpan.FromMinutes(10);
    public IReadOnlyDictionary<string, object> Parameters { get; init; } = new Dictionary<string, object>();
    public IReadOnlyDictionary<string, string> Metadata { get; init; } = new Dictionary<string, string>();
}
