using Gabi.ReliabilityLab.Experiment;
using Gabi.ReliabilityLab.Policy;

namespace Gabi.ReliabilityLab.Reporting;

public sealed record RunSummary(
    string CorrelationId,
    string ExperimentName,
    DateTimeOffset StartedAt,
    DateTimeOffset CompletedAt,
    bool VerdictPassed,
    IReadOnlyList<string> ViolationSummaries,
    string ArtifactPath);
