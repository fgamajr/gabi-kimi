using Gabi.Contracts.Jobs;
using Gabi.Postgres.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace Gabi.Postgres.Repositories;

/// <summary>
/// PostgreSQL implementation of the job queue repository using EF Core.
/// </summary>
public class JobQueueRepository : IJobQueueRepository
{
    private readonly GabiDbContext _context;
    private readonly ILogger<JobQueueRepository> _logger;

    public JobQueueRepository(GabiDbContext context, ILogger<JobQueueRepository> logger)
    {
        _context = context;
        _logger = logger;
    }

    public async Task<Guid> EnqueueAsync(IngestJob job, CancellationToken ct = default)
    {
        var id = job.Id == Guid.Empty ? Guid.NewGuid() : job.Id;
        var payloadJson = System.Text.Json.JsonSerializer.Serialize(job.Payload);
        var hashInput = !string.IsNullOrWhiteSpace(job.IdempotencyKey)
            ? $"idem|{job.JobType}|{job.SourceId}|{job.IdempotencyKey}"
            : $"job|{job.JobType}|{job.SourceId}|{payloadJson}";
        var entity = new IngestJobEntity
        {
            Id = id,
            JobType = job.JobType,
            Payload = payloadJson,
            PayloadHash = ComputeHash(hashInput),
            SourceId = string.IsNullOrEmpty(job.SourceId) ? null : job.SourceId,
            Status = MapStatus(job.Status),
            Priority = (int)job.Priority,
            ScheduledAt = job.ScheduledAt ?? DateTime.UtcNow,
            MaxAttempts = job.MaxRetries,
            ProgressPercent = job.ProgressPercent,
            ProgressMessage = job.ProgressMessage,
            LinksDiscovered = 0
        };

        await _context.IngestJobs.AddAsync(entity, ct);
        await _context.SaveChangesAsync(ct);

        _logger.LogInformation(
            "Enqueued job {JobId} for source {SourceId}",
            entity.Id, job.SourceId);

        return entity.Id;
    }

    public async Task<IngestJob?> DequeueAsync(string workerId, TimeSpan leaseDuration, CancellationToken ct = default)
    {
        var now = DateTime.UtcNow;
        var expiresAt = now.Add(leaseDuration);

        await using var transaction = await _context.Database.BeginTransactionAsync(ct);

        try
        {
            var entity = await _context.IngestJobs
                .Where(j => j.Status == "pending" || j.Status == "queued")
                .Where(j => j.ScheduledAt <= now)
                .Where(j => j.LockExpiresAt == null || j.LockExpiresAt < now)
                .OrderBy(j => j.Priority)
                .ThenBy(j => j.CreatedAt)
                .FirstOrDefaultAsync(ct);

            if (entity == null)
            {
                await transaction.RollbackAsync(ct);
                return null;
            }

            entity.Status = "processing";
            entity.WorkerId = workerId;
            entity.LockedAt = now;
            entity.LockExpiresAt = expiresAt;
            entity.StartedAt = now;
            entity.Attempts++;

            await _context.SaveChangesAsync(ct);
            await transaction.CommitAsync(ct);

            _logger.LogDebug("Job {JobId} claimed by worker {WorkerId}", entity.Id, workerId);

            return MapToIngestJob(entity);
        }
        catch (Exception)
        {
            await transaction.RollbackAsync(ct);
            throw;
        }
    }

    public async Task CompleteAsync(Guid jobId, CancellationToken ct = default)
    {
        var updated = await _context.IngestJobs
            .Where(j => j.Id == jobId)
            .ExecuteUpdateAsync(setters => setters
                .SetProperty(j => j.Status, "completed")
                .SetProperty(j => j.WorkerId, (string?)null)
                .SetProperty(j => j.LockedAt, (DateTime?)null)
                .SetProperty(j => j.LockExpiresAt, (DateTime?)null)
                .SetProperty(j => j.CompletedAt, DateTime.UtcNow)
                .SetProperty(j => j.ProgressPercent, 100), ct);

        if (updated > 0)
            _logger.LogInformation("Job {JobId} completed", jobId);
    }

    public async Task FailAsync(Guid jobId, string error, bool shouldRetry, CancellationToken ct = default)
    {
        var entity = await _context.IngestJobs
            .AsNoTracking()
            .FirstOrDefaultAsync(j => j.Id == jobId, ct);
        if (entity == null)
            return;

        if (shouldRetry && entity.Attempts < entity.MaxAttempts)
        {
            var delay = TimeSpan.FromMinutes(Math.Pow(2, entity.Attempts));
            var retryAt = DateTime.UtcNow.Add(delay);
            await _context.IngestJobs
                .Where(j => j.Id == jobId)
                .ExecuteUpdateAsync(setters => setters
                    .SetProperty(j => j.LastError, error)
                    .SetProperty(j => j.WorkerId, (string?)null)
                    .SetProperty(j => j.LockedAt, (DateTime?)null)
                    .SetProperty(j => j.LockExpiresAt, (DateTime?)null)
                    .SetProperty(j => j.CompletedAt, DateTime.UtcNow)
                    .SetProperty(j => j.Status, "pending")
                    .SetProperty(j => j.RetryAt, retryAt), ct);
            _logger.LogWarning("Job {JobId} failed, will retry. Error: {Error}", jobId, error);
        }
        else
        {
            await _context.IngestJobs
                .Where(j => j.Id == jobId)
                .ExecuteUpdateAsync(setters => setters
                    .SetProperty(j => j.LastError, error)
                    .SetProperty(j => j.WorkerId, (string?)null)
                    .SetProperty(j => j.LockedAt, (DateTime?)null)
                    .SetProperty(j => j.LockExpiresAt, (DateTime?)null)
                    .SetProperty(j => j.CompletedAt, DateTime.UtcNow)
                    .SetProperty(j => j.Status, "failed"), ct);
            _logger.LogError("Job {JobId} failed permanently. Error: {Error}", jobId, error);
        }
    }

    public async Task ReleaseLeaseAsync(Guid jobId, CancellationToken ct = default)
    {
        var entity = await _context.IngestJobs.FindAsync(new object[] { jobId }, ct);
        if (entity == null) return;

        entity.WorkerId = null;
        entity.LockedAt = null;
        entity.LockExpiresAt = null;
        entity.Status = "pending";

        await _context.SaveChangesAsync(ct);
    }

    public async Task<bool> HeartbeatAsync(Guid jobId, CancellationToken ct = default)
    {
        var updated = await _context.IngestJobs
            .Where(j => j.Id == jobId)
            .ExecuteUpdateAsync(setters => setters
                .SetProperty(j => j.LockExpiresAt, DateTime.UtcNow.AddMinutes(2)), ct);
        return updated > 0;
    }

    public async Task UpdateProgressAsync(Guid jobId, int percent, string? message, int? linksDiscovered, CancellationToken ct = default)
    {
        var query = _context.IngestJobs.Where(j => j.Id == jobId);
        if (linksDiscovered.HasValue)
        {
            await query.ExecuteUpdateAsync(setters => setters
                .SetProperty(j => j.ProgressPercent, percent)
                .SetProperty(j => j.ProgressMessage, message)
                .SetProperty(j => j.LinksDiscovered, linksDiscovered.Value)
                .SetProperty(j => j.LockExpiresAt, DateTime.UtcNow.AddMinutes(2)), ct);
        }
        else
        {
            await query.ExecuteUpdateAsync(setters => setters
                .SetProperty(j => j.ProgressPercent, percent)
                .SetProperty(j => j.ProgressMessage, message)
                .SetProperty(j => j.LockExpiresAt, DateTime.UtcNow.AddMinutes(2)), ct);
        }
    }

    public async Task<Gabi.Contracts.Jobs.JobStatus?> GetStatusAsync(Guid jobId, CancellationToken ct = default)
    {
        var entity = await _context.IngestJobs
            .AsNoTracking()
            .FirstOrDefaultAsync(j => j.Id == jobId, ct);

        if (entity == null) return null;

        return ParseStatus(entity.Status);
    }

    public async Task CancelAsync(Guid jobId, string reason, CancellationToken ct = default)
    {
        var entity = await _context.IngestJobs.FindAsync(new object[] { jobId }, ct);
        if (entity == null) return;

        entity.Status = "cancelled";
        entity.WorkerId = null;
        entity.LockedAt = null;
        entity.LockExpiresAt = null;
        entity.LastError = $"Cancelled: {reason}";

        await _context.SaveChangesAsync(ct);
    }

    public async Task<IReadOnlyList<Guid>> RecoverStalledJobsAsync(TimeSpan stallTimeout, CancellationToken ct = default)
    {
        var cutoff = DateTime.UtcNow.Subtract(stallTimeout);

        var stalledJobs = await _context.IngestJobs
            .Where(j => j.Status == "processing")
            .Where(j => j.LockExpiresAt < cutoff)
            .ToListAsync(ct);

        if (!stalledJobs.Any())
            return Array.Empty<Guid>();

        var recovered = new List<Guid>();

        foreach (var job in stalledJobs)
        {
            job.WorkerId = null;
            job.LockedAt = null;
            job.LockExpiresAt = null;
            job.Attempts++;

            if (job.Attempts >= job.MaxAttempts)
            {
                job.Status = "failed";
                _logger.LogError("Job {JobId} failed after stall timeout", job.Id);
            }
            else
            {
                job.Status = "pending";
                recovered.Add(job.Id);
                _logger.LogWarning("Recovered stalled job {JobId}", job.Id);
            }
        }

        await _context.SaveChangesAsync(ct);
        return recovered;
    }

    public async Task<JobQueueStatistics> GetStatisticsAsync(CancellationToken ct = default)
    {
        var stats = await _context.IngestJobs
            .GroupBy(j => j.Status)
            .Select(g => new { Status = g.Key, Count = g.Count() })
            .ToListAsync(ct);

        var running = await _context.IngestJobs
            .Where(j => j.Status == "processing")
            .Select(j => new RunningJobInfo
            {
                JobId = j.Id,
                SourceId = j.SourceId ?? string.Empty,
                WorkerId = j.WorkerId ?? string.Empty,
                StartedAt = j.StartedAt ?? DateTime.UtcNow,
                ProgressPercent = j.ProgressPercent ?? 0
            })
            .ToListAsync(ct);

        return new JobQueueStatistics
        {
            PendingCount = stats.FirstOrDefault(s => s.Status == "pending")?.Count ?? 0,
            RunningCount = stats.FirstOrDefault(s => s.Status == "processing")?.Count ?? 0,
            CompletedCount = stats.FirstOrDefault(s => s.Status == "completed")?.Count ?? 0,
            FailedCount = stats.FirstOrDefault(s => s.Status == "failed")?.Count ?? 0,
            CancelledCount = stats.FirstOrDefault(s => s.Status == "cancelled")?.Count ?? 0,
            TotalCount = stats.Sum(s => s.Count),
            RunningJobs = running
        };
    }

    /// <summary>
    /// Get latest job status for a source.
    /// </summary>
    public async Task<IngestJob?> GetLatestForSourceAsync(string sourceId, CancellationToken ct = default)
    {
        var entity = await _context.IngestJobs
            .AsNoTracking()
            .Where(j => j.SourceId == sourceId)
            .OrderByDescending(j => j.CreatedAt)
            .FirstOrDefaultAsync(ct);

        return entity == null ? null : MapToIngestJob(entity);
    }

    /// <inheritdoc />
    public async Task<IngestJob?> GetLatestByJobTypeAsync(string jobType, CancellationToken ct = default)
    {
        var entity = await _context.IngestJobs
            .AsNoTracking()
            .Where(j => j.JobType == jobType)
            .OrderByDescending(j => j.CreatedAt)
            .FirstOrDefaultAsync(ct);
        return entity == null ? null : MapToIngestJob(entity);
    }

    /// <summary>
    /// Gets recent jobs for the dashboard.
    /// </summary>
    public async Task<IReadOnlyList<IngestJob>> GetRecentJobsAsync(int limit = 50, CancellationToken ct = default)
    {
        var entities = await _context.IngestJobs
            .AsNoTracking()
            .OrderByDescending(j => j.CreatedAt)
            .Take(limit)
            .ToListAsync(ct);

        return entities.Select(MapToIngestJob).ToList();
    }

    /// <summary>
    /// Get job status with details for API.
    /// </summary>
    public async Task<Gabi.Contracts.Api.JobStatusDto?> GetJobStatusDtoAsync(string sourceId, CancellationToken ct = default)
    {
        var entity = await _context.IngestJobs
            .AsNoTracking()
            .Where(j => j.SourceId == sourceId)
            .OrderByDescending(j => j.CreatedAt)
            .FirstOrDefaultAsync(ct);
        if (entity == null) return null;
        return new Gabi.Contracts.Api.JobStatusDto(
            entity.Id.ToString(),
            entity.SourceId ?? string.Empty,
            entity.Status,
            entity.ProgressPercent ?? 0,
            entity.ProgressMessage,
            entity.LinksDiscovered,
            entity.StartedAt,
            entity.CompletedAt,
            entity.LastError
        );
    }

    private static IngestJob MapToIngestJob(IngestJobEntity entity)
    {
        var discoveryConfig = ParseDiscoveryConfigFromPayload(entity.Payload);

        return new IngestJob
        {
            Id = entity.Id,
            SourceId = entity.SourceId ?? string.Empty,
            JobType = entity.JobType,
            Status = ParseStatus(entity.Status),
            Priority = (Gabi.Contracts.Jobs.JobPriority)entity.Priority,
            MaxRetries = entity.MaxAttempts,
            RetryCount = entity.Attempts,
            CreatedAt = entity.CreatedAt,
            StartedAt = entity.StartedAt,
            CompletedAt = entity.CompletedAt,
            WorkerId = entity.WorkerId,
            LastHeartbeatAt = entity.LockedAt,
            ErrorMessage = entity.LastError,
            ProgressPercent = entity.ProgressPercent ?? 0,
            ProgressMessage = entity.ProgressMessage,
            DiscoveryConfig = discoveryConfig ?? new Gabi.Contracts.Discovery.DiscoveryConfig(),
            Payload = ParsePayload(entity.Payload)
        };
    }

    private static Dictionary<string, object> ParsePayload(string? payloadJson)
    {
        if (string.IsNullOrWhiteSpace(payloadJson)) return new Dictionary<string, object>();
        try
        {
            var doc = System.Text.Json.JsonSerializer.Deserialize<System.Text.Json.JsonElement>(payloadJson);
            return JsonElementToDictionary(doc);
        }
        catch
        {
            return new Dictionary<string, object>();
        }
    }

    private static Dictionary<string, object> JsonElementToDictionary(System.Text.Json.JsonElement el)
    {
        var d = new Dictionary<string, object>();
        foreach (var p in el.EnumerateObject())
        {
            d[p.Name] = p.Value.ValueKind switch
            {
                System.Text.Json.JsonValueKind.Object => JsonElementToDictionary(p.Value),
                System.Text.Json.JsonValueKind.Array => p.Value.EnumerateArray().Select(e => (object)e.Clone()).ToList(),
                System.Text.Json.JsonValueKind.String => p.Value.GetString() ?? "",
                System.Text.Json.JsonValueKind.Number => p.Value.TryGetInt64(out var n) ? n : p.Value.GetDouble(),
                System.Text.Json.JsonValueKind.True => true,
                System.Text.Json.JsonValueKind.False => false,
                _ => p.Value.Clone()
            };
        }
        return d;
    }

    private static Gabi.Contracts.Discovery.DiscoveryConfig? ParseDiscoveryConfigFromPayload(string? payloadJson)
    {
        if (string.IsNullOrWhiteSpace(payloadJson)) return null;
        try
        {
            var doc = System.Text.Json.JsonSerializer.Deserialize<System.Text.Json.JsonElement>(payloadJson);
            if (!doc.TryGetProperty("discoveryConfig", out var dc)) return null;
            var innerJson = dc.ValueKind == System.Text.Json.JsonValueKind.String ? dc.GetString() : dc.GetRawText();
            if (string.IsNullOrWhiteSpace(innerJson)) return null;
            var options = new System.Text.Json.JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true,
                ReadCommentHandling = System.Text.Json.JsonCommentHandling.Skip,
                AllowTrailingCommas = true
            };
            try
            {
                return System.Text.Json.JsonSerializer.Deserialize<Gabi.Contracts.Discovery.DiscoveryConfig>(innerJson, options);
            }
            catch
            {
                var fallback = System.Text.Json.JsonSerializer.Deserialize<System.Text.Json.JsonElement>(innerJson);
                var strategy = fallback.TryGetProperty("strategy", out var s) ? s.GetString() : null;
                var urlTemplate = fallback.TryGetProperty("urlTemplate", out var u) ? u.GetString() : null;
                if (string.IsNullOrEmpty(urlTemplate) && fallback.TryGetProperty("template", out var t))
                    urlTemplate = t.GetString();
                var url = fallback.TryGetProperty("url", out var urlNode) ? urlNode.GetString() : null;
                if (string.IsNullOrEmpty(strategy) && !string.IsNullOrEmpty(urlTemplate)) strategy = "url_pattern";
                if (string.IsNullOrEmpty(strategy)) strategy = "static_url";
                return new Gabi.Contracts.Discovery.DiscoveryConfig
                {
                    Strategy = strategy ?? "static_url",
                    UrlTemplate = urlTemplate ?? "",
                    Url = url
                };
            }
        }
        catch
        {
            return null;
        }
    }

    private static string MapStatus(Gabi.Contracts.Jobs.JobStatus status) => status.ToString().ToLowerInvariant();

    private static Gabi.Contracts.Jobs.JobStatus ParseStatus(string status) => status.ToLowerInvariant() switch
    {
        "pending" => Gabi.Contracts.Jobs.JobStatus.Pending,
        "running" => Gabi.Contracts.Jobs.JobStatus.Running,
        "completed" => Gabi.Contracts.Jobs.JobStatus.Completed,
        "failed" => Gabi.Contracts.Jobs.JobStatus.Failed,
        "cancelled" => Gabi.Contracts.Jobs.JobStatus.Cancelled,
        _ => Gabi.Contracts.Jobs.JobStatus.Pending
    };

    private static string ComputeHash(string input)
    {
        using var sha256 = System.Security.Cryptography.SHA256.Create();
        var bytes = sha256.ComputeHash(System.Text.Json.JsonSerializer.SerializeToUtf8Bytes(input));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }
}

/// <summary>
/// Linha de job para o dashboard (fonte, status, datas).
/// </summary>
public record RecentJobView(
    string SourceId,
    string Status,
    DateTime? CompletedAt,
    DateTime? StartedAt,
    DateTime CreatedAt
);
