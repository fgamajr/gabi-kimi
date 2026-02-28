using Gabi.ReliabilityLab.Telemetry;
using Gabi.ReliabilityLab.Verification;

namespace Gabi.ReliabilityLab.Experiment;

/// <summary>
/// Immutable result of an experiment execution. Contains all data needed for post-hoc analysis.
/// </summary>
public sealed record ExperimentResult
{
    public required string ExperimentName { get; init; }
    public required string CorrelationId { get; init; }
    public required DateTimeOffset StartedAt { get; init; }
    public required DateTimeOffset CompletedAt { get; init; }
    public required TimeSpan Duration { get; init; }
    public required bool Crashed { get; init; }
    public string? ErrorSummary { get; init; }
    public required IReadOnlyList<VerificationResult> Verifications { get; init; }
    public required ResourceMetrics Resources { get; init; }
    public required IReadOnlyList<StageMetrics> Stages { get; init; }
    public required ExecutionTrace Trace { get; init; }
    public int RandomSeed { get; init; }
}
