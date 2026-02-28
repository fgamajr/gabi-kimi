namespace Gabi.Contracts.Jobs;

/// <summary>
/// Status of a job worker.
/// </summary>
public enum WorkerStatus
{
    /// <summary>Worker is idle, waiting for a job.</summary>
    Idle,
    
    /// <summary>Worker is currently processing a job.</summary>
    Busy,
    
    /// <summary>Worker is stopping (finishing current job).</summary>
    Stopping,
    
    /// <summary>Worker has stopped.</summary>
    Stopped
}

/// <summary>
/// Interface for a job worker that processes jobs from the queue.
/// </summary>
public interface IJobWorker : IDisposable
{
    /// <summary>
    /// Unique identifier for this worker.
    /// </summary>
    string WorkerId { get; }
    
    /// <summary>
    /// Current status of the worker.
    /// </summary>
    WorkerStatus CurrentStatus { get; }
    
    /// <summary>
    /// ID of the job currently being processed, or null if idle.
    /// </summary>
    Guid? CurrentJobId { get; }
    
    /// <summary>
    /// Source ID of the job currently being processed, or null if idle.
    /// </summary>
    string? CurrentSourceId { get; }
    
    /// <summary>
    /// When the current job started, or null if idle.
    /// </summary>
    DateTime? JobStartedAt { get; }
    
    /// <summary>
    /// Starts the worker.
    /// </summary>
    /// <param name="ct">Cancellation token.</param>
    Task StartAsync(CancellationToken ct);
    
    /// <summary>
    /// Stops the worker gracefully.
    /// </summary>
    /// <param name="ct">Cancellation token.</param>
    Task StopAsync(CancellationToken ct);
}

/// <summary>
/// Interface for executing a specific type of job.
/// </summary>
public interface IJobExecutor
{
    /// <summary>
    /// The type of job this executor handles (e.g., "sync", "crawl").
    /// </summary>
    string JobType { get; }
    
    /// <summary>
    /// Executes the job.
    /// </summary>
    /// <param name="job">The job to execute.</param>
    /// <param name="progress">Progress reporter.</param>
    /// <param name="ct">Cancellation token.</param>
    /// <returns>Result of the job execution.</returns>
    Task<JobResult> ExecuteAsync(
        IngestJob job,
        IProgress<JobProgress> progress,
        CancellationToken ct);
}

/// <summary>
/// Result of a job execution.
/// </summary>
public record JobResult
{
    /// <summary>Terminal status of the job (semantic closure: no collapse to boolean).</summary>
    public JobTerminalStatus Status { get; init; } = JobTerminalStatus.Success;

    /// <summary>Whether the job was fully successful (Status == Success).</summary>
    public bool Success => Status == JobTerminalStatus.Success;

    /// <summary>Error message if the job failed.</summary>
    public string? ErrorMessage { get; init; }

    /// <summary>Type of error if the job failed.</summary>
    public string? ErrorType { get; init; }

    /// <summary>Additional metadata about the job execution.</summary>
    public Dictionary<string, object> Metadata { get; init; } = new();
}

/// <summary>
/// Progress update for a running job.
/// </summary>
public record JobProgress
{
    /// <summary>Progress percentage (0-100).</summary>
    public int PercentComplete { get; init; }
    
    /// <summary>Progress message.</summary>
    public string Message { get; init; } = string.Empty;
    
    /// <summary>Additional metrics.</summary>
    public Dictionary<string, object> Metrics { get; init; } = new();
}

/// <summary>
/// Options for configuring the worker pool.
/// </summary>
public class WorkerPoolOptions
{
    /// <summary>
    /// Number of parallel workers.
    /// For serverless (1GB RAM): 1-2 workers
    /// For dedicated server: 4-8 workers per CPU core
    /// Default: 1 (for 1GB RAM environments)
    /// </summary>
    public int WorkerCount { get; set; } = 1;
    
    /// <summary>
    /// How often to poll the database for new jobs when idle.
    /// </summary>
    public TimeSpan PollInterval { get; set; } = TimeSpan.FromSeconds(5);
    
    /// <summary>
    /// Heartbeat interval for running jobs.
    /// </summary>
    public TimeSpan HeartbeatInterval { get; set; } = TimeSpan.FromSeconds(30);
    
    /// <summary>
    /// Lease duration for claimed jobs.
    /// Jobs not heartbeated within this time can be reclaimed by other workers.
    /// </summary>
    public TimeSpan LeaseDuration { get; set; } = TimeSpan.FromMinutes(2);
    
    /// <summary>
    /// Graceful shutdown timeout.
    /// </summary>
    public TimeSpan ShutdownTimeout { get; set; } = TimeSpan.FromMinutes(1);
    
    /// <summary>
    /// How often to check for and recover stalled jobs.
    /// </summary>
    public TimeSpan RecoveryInterval { get; set; } = TimeSpan.FromMinutes(1);
    
    /// <summary>
    /// How long since last heartbeat to consider a job stalled.
    /// </summary>
    public TimeSpan StallTimeout { get; set; } = TimeSpan.FromMinutes(5);
}
