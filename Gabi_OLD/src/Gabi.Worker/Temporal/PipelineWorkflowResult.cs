using Gabi.Contracts.Jobs;

namespace Gabi.Worker.Temporal;

/// <summary>Result returned by PipelineWorkflow upon completion.</summary>
public record PipelineWorkflowResult(
    JobTerminalStatus Status,
    string? ErrorMessage = null,
    IReadOnlyDictionary<string, object>? Metadata = null);
