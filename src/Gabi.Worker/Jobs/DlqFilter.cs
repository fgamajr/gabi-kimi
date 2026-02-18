using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Hangfire;
using Hangfire.Common;
using Hangfire.States;
using Hangfire.Storage;
using Microsoft.Extensions.Options;
namespace Gabi.Worker.Jobs;

/// <summary>
/// Hangfire filter that moves failed jobs to Dead Letter Queue after max retries.
/// Jobs that exhaust their retry attempts are captured here for inspection and replay.
/// </summary>
public class DlqFilter : IElectStateFilter
{
    private readonly IServiceProvider _serviceProvider;
    private readonly ILogger<DlqFilter> _logger;
    private readonly int _maxRetries;

    public DlqFilter(
        IServiceProvider serviceProvider,
        ILogger<DlqFilter> logger,
        IOptions<HangfireRetryPolicyOptions> retryOptions)
    {
        _serviceProvider = serviceProvider;
        _logger = logger;
        _maxRetries = retryOptions.Value.Normalize().Attempts;
    }

    public void OnStateElection(ElectStateContext context)
    {
        if (context.CandidateState is not FailedState failedState)
            return;

        var jobId = context.BackgroundJob?.Id;
        if (string.IsNullOrEmpty(jobId))
            return;

        var retryCount = GetRetryCount(jobId);

        if (retryCount < _maxRetries)
        {
            _logger.LogDebug(
                "Job {JobId} failed (attempt {RetryCount}/{MaxRetries}), will be retried by Hangfire",
                jobId, retryCount + 1, _maxRetries);
            return;
        }

        _logger.LogWarning(
            "Job {JobId} failed after {RetryCount} attempts, moving to Dead Letter Queue",
            jobId, retryCount);

        try
        {
            MoveToDlqAsync(context, failedState, retryCount).GetAwaiter().GetResult();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to move job {JobId} to DLQ", jobId);
        }
    }

    private static int GetRetryCount(string jobId)
    {
        try
        {
            var monitoring = JobStorage.Current.GetMonitoringApi();
            var details = monitoring.JobDetails(jobId);
            return details?.History?.Count(h => h.StateName == "Failed") ?? 0;
        }
        catch
        {
            return 0;
        }
    }

    private async Task MoveToDlqAsync(ElectStateContext context, FailedState failedState, int retryCount)
    {
        using var scope = _serviceProvider.CreateScope();
        var dbContext = scope.ServiceProvider.GetRequiredService<GabiDbContext>();

        var job = context.BackgroundJob?.Job;
        var jobId = context.BackgroundJob?.Id ?? "";

        var extracted = DlqJobContextExtractor.Extract(job?.Args);

        var dlqEntry = new DlqEntryEntity
        {
            Id = Guid.NewGuid(),
            JobType = job?.Method?.Name ?? "unknown",
            SourceId = extracted.SourceId,
            OriginalJobId = extracted.OriginalJobId,
            HangfireJobId = jobId,
            Payload = extracted.Payload,
            ErrorMessage = failedState.Exception?.Message,
            ErrorType = failedState.Exception?.GetType().Name,
            StackTrace = DlqJsonSerializer.SerializeStackTrace(failedState.Exception?.StackTrace),
            RetryCount = retryCount,
            FailedAt = DateTime.UtcNow,
            Status = "pending"
        };

        dbContext.DlqEntries.Add(dlqEntry);
        await dbContext.SaveChangesAsync();

        _logger.LogInformation(
            "Job {JobId} moved to DLQ as {DlqId}. JobType={JobType}, SourceId={SourceId}",
            jobId, dlqEntry.Id, dlqEntry.JobType, dlqEntry.SourceId);
    }
}
