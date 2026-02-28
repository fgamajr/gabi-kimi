using Gabi.Contracts.Jobs;

namespace Gabi.Jobs;

/// <summary>
/// Manages state transitions for ingestion jobs.
/// </summary>
public interface IJobStateMachine
{
    /// <summary>
    /// Gets valid transitions from a given status.
    /// </summary>
    IReadOnlyList<JobStatus> GetValidTransitions(JobStatus currentStatus);

    /// <summary>
    /// Transitions a job to a new status.
    /// </summary>
    /// <param name="job">The job to transition</param>
    /// <param name="toStatus">Target status</param>
    /// <param name="context">Additional context (workerId, errorMessage, etc.)</param>
    /// <param name="cancellationToken">Cancellation token</param>
    /// <returns>The updated job</returns>
    /// <exception cref="InvalidOperationException">If transition is invalid</exception>
    Task<IngestJob> TransitionAsync(
        IngestJob job, 
        JobStatus toStatus, 
        string? context,
        CancellationToken cancellationToken);

    /// <summary>
    /// Event raised when a transition occurs.
    /// </summary>
    event EventHandler<JobTransitionEvent>? OnTransition;
}

/// <summary>
/// Event args for job transition events.
/// </summary>
public class JobTransitionEvent : EventArgs
{
    public Guid JobId { get; init; }
    public JobStatus FromStatus { get; init; }
    public JobStatus ToStatus { get; init; }
    public DateTime TransitionedAt { get; init; } = DateTime.UtcNow;
    public string? WorkerId { get; init; }
}
