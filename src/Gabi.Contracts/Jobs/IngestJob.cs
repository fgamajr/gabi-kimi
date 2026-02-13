using Gabi.Contracts.Discovery;
using Gabi.Contracts.Pipeline;

namespace Gabi.Contracts.Jobs;

/// <summary>
/// Represents an ingestion job in the queue.
/// </summary>
public record IngestJob
{
    /// <summary>Unique identifier for the job.</summary>
    public Guid Id { get; init; } = Guid.NewGuid();
    
    /// <summary>Source identifier (e.g., "tcu_acordaos").</summary>
    public string SourceId { get; init; } = string.Empty;
    
    /// <summary>Type of job (e.g., "sync", "crawl", "api_fetch").</summary>
    public string JobType { get; init; } = "sync";
    
    /// <summary>Current status of the job.</summary>
    public JobStatus Status { get; init; } = JobStatus.Pending;
    
    /// <summary>Priority of the job (higher = first).</summary>
    public JobPriority Priority { get; init; } = JobPriority.Normal;
    
    /// <summary>Discovery configuration for the source.</summary>
    public DiscoveryConfig DiscoveryConfig { get; init; } = new();
    
    /// <summary>Pipeline options for processing.</summary>
    public PipelineOptions PipelineOptions { get; init; } = new();
    
    /// <summary>Custom data payload for the job.</summary>
    public Dictionary<string, object> Payload { get; init; } = new();
    
    /// <summary>Maximum number of retry attempts.</summary>
    public int MaxRetries { get; init; } = 3;
    
    /// <summary>Current retry count.</summary>
    public int RetryCount { get; init; } = 0;
    
    /// <summary>When the job was created.</summary>
    public DateTime CreatedAt { get; init; } = DateTime.UtcNow;
    
    /// <summary>When the job is scheduled to run (for delayed jobs).</summary>
    public DateTime? ScheduledAt { get; init; }
    
    /// <summary>When the job started running.</summary>
    public DateTime? StartedAt { get; init; }
    
    /// <summary>When the job completed or failed.</summary>
    public DateTime? CompletedAt { get; init; }
    
    /// <summary>ID of the worker processing this job.</summary>
    public string? WorkerId { get; init; }
    
    /// <summary>Last heartbeat timestamp from worker.</summary>
    public DateTime? LastHeartbeatAt { get; init; }
    
    /// <summary>Error message if job failed.</summary>
    public string? ErrorMessage { get; init; }
    
    /// <summary>Idempotency key to prevent duplicate jobs.</summary>
    public string? IdempotencyKey { get; init; }
    
    /// <summary>Correlation ID for tracing.</summary>
    public Guid CorrelationId { get; init; } = Guid.NewGuid();
    
    /// <summary>Progress percentage (0-100) for long-running jobs.</summary>
    public int ProgressPercent { get; init; } = 0;
    
    /// <summary>Progress message for long-running jobs.</summary>
    public string? ProgressMessage { get; init; }
    
    /// <summary>Timeout for the job in seconds.</summary>
    public int TimeoutSeconds { get; init; } = 3600; // 1 hour default
}
