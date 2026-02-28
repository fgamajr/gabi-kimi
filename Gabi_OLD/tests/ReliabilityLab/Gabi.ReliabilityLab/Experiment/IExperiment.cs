using Gabi.ReliabilityLab.Verification;

namespace Gabi.ReliabilityLab.Experiment;

/// <summary>
/// Defines what is tested. Execution engine invokes ExecuteAsync; no pipeline knowledge in core.
/// </summary>
public interface IExperiment
{
    string Name { get; }

    Task ExecuteAsync(ExperimentContext context, CancellationToken ct = default);

    IReadOnlyList<IIntegrityCheck> IntegrityChecks { get; }
    IReadOnlyList<ISemanticCheck> SemanticChecks { get; }
    IReadOnlyList<IConsistencyCheck> ConsistencyChecks { get; }
}
