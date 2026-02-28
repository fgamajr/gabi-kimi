using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Gabi.Contracts.Errors;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Hangfire;
using Hangfire.Common;
using Hangfire.States;
using Hangfire.Storage;
using Microsoft.Extensions.Options;

namespace Gabi.Worker.Jobs;

/// <summary>
/// Enhanced Hangfire filter that classifies errors, applies jittered backoff,
/// and moves failed jobs to DLQ with rich context.
/// </summary>
public class EnhancedDlqFilter : JobFilterAttribute, IElectStateFilter
{
    private readonly IServiceProvider _serviceProvider;
    private readonly ILogger<EnhancedDlqFilter> _logger;
    private readonly int _maxRetries;
    private readonly BackoffOptions _backoffOptions;

    public EnhancedDlqFilter(
        IServiceProvider serviceProvider,
        ILogger<EnhancedDlqFilter> logger,
        IOptions<HangfireRetryPolicyOptions> retryOptions,
        IOptions<BackoffOptions>? backoffOptions = null)
    {
        _serviceProvider = serviceProvider;
        _logger = logger;
        _maxRetries = retryOptions.Value.Normalize().Attempts;
        _backoffOptions = backoffOptions?.Value ?? BackoffOptions.Default;
    }

    public void OnStateElection(ElectStateContext context)
    {
        if (context.CandidateState is not FailedState failedState)
            return;

        var jobId = context.BackgroundJob?.Id;
        if (string.IsNullOrEmpty(jobId))
            return;

        var retryCount = GetRetryCount(context, jobId);
        var observedAttempts = retryCount + 1;
        
        // Build error context for classification
        var errorContext = ExtractErrorContext(failedState.Exception);
        var classification = ErrorClassifier.Classify(failedState.Exception, errorContext);
        
        var plan = IntelligentRetryPlanner.Plan(
            classification, 
            retryCount, 
            _maxRetries,
            _backoffOptions);

        _logger.LogWarning(
            "Job {JobId} failed (attempt {Attempt}/{MaxRetries}): " +
            "Category={Category}, Code={Code}, IsRecoverable={IsRecoverable}, " +
            "Decision={Decision}, Delay={DelayMs}ms",
            jobId,
            observedAttempts,
            _maxRetries,
            classification.Category,
            classification.Code,
            classification.IsRecoverable,
            plan.Decision,
            plan.Delay.TotalMilliseconds);

        if (plan.Decision == RetryDecision.ScheduleRetry)
        {
            var description = IntelligentRetryPlanner.Describe(plan, classification);
            _logger.LogInformation(
                "Scheduling retry for job {JobId} in {Delay}: {Description}",
                jobId, plan.Delay, description);

            context.SetJobParameter("RetryCount", retryCount + 1);
            context.SetJobParameter("LastErrorCategory", classification.Category.ToString());
            context.SetJobParameter("LastErrorCode", classification.Code);
            
            context.CandidateState = new ScheduledState(plan.Delay)
            {
                Reason = $"Retry {observedAttempts}/{_maxRetries}: {classification.Category}/{classification.Code}"
            };
            return;
        }

        // Move to DLQ
        _logger.LogWarning(
            "Job {JobId} exhausted retries ({RetryCount}), moving to DLQ. " +
            "Category={Category}, Code={Code}, SuggestedAction={Action}",
            jobId, retryCount, classification.Category, classification.Code, classification.SuggestedAction);

        context.SetJobParameter("RetryCount", Math.Max(retryCount, _maxRetries));
        context.SetJobParameter("MovedToDlqAt", DateTime.UtcNow.ToString("O"));
        
        context.CandidateState = new FailedState(failedState.Exception)
        {
            Reason = $"{classification.Category} ({classification.Code})"
        };

        try
        {
            MoveToDlq(context, failedState, retryCount, classification, errorContext);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Critical: Failed to move job {JobId} to DLQ", jobId);
        }
    }

    private void MoveToDlq(
        ElectStateContext context,
        FailedState failedState,
        int retryCount,
        ErrorClassification classification,
        ErrorContext? errorContext)
    {
        using var scope = _serviceProvider.CreateScope();
        var dbContext = scope.ServiceProvider.GetRequiredService<GabiDbContext>();

        var job = context.BackgroundJob?.Job;
        var jobId = context.BackgroundJob?.Id ?? "";

        var extracted = DlqJobContextExtractor.Extract(job?.Args);
        var failureSignature = ErrorClassifier.ComputeFailureSignature(classification, errorContext?.Url);

        // Calculate total retry duration
        var totalRetryDuration = errorContext?.TotalRetryDuration 
            ?? (errorContext?.FirstFailedAt != null 
                ? DateTime.UtcNow - errorContext.FirstFailedAt.Value 
                : TimeSpan.Zero);

        var dlqEntry = new DlqEntryEntity
        {
            Id = Guid.NewGuid(),
            JobType = job?.Method?.Name ?? "unknown",
            SourceId = extracted.SourceId,
            OriginalJobId = extracted.OriginalJobId,
            HangfireJobId = jobId,
            Payload = extracted.Payload,
            
            // Error details (truncate to avoid oversized entries)
            ErrorMessage = Truncate(failedState.Exception?.Message, 4000),
            ErrorType = failedState.Exception?.GetType().Name,
            StackTrace = SerializeStackTrace(failedState.Exception?.StackTrace),
            
            // Classification
            ErrorCategory = classification.Category.ToString().ToLowerInvariant(),
            ErrorCode = classification.Code,
            ErrorContext = SerializeErrorContext(errorContext),
            
            // Recovery metadata
            SuggestedAction = Truncate(classification.SuggestedAction, 500),
            IsRecoverable = classification.IsRecoverable,
            FirstFailedAt = errorContext?.FirstFailedAt ?? DateTime.UtcNow,
            TotalRetryDuration = totalRetryDuration,
            
            // Grouping
            FailureSignature = failureSignature,
            SimilarFailureCount = 0, // Updated below
            
            RetryCount = retryCount,
            FailedAt = DateTime.UtcNow,
            Status = "pending"
        };

        // Update similar failure counts
        UpdateSimilarFailureCounts(dbContext, failureSignature);

        dbContext.DlqEntries.Add(dlqEntry);
        dbContext.SaveChanges();

        _logger.LogInformation(
            "Job {JobId} moved to DLQ as {DlqId}. " +
            "JobType={JobType}, SourceId={SourceId}, Category={Category}, " +
            "Signature={Signature}, IsRecoverable={IsRecoverable}",
            jobId, dlqEntry.Id, dlqEntry.JobType, dlqEntry.SourceId, 
            classification.Category, failureSignature, classification.IsRecoverable);

        // Emit metric (if available)
        try
        {
            var meter = scope.ServiceProvider.GetService<System.Diagnostics.Metrics.Meter>();
            if (meter != null)
            {
                var counter = meter.CreateCounter<long>("fetch.dlq.additions");
                counter.Add(1, 
                    new KeyValuePair<string, object?>("category", classification.Category.ToString()),
                    new KeyValuePair<string, object?>("code", classification.Code));
            }
        }
        catch { /* Best effort */ }
    }

    private static ErrorContext? ExtractErrorContext(Exception? exception)
    {
        // Try to extract context from custom exception types
        if (exception is FetchException fetchEx)
        {
            return fetchEx.Context;
        }

        // Look for context in exception data
        if (exception?.Data["ErrorContext"] is ErrorContext ctx)
        {
            return ctx;
        }

        return null;
    }

    private static void UpdateSimilarFailureCounts(GabiDbContext dbContext, string? failureSignature)
    {
        if (string.IsNullOrEmpty(failureSignature))
            return;

        try
        {
            // Get count of all entries with this signature
            var count = dbContext.DlqEntries
                .Count(e => e.FailureSignature == failureSignature);

            // Update all entries with the new count
            var entries = dbContext.DlqEntries
                .Where(e => e.FailureSignature == failureSignature)
                .ToList();

            foreach (var entry in entries)
            {
                entry.SimilarFailureCount = count;
            }
        }
        catch (Exception ex)
        {
            // Don't fail the DLQ operation if count update fails
            System.Diagnostics.Debug.WriteLine($"Failed to update similar failure counts: {ex}");
        }
    }

    private static int GetRetryCount(ElectStateContext context, string jobId)
    {
        try
        {
            // Try to get from job parameter first
            var fromParameter = context.GetJobParameter<int>("RetryCount");
            if (fromParameter > 0)
                return fromParameter;

            // Fall back to counting failed states in history
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

    private static string? SerializeErrorContext(ErrorContext? context)
    {
        if (context == null)
            return null;

        try
        {
            return JsonSerializer.Serialize(context, new JsonSerializerOptions
            {
                PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
                WriteIndented = false
            });
        }
        catch
        {
            return null;
        }
    }

    private static string? SerializeStackTrace(string? stackTrace)
    {
        if (string.IsNullOrEmpty(stackTrace))
            return null;

        try
        {
            // Store as JSON array for easier parsing
            var lines = stackTrace
                .Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)
                .Select(l => l.Trim())
                .Where(l => !string.IsNullOrEmpty(l))
                .ToList();

            return JsonSerializer.Serialize(lines);
        }
        catch
        {
            return JsonSerializer.Serialize(new[] { stackTrace });
        }
    }

    private static string? Truncate(string? value, int maxLength)
    {
        if (string.IsNullOrEmpty(value)) return value;
        return value.Length <= maxLength ? value : value[..maxLength];
    }
}
