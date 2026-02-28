using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Gabi.Contracts.Errors;
using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Hangfire;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Api.Services;

/// <summary>
/// Enhanced DLQ service with error classification, bulk operations, and health monitoring.
/// </summary>
public interface IEnhancedDlqService
{
    // Query operations
    Task<DlqListResponse> GetEntriesAsync(DlqQueryRequest request, CancellationToken ct = default);
    Task<DlqEntryDto?> GetEntryAsync(Guid id, CancellationToken ct = default);
    Task<DlqStatsResponse> GetStatsAsync(CancellationToken ct = default);
    Task<DlqFailurePatternsResponse> GetFailurePatternsAsync(CancellationToken ct = default);
    Task<DlqHealthReport> GetHealthReportAsync(CancellationToken ct = default);
    
    // Recovery operations
    Task<DlqReplayResponse> ReplayAsync(Guid id, string? notes, CancellationToken ct = default);
    Task<DlqBulkReplayResponse> ReplayByPatternAsync(string failureSignature, string? notes, CancellationToken ct = default);
    Task<DlqBulkReplayResponse> ReplayByCategoryAsync(string category, string? notes, CancellationToken ct = default);
    
    // Archive operations
    Task<DlqArchiveResponse> ArchiveAsync(Guid id, string reason, CancellationToken ct = default);
    Task<DlqBulkArchiveResponse> ArchiveByPatternAsync(string failureSignature, string reason, CancellationToken ct = default);
    
    // Analysis
    Task<List<DlqAlert>> GetActiveAlertsAsync(CancellationToken ct = default);
}

/// <summary>
/// Request parameters for querying DLQ entries.
/// </summary>
public record DlqQueryRequest(
    int Page = 1,
    int PageSize = 20,
    string? Status = null,
    string? Category = null,
    string? SourceId = null,
    string? ErrorCode = null,
    DateTime? FromDate = null,
    DateTime? ToDate = null,
    bool? IsRecoverable = null);

/// <summary>
/// Enhanced DLQ entry DTO with classification fields.
/// </summary>
public record DlqEntryDto(
    Guid Id,
    string JobType,
    string? SourceId,
    Guid? OriginalJobId,
    string? HangfireJobId,
    string? ErrorMessage,
    string? ErrorType,
    string ErrorCategory,
    string ErrorCode,
    bool IsRecoverable,
    string? SuggestedAction,
    int RetryCount,
    DateTime FailedAt,
    DateTime? FirstFailedAt,
    TimeSpan TotalRetryDuration,
    string? FailureSignature,
    int SimilarFailureCount,
    DateTime? ReplayedAt,
    string? ReplayedBy,
    string Status,
    string? Notes,
    string? ErrorContextJson);

/// <summary>
/// Failure pattern for bulk operations.
/// </summary>
public record FailurePattern(
    string Signature,
    string ErrorCategory,
    string ErrorCode,
    string? SuggestedAction,
    bool IsRecoverable,
    int Count,
    int AffectedSources,
    DateTime FirstSeen,
    DateTime LastSeen,
    IReadOnlyList<string> SourceIds);

// Response records
public record DlqListResponse(IReadOnlyList<DlqEntryDto> Entries, int Total, int Page, int PageSize);
public record DlqStatsResponse(
    int Total, 
    int Pending, 
    int Replayed, 
    int Archived,
    Dictionary<string, int> ByJobType,
    Dictionary<string, int> ByCategory);
public record DlqFailurePatternsResponse(IReadOnlyList<FailurePattern> Patterns);
public record DlqHealthReport(
    int TotalPending,
    int AuthFailures,
    int NewInLastHour,
    IReadOnlyList<DlqAlert> ActiveAlerts,
    Dictionary<string, int> Trends);
public record DlqAlert(
    string Severity,
    string Message,
    string? Category,
    int AffectedEntries,
    string? SuggestedAction);
public record DlqReplayResponse(bool Success, Guid? NewJobId, string Message)
{
    public string? HangfireJobId { get; init; }
}
public record DlqBulkReplayResponse(int ReplayCount, string Message, IReadOnlyList<Guid> ReplayJobIds);
public record DlqArchiveResponse(bool Success, string Message);
public record DlqBulkArchiveResponse(int ArchiveCount, string Message);

/// <summary>
/// Implementation of enhanced DLQ service.
/// </summary>
public class EnhancedDlqService : IEnhancedDlqService
{
    private const int ReplayThrottlePerMinute = 10;
    private readonly IServiceProvider _serviceProvider;
    private readonly ILogger<EnhancedDlqService> _logger;

    public EnhancedDlqService(IServiceProvider serviceProvider, ILogger<EnhancedDlqService> logger)
    {
        _serviceProvider = serviceProvider;
        _logger = logger;
    }

    /// <inheritdoc />
    public async Task<DlqListResponse> GetEntriesAsync(DlqQueryRequest request, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var dbContext = scope.ServiceProvider.GetRequiredService<GabiDbContext>();

        var query = dbContext.DlqEntries.AsNoTracking().AsQueryable();

        // Apply filters
        if (!string.IsNullOrEmpty(request.Status))
            query = query.Where(e => e.Status == request.Status);

        if (!string.IsNullOrEmpty(request.Category))
            query = query.Where(e => e.ErrorCategory == request.Category);

        if (!string.IsNullOrEmpty(request.SourceId))
            query = query.Where(e => e.SourceId == request.SourceId);

        if (!string.IsNullOrEmpty(request.ErrorCode))
            query = query.Where(e => e.ErrorCode == request.ErrorCode);

        if (request.FromDate.HasValue)
            query = query.Where(e => e.FailedAt >= request.FromDate.Value);

        if (request.ToDate.HasValue)
            query = query.Where(e => e.FailedAt <= request.ToDate.Value);

        if (request.IsRecoverable.HasValue)
            query = query.Where(e => e.IsRecoverable == request.IsRecoverable.Value);

        var total = await query.CountAsync(ct);

        var entries = await query
            .OrderByDescending(e => e.FailedAt)
            .Skip((request.Page - 1) * request.PageSize)
            .Take(request.PageSize)
            .Select(e => MapToDto(e))
            .ToListAsync(ct);

        return new DlqListResponse(entries, total, request.Page, request.PageSize);
    }

    /// <inheritdoc />
    public async Task<DlqEntryDto?> GetEntryAsync(Guid id, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var dbContext = scope.ServiceProvider.GetRequiredService<GabiDbContext>();

        var entry = await dbContext.DlqEntries.AsNoTracking()
            .FirstOrDefaultAsync(e => e.Id == id, ct);

        return entry == null ? null : MapToDto(entry);
    }

    /// <inheritdoc />
    public async Task<DlqStatsResponse> GetStatsAsync(CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var dbContext = scope.ServiceProvider.GetRequiredService<GabiDbContext>();

        var total = await dbContext.DlqEntries.CountAsync(ct);
        var pending = await dbContext.DlqEntries.CountAsync(e => e.Status == "pending", ct);
        var replayed = await dbContext.DlqEntries.CountAsync(e => e.Status == "replayed", ct);
        var archived = await dbContext.DlqEntries.CountAsync(e => e.Status == "archived", ct);

        var byJobType = await dbContext.DlqEntries
            .GroupBy(e => e.JobType)
            .Select(g => new { JobType = g.Key, Count = g.Count() })
            .ToDictionaryAsync(x => x.JobType, x => x.Count, ct);

        var byCategory = await dbContext.DlqEntries
            .GroupBy(e => e.ErrorCategory)
            .Select(g => new { Category = g.Key, Count = g.Count() })
            .ToDictionaryAsync(x => x.Category, x => x.Count, ct);

        return new DlqStatsResponse(total, pending, replayed, archived, byJobType, byCategory);
    }

    /// <inheritdoc />
    public async Task<DlqFailurePatternsResponse> GetFailurePatternsAsync(CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var dbContext = scope.ServiceProvider.GetRequiredService<GabiDbContext>();

        var patterns = await dbContext.DlqEntries
            .AsNoTracking()
            .Where(e => e.Status == "pending" && e.FailureSignature != null)
            .GroupBy(e => new { e.FailureSignature, e.ErrorCategory, e.ErrorCode, e.SuggestedAction, e.IsRecoverable })
            .Select(g => new FailurePattern(
                g.Key.FailureSignature!,
                g.Key.ErrorCategory,
                g.Key.ErrorCode,
                g.Key.SuggestedAction,
                g.Key.IsRecoverable,
                g.Count(),
                g.Select(e => e.SourceId).Distinct().Count(),
                g.Min(e => e.FailedAt),
                g.Max(e => e.FailedAt),
                g.Select(e => e.SourceId!).Distinct().Take(10).ToList()
            ))
            .Where(p => p.Count >= 2)
            .OrderByDescending(p => p.Count)
            .Take(50)
            .ToListAsync(ct);

        return new DlqFailurePatternsResponse(patterns);
    }

    /// <inheritdoc />
    public async Task<DlqHealthReport> GetHealthReportAsync(CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var dbContext = scope.ServiceProvider.GetRequiredService<GabiDbContext>();

        var totalPending = await dbContext.DlqEntries.CountAsync(e => e.Status == "pending", ct);
        var authFailures = await dbContext.DlqEntries.CountAsync(
            e => e.Status == "pending" && e.ErrorCategory == "authentication", ct);
        var newInLastHour = await dbContext.DlqEntries.CountAsync(
            e => e.FailedAt >= DateTime.UtcNow.AddHours(-1), ct);

        var alerts = new List<DlqAlert>();

        // Check for auth failure spike
        if (authFailures > 0)
        {
            alerts.Add(new DlqAlert(
                "critical",
                $"{authFailures} authentication failures require attention",
                "authentication",
                authFailures,
                "Check source credentials and permissions"));
        }

        // Check for DLQ growth
        if (totalPending > 100)
        {
            alerts.Add(new DlqAlert(
                "warning",
                $"DLQ has {totalPending} pending items",
                null,
                totalPending,
                "Review and replay recoverable items"));
        }

        // Check for burst of new failures
        if (newInLastHour > 50)
        {
            alerts.Add(new DlqAlert(
                "warning",
                $"High failure rate: {newInLastHour} items in last hour",
                null,
                newInLastHour,
                "Investigate source availability"));
        }

        // Calculate trends
        var trends = new Dictionary<string, int>();
        var categories = await dbContext.DlqEntries
            .Where(e => e.FailedAt >= DateTime.UtcNow.AddHours(-24))
            .GroupBy(e => e.ErrorCategory)
            .Select(g => new { Category = g.Key, Count = g.Count() })
            .ToListAsync(ct);

        foreach (var cat in categories)
        {
            trends[cat.Category] = cat.Count;
        }

        return new DlqHealthReport(totalPending, authFailures, newInLastHour, alerts, trends);
    }

    /// <inheritdoc />
    public async Task<DlqReplayResponse> ReplayAsync(Guid id, string? notes, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var dbContext = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
        var backgroundJob = scope.ServiceProvider.GetRequiredService<IBackgroundJobClient>();

        var entry = await dbContext.DlqEntries.FindAsync([id], ct);
        if (entry == null)
            return new DlqReplayResponse(false, null, "DLQ entry not found");

        if (entry.Status == "replayed")
            return new DlqReplayResponse(false, null, "Entry already replayed");

        if (entry.Status == "archived")
            return new DlqReplayResponse(false, null, "Entry is archived");

        if (entry.ReplayedAt.HasValue && entry.ReplayedAt.Value >= DateTime.UtcNow.AddMinutes(-1))
            return new DlqReplayResponse(false, null, $"Replay throttled: max {ReplayThrottlePerMinute} replay/min per entry");

        // Re-classify to check if still recoverable
        var classification = ErrorClassifier.Classify(entry.ErrorType, entry.ErrorMessage);
        if (classification.Category == ErrorCategory.Permanent && !entry.IsRecoverable)
        {
            _logger.LogWarning(
                "DLQ replay rejected for {DlqId}: permanent error {Code}",
                id, classification.Code);
            return new DlqReplayResponse(false, null, $"Replay denied: permanent error ({classification.Code})");
        }

        return await ReplayEntryAsync(entry, notes, "api:single", dbContext, backgroundJob, ct);
    }

    /// <inheritdoc />
    public async Task<DlqBulkReplayResponse> ReplayByPatternAsync(string failureSignature, string? notes, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var dbContext = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
        var backgroundJob = scope.ServiceProvider.GetRequiredService<IBackgroundJobClient>();

        var entries = await dbContext.DlqEntries
            .Where(e => e.FailureSignature == failureSignature 
                        && e.Status == "pending"
                        && e.IsRecoverable)
            .Take(100) // Limit bulk operations
            .ToListAsync(ct);

        if (entries.Count == 0)
            return new DlqBulkReplayResponse(0, "No matching recoverable entries found", Array.Empty<Guid>());

        var replayed = new List<Guid>();
        foreach (var entry in entries)
        {
            var result = await ReplayEntryAsync(entry, notes, "api:bulk", dbContext, backgroundJob, ct);
            if (result.Success && result.NewJobId.HasValue)
            {
                replayed.Add(result.NewJobId.Value);
            }
        }

        await dbContext.SaveChangesAsync(ct);

        _logger.LogInformation(
            "Bulk replayed {Replayed} DLQ entries with signature {Signature}",
            replayed.Count, failureSignature);

        return new DlqBulkReplayResponse(replayed.Count, 
            $"Replayed {replayed.Count} jobs with signature: {failureSignature}", 
            replayed);
    }

    /// <inheritdoc />
    public async Task<DlqBulkReplayResponse> ReplayByCategoryAsync(string category, string? notes, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var dbContext = scope.ServiceProvider.GetRequiredService<GabiDbContext>();
        var backgroundJob = scope.ServiceProvider.GetRequiredService<IBackgroundJobClient>();

        var entries = await dbContext.DlqEntries
            .Where(e => e.ErrorCategory == category 
                        && e.Status == "pending"
                        && e.IsRecoverable)
            .OrderBy(e => e.FailedAt)
            .Take(50)
            .ToListAsync(ct);

        var replayed = new List<Guid>();
        foreach (var entry in entries)
        {
            var result = await ReplayEntryAsync(entry, notes, "api:category", dbContext, backgroundJob, ct);
            if (result.Success && result.NewJobId.HasValue)
            {
                replayed.Add(result.NewJobId.Value);
            }
        }

        await dbContext.SaveChangesAsync(ct);

        return new DlqBulkReplayResponse(replayed.Count,
            $"Replayed {replayed.Count} jobs in category: {category}",
            replayed);
    }

    /// <inheritdoc />
    public async Task<DlqArchiveResponse> ArchiveAsync(Guid id, string reason, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var dbContext = scope.ServiceProvider.GetRequiredService<GabiDbContext>();

        var entry = await dbContext.DlqEntries.FindAsync([id], ct);
        if (entry == null)
            return new DlqArchiveResponse(false, "DLQ entry not found");

        entry.Status = "archived";
        entry.Notes = $"[Archived: {DateTime.UtcNow:yyyy-MM-dd HH:mm}] {reason}\n{entry.Notes}";

        await dbContext.SaveChangesAsync(ct);

        _logger.LogInformation("DLQ entry {DlqId} archived. Reason: {Reason}", id, reason);

        return new DlqArchiveResponse(true, "Entry archived successfully");
    }

    /// <inheritdoc />
    public async Task<DlqBulkArchiveResponse> ArchiveByPatternAsync(string failureSignature, string reason, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var dbContext = scope.ServiceProvider.GetRequiredService<GabiDbContext>();

        var entries = await dbContext.DlqEntries
            .Where(e => e.FailureSignature == failureSignature && e.Status == "pending")
            .ToListAsync(ct);

        var timestamp = DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm");
        foreach (var entry in entries)
        {
            entry.Status = "archived";
            entry.Notes = $"[Archived: {timestamp} (bulk)] {reason}\n{entry.Notes}";
        }

        await dbContext.SaveChangesAsync(ct);

        _logger.LogInformation(
            "Bulk archived {Count} DLQ entries with signature {Signature}. Reason: {Reason}",
            entries.Count, failureSignature, reason);

        return new DlqBulkArchiveResponse(entries.Count, 
            $"Archived {entries.Count} entries with signature: {failureSignature}");
    }

    /// <inheritdoc />
    public async Task<List<DlqAlert>> GetActiveAlertsAsync(CancellationToken ct = default)
    {
        var report = await GetHealthReportAsync(ct);
        return report.ActiveAlerts.ToList();
    }

    private async Task<DlqReplayResponse> ReplayEntryAsync(
        DlqEntryEntity entry,
        string? notes,
        string replayedBy,
        GabiDbContext dbContext,
        IBackgroundJobClient backgroundJob,
        CancellationToken ct)
    {
        var newJobId = Guid.NewGuid();

        var job = new IngestJob
        {
            Id = newJobId,
            SourceId = entry.SourceId ?? "",
            JobType = entry.JobType,
            Payload = DeserializePayload(entry.Payload),
            DiscoveryConfig = new Gabi.Contracts.Discovery.DiscoveryConfig(),
            Status = JobStatus.Pending
        };

        var hangfireJobId = backgroundJob.Enqueue<IGabiJobRunner>(runner =>
            runner.RunAsync(newJobId, entry.JobType, entry.SourceId ?? "", entry.Payload ?? "{}", ct));

        entry.Status = "replayed";
        entry.ReplayedAt = DateTime.UtcNow;
        entry.ReplayedBy = replayedBy;
        entry.ReplayedAsJobId = newJobId;
        entry.Notes = notes;

        await dbContext.SaveChangesAsync(ct);

        _logger.LogInformation(
            "DLQ entry {DlqId} replayed as new job {NewJobId} (Hangfire: {HangfireJobId})",
            entry.Id, newJobId, hangfireJobId);

        return new DlqReplayResponse(true, newJobId, "Job re-enqueued successfully")
        {
            HangfireJobId = hangfireJobId
        };
    }

    private static DlqEntryDto MapToDto(DlqEntryEntity e)
    {
        return new DlqEntryDto(
            e.Id,
            e.JobType,
            e.SourceId,
            e.OriginalJobId,
            e.HangfireJobId,
            e.ErrorMessage,
            e.ErrorType,
            e.ErrorCategory,
            e.ErrorCode,
            e.IsRecoverable,
            e.SuggestedAction,
            e.RetryCount,
            e.FailedAt,
            e.FirstFailedAt,
            e.TotalRetryDuration,
            e.FailureSignature,
            e.SimilarFailureCount,
            e.ReplayedAt,
            e.ReplayedBy,
            e.Status,
            e.Notes,
            e.ErrorContext);
    }

    private static Dictionary<string, object> DeserializePayload(string? payload)
    {
        if (string.IsNullOrEmpty(payload))
            return new Dictionary<string, object>();

        try
        {
            return JsonSerializer.Deserialize<Dictionary<string, object>>(payload) 
                ?? new Dictionary<string, object>();
        }
        catch
        {
            return new Dictionary<string, object>();
        }
    }
}

/// <summary>
/// Extension methods for string truncation.
/// </summary>
public static class StringExtensions
{
    public static string Truncate(this string? value, int maxLength)
    {
        if (string.IsNullOrEmpty(value)) return string.Empty;
        return value.Length <= maxLength ? value : value[..maxLength];
    }
}
