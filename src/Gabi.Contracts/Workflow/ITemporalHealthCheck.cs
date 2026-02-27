namespace Gabi.Contracts.Workflow;

/// <summary>
/// Checks whether the Temporal server is reachable within a timeout.
/// Used by HangfireJobQueueRepository to implement fail-closed Temporal dispatch.
/// </summary>
public interface ITemporalHealthCheck
{
    /// <summary>Returns true if Temporal is reachable within <paramref name="timeout"/>.</summary>
    Task<bool> IsReachableAsync(TimeSpan timeout, CancellationToken ct);
}
