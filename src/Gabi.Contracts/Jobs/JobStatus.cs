namespace Gabi.Contracts.Jobs;

/// <summary>
/// Status of a job in the queue.
/// </summary>
public enum JobStatus
{
    /// <summary>Job is waiting to be processed.</summary>
    Pending,
    
    /// <summary>Job is currently being processed by a worker.</summary>
    Running,
    
    /// <summary>Job completed successfully.</summary>
    Completed,
    
    /// <summary>Job failed and will be retried or moved to DLQ.</summary>
    Failed,
    
    /// <summary>Job was cancelled manually or by timeout.</summary>
    Cancelled,
    
    /// <summary>Job was skipped (e.g., duplicate or no changes).</summary>
    Skipped,
    
    /// <summary>Job is scheduled for retry.</summary>
    Retrying
}
