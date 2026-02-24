using Gabi.Contracts.Jobs;
using Gabi.Contracts.Observability;
using Gabi.Postgres;
using Microsoft.EntityFrameworkCore;
using System.Diagnostics;
using System.Threading.Channels;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Job Hangfire executado no Worker: atualiza job_registry, monta IngestJob e delega para IJobExecutor.
/// </summary>
public class GabiJobRunner : IGabiJobRunner
{
    private readonly IServiceProvider _serviceProvider;
    private readonly ILogger<GabiJobRunner> _logger;

    public GabiJobRunner(IServiceProvider serviceProvider, ILogger<GabiJobRunner> logger)
    {
        _serviceProvider = serviceProvider;
        _logger = logger;
    }

    public async Task RunAsync(Guid jobId, string jobType, string sourceId, string payloadJson, CancellationToken ct)
    {
        using var scope = _serviceProvider.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
        var executors = scope.ServiceProvider.GetRequiredService<IEnumerable<IJobExecutor>>();
        var payload = JobPayloadParser.ParsePayload(payloadJson);

        var requestId = payload.TryGetValue("request_id", out var requestIdValue)
            ? Convert.ToString(requestIdValue)
            : null;
        var traceParent = payload.TryGetValue("traceparent", out var traceParentValue)
            ? Convert.ToString(traceParentValue)
            : null;

        using var activity = StartActivity(jobType, sourceId, jobId, requestId, traceParent);

        var reg = await context.JobRegistry.FirstOrDefaultAsync(r => r.JobId == jobId, ct);
        if (reg != null)
        {
            reg.Status = "processing";
            reg.StartedAt = DateTime.UtcNow;
            reg.ErrorMessage = null;
            reg.CompletedAt = null;
            await context.SaveChangesAsync(ct);
        }

        var discoveryConfig = JobPayloadParser.ParseDiscoveryConfigFromPayload(payloadJson) ?? new Gabi.Contracts.Discovery.DiscoveryConfig();

        var job = new IngestJob
        {
            Id = jobId,
            SourceId = sourceId,
            JobType = jobType,
            Payload = payload,
            DiscoveryConfig = discoveryConfig,
            Status = JobStatus.Running
        };

        var executor = executors.FirstOrDefault(e => e.JobType == jobType);
        if (executor == null)
        {
            _logger.LogError("No executor for job type {JobType}", jobType);
            await UpdateRegistryAsync(context, jobId, "failed", "No executor for type: " + jobType, ct);
            return;
        }

        var progressChannel = Channel.CreateUnbounded<JobProgress>(new UnboundedChannelOptions
        {
            SingleReader = true,
            SingleWriter = false,
            AllowSynchronousContinuations = false
        });
        var progressPumpTask = Task.Run(() => PumpProgressUpdatesAsync(jobId, progressChannel.Reader, CancellationToken.None));

        var progress = new Progress<JobProgress>(p =>
        {
            if (!progressChannel.Writer.TryWrite(p))
            {
                _logger.LogWarning("Dropped progress update for job {JobId} because channel is closed", jobId);
            }
        });

        try
        {
            var result = await executor.ExecuteAsync(job, progress, ct);
            progressChannel.Writer.TryComplete();
            await AwaitProgressPumpSafelyAsync(jobId, progressPumpTask);
            await UpdateRegistryAsync(context, jobId, result.Success ? "completed" : "failed", result.ErrorMessage, ct);
        }
        catch (Exception ex)
        {
            progressChannel.Writer.TryComplete();
            await AwaitProgressPumpSafelyAsync(jobId, progressPumpTask);
            activity?.SetStatus(ActivityStatusCode.Error, ex.Message);
            activity?.AddException(ex);
            activity?.SetTag("error.type", ex.GetType().Name);
            _logger.LogError(ex, "Job {JobId} failed", jobId);
            await UpdateRegistryAsync(context, jobId, "failed", ex.Message, ct);
            throw;
        }
    }

    private static Activity? StartActivity(string jobType, string sourceId, Guid jobId, string? requestId, string? traceParent)
    {
        if (!string.IsNullOrWhiteSpace(traceParent) &&
            ActivityContext.TryParse(traceParent, null, out var parentContext))
        {
            var child = PipelineTelemetry.ActivitySource.StartActivity("pipeline.job", ActivityKind.Consumer, parentContext);
            child?.SetTag("job.type", jobType);
            child?.SetTag("job.id", jobId.ToString());
            child?.SetTag("source.id", sourceId);
            child?.SetTag("request.id", requestId);
            return child;
        }

        var activity = PipelineTelemetry.ActivitySource.StartActivity("pipeline.job", ActivityKind.Consumer);
        activity?.SetTag("job.type", jobType);
        activity?.SetTag("job.id", jobId.ToString());
        activity?.SetTag("source.id", sourceId);
        activity?.SetTag("request.id", requestId);
        return activity;
    }

    private static async Task UpdateRegistryAsync(GabiDbContext context, Guid jobId, string status, string? errorMessage, CancellationToken ct)
    {
        var reg = await context.JobRegistry.FirstOrDefaultAsync(r => r.JobId == jobId, ct);
        if (reg == null) return;
        reg.Status = status;
        reg.CompletedAt = DateTime.UtcNow;
        reg.ErrorMessage = errorMessage?.Length > 2000 ? errorMessage[..2000] : errorMessage;
        if (status == "completed") reg.ProgressPercent = 100;
        await context.SaveChangesAsync(ct);
    }

    private static async Task UpdateProgressAsync(GabiDbContext context, Guid jobId, int percent, string? message, CancellationToken ct)
    {
        var normalizedMessage = message?.Length > 500 ? message[..500] : message;

        await context.JobRegistry
            .Where(r => r.JobId == jobId)
            .ExecuteUpdateAsync(setters => setters
                .SetProperty(r => r.ProgressPercent, percent)
                .SetProperty(r => r.ProgressMessage, normalizedMessage), ct);
    }

    private async Task PumpProgressUpdatesAsync(Guid jobId, ChannelReader<JobProgress> reader, CancellationToken ct)
    {
        using var scope = _serviceProvider.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<GabiDbContext>();

        await foreach (var update in reader.ReadAllAsync(ct))
        {
            try
            {
                await UpdateProgressAsync(context, jobId, update.PercentComplete, update.Message, ct);
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Progress update failed for job {JobId}", jobId);
            }
        }
    }

    private async Task AwaitProgressPumpSafelyAsync(Guid jobId, Task progressPumpTask)
    {
        try
        {
            await progressPumpTask;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Progress pump task failed for job {JobId}", jobId);
        }
    }
}
