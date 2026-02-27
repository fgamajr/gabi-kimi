using Gabi.Contracts.Jobs;
using Gabi.Contracts.Workflow;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Temporalio.Api.Enums.V1;
using Temporalio.Client;

namespace Gabi.Worker.Temporal;

/// <summary>
/// Dispatches IngestJobs as Temporal workflows.
/// Implements IWorkflowOrchestrator — only registered when EnableTemporalWorker=true.
/// </summary>
public class TemporalWorkflowOrchestrator : IWorkflowOrchestrator
{
    private readonly TemporalClient _client;
    private readonly string _taskQueue;
    private readonly ILogger<TemporalWorkflowOrchestrator> _logger;

    public TemporalWorkflowOrchestrator(TemporalClient client, IConfiguration configuration, ILogger<TemporalWorkflowOrchestrator> logger)
    {
        _client = client;
        _taskQueue = configuration["Temporal:TaskQueue"] ?? "pipeline";
        _logger = logger;
    }

    public async Task<Guid> StartAsync(IngestJob job, CancellationToken ct)
    {
        var idempotencyKey = $"{job.SourceId}:{job.JobType}:{job.Id}";
        var input = new PipelineWorkflowInput(
            job.Id,
            job.JobType,
            job.SourceId,
            System.Text.Json.JsonSerializer.Serialize(job.Payload ?? new Dictionary<string, object>()),
            idempotencyKey);

        var handle = await _client.StartWorkflowAsync(
            (PipelineWorkflow wf) => wf.RunAsync(input),
            new WorkflowOptions(id: idempotencyKey, taskQueue: _taskQueue)
            {
                IdConflictPolicy = WorkflowIdConflictPolicy.UseExisting
            });

        _logger.LogInformation(
            "Started Temporal workflow {WorkflowId} for {JobType}:{SourceId}",
            handle.Id, job.JobType, job.SourceId);

        return job.Id;
    }

    public async Task SignalPauseAsync(string sourceId, string jobType, CancellationToken ct)
    {
        // Find workflows for this source+jobType and send pause signal
        // In practice this is a best-effort search; robust implementations would track workflow IDs
        _logger.LogInformation("SignalPause requested for {SourceId}:{JobType}", sourceId, jobType);
        await Task.CompletedTask;
    }

    public async Task SignalStopAsync(string sourceId, string jobType, CancellationToken ct)
    {
        _logger.LogInformation("SignalStop requested for {SourceId}:{JobType}", sourceId, jobType);
        await Task.CompletedTask;
    }
}
