namespace Gabi.Contracts.Jobs;

/// <summary>
/// Repository interface for the job queue.
/// Provides atomic operations for job management using PostgreSQL SKIP LOCKED.
/// </summary>
public interface IJobQueueRepository
{
    /// <summary>
    /// Adds a new job to the queue.
    /// </summary>
    /// <param name="job">The job to enqueue.</param>
    /// <param name="ct">Cancellation token.</param>
    /// <returns>The ID of the enqueued job.</returns>
    Task<Guid> EnqueueAsync(IngestJob job, CancellationToken ct = default);
    
    /// <summary>
    /// Atomically claims the next available job from the queue using SKIP LOCKED.
    /// </summary>
    /// <param name="workerId">Unique identifier of the worker claiming the job.</param>
    /// <param name="leaseDuration">How long the lease is valid before the job can be reclaimed.</param>
    /// <param name="ct">Cancellation token.</param>
    /// <returns>The claimed job, or null if no jobs available.</returns>
    Task<IngestJob?> DequeueAsync(string workerId, TimeSpan leaseDuration, CancellationToken ct = default);
    
    /// <summary>
    /// Marks a job as completed successfully.
    /// </summary>
    /// <param name="jobId">The job ID.</param>
    /// <param name="ct">Cancellation token.</param>
    Task CompleteAsync(Guid jobId, CancellationToken ct = default);
    
    /// <summary>
    /// Marks a job as failed. Handles retry logic or moves to DLQ if max retries exceeded.
    /// </summary>
    /// <param name="jobId">The job ID.</param>
    /// <param name="error">Error message.</param>
    /// <param name="shouldRetry">Whether the job should be retried.</param>
    /// <param name="ct">Cancellation token.</param>
    Task FailAsync(Guid jobId, string error, bool shouldRetry, CancellationToken ct = default);
    
    /// <summary>
    /// Releases the lease on a job, making it available for other workers.
    /// Used when a worker crashes or needs to abandon a job.
    /// </summary>
    /// <param name="jobId">The job ID.</param>
    /// <param name="ct">Cancellation token.</param>
    Task ReleaseLeaseAsync(Guid jobId, CancellationToken ct = default);
    
    /// <summary>
    /// Updates the heartbeat timestamp for a running job.
    /// </summary>
    /// <param name="jobId">The job ID.</param>
    /// <param name="ct">Cancellation token.</param>
    /// <returns>True if the job is still claimed by this worker.</returns>
    Task<bool> HeartbeatAsync(Guid jobId, CancellationToken ct = default);

    /// <summary>
    /// Updates progress (percent, message, links discovered) for a running job so the frontend can show it.
    /// </summary>
    Task UpdateProgressAsync(Guid jobId, int percent, string? message, int? linksDiscovered, CancellationToken ct = default);
    
    /// <summary>
    /// Gets the current status of a job.
    /// </summary>
    /// <param name="jobId">The job ID.</param>
    /// <param name="ct">Cancellation token.</param>
    /// <returns>The job status, or null if job not found.</returns>
    Task<JobStatus?> GetStatusAsync(Guid jobId, CancellationToken ct = default);
    
    /// <summary>
    /// Cancels a pending or running job.
    /// </summary>
    /// <param name="jobId">The job ID.</param>
    /// <param name="reason">Cancellation reason.</param>
    /// <param name="ct">Cancellation token.</param>
    Task CancelAsync(Guid jobId, string reason, CancellationToken ct = default);
    
    /// <summary>
    /// Recovers jobs that have expired leases (stalled jobs from crashed workers).
    /// </summary>
    /// <param name="stallTimeout">How long since last heartbeat to consider a job stalled.</param>
    /// <param name="ct">Cancellation token.</param>
    /// <returns>List of recovered job IDs.</returns>
    Task<IReadOnlyList<Guid>> RecoverStalledJobsAsync(TimeSpan stallTimeout, CancellationToken ct = default);
    
    /// <summary>
    /// Gets statistics about the job queue.
    /// </summary>
    /// <param name="ct">Cancellation token.</param>
    /// <returns>Queue statistics.</returns>
    Task<JobQueueStatistics> GetStatisticsAsync(CancellationToken ct = default);
    
    /// <summary>
    /// Gets the most recent job for a source.
    /// </summary>
    /// <param name="sourceId">The source ID.</param>
    /// <param name="ct">Cancellation token.</param>
    /// <returns>The latest job, or null if no jobs found.</returns>
    Task<IngestJob?> GetLatestForSourceAsync(string sourceId, CancellationToken ct = default);

    /// <summary>
    /// Gets the latest job of a given type (e.g. catalog_seed). Used to detect "already in progress".
    /// </summary>
    Task<IngestJob?> GetLatestByJobTypeAsync(string jobType, CancellationToken ct = default);
    
    /// <summary>
    /// Gets recent jobs for the dashboard.
    /// </summary>
    /// <param name="limit">Maximum number of jobs to return.</param>
    /// <param name="ct">Cancellation token.</param>
    /// <returns>List of recent jobs.</returns>
    Task<IReadOnlyList<IngestJob>> GetRecentJobsAsync(int limit = 50, CancellationToken ct = default);

    /// <summary>Gets job status DTO for a source (API polling).</summary>
    Task<Gabi.Contracts.Api.JobStatusDto?> GetJobStatusDtoAsync(string sourceId, CancellationToken ct = default);
}

/// <summary>
/// Statistics for the job queue.
/// </summary>
public record JobQueueStatistics
{
    public int PendingCount { get; init; }
    public int RunningCount { get; init; }
    public int CompletedCount { get; init; }
    public int FailedCount { get; init; }
    public int CancelledCount { get; init; }
    public int TotalCount { get; init; }
    public IReadOnlyList<RunningJobInfo> RunningJobs { get; init; } = new List<RunningJobInfo>();
}

/// <summary>
/// Information about a running job.
/// </summary>
public record RunningJobInfo
{
    public Guid JobId { get; init; }
    public string SourceId { get; init; } = string.Empty;
    public string WorkerId { get; init; } = string.Empty;
    public DateTime StartedAt { get; init; }
    public TimeSpan RunningFor => DateTime.UtcNow - StartedAt;
    public int ProgressPercent { get; init; }
}
