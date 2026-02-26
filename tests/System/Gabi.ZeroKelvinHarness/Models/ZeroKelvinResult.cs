namespace Gabi.ZeroKelvinHarness.Models;

/// <summary>
/// Machine-readable result of a Zero-Kelvin pipeline run. The harness never asserts; xUnit evaluates these fields.
/// </summary>
public sealed record ZeroKelvinResult
{
    public required TimeSpan Duration { get; init; }
    public required double PeakMemoryMb { get; init; }
    public required int Retries { get; init; }
    public required int DlqEntries { get; init; }
    public required Dictionary<string, int> StageCounts { get; init; }
    public required double LossRate { get; init; }
    public required double DuplicationRate { get; init; }
    public required double CorruptionRate { get; init; }
    public required double SemanticPreservationScore { get; init; }
    public bool Crashed { get; init; }
    public string? ErrorSummary { get; init; }
}
