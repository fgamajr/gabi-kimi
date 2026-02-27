using Gabi.Contracts.Jobs;

namespace Gabi.Contracts.Workflow;

/// <summary>
/// Dispatches jobs to a durable workflow engine (Temporal).
/// Registered in DI only when EnableTemporalWorker=true.
/// </summary>
public interface IWorkflowOrchestrator
{
    Task<Guid> StartAsync(IngestJob job, CancellationToken ct);
    Task SignalPauseAsync(string sourceId, string jobType, CancellationToken ct);
    Task SignalStopAsync(string sourceId, string jobType, CancellationToken ct);
}
