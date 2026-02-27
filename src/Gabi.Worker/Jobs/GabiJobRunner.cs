using Gabi.Contracts.Common;
using Gabi.Contracts.Jobs;
using Gabi.Contracts.Observability;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Microsoft.EntityFrameworkCore;
using System.Diagnostics;
using System.Threading.Channels;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Job Hangfire executado no Worker: atualiza job_registry, monta IngestJob e delega para IJobExecutor.
/// </summary>
public class GabiJobRunner : IGabiJobRunner
{
    // Job types that own a specific source's pipeline state (GAP-07).
    // embed_and_index is excluded: it's a fan-out sub-job with many concurrent instances.
    // seed is excluded: it processes all sources at once, has no per-source state.
    private static readonly HashSet<string> PipelinePhaseJobTypes =
        new(StringComparer.OrdinalIgnoreCase) { "discovery", "fetch", "ingest" };

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
            reg.Status = Status.Processing;
            reg.StartedAt = DateTime.UtcNow;
            reg.ErrorMessage = null;
            reg.CompletedAt = null;
            await context.SaveChangesAsync(ct);
        }

        // GAP-07: confirm pipeline state = "running" at actual job start.
        // Handles Hangfire retries where StartPhaseAsync (which sets "running" at enqueue time)
        // was never called (e.g. worker restart, Hangfire re-pickup after crash).
        await TrySetPipelineStateAsync(context, jobType, sourceId, Status.Running, jobType, ct);

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
            await UpdateRegistryAsync(context, jobId, Status.Failed, "No executor for type: " + jobType, ct);
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
            var statusString = StatusVocabulary.ToCanonical(result.Status);
            await UpdateRegistryAsync(context, jobId, statusString, result.ErrorMessage, ct);

            // GAP-07: return source to "idle" after a phase completes.
            // Partial/Capped/Inconclusive are still terminal completions — source is idle.
            // Only JobTerminalStatus.Failed maps to pipeline state "failed".
            var pipelineEndState = result.Status == JobTerminalStatus.Failed ? Status.Failed : Status.Idle;
            await TrySetPipelineStateAsync(context, jobType, sourceId, pipelineEndState, null, ct);
        }
        catch (Exception ex)
        {
            progressChannel.Writer.TryComplete();
            await AwaitProgressPumpSafelyAsync(jobId, progressPumpTask);
            activity?.SetStatus(ActivityStatusCode.Error, ex.Message);
            activity?.AddException(ex);
            activity?.SetTag("error.type", ex.GetType().Name);
            _logger.LogError(ex, "Job {JobId} failed", jobId);
            await UpdateRegistryAsync(context, jobId, Status.Failed, ex.Message, ct);

            // GAP-07: unhandled exception → source enters "failed" state.
            await TrySetPipelineStateAsync(context, jobType, sourceId, Status.Failed, null, ct);
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
        reg.ProgressPercent = 100;
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

        var nextUpdateAllowed = DateTime.UtcNow;

        await foreach (var update in reader.ReadAllAsync(ct))
        {
            var latestUpdate = update;
            
            // Drena a fila para pegar apenas a atualização mais recente (Debounce/Write-Amplification fix)
            while (reader.TryRead(out var newerUpdate))
            {
                latestUpdate = newerUpdate;
            }

            var now = DateTime.UtcNow;
            if (now >= nextUpdateAllowed || latestUpdate.PercentComplete == 100)
            {
                try
                {
                    await UpdateProgressAsync(context, jobId, latestUpdate.PercentComplete, latestUpdate.Message, ct);
                    nextUpdateAllowed = now.AddSeconds(1); // Throttle: máx 1 update por segundo
                }
                catch (Exception ex)
                {
                    _logger.LogWarning(ex, "Progress update failed for job {JobId}", jobId);
                }
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

    /// <summary>
    /// Writes source pipeline state (GAP-07). Only applies to phase-owning job types
    /// (discovery, fetch, ingest). Never overwrites operator-set states (paused, stopped)
    /// so that Pause/Stop controls are not clobbered by job lifecycle events.
    /// Failures are non-fatal: state is observability metadata, not business logic.
    /// </summary>
    private async Task TrySetPipelineStateAsync(
        GabiDbContext context,
        string jobType,
        string sourceId,
        string targetState,
        string? activePhase,
        CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(sourceId) || !PipelinePhaseJobTypes.Contains(jobType))
            return;

        try
        {
            var existing = await context.SourcePipelineStates
                .FirstOrDefaultAsync(s => s.SourceId == sourceId, ct);
            var now = DateTime.UtcNow;

            if (existing == null)
            {
                context.SourcePipelineStates.Add(new SourcePipelineStateEntity
                {
                    SourceId = sourceId,
                    State = targetState,
                    ActivePhase = activePhase,
                    UpdatedAt = now
                });
            }
            else
            {
                // Never overwrite a state set by the operator (Pause/Stop).
                // The executor already checked IsSourcePausedOrStoppedAsync and returned
                // early, so the source remains paused/stopped after the job exits.
                if (existing.State is Status.Paused or Status.Stopped)
                    return;

                existing.State = targetState;
                existing.ActivePhase = activePhase;
                existing.UpdatedAt = now;
            }

            await context.SaveChangesAsync(ct);
            _logger.LogDebug(
                "Pipeline state for {SourceId}: {PreviousState} → {TargetState} (job={JobType})",
                sourceId, existing?.State ?? "new", targetState, jobType);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex,
                "Failed to update pipeline state for {SourceId} to {TargetState} (non-fatal)",
                sourceId, targetState);
        }
    }
}
