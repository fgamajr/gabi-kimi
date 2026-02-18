using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Hangfire;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Api.Services;

public interface IDlqService
{
    Task<DlqListResponse> GetEntriesAsync(int page, int pageSize, string? status, CancellationToken ct = default);
    Task<DlqEntryDto?> GetEntryAsync(Guid id, CancellationToken ct = default);
    Task<DlqReplayResponse> ReplayAsync(Guid id, string? notes, CancellationToken ct = default);
    Task<DlqStatsResponse> GetStatsAsync(CancellationToken ct = default);
}

public class DlqService : IDlqService
{
    private readonly IServiceProvider _serviceProvider;
    private readonly ILogger<DlqService> _logger;

    public DlqService(IServiceProvider serviceProvider, ILogger<DlqService> logger)
    {
        _serviceProvider = serviceProvider;
        _logger = logger;
    }

    public async Task<DlqListResponse> GetEntriesAsync(int page, int pageSize, string? status, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var dbContext = scope.ServiceProvider.GetRequiredService<GabiDbContext>();

        var query = dbContext.DlqEntries.AsQueryable();

        if (!string.IsNullOrEmpty(status))
            query = query.Where(e => e.Status == status);

        var total = await query.CountAsync(ct);

        var entries = await query
            .OrderByDescending(e => e.FailedAt)
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .Select(e => new DlqEntryDto(
                e.Id,
                e.JobType,
                e.SourceId,
                e.OriginalJobId,
                e.HangfireJobId,
                e.ErrorMessage,
                e.ErrorType,
                e.RetryCount,
                e.FailedAt,
                e.ReplayedAt,
                e.ReplayedBy,
                e.Status,
                e.Notes
            ))
            .ToListAsync(ct);

        return new DlqListResponse(entries, total, page, pageSize);
    }

    public async Task<DlqEntryDto?> GetEntryAsync(Guid id, CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var dbContext = scope.ServiceProvider.GetRequiredService<GabiDbContext>();

        var entry = await dbContext.DlqEntries.FindAsync([id], ct);
        if (entry == null)
            return null;

        return new DlqEntryDto(
            entry.Id,
            entry.JobType,
            entry.SourceId,
            entry.OriginalJobId,
            entry.HangfireJobId,
            entry.ErrorMessage,
            entry.ErrorType,
            entry.RetryCount,
            entry.FailedAt,
            entry.ReplayedAt,
            entry.ReplayedBy,
            entry.Status,
            entry.Notes
        );
    }

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

        var newJobId = Guid.NewGuid();

        var job = new IngestJob
        {
            Id = newJobId,
            SourceId = entry.SourceId ?? "",
            JobType = entry.JobType,
            Payload = new Dictionary<string, object>(),
            DiscoveryConfig = new Gabi.Contracts.Discovery.DiscoveryConfig(),
            Status = JobStatus.Pending
        };

        var hangfireJobId = backgroundJob.Enqueue<IGabiJobRunner>(runner =>
            runner.RunAsync(newJobId, entry.JobType, entry.SourceId ?? "", entry.Payload ?? "{}", ct));

        entry.Status = "replayed";
        entry.ReplayedAt = DateTime.UtcNow;
        entry.ReplayedBy = "api";
        entry.ReplayedAsJobId = newJobId;
        entry.Notes = notes;

        await dbContext.SaveChangesAsync(ct);

        _logger.LogInformation(
            "DLQ entry {DlqId} replayed as new job {NewJobId} (Hangfire: {HangfireJobId})",
            id, newJobId, hangfireJobId);

        return new DlqReplayResponse(true, newJobId, "Job re-enqueued successfully")
        {
            HangfireJobId = hangfireJobId
        };
    }

    public async Task<DlqStatsResponse> GetStatsAsync(CancellationToken ct = default)
    {
        using var scope = _serviceProvider.CreateScope();
        var dbContext = scope.ServiceProvider.GetRequiredService<GabiDbContext>();

        var total = await dbContext.DlqEntries.CountAsync(ct);
        var pending = await dbContext.DlqEntries.CountAsync(e => e.Status == "pending", ct);
        var replayed = await dbContext.DlqEntries.CountAsync(e => e.Status == "replayed", ct);

        var byJobType = await dbContext.DlqEntries
            .GroupBy(e => e.JobType)
            .Select(g => new { JobType = g.Key, Count = g.Count() })
            .ToDictionaryAsync(x => x.JobType, x => x.Count, ct);

        return new DlqStatsResponse(total, pending, replayed, byJobType);
    }
}

public record DlqListResponse(IReadOnlyList<DlqEntryDto> Entries, int Total, int Page, int PageSize);
public record DlqEntryDto(
    Guid Id,
    string JobType,
    string? SourceId,
    Guid? OriginalJobId,
    string? HangfireJobId,
    string? ErrorMessage,
    string? ErrorType,
    int RetryCount,
    DateTime FailedAt,
    DateTime? ReplayedAt,
    string? ReplayedBy,
    string Status,
    string? Notes
);
public record DlqReplayResponse(bool Success, Guid? NewJobId, string Message)
{
    public string? HangfireJobId { get; init; }
}
public record DlqStatsResponse(int Total, int Pending, int Replayed, Dictionary<string, int> ByJobType);
