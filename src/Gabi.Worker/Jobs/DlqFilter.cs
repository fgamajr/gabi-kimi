using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Contracts.Common;
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
public class DlqFilter : JobFilterAttribute, IElectStateFilter
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

        var retryCount = GetRetryCount(context, jobId);
        var observedAttempts = DlqRetryDecision.ToObservedAttempts(retryCount);
        var classification = ErrorClassifier.Classify(failedState.Exception);
        var plan = IntelligentRetryPlanner.Plan(classification, retryCount, _maxRetries);

        _logger.LogWarning(
            "Retry classification for job {JobId}: Category={Category}, Code={Code}, RetryCount={RetryCount}, MaxRetries={MaxRetries}",
            jobId,
            classification.Category,
            classification.Code,
            retryCount,
            _maxRetries);

        if (plan.Decision == RetryDecision.ScheduleRetry)
        {
            _logger.LogDebug(
                "Job {JobId} failed (attempt {RetryCount}/{MaxRetries}), scheduling retry in {Delay}",
                jobId, observedAttempts, _maxRetries, plan.Delay);

            context.SetJobParameter("RetryCount", retryCount + 1);
            context.CandidateState = new ScheduledState(plan.Delay)
            {
                Reason = $"Retry ({classification.Category}/{classification.Code}) in {plan.Delay}"
            };
            return;
        }

        _logger.LogWarning(
            "Job {JobId} failed after retryCount={RetryCount} (attempt {Attempt}), moving to Dead Letter Queue. Category={Category}, Code={Code}",
            jobId, retryCount, observedAttempts, classification.Category, classification.Code);

        context.SetJobParameter("RetryCount", Math.Max(retryCount, _maxRetries));
        context.CandidateState = new FailedState(failedState.Exception)
        {
            Reason = $"{classification.Category} ({classification.Code})"
        };

        try
        {
            MoveToDlqAsync(context, failedState, retryCount, classification).GetAwaiter().GetResult();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to move job {JobId} to DLQ", jobId);
        }
    }

    private static int GetRetryCount(ElectStateContext context, string jobId)
    {
        try
        {
            var fromParameter = context.GetJobParameter<int>("RetryCount");
            if (fromParameter >= 0)
                return fromParameter;

            var monitoring = JobStorage.Current.GetMonitoringApi();
            var details = monitoring.JobDetails(jobId);
            var failedHistoryCount = details?.History?.Count(h => h.StateName == "Failed") ?? 0;
            return Math.Max(0, failedHistoryCount - 1);
        }
        catch
        {
            return 0;
        }
    }

    private async Task MoveToDlqAsync(
        ElectStateContext context,
        FailedState failedState,
        int retryCount,
        ErrorClassification classification)
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
            Status = "pending",
            Notes = $"Category={classification.Category}; Code={classification.Code}"
        };

        dbContext.DlqEntries.Add(dlqEntry);
        await dbContext.SaveChangesAsync();

        _logger.LogInformation(
            "Job {JobId} moved to DLQ as {DlqId}. JobType={JobType}, SourceId={SourceId}",
            jobId, dlqEntry.Id, dlqEntry.JobType, dlqEntry.SourceId);
    }
}
