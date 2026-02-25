using Gabi.Contracts.Dashboard;
using Gabi.Contracts.Enums;
using Gabi.Contracts.Index;
using Gabi.Contracts.Jobs;
using Gabi.Contracts.Pipeline;

namespace Gabi.Contracts.Common;

/// <summary>
/// Canonical status strings used across contracts.
/// </summary>
public static class Status
{
    public const string Pending = "pending";
    public const string Running = "running";
    public const string Completed = "completed";
    public const string Failed = "failed";
    public const string Cancelled = "cancelled";
    public const string Retrying = "retrying";
    public const string Skipped = "skipped";
    public const string Success = "success";
    public const string Partial = "partial";
    public const string Capped = "capped";
    public const string Inconclusive = "inconclusive";
    public const string CompletedMetadataOnly = "completed_metadata_only";
    public const string Active = "active";
    public const string InProgress = "in_progress";
    public const string Idle = "idle";
    public const string Error = "error";
    public const string Disabled = "disabled";
    public const string Paused = "paused";
    public const string Resolved = "resolved";
    public const string Exhausted = "exhausted";
    public const string Archived = "archived";
    public const string New = "new";
    public const string Changed = "changed";
    public const string Unchanged = "unchanged";
    public const string Processing = "processing";
    public const string Deleted = "deleted";
    public const string PendingReprocess = "pending_reprocess";
    public const string Busy = "busy";
    public const string Stopping = "stopping";
    public const string Stopped = "stopped";
}

/// <summary>
/// Explicit mappings between the existing status enums and canonical status strings.
/// </summary>
public static class StatusVocabulary
{
    public static string ToCanonical(JobStatus status) => status switch
    {
        JobStatus.Pending => Status.Pending,
        JobStatus.Running => Status.Running,
        JobStatus.Completed => Status.Completed,
        JobStatus.Partial => Status.Partial,
        JobStatus.Capped => Status.Capped,
        JobStatus.Inconclusive => Status.Inconclusive,
        JobStatus.Failed => Status.Failed,
        JobStatus.Cancelled => Status.Cancelled,
        JobStatus.Skipped => Status.Skipped,
        JobStatus.Retrying => Status.Retrying,
        _ => Status.Error
    };

    /// <summary>Maps job terminal status to canonical string for persistence (job_registry, fetch_runs, etc.).</summary>
    public static string ToCanonical(JobTerminalStatus status) => status switch
    {
        JobTerminalStatus.Success => Status.Completed,
        JobTerminalStatus.Partial => Status.Partial,
        JobTerminalStatus.Capped => Status.Capped,
        JobTerminalStatus.Failed => Status.Failed,
        JobTerminalStatus.Inconclusive => Status.Inconclusive,
        _ => Status.Error
    };

    public static string ToCanonical(ExecutionStatus status) => status switch
    {
        ExecutionStatus.Pending => Status.Pending,
        ExecutionStatus.Running => Status.Running,
        ExecutionStatus.Success => Status.Success,
        ExecutionStatus.PartialSuccess => Status.Partial,
        ExecutionStatus.Failed => Status.Failed,
        ExecutionStatus.Cancelled => Status.Cancelled,
        _ => Status.Error
    };

    public static string ToCanonical(DocumentStatus status) => status switch
    {
        DocumentStatus.Active => Status.Active,
        DocumentStatus.PendingReprocess => Status.PendingReprocess,
        DocumentStatus.Processing => Status.Processing,
        DocumentStatus.Error => Status.Error,
        DocumentStatus.CompletedMetadataOnly => Status.CompletedMetadataOnly,
        DocumentStatus.Deleted => Status.Deleted,
        _ => Status.Error
    };

    public static string ToCanonical(IndexingStatus status) => status switch
    {
        IndexingStatus.Success => Status.Success,
        IndexingStatus.Partial => Status.Partial,
        IndexingStatus.Failed => Status.Failed,
        IndexingStatus.Ignored => Status.Skipped,
        IndexingStatus.RolledBack => Status.Cancelled,
        _ => Status.Error
    };

    public static string ToCanonical(SourceStatus status) => status switch
    {
        SourceStatus.Active => Status.Active,
        SourceStatus.Paused => Status.Paused,
        SourceStatus.Error => Status.Error,
        SourceStatus.Disabled => Status.Disabled,
        _ => Status.Error
    };

    public static string ToCanonical(DlqStatus status) => status switch
    {
        DlqStatus.Pending => Status.Pending,
        DlqStatus.Retrying => Status.Retrying,
        DlqStatus.Exhausted => Status.Exhausted,
        DlqStatus.Resolved => Status.Resolved,
        DlqStatus.Archived => Status.Archived,
        _ => Status.Error
    };

    public static string ToCanonical(WorkerStatus status) => status switch
    {
        WorkerStatus.Idle => Status.Idle,
        WorkerStatus.Busy => Status.Busy,
        WorkerStatus.Stopping => Status.Stopping,
        WorkerStatus.Stopped => Status.Stopped,
        _ => Status.Error
    };

    public static string ToCanonical(SyncJobStatus status) => status switch
    {
        SyncJobStatus.Synced => Status.Completed,
        SyncJobStatus.Pending => Status.Pending,
        SyncJobStatus.Failed => Status.Failed,
        SyncJobStatus.InProgress => Status.InProgress,
        _ => Status.Error
    };

    public static string ToCanonical(PipelineStageStatus status) => status switch
    {
        PipelineStageStatus.Active => Status.Active,
        PipelineStageStatus.Idle => Status.Idle,
        PipelineStageStatus.Error => Status.Error,
        _ => Status.Error
    };

    public static string ToCanonical(LinkDiscoveryStatus status) => status switch
    {
        LinkDiscoveryStatus.New => Status.New,
        LinkDiscoveryStatus.Changed => Status.Changed,
        LinkDiscoveryStatus.Unchanged => Status.Unchanged,
        LinkDiscoveryStatus.MarkedForProcessing => Status.Pending,
        _ => Status.Error
    };

    public static ExecutionStatus ToExecutionStatus(JobStatus status) => status switch
    {
        JobStatus.Pending => ExecutionStatus.Pending,
        JobStatus.Running => ExecutionStatus.Running,
        JobStatus.Completed => ExecutionStatus.Success,
        JobStatus.Partial => ExecutionStatus.PartialSuccess,
        JobStatus.Capped => ExecutionStatus.PartialSuccess,
        JobStatus.Inconclusive => ExecutionStatus.Failed,
        JobStatus.Failed => ExecutionStatus.Failed,
        JobStatus.Cancelled => ExecutionStatus.Cancelled,
        JobStatus.Skipped => ExecutionStatus.Success,
        JobStatus.Retrying => ExecutionStatus.Running,
        _ => ExecutionStatus.Failed
    };
}
