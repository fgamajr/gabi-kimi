namespace Gabi.ReliabilityLab.Environment;

/// <summary>
/// Health status of each infrastructure component.
/// </summary>
public sealed record ReadinessSnapshot
{
    public required bool PostgreSql { get; init; }
    public required bool Redis { get; init; }
    public required bool Elasticsearch { get; init; }
    public bool AllReady => PostgreSql && Redis && Elasticsearch;
}
