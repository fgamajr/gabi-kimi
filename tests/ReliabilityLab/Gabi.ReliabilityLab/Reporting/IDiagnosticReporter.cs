using Gabi.ReliabilityLab.Experiment;
using Gabi.ReliabilityLab.Policy;

namespace Gabi.ReliabilityLab.Reporting;

public interface IDiagnosticReporter
{
    Task<string> GenerateAsync(string artifactRoot, ExperimentResult result, PolicyVerdict verdict, CancellationToken ct = default);
}
