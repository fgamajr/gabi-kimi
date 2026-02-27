using System.Text.Json;
using Gabi.Contracts.Discovery;
using Gabi.Contracts.Jobs;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Temporalio.Activities;

namespace Gabi.Worker.Temporal;

/// <summary>
/// Temporal activities that bridge Temporal's retry/cancellation model to GABI's IJobExecutor pattern.
/// Each activity resolves the appropriate IJobExecutor by JobType and delegates execution.
/// ActivityExecutionContext.Current.CancellationToken is used so Temporal can cancel the activity.
/// </summary>
public class PipelineActivities
{
    private readonly IServiceProvider _services;
    private readonly ILogger<PipelineActivities> _logger;

    public PipelineActivities(IServiceProvider services, ILogger<PipelineActivities> logger)
    {
        _services = services;
        _logger = logger;
    }

    [Activity]
    public async Task<PipelineWorkflowResult> RunJobAsync(PipelineWorkflowInput input)
    {
        var ct = ActivityExecutionContext.Current.CancellationToken;

        using var scope = _services.CreateScope();
        var executors = scope.ServiceProvider.GetRequiredService<IEnumerable<IJobExecutor>>();
        var executor = executors.FirstOrDefault(e =>
            string.Equals(e.JobType, input.JobType, StringComparison.OrdinalIgnoreCase));

        if (executor is null)
        {
            _logger.LogError("No IJobExecutor for JobType={JobType}", input.JobType);
            return new PipelineWorkflowResult(JobTerminalStatus.Failed, $"No executor for type: {input.JobType}");
        }

        Dictionary<string, object> payload;
        try
        {
            payload = JsonSerializer.Deserialize<Dictionary<string, object>>(input.PayloadJson)
                      ?? new Dictionary<string, object>();
        }
        catch
        {
            payload = new Dictionary<string, object>();
        }

        var job = new IngestJob
        {
            Id = input.JobId,
            SourceId = input.SourceId,
            JobType = input.JobType,
            Payload = payload,
            DiscoveryConfig = new DiscoveryConfig(),
            Status = JobStatus.Running
        };

        var progress = new Progress<JobProgress>(p =>
            _logger.LogDebug("Temporal activity progress [{JobType}:{JobId}] {Pct}%: {Msg}",
                input.JobType, input.JobId, p.PercentComplete, p.Message));

        try
        {
            var result = await executor.ExecuteAsync(job, progress, ct);
            return new PipelineWorkflowResult(result.Status, result.ErrorMessage, result.Metadata);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "PipelineActivity failed for {JobType}:{JobId}", input.JobType, input.JobId);
            throw; // re-throw so Temporal retries
        }
    }
}
