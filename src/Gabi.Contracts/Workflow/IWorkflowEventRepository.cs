namespace Gabi.Contracts.Workflow;

/// <summary>
/// Persists pipeline stage history events (append-only, best-effort observability).
/// Implementations must never throw — failures are silently swallowed.
/// </summary>
public interface IWorkflowEventRepository
{
    /// <summary>
    /// Emits an event to workflow_events. Best-effort: callers fire-and-forget this.
    /// </summary>
    Task EmitAsync(
        Guid correlationId,
        Guid jobId,
        string sourceId,
        string jobType,
        string eventType,
        IReadOnlyDictionary<string, object>? metadata,
        CancellationToken ct = default);
}
