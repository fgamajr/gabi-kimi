namespace Gabi.Worker.Temporal;

/// <summary>Input record for PipelineWorkflow.</summary>
public record PipelineWorkflowInput(
    Guid    JobId,
    string  JobType,
    string  SourceId,
    string  PayloadJson,
    /// <summary>"{sourceId}:{jobType}:{jobId}" — used as Temporal workflow ID for deduplication.</summary>
    string  IdempotencyKey);
