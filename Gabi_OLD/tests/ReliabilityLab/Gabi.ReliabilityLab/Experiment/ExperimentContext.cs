using Gabi.ReliabilityLab.Determinism;
using Gabi.ReliabilityLab.Environment;
using Gabi.ReliabilityLab.Telemetry;
using Microsoft.Extensions.Logging;

namespace Gabi.ReliabilityLab.Experiment;

/// <summary>
/// Runtime context for an experiment. Provides services to stage executors.
/// </summary>
public sealed class ExperimentContext
{
    public required string CorrelationId { get; init; }
    public required IClock Clock { get; init; }
    public required DeterministicRandom Random { get; init; }
    public required ITelemetrySink Telemetry { get; init; }
    public required ILogger Logger { get; init; }
    public required EnvironmentConnectionInfo Environment { get; init; }
    public required ExperimentDefinition Definition { get; init; }
}
