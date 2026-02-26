using System.Data;
using System.Text.Json;
using Dapper;
using Gabi.Contracts.Jobs;
using Microsoft.Extensions.Logging;

namespace Gabi.Sync.Jobs;

/// <summary>
/// PostgreSQL implementation of the job queue repository using SKIP LOCKED for atomic claims.
/// Works with the existing ingest_jobs table schema.
/// </summary>
public class JobQueueRepository : IJobQueueRepository
{
    private readonly IDbConnection _connection;
    private readonly ILogger<JobQueueRepository> _logger;
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase
    };

    // Reject payloads above 256 KB to prevent OOM poison-pill jobs (GEMINI-04)
    private const int MaxPayloadBytes = 256 * 1024;

    public JobQueueRepository(IDbConnection connection, ILogger<JobQueueRepository> logger)
    {
        _connection = connection;
        _logger = logger;
    }

    /// <inheritdoc />
    public async Task<Guid> EnqueueAsync(IngestJob job, CancellationToken ct = default)
    {
        const string sql = @"
            INSERT INTO ingest_jobs (
                job_type, payload, payload_hash, source_id, status, 
                priority, scheduled_at, max_attempts, attempts,
                link_id, progress_percent, progress_message,
                created_at, updated_at
            ) VALUES (
                @JobType, @Payload::jsonb, @PayloadHash, @SourceId, @Status,
                @Priority, COALESCE(@ScheduledAt, NOW()), @MaxRetries, 0,
                NULL, 0, @ProgressMessage,
                NOW(), NOW()
            )
            ON CONFLICT (payload_hash) 
            WHERE status IN ('pending', 'queued', 'processing')
            DO UPDATE SET 
                updated_at = NOW()
            RETURNING id";

        var payloadJson = JsonSerializer.Serialize(job.Payload, JsonOptions);
        if (payloadJson.Length > MaxPayloadBytes)
            throw new InvalidOperationException(
                $"Job payload for source '{job.SourceId}' exceeds the {MaxPayloadBytes / 1024} KB limit ({payloadJson.Length / 1024} KB). Reduce payload size.");
        var payloadHash = ComputeHash(payloadJson);

        var parameters = new
        {
            job.JobType,
            Payload = payloadJson,
            PayloadHash = payloadHash,
            job.SourceId,
            Status = "pending",
            Priority = (int)job.Priority,
            job.ScheduledAt,
            job.MaxRetries,
            ProgressMessage = $"Enqueued job for {job.SourceId}"
        };

        var id = await _connection.ExecuteScalarAsync<long>(
            new CommandDefinition(sql, parameters, cancellationToken: ct));

        _logger.LogInformation(
            "Enqueued job {JobId} for source {SourceId} with priority {Priority}",
            id, job.SourceId, job.Priority);

        // Return a deterministic GUID based on the ID for consistency
        return IdToGuid(id);
    }

    /// <inheritdoc />
    public async Task<Guid> ScheduleAsync(IngestJob job, TimeSpan delay, CancellationToken ct = default)
    {
        var scheduledAt = DateTime.UtcNow.Add(delay);
        const string sql = @"
            INSERT INTO ingest_jobs (
                job_type, payload, payload_hash, source_id, status,
                priority, scheduled_at, max_attempts, attempts,
                link_id, progress_percent, progress_message,
                created_at, updated_at
            ) VALUES (
                @JobType, @Payload::jsonb, @PayloadHash, @SourceId, @Status,
                @Priority, @ScheduledAt, @MaxRetries, 0,
                NULL, 0, @ProgressMessage,
                NOW(), NOW()
            )
            ON CONFLICT (payload_hash)
            WHERE status IN ('pending', 'queued', 'processing')
            DO UPDATE SET
                scheduled_at = @ScheduledAt,
                updated_at = NOW()
            RETURNING id";

        var payloadJson = JsonSerializer.Serialize(job.Payload, JsonOptions);
        if (payloadJson.Length > MaxPayloadBytes)
            throw new InvalidOperationException(
                $"Job payload for source '{job.SourceId}' exceeds the {MaxPayloadBytes / 1024} KB limit ({payloadJson.Length / 1024} KB). Reduce payload size.");
        var payloadHash = ComputeHash(payloadJson);

        var parameters = new
        {
            job.JobType,
            Payload = payloadJson,
            PayloadHash = payloadHash,
            job.SourceId,
            Status = "pending",
            Priority = (int)job.Priority,
            ScheduledAt = scheduledAt,
            job.MaxRetries,
            ProgressMessage = $"Scheduled in {delay.TotalSeconds:F0}s for {job.SourceId}"
        };

        var id = await _connection.ExecuteScalarAsync<long>(
            new CommandDefinition(sql, parameters, cancellationToken: ct));

        _logger.LogInformation(
            "Scheduled job for source {SourceId} in {Delay}s",
            job.SourceId, delay.TotalSeconds);

        return IdToGuid(id);
    }

    /// <inheritdoc />
    public async Task<IngestJob?> DequeueAsync(string workerId, TimeSpan leaseDuration, CancellationToken ct = default)
    {
        // Use SKIP LOCKED to atomically claim the next available job
        const string sql = @"
            WITH next_job AS (
                SELECT id 
                FROM ingest_jobs 
                WHERE status IN ('pending', 'queued')
                  AND (scheduled_at IS NULL OR scheduled_at <= NOW())
                  AND (lock_expires_at IS NULL OR lock_expires_at < NOW())
                ORDER BY priority ASC, created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE ingest_jobs 
            SET status = 'processing',
                worker_id = @WorkerId,
                locked_at = NOW(),
                lock_expires_at = NOW() + @LeaseDuration,
                started_at = COALESCE(started_at, NOW()),
                attempts = attempts + 1,
                updated_at = NOW()
            FROM next_job
            WHERE ingest_jobs.id = next_job.id
            RETURNING 
                id, source_id, job_type, status, priority,
                payload, max_attempts, attempts, created_at, scheduled_at,
                started_at, worker_id, locked_at, lock_expires_at,
                progress_percent, progress_message, last_error";

        var result = await _connection.QueryFirstOrDefaultAsync<JobRow>(
            new CommandDefinition(sql, new 
            { 
                WorkerId = workerId,
                LeaseDuration = leaseDuration
            }, cancellationToken: ct));

        if (result == null)
            return null;

        _logger.LogDebug(
            "Worker {WorkerId} claimed job {JobId} for source {SourceId}",
            workerId, result.id, result.source_id);

        return MapToIngestJob(result);
    }

    /// <inheritdoc />
    public async Task CompleteAsync(Guid jobId, CancellationToken ct = default)
    {
        await CompleteAsync(jobId, "completed", ct);
    }

    /// <inheritdoc />
    public async Task CompleteAsync(Guid jobId, string terminalStatus, CancellationToken ct = default)
    {
        var id = GuidToId(jobId);

        const string sql = @"
            UPDATE ingest_jobs 
            SET status = @Status,
                completed_at = NOW(),
                updated_at = NOW(),
                progress_percent = 100,
                progress_message = 'Completed',
                worker_id = NULL,
                lock_expires_at = NULL
            WHERE id = @JobId
            RETURNING source_id";

        var sourceId = await _connection.ExecuteScalarAsync<string>(
            new CommandDefinition(sql, new { JobId = id, Status = terminalStatus }, cancellationToken: ct));

        if (sourceId != null)
        {
            _logger.LogInformation(
                "Job {JobId} for source {SourceId} completed with status {Status}",
                jobId, sourceId, terminalStatus);
        }
    }

    /// <inheritdoc />
    public async Task FailAsync(Guid jobId, string error, bool shouldRetry, CancellationToken ct = default)
    {
        var id = GuidToId(jobId);
        
        if (shouldRetry)
        {
            // Schedule for retry with exponential backoff
            const string retrySql = @"
                UPDATE ingest_jobs 
                SET status = 'pending',
                    retry_at = @NextRetryAt,
                    last_error = @Error,
                    worker_id = NULL,
                    locked_at = NULL,
                    lock_expires_at = NULL,
                    updated_at = NOW()
                WHERE id = @JobId
                RETURNING attempts, max_attempts, source_id";

            var nextRetryAt = RetryPolicy.CalculateNextRetryTime(0);
            
            var result = await _connection.QueryFirstOrDefaultAsync<RetryResult>(
                new CommandDefinition(retrySql, new 
                { 
                    JobId = id, 
                    Error = error,
                    NextRetryAt = nextRetryAt
                }, cancellationToken: ct));

            if (result != null)
            {
                _logger.LogWarning(
                    "Job {JobId} for source {SourceId} failed, scheduled for retry {RetryCount}/{MaxRetries} at {NextRetryAt}",
                    jobId, result.source_id, result.attempts, result.max_attempts, nextRetryAt);
            }
        }
        else
        {
            // Move to dead letter queue
            const string failSql = @"
                WITH job_data AS (
                    SELECT * FROM ingest_jobs WHERE id = @JobId
                )
                INSERT INTO job_dlq (
                    original_job_id, error_message, error_type, 
                    failed_at, worker_id, retry_count, status
                )
                SELECT 
                    id, @Error, 'ExecutionFailed',
                    NOW(), worker_id, attempts, 'pending'
                FROM job_data;

                UPDATE ingest_jobs 
                SET status = 'dead',
                    last_error = @Error,
                    completed_at = NOW(),
                    updated_at = NOW(),
                    worker_id = NULL,
                    lock_expires_at = NULL
                WHERE id = @JobId
                RETURNING source_id";

            var sourceId = await _connection.ExecuteScalarAsync<string>(
                new CommandDefinition(failSql, new { JobId = id, Error = error }, cancellationToken: ct));

            if (sourceId != null)
            {
                _logger.LogError(
                    "Job {JobId} for source {SourceId} moved to DLQ: {Error}",
                    jobId, sourceId, error);
            }
        }
    }

    /// <inheritdoc />
    public async Task ReleaseLeaseAsync(Guid jobId, CancellationToken ct = default)
    {
        var id = GuidToId(jobId);
        
        const string sql = @"
            UPDATE ingest_jobs 
            SET status = 'pending',
                worker_id = NULL,
                locked_at = NULL,
                lock_expires_at = NULL,
                updated_at = NOW()
            WHERE id = @JobId AND status = 'processing'
            RETURNING source_id";

        var sourceId = await _connection.ExecuteScalarAsync<string>(
            new CommandDefinition(sql, new { JobId = id }, cancellationToken: ct));

        if (sourceId != null)
        {
            _logger.LogWarning(
                "Released lease on job {JobId} for source {SourceId}",
                jobId, sourceId);
        }
    }

    /// <inheritdoc />
    public async Task<bool> HeartbeatAsync(Guid jobId, CancellationToken ct = default)
    {
        var id = GuidToId(jobId);
        
        const string sql = @"
            UPDATE ingest_jobs 
            SET lock_expires_at = NOW() + INTERVAL '5 minutes',
                updated_at = NOW()
            WHERE id = @JobId AND status = 'processing'
            RETURNING true";

        return await _connection.ExecuteScalarAsync<bool>(
            new CommandDefinition(sql, new { JobId = id }, cancellationToken: ct));
    }

    /// <inheritdoc />
    public Task UpdateProgressAsync(Guid jobId, int percent, string? message, int? linksDiscovered, CancellationToken ct = default)
    {
        // Sync.JobQueueRepository: optional implementation; Worker uses Postgres.Repositories.JobQueueRepository for progress
        return Task.CompletedTask;
    }

    /// <inheritdoc />
    public async Task<JobStatus?> GetStatusAsync(Guid jobId, CancellationToken ct = default)
    {
        var id = GuidToId(jobId);
        
        const string sql = "SELECT status FROM ingest_jobs WHERE id = @JobId";
        
        var statusStr = await _connection.QueryFirstOrDefaultAsync<string>(
            new CommandDefinition(sql, new { JobId = id }, cancellationToken: ct));

        if (statusStr == null)
            return null;

        return MapStatus(statusStr);
    }

    /// <inheritdoc />
    public async Task CancelAsync(Guid jobId, string reason, CancellationToken ct = default)
    {
        var id = GuidToId(jobId);
        
        const string sql = @"
            UPDATE ingest_jobs 
            SET status = 'cancelled',
                last_error = @Reason,
                completed_at = NOW(),
                updated_at = NOW(),
                worker_id = NULL,
                lock_expires_at = NULL
            WHERE id = @JobId AND status IN ('pending', 'queued', 'processing')
            RETURNING source_id";

        var sourceId = await _connection.ExecuteScalarAsync<string>(
            new CommandDefinition(sql, new { JobId = id, Reason = reason }, cancellationToken: ct));

        if (sourceId != null)
        {
            _logger.LogInformation(
                "Job {JobId} for source {SourceId} cancelled: {Reason}",
                jobId, sourceId, reason);
        }
    }

    /// <inheritdoc />
    public async Task<IReadOnlyList<Guid>> RecoverStalledJobsAsync(TimeSpan stallTimeout, CancellationToken ct = default)
    {
        const string sql = @"
            UPDATE ingest_jobs 
            SET status = 'pending',
                worker_id = NULL,
                locked_at = NULL,
                lock_expires_at = NULL,
                retry_at = @NextRetryAt,
                updated_at = NOW()
            WHERE status = 'processing'
              AND (lock_expires_at IS NULL OR lock_expires_at < NOW() - @Timeout)
            RETURNING id, source_id, worker_id";

        var nextRetryAt = DateTime.UtcNow.Add(RetryPolicy.CalculateDelay(0));
        
        var rows = await _connection.QueryAsync<StalledJobRow>(
            new CommandDefinition(sql, new 
            { 
                Timeout = stallTimeout,
                NextRetryAt = nextRetryAt
            }, cancellationToken: ct));

        var recoveredJobs = rows.ToList();
        
        foreach (var job in recoveredJobs)
        {
            _logger.LogWarning(
                "Recovered stalled job {JobId} for source {SourceId} from worker {WorkerId}",
                job.id, job.source_id, job.worker_id);
        }

        return recoveredJobs.Select(j => IdToGuid(j.id)).ToList();
    }

    /// <inheritdoc />
    public async Task<JobQueueStatistics> GetStatisticsAsync(CancellationToken ct = default)
    {
        const string sql = @"
            SELECT 
                COUNT(*) FILTER (WHERE status IN ('pending', 'queued')) as pending_count,
                COUNT(*) FILTER (WHERE status = 'processing') as running_count,
                COUNT(*) FILTER (WHERE status = 'completed') as completed_count,
                COUNT(*) FILTER (WHERE status = 'failed') as failed_count,
                COUNT(*) FILTER (WHERE status = 'cancelled') as cancelled_count,
                COUNT(*) FILTER (WHERE status = 'dead') as dead_count,
                COUNT(*) as total_count
            FROM ingest_jobs";

        const string runningSql = @"
            SELECT 
                id as JobId,
                source_id as SourceId,
                worker_id as WorkerId,
                started_at as StartedAt,
                COALESCE(progress_percent, 0) as ProgressPercent
            FROM ingest_jobs
            WHERE status = 'processing'
            ORDER BY started_at DESC";

        var stats = await _connection.QueryFirstAsync<StatsRow>(
            new CommandDefinition(sql, cancellationToken: ct));

        var runningJobs = await _connection.QueryAsync<RunningJobInfo>(
            new CommandDefinition(runningSql, cancellationToken: ct));

        return new JobQueueStatistics
        {
            PendingCount = stats.pending_count,
            RunningCount = stats.running_count,
            CompletedCount = stats.completed_count,
            FailedCount = stats.failed_count + stats.dead_count,
            CancelledCount = stats.cancelled_count,
            TotalCount = stats.total_count,
            RunningJobs = runningJobs.ToList()
        };
    }

    /// <inheritdoc />
    public async Task<IngestJob?> GetLatestForSourceAsync(string sourceId, CancellationToken ct = default)
    {
        const string sql = @"
            SELECT 
                id, source_id, job_type, status, priority,
                payload, max_attempts, attempts, created_at, scheduled_at,
                started_at, worker_id, locked_at, lock_expires_at,
                progress_percent, progress_message, last_error
            FROM ingest_jobs
            WHERE source_id = @SourceId
            ORDER BY created_at DESC
            LIMIT 1";

        var result = await _connection.QueryFirstOrDefaultAsync<JobRow>(
            new CommandDefinition(sql, new { SourceId = sourceId }, cancellationToken: ct));

        return result == null ? null : MapToIngestJob(result);
    }

    /// <inheritdoc />
    public async Task<IngestJob?> GetLatestByJobTypeAsync(string jobType, CancellationToken ct = default)
    {
        const string sql = @"
            SELECT 
                id, source_id, job_type, status, priority,
                payload, max_attempts, attempts, created_at, scheduled_at,
                started_at, worker_id, locked_at, lock_expires_at,
                progress_percent, progress_message, last_error
            FROM ingest_jobs
            WHERE job_type = @JobType
            ORDER BY created_at DESC
            LIMIT 1";

        var result = await _connection.QueryFirstOrDefaultAsync<JobRow>(
            new CommandDefinition(sql, new { JobType = jobType }, cancellationToken: ct));

        return result == null ? null : MapToIngestJob(result);
    }

    /// <inheritdoc />
    public async Task<IReadOnlyList<IngestJob>> GetRecentJobsAsync(int limit = 50, CancellationToken ct = default)
    {
        const string sql = @"
            SELECT 
                id, source_id, job_type, status, priority,
                payload, max_attempts, attempts, created_at, scheduled_at,
                started_at, worker_id, locked_at, lock_expires_at,
                progress_percent, progress_message, last_error
            FROM ingest_jobs
            ORDER BY created_at DESC
            LIMIT @Limit";

        var results = await _connection.QueryAsync<JobRow>(
            new CommandDefinition(sql, new { Limit = limit }, cancellationToken: ct));

        return results.Select(MapToIngestJob).ToList();
    }

    /// <inheritdoc />
    public async Task<Gabi.Contracts.Api.JobStatusDto?> GetJobStatusDtoAsync(string sourceId, CancellationToken ct = default)
    {
        const string sql = @"
            SELECT id, source_id, status, progress_percent, progress_message,
                   started_at, completed_at, last_error
            FROM ingest_jobs
            WHERE source_id = @SourceId
            ORDER BY created_at DESC
            LIMIT 1";
        var row = await _connection.QueryFirstOrDefaultAsync<JobStatusRow>(
            new CommandDefinition(sql, new { SourceId = sourceId }, cancellationToken: ct));
        if (row == null) return null;
        return new Gabi.Contracts.Api.JobStatusDto(
            IdToGuid(row.id).ToString(),
            row.source_id ?? string.Empty,
            row.status,
            row.progress_percent ?? 0,
            row.progress_message,
            0,
            row.started_at,
            row.completed_at,
            row.last_error
        );
    }

    private static IngestJob MapToIngestJob(JobRow row)
    {
        var payload = DeserializeOrDefault<Dictionary<string, object>>(row.payload);
        
        return new IngestJob
        {
            Id = IdToGuid(row.id),
            SourceId = row.source_id ?? string.Empty,
            JobType = row.job_type,
            Status = MapStatus(row.status),
            Priority = (JobPriority)row.priority,
            Payload = payload,
            MaxRetries = row.max_attempts,
            RetryCount = row.attempts - 1, // attempts is incremented on claim
            CreatedAt = row.created_at,
            ScheduledAt = row.scheduled_at,
            StartedAt = row.started_at,
            WorkerId = row.worker_id,
            LastHeartbeatAt = row.lock_expires_at,
            ProgressPercent = row.progress_percent ?? 0,
            ProgressMessage = row.progress_message,
            ErrorMessage = row.last_error
        };
    }

    private static JobStatus MapStatus(string status)
    {
        return status.ToLowerInvariant() switch
        {
            "pending" or "queued" => JobStatus.Pending,
            "processing" => JobStatus.Running,
            "completed" => JobStatus.Completed,
            "failed" => JobStatus.Failed,
            "dead" => JobStatus.Failed,
            "cancelled" => JobStatus.Cancelled,
            _ => JobStatus.Pending
        };
    }

    private static T DeserializeOrDefault<T>(string? json) where T : new()
    {
        if (string.IsNullOrEmpty(json))
            return new T();

        if (json.Length > MaxPayloadBytes)
            return new T();

        try
        {
            return JsonSerializer.Deserialize<T>(json, JsonOptions) ?? new T();
        }
        catch
        {
            return new T();
        }
    }

    private static string ComputeHash(string input)
    {
        using var sha256 = System.Security.Cryptography.SHA256.Create();
        var bytes = sha256.ComputeHash(System.Text.Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }

    // Convert long ID to deterministic GUID for API consistency
    private static Guid IdToGuid(long id)
    {
        var bytes = new byte[16];
        BitConverter.GetBytes(id).CopyTo(bytes, 0);
        return new Guid(bytes);
    }

    // Convert GUID back to long ID
    private static long GuidToId(Guid guid)
    {
        var bytes = guid.ToByteArray();
        return BitConverter.ToInt64(bytes, 0);
    }

    // ReSharper disable InconsistentNaming
    private record JobRow(
        long id,
        string? source_id,
        string job_type,
        string status,
        int priority,
        string payload,
        int max_attempts,
        int attempts,
        DateTime created_at,
        DateTime? scheduled_at,
        DateTime? started_at,
        string? worker_id,
        DateTime? locked_at,
        DateTime? lock_expires_at,
        int? progress_percent,
        string? progress_message,
        string? last_error);

    private record RetryResult(int attempts, int max_attempts, string? source_id);

    private record JobStatusRow(long id, string? source_id, string status, int? progress_percent, string? progress_message, DateTime? started_at, DateTime? completed_at, string? last_error);
    
    private record StalledJobRow(long id, string? source_id, string? worker_id);
    
    private record StatsRow(
        int pending_count,
        int running_count,
        int completed_count,
        int failed_count,
        int cancelled_count,
        int dead_count,
        int total_count);
    // ReSharper restore InconsistentNaming
}
