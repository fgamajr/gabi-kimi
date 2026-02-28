namespace Gabi.ZeroKelvinHarness.Models;

/// <summary>
/// Result of verifying a single sampled document (source vs stored).
/// </summary>
public sealed record SampleResult
{
    public string ExternalId { get; init; } = string.Empty;
    public string SourceId { get; init; } = string.Empty;
    public bool Missing { get; init; }
    public bool Duplicate { get; init; }
    public bool Truncated { get; init; }
    public double SemanticSimilarity { get; init; }
    public string Classification { get; init; } = string.Empty; // preserved | degraded | corrupted
}
