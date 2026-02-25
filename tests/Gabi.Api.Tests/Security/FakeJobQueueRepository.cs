using Gabi.Contracts.Api;
using Gabi.Contracts.Jobs;

namespace Gabi.Api.Tests.Security;

internal sealed class FakeJobQueueRepository : IJobQueueRepository
{
    /// <summary>When non-null, last job passed to EnqueueAsync is stored here (for tests that verify payload, e.g. strict_coverage fallback).</summary>
    public static IngestJob? LastEnqueuedJob { get; set; }

    /// <summary>Clears the captured job so tests can assert only the job they triggered.</summary>
    public static void ClearLastEnqueuedJob() => LastEnqueuedJob = null;

    public Task<Guid> EnqueueAsync(IngestJob job, CancellationToken ct = default)
    {
        LastEnqueuedJob = job;
        return Task.FromResult(Guid.NewGuid());
    }

    public Task<IngestJob?> DequeueAsync(string workerId, TimeSpan leaseDuration, CancellationToken ct = default) => Task.FromResult<IngestJob?>(null);

    public Task CompleteAsync(Guid jobId, CancellationToken ct = default) => Task.CompletedTask;

    public Task CompleteAsync(Guid jobId, string terminalStatus, CancellationToken ct = default) => Task.CompletedTask;

    public Task FailAsync(Guid jobId, string error, bool shouldRetry, CancellationToken ct = default) => Task.CompletedTask;

    public Task ReleaseLeaseAsync(Guid jobId, CancellationToken ct = default) => Task.CompletedTask;

    public Task<bool> HeartbeatAsync(Guid jobId, CancellationToken ct = default) => Task.FromResult(true);

    public Task UpdateProgressAsync(Guid jobId, int percent, string? message, int? linksDiscovered, CancellationToken ct = default) => Task.CompletedTask;

    public Task<JobStatus?> GetStatusAsync(Guid jobId, CancellationToken ct = default) => Task.FromResult<JobStatus?>(null);

    public Task CancelAsync(Guid jobId, string reason, CancellationToken ct = default) => Task.CompletedTask;

    public Task<IReadOnlyList<Guid>> RecoverStalledJobsAsync(TimeSpan stallTimeout, CancellationToken ct = default)
        => Task.FromResult<IReadOnlyList<Guid>>(Array.Empty<Guid>());

    public Task<JobQueueStatistics> GetStatisticsAsync(CancellationToken ct = default) => Task.FromResult(new JobQueueStatistics());

    public Task<IngestJob?> GetLatestForSourceAsync(string sourceId, CancellationToken ct = default) => Task.FromResult<IngestJob?>(null);

    public Task<IngestJob?> GetLatestByJobTypeAsync(string jobType, CancellationToken ct = default) => Task.FromResult<IngestJob?>(null);

    public Task<IReadOnlyList<IngestJob>> GetRecentJobsAsync(int limit = 50, CancellationToken ct = default)
        => Task.FromResult<IReadOnlyList<IngestJob>>(Array.Empty<IngestJob>());

    public Task<JobStatusDto?> GetJobStatusDtoAsync(string sourceId, CancellationToken ct = default) => Task.FromResult<JobStatusDto?>(null);
}
