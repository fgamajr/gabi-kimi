using Gabi.Contracts.Jobs;
using Gabi.Contracts.Workflow;
using Gabi.Postgres.Entities;
using Hangfire;
using Hangfire.States;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;

namespace Gabi.Postgres.Repositories;

/// <summary>
/// Implementação de IJobQueueRepository usando Hangfire (Postgres) + job_registry para consultas do dashboard.
/// Enfileiramento por fila (seed, discovery, fetch, ingest, default) para o Worker processar na ordem correta.
/// </summary>
public class HangfireJobQueueRepository : IJobQueueRepository
{
    private readonly GabiDbContext _context;
    private readonly IBackgroundJobClient _client;
    private readonly ILogger<HangfireJobQueueRepository> _logger;
    private readonly IConfiguration _configuration;
    private readonly IWorkflowOrchestrator? _orchestrator;
    private readonly ITemporalHealthCheck? _temporalHealthCheck;

    public HangfireJobQueueRepository(
        GabiDbContext context,
        IBackgroundJobClient client,
        ILogger<HangfireJobQueueRepository> logger,
        IConfiguration configuration,
        IWorkflowOrchestrator? orchestrator = null,
        ITemporalHealthCheck? temporalHealthCheck = null)
    {
        _context = context;
        _client = client;
        _logger = logger;
        _configuration = configuration;
        _orchestrator = orchestrator;
        _temporalHealthCheck = temporalHealthCheck;
    }

    private static string QueueForJobType(string jobType)
    {
        return jobType switch
        {
            "catalog_seed" => "seed",
            "source_discovery" => "discovery",
            "fetch" => "fetch",
            "ingest" => "ingest",
            "media_transcribe" => "ingest",
            "embed_and_index" => "embed",
            _ => "default"
        };
    }

    private static bool EnforceSingleInFlightPerSource(string jobType)
        => jobType is "source_discovery" or "fetch" or "ingest" or "media_transcribe";

    public async Task<Guid> EnqueueAsync(IngestJob job, CancellationToken ct = default)
    {
        // Invariant 5: per-source Temporal dispatch (AND-gated with global kill-switch)
        var globalEnabled = string.Equals(_configuration["Gabi:EnableTemporalWorker"], "true", StringComparison.OrdinalIgnoreCase);
        if (globalEnabled && _orchestrator is not null && _temporalHealthCheck is not null
            && !string.IsNullOrEmpty(job.SourceId))
        {
            var sourceConfig = await _context.SourceRegistries
                .AsNoTracking()
                .FirstOrDefaultAsync(s => s.Id == job.SourceId, ct);
            if (sourceConfig?.UseTemporalOrchestration == true)
            {
                var timeoutMs = int.TryParse(_configuration["Gabi:TemporalReachabilityTimeoutMs"], out var ms) ? ms : 2000;
                var reachabilityTimeout = TimeSpan.FromMilliseconds(timeoutMs);
                var reachable = await _temporalHealthCheck.IsReachableAsync(reachabilityTimeout, ct);
                if (reachable)
                {
                    var temporalJobId = await _orchestrator.StartAsync(job, ct);
                    _logger.LogInformation(
                        "Dispatched job {JobId} ({JobType}) via Temporal for source {SourceId}",
                        temporalJobId, job.JobType, job.SourceId);
                    return temporalJobId;
                }
                _logger.LogWarning(
                    "Temporal unreachable (timeout {Ms}ms); falling back to Hangfire for source {SourceId}",
                    reachabilityTimeout.TotalMilliseconds, job.SourceId);
            }
        }

        // ── Hangfire path (unchanged) ──
        await using var tx = await _context.Database.BeginTransactionAsync(ct);

        if (job.JobType == "catalog_seed")
        {
            await AcquireEnqueueLockAsync($"jobtype:{job.JobType}", ct);
            var existing = await GetLatestByJobTypeAsync("catalog_seed", ct);
            if (existing?.Status is JobStatus.Pending or JobStatus.Running)
            {
                _logger.LogInformation("Seed already in progress, returning existing job {JobId}", existing.Id);
                await tx.CommitAsync(ct);
                return existing.Id;
            }
        }
        else if (!string.IsNullOrEmpty(job.SourceId) && EnforceSingleInFlightPerSource(job.JobType))
        {
            await AcquireEnqueueLockAsync($"source:{job.JobType}:{job.SourceId}", ct);
            var existing = await GetLatestActiveForSourceAndJobTypeAsync(job.SourceId, job.JobType, ct);
            if (existing is not null)
            {
                _logger.LogInformation(
                    "Job already in progress for source {SourceId} and job type {JobType}, returning {JobId}",
                    job.SourceId,
                    job.JobType,
                    existing.Id);
                await tx.CommitAsync(ct);
                return existing.Id;
            }
        }

        var jobId = job.Id == Guid.Empty ? Guid.NewGuid() : job.Id;
        var payloadJson = System.Text.Json.JsonSerializer.Serialize(job.Payload ?? new Dictionary<string, object>());

        var reg = new JobRegistryEntity
        {
            JobId = jobId,
            SourceId = string.IsNullOrEmpty(job.SourceId) ? null : job.SourceId,
            JobType = job.JobType,
            Status = "pending",
            CreatedAt = DateTime.UtcNow,
            ProgressPercent = 0
        };
        _context.JobRegistry.Add(reg);
        await _context.SaveChangesAsync(ct);

        var queue = QueueForJobType(job.JobType);
        _logger.LogInformation("Enqueuing job {JobId} ({JobType}) to queue '{Queue}' for source {SourceId}", jobId, job.JobType, queue, job.SourceId);
        try
        {
            var hangfireJobId = _client.Create(
                (IGabiJobRunner r) => r.RunAsync(jobId, job.JobType, job.SourceId ?? string.Empty, payloadJson, CancellationToken.None),
                new EnqueuedState(queue));

            if (string.IsNullOrWhiteSpace(hangfireJobId))
                throw new InvalidOperationException("Hangfire returned an empty job id for enqueue request.");

            reg.HangfireJobId = hangfireJobId;
            await _context.SaveChangesAsync(ct);
            _logger.LogInformation("Hangfire job created successfully for {JobId}", jobId);
        }
        catch (Exception ex)
        {
            reg.Status = "failed";
            reg.ErrorMessage = "Falha ao enfileirar no Hangfire: " + (ex.Message.Length > 1900 ? ex.Message[..1900] : ex.Message);
            reg.CompletedAt = DateTime.UtcNow;
            await _context.SaveChangesAsync(ct);
            await tx.CommitAsync(ct);
            _logger.LogError(ex, "Failed to enqueue Hangfire job {JobId} of type {JobType}. Exception: {ExceptionType}", jobId, job.JobType, ex.GetType().Name);
            throw;
        }

        await tx.CommitAsync(ct);
        _logger.LogInformation("Enqueued job {JobId} ({JobType}) for source {SourceId} in queue '{Queue}'", jobId, job.JobType, job.SourceId, queue);
        return jobId;
    }

    public async Task<Guid> ScheduleAsync(IngestJob job, TimeSpan delay, CancellationToken ct = default)
    {
        var jobId = job.Id == Guid.Empty ? Guid.NewGuid() : job.Id;
        var payloadJson = System.Text.Json.JsonSerializer.Serialize(job.Payload ?? new Dictionary<string, object>());

        var reg = new JobRegistryEntity
        {
            JobId = jobId,
            SourceId = string.IsNullOrEmpty(job.SourceId) ? null : job.SourceId,
            JobType = job.JobType,
            Status = "pending",
            CreatedAt = DateTime.UtcNow,
            ProgressPercent = 0
        };
        _context.JobRegistry.Add(reg);
        await _context.SaveChangesAsync(ct);

        try
        {
            var hangfireJobId = _client.Create(
                (IGabiJobRunner r) => r.RunAsync(jobId, job.JobType, job.SourceId ?? string.Empty, payloadJson, CancellationToken.None),
                new ScheduledState(delay));

            if (string.IsNullOrWhiteSpace(hangfireJobId))
                throw new InvalidOperationException("Hangfire returned an empty job id for schedule request.");

            reg.HangfireJobId = hangfireJobId;
            await _context.SaveChangesAsync(ct);
            _logger.LogInformation("Scheduled job {JobId} ({JobType}) for source {SourceId} in {Delay}s", jobId, job.JobType, job.SourceId, delay.TotalSeconds);
        }
        catch (Exception ex)
        {
            reg.Status = "failed";
            reg.ErrorMessage = "Falha ao agendar no Hangfire: " + (ex.Message.Length > 1900 ? ex.Message[..1900] : ex.Message);
            reg.CompletedAt = DateTime.UtcNow;
            await _context.SaveChangesAsync(ct);
            _logger.LogError(ex, "Failed to schedule Hangfire job {JobId} of type {JobType}", jobId, job.JobType);
            throw;
        }

        return jobId;
    }

    public Task<IngestJob?> DequeueAsync(string workerId, TimeSpan leaseDuration, CancellationToken ct = default)
        => Task.FromResult<IngestJob?>(null);

    public async Task CompleteAsync(Guid jobId, CancellationToken ct = default)
    {
        await CompleteAsync(jobId, "completed", ct);
    }

    public async Task CompleteAsync(Guid jobId, string terminalStatus, CancellationToken ct = default)
    {
        var reg = await _context.JobRegistry.FirstOrDefaultAsync(r => r.JobId == jobId, ct);
        if (reg == null) return;
        reg.Status = terminalStatus;
        reg.CompletedAt = DateTime.UtcNow;
        reg.ErrorMessage = null;
        reg.ProgressPercent = 100;
        await _context.SaveChangesAsync(ct);
    }

    public async Task FailAsync(Guid jobId, string error, bool shouldRetry, CancellationToken ct = default)
    {
        var reg = await _context.JobRegistry.FirstOrDefaultAsync(r => r.JobId == jobId, ct);
        if (reg == null) return;
        reg.Status = "failed";
        reg.CompletedAt = DateTime.UtcNow;
        reg.ErrorMessage = error.Length > 2000 ? error[..2000] : error;
        await _context.SaveChangesAsync(ct);
    }

    public Task ReleaseLeaseAsync(Guid jobId, CancellationToken ct = default) => Task.CompletedTask;
    public Task<bool> HeartbeatAsync(Guid jobId, CancellationToken ct = default) => Task.FromResult(true);

    public async Task UpdateProgressAsync(Guid jobId, int percent, string? message, int? linksDiscovered, CancellationToken ct = default)
    {
        var reg = await _context.JobRegistry.FirstOrDefaultAsync(r => r.JobId == jobId, ct);
        if (reg == null) return;
        reg.ProgressPercent = percent;
        reg.ProgressMessage = message?.Length > 500 ? message[..500] : message;
        await _context.SaveChangesAsync(ct);
    }

    public async Task<JobStatus?> GetStatusAsync(Guid jobId, CancellationToken ct = default)
    {
        var reg = await _context.JobRegistry.AsNoTracking().FirstOrDefaultAsync(r => r.JobId == jobId, ct);
        return reg == null ? null : ParseStatus(reg.Status);
    }

    public async Task CancelAsync(Guid jobId, string reason, CancellationToken ct = default)
    {
        var reg = await _context.JobRegistry.FirstOrDefaultAsync(r => r.JobId == jobId, ct);
        if (reg == null) return;
        if (reg.Status == "pending" || reg.Status == "processing")
        {
            reg.Status = "cancelled";
            reg.CompletedAt = DateTime.UtcNow;
            reg.ErrorMessage = reason?.Length > 2000 ? reason[..2000] : reason;
            await _context.SaveChangesAsync(ct);
        }
    }

    public Task<IReadOnlyList<Guid>> RecoverStalledJobsAsync(TimeSpan stallTimeout, CancellationToken ct = default)
        => Task.FromResult<IReadOnlyList<Guid>>(Array.Empty<Guid>());

    public async Task<JobQueueStatistics> GetStatisticsAsync(CancellationToken ct = default)
    {
        var stats = await _context.JobRegistry
            .GroupBy(r => r.Status)
            .Select(g => new { Status = g.Key, Count = g.Count() })
            .ToListAsync(ct);

        var running = await _context.JobRegistry
            .Where(r => r.Status == "processing")
            .Select(r => new RunningJobInfo
            {
                JobId = r.JobId,
                SourceId = r.SourceId ?? string.Empty,
                WorkerId = "",
                StartedAt = r.StartedAt ?? DateTime.UtcNow,
                ProgressPercent = r.ProgressPercent
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

    public async Task<IngestJob?> GetLatestForSourceAsync(string sourceId, CancellationToken ct = default)
    {
        var reg = await _context.JobRegistry
            .AsNoTracking()
            .Where(r => r.SourceId == sourceId)
            .OrderByDescending(r => r.CreatedAt)
            .FirstOrDefaultAsync(ct);
        return reg == null ? null : MapToIngestJob(reg);
    }

    public async Task<IngestJob?> GetLatestByJobTypeAsync(string jobType, CancellationToken ct = default)
    {
        var reg = await _context.JobRegistry
            .AsNoTracking()
            .Where(r => r.JobType == jobType)
            .OrderByDescending(r => r.CreatedAt)
            .FirstOrDefaultAsync(ct);
        return reg == null ? null : MapToIngestJob(reg);
    }

    public async Task<IReadOnlyList<IngestJob>> GetRecentJobsAsync(int limit = 50, CancellationToken ct = default)
    {
        var list = await _context.JobRegistry
            .AsNoTracking()
            .OrderByDescending(r => r.CreatedAt)
            .Take(limit)
            .ToListAsync(ct);
        return list.Select(MapToIngestJob).ToList();
    }

    private static IngestJob MapToIngestJob(JobRegistryEntity r)
    {
        return new IngestJob
        {
            Id = r.JobId,
            SourceId = r.SourceId ?? string.Empty,
            JobType = r.JobType,
            Status = ParseStatus(r.Status),
            CreatedAt = r.CreatedAt,
            StartedAt = r.StartedAt,
            CompletedAt = r.CompletedAt,
            ErrorMessage = r.ErrorMessage,
            ProgressPercent = r.ProgressPercent,
            ProgressMessage = r.ProgressMessage,
            Payload = new Dictionary<string, object>(),
            DiscoveryConfig = new Gabi.Contracts.Discovery.DiscoveryConfig()
        };
    }

    public async Task<Gabi.Contracts.Api.JobStatusDto?> GetJobStatusDtoAsync(string sourceId, CancellationToken ct = default)
    {
        var reg = await _context.JobRegistry
            .AsNoTracking()
            .Where(r => r.SourceId == sourceId)
            .OrderByDescending(r => r.CreatedAt)
            .FirstOrDefaultAsync(ct);
        if (reg == null) return null;
        return new Gabi.Contracts.Api.JobStatusDto(
            reg.JobId.ToString(),
            reg.SourceId ?? string.Empty,
            reg.Status,
            reg.ProgressPercent,
            reg.ProgressMessage,
            0,
            reg.StartedAt,
            reg.CompletedAt,
            reg.ErrorMessage
        );
    }

    private static JobStatus ParseStatus(string status) => status?.ToLowerInvariant() switch
    {
        "pending" or "queued" => JobStatus.Pending,
        "processing" or "running" => JobStatus.Running,
        "completed" => JobStatus.Completed,
        "partial" => JobStatus.Partial,
        "capped" => JobStatus.Capped,
        "inconclusive" => JobStatus.Inconclusive,
        "failed" => JobStatus.Failed,
        "cancelled" => JobStatus.Cancelled,
        _ => JobStatus.Pending
    };

    private async Task AcquireEnqueueLockAsync(string lockScope, CancellationToken ct)
    {
        var lockKey = ComputeAdvisoryLockKey(lockScope);
        await _context.Database.ExecuteSqlInterpolatedAsync(
            $"SELECT pg_advisory_xact_lock({lockKey})",
            ct);
    }

    private static long ComputeAdvisoryLockKey(string lockScope)
    {
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(lockScope));
        return BinaryPrimitives.ReadInt64LittleEndian(hash.AsSpan(0, sizeof(long)));
    }

    private async Task<IngestJob?> GetLatestActiveForSourceAndJobTypeAsync(string sourceId, string jobType, CancellationToken ct)
    {
        var reg = await _context.JobRegistry
            .AsNoTracking()
            .Where(r => r.SourceId == sourceId && r.JobType == jobType)
            .Where(r => r.Status == "pending" || r.Status == "queued" || r.Status == "processing" || r.Status == "running")
            .OrderByDescending(r => r.CreatedAt)
            .FirstOrDefaultAsync(ct);

        return reg == null ? null : MapToIngestJob(reg);
    }
}
