using Gabi.Contracts.Jobs;

namespace Gabi.Jobs;

/// <summary>
/// Implementation of job state machine following state transition rules.
/// </summary>
public class JobStateMachine : IJobStateMachine
{
    // Define valid state transitions
    private static readonly Dictionary<JobStatus, JobStatus[]> ValidTransitions = new()
    {
        [JobStatus.Pending] = new[] { JobStatus.Running, JobStatus.Skipped, JobStatus.Cancelled },
        [JobStatus.Running] = new[] { JobStatus.Completed, JobStatus.Failed, JobStatus.Cancelled },
        [JobStatus.Failed] = new[] { JobStatus.Pending }, // For retry
        [JobStatus.Completed] = Array.Empty<JobStatus>(), // Terminal state
        [JobStatus.Skipped] = Array.Empty<JobStatus>(),   // Terminal state
        [JobStatus.Cancelled] = Array.Empty<JobStatus>(), // Terminal state
        [JobStatus.Retrying] = new[] { JobStatus.Running, JobStatus.Failed }
    };

    public event EventHandler<JobTransitionEvent>? OnTransition;

    public IReadOnlyList<JobStatus> GetValidTransitions(JobStatus currentStatus)
    {
        if (ValidTransitions.TryGetValue(currentStatus, out var transitions))
        {
            return transitions;
        }
        return Array.Empty<JobStatus>();
    }

    public Task<IngestJob> TransitionAsync(
        IngestJob job, 
        JobStatus toStatus, 
        string? context,
        CancellationToken cancellationToken)
    {
        // Validate transition
        var validTransitions = GetValidTransitions(job.Status);
        if (!validTransitions.Contains(toStatus))
        {
            throw new InvalidOperationException(
                $"Cannot transition from {job.Status} to {toStatus}. " +
                $"Valid transitions: {string.Join(", ", validTransitions)}");
        }

        var fromStatus = job.Status;
        IngestJob updatedJob;

        // Apply transition-specific updates
        switch (toStatus)
        {
            case JobStatus.Running:
                updatedJob = job with 
                { 
                    Status = toStatus,
                    WorkerId = context,
                    StartedAt = DateTime.UtcNow
                };
                break;

            case JobStatus.Completed:
                updatedJob = job with 
                { 
                    Status = toStatus,
                    CompletedAt = DateTime.UtcNow
                };
                break;

            case JobStatus.Failed:
                updatedJob = job with 
                { 
                    Status = toStatus,
                    ErrorMessage = context,
                    CompletedAt = DateTime.UtcNow
                };
                break;

            case JobStatus.Pending when fromStatus == JobStatus.Failed:
                // Retry scenario
                updatedJob = job with 
                { 
                    Status = toStatus,
                    RetryCount = job.RetryCount + 1,
                    RetryAt = DateTime.UtcNow.AddMinutes(CalculateBackoffMinutes(job.RetryCount + 1))
                };
                break;

            case JobStatus.Skipped:
            case JobStatus.Cancelled:
                updatedJob = job with 
                { 
                    Status = toStatus,
                    CompletedAt = DateTime.UtcNow
                };
                break;

            default:
                updatedJob = job with { Status = toStatus };
                break;
        }

        // Raise event
        OnTransition?.Invoke(this, new JobTransitionEvent
        {
            JobId = updatedJob.Id,
            FromStatus = fromStatus,
            ToStatus = toStatus,
            WorkerId = updatedJob.WorkerId,
            TransitionedAt = DateTime.UtcNow
        });

        return Task.FromResult(updatedJob);
    }

    private static int CalculateBackoffMinutes(int retryCount)
    {
        // Exponential backoff: 1, 2, 4, 8, 15, 30, 60 minutes
        return retryCount switch
        {
            1 => 1,
            2 => 2,
            3 => 4,
            4 => 8,
            5 => 15,
            6 => 30,
            _ => 60
        };
    }
}
