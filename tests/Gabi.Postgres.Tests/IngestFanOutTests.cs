using FluentAssertions;
using Gabi.Contracts.Api;
using Gabi.Contracts.Ingest;
using Gabi.Contracts.Index;
using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Worker.Jobs;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Moq;

namespace Gabi.Postgres.Tests;

/// <summary>
/// Verifies that IngestJobExecutor (fan-out) enqueues embed_and_index jobs with correct batch sizes and payload.
/// </summary>
public sealed class IngestFanOutTests : IDisposable
{
    private readonly GabiDbContext _context;
    private readonly List<IngestJob> _enqueuedJobs = new();
    private readonly IngestJobExecutor _executor;

    public IngestFanOutTests()
    {
        var options = new DbContextOptionsBuilder<GabiDbContext>()
            .UseInMemoryDatabase(Guid.NewGuid().ToString())
            .Options;
        _context = new GabiDbContext(options);
        _context.Database.EnsureCreated();

        var jobQueue = new RecordingJobQueueRepository(_enqueuedJobs);
        var normalizer = new Mock<ICanonicalDocumentNormalizer>();
        var indexer = new Mock<IDocumentIndexer>();
        indexer.Setup(x => x.GetActiveDocumentCountAsync(It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(0);
        var mediaProjector = new Mock<IMediaTextProjector>();
        var logger = new Mock<ILogger<IngestJobExecutor>>();

        _executor = new IngestJobExecutor(
            _context,
            normalizer.Object,
            indexer.Object,
            mediaProjector.Object,
            jobQueue,
            logger.Object);
    }

    [Fact]
    public async Task ExecuteAsync_EnqueuesEmbedAndIndexJobs_WithDynamicBatchSizing()
    {
        const string sourceId = "test_source";
        var linkId = await SeedLinkAsync(sourceId);
        var docIds = new List<Guid>();
        for (int i = 0; i < 100; i++)
        {
            var id = Guid.NewGuid();
            docIds.Add(id);
            _context.Documents.Add(new DocumentEntity
            {
                Id = id,
                SourceId = sourceId,
                LinkId = linkId,
                Status = "pending",
                Content = "sample content " + i,
                Title = "Doc " + i,
                ExternalId = "ext-" + i,
                CreatedAt = DateTime.UtcNow
            });
        }
        await _context.SaveChangesAsync();

        var job = new IngestJob
        {
            Id = Guid.NewGuid(),
            SourceId = sourceId,
            JobType = "ingest"
        };

        await _executor.ExecuteAsync(job, new Progress<JobProgress>(_ => { }), CancellationToken.None);

        _enqueuedJobs.Should().NotBeEmpty();
        _enqueuedJobs.Should().OnlyContain(j => j.JobType == "embed_and_index");
        _enqueuedJobs.Should().OnlyContain(j => j.SourceId == sourceId);

        // Dynamic batch: default max 32 docs per batch => ceil(100/32) = 4 batches
        var allIds = _enqueuedJobs.SelectMany(j => GetDocumentIdsFromPayload(j)).ToList();
        allIds.Count.Should().Be(100);
        allIds.OrderBy(x => x).Should().BeEquivalentTo(docIds.OrderBy(x => x));
        foreach (var enqueued in _enqueuedJobs)
        {
            var batchIds = GetDocumentIdsFromPayload(enqueued);
            batchIds.Count.Should().BeLessOrEqualTo(32, "default max_docs_per_batch is 32");
        }
    }

    [Fact]
    public async Task ExecuteAsync_EnqueuesNoEmbedJob_WhenNoPendingDocuments()
    {
        const string sourceId = "empty_source";
        await SeedLinkAsync(sourceId);

        var job = new IngestJob
        {
            Id = Guid.NewGuid(),
            SourceId = sourceId,
            JobType = "ingest"
        };

        await _executor.ExecuteAsync(job, new Progress<JobProgress>(_ => { }), CancellationToken.None);

        _enqueuedJobs.Should().BeEmpty();
    }

    [Fact]
    public async Task ExecuteAsync_YieldsAndSchedulesRetry_WhenBackpressurePendingEmbedExceeded()
    {
        const string sourceId = "bp_source";
        await SeedLinkAsync(sourceId);
        for (int i = 0; i < 501; i++)
        {
            _context.JobRegistry.Add(new JobRegistryEntity
            {
                JobId = Guid.NewGuid(),
                SourceId = sourceId,
                JobType = "embed_and_index",
                Status = "pending",
                CreatedAt = DateTime.UtcNow
            });
        }
        await _context.SaveChangesAsync();

        var job = new IngestJob { Id = Guid.NewGuid(), SourceId = sourceId, JobType = "ingest" };
        var result = await _executor.ExecuteAsync(job, new Progress<JobProgress>(_ => { }), CancellationToken.None);

        result.Status.Should().Be(JobTerminalStatus.Success);
        result.Metadata.Should().ContainKey("yielded");
        result.Metadata["yielded"].Should().Be(true);
        result.Metadata.Should().ContainKey("reason");
        result.Metadata["reason"].Should().Be("backpressure");
        _enqueuedJobs.Should().ContainSingle(j => j.JobType == "ingest");
    }

    [Fact]
    public async Task ExecuteAsync_ReturnsSuccessWithInterruptedBy_WhenSourcePaused()
    {
        const string sourceId = "paused_source";
        var linkId = await SeedLinkAsync(sourceId);
        _context.SourcePipelineStates.Add(new SourcePipelineStateEntity
        {
            SourceId = sourceId,
            State = "paused",
            UpdatedAt = DateTime.UtcNow
        });
        _context.Documents.Add(new DocumentEntity
        {
            Id = Guid.NewGuid(),
            SourceId = sourceId,
            LinkId = linkId,
            Status = "pending",
            Content = "x",
            ExternalId = "ext-1",
            CreatedAt = DateTime.UtcNow
        });
        await _context.SaveChangesAsync();

        var job = new IngestJob { Id = Guid.NewGuid(), SourceId = sourceId, JobType = "ingest" };
        var result = await _executor.ExecuteAsync(job, new Progress<JobProgress>(_ => { }), CancellationToken.None);

        result.Status.Should().Be(JobTerminalStatus.Success);
        result.Metadata.Should().ContainKey("interrupted_by");
        result.Metadata["interrupted_by"].Should().Be("pause");
        _enqueuedJobs.Should().BeEmpty();
    }

    private async Task<long> SeedLinkAsync(string sourceId)
    {
        _context.SourceRegistries.Add(new SourceRegistryEntity
        {
            Id = sourceId,
            Name = "Test",
            Provider = "TEST",
            DiscoveryConfig = "{}"
        });
        _context.DiscoveredLinks.Add(new DiscoveredLinkEntity
        {
            SourceId = sourceId,
            Url = "https://example.com/1",
            UrlHash = "h1",
            Status = "completed",
            DiscoveryStatus = "completed",
            FetchStatus = "completed",
            IngestStatus = "pending",
            FirstSeenAt = DateTime.UtcNow,
            DiscoveredAt = DateTime.UtcNow,
            CreatedAt = DateTime.UtcNow,
            UpdatedAt = DateTime.UtcNow
        });
        await _context.SaveChangesAsync();
        var link = await _context.DiscoveredLinks.FirstAsync(l => l.SourceId == sourceId);
        return link.Id;
    }

    private static List<Guid> GetDocumentIdsFromPayload(IngestJob j)
    {
        if (j.Payload == null || !j.Payload.TryGetValue("document_ids", out var raw) || raw == null)
            return new List<Guid>();
        if (raw is List<string> strList)
            return strList.Select(Guid.Parse).ToList();
        if (raw is List<object> arr)
            return arr.Select(x => Guid.Parse(x is System.Text.Json.JsonElement je ? je.GetString()! : x.ToString()!)).ToList();
        return new List<Guid>();
    }

    public void Dispose() => _context.Dispose();

    private sealed class RecordingJobQueueRepository : IJobQueueRepository
    {
        private readonly List<IngestJob> _captured;

        public RecordingJobQueueRepository(List<IngestJob> captured) => _captured = captured;

        public Task<Guid> EnqueueAsync(IngestJob job, CancellationToken ct = default)
        {
            _captured.Add(new IngestJob
            {
                Id = job.Id,
                SourceId = job.SourceId,
                JobType = job.JobType,
                Payload = job.Payload == null ? new Dictionary<string, object>() : new Dictionary<string, object>(job.Payload)
            });
            return Task.FromResult(Guid.NewGuid());
        }

        public Task<Guid> ScheduleAsync(IngestJob job, TimeSpan delay, CancellationToken ct = default)
        {
            _captured.Add(new IngestJob { Id = job.Id, SourceId = job.SourceId, JobType = job.JobType, Payload = job.Payload == null ? new Dictionary<string, object>() : new Dictionary<string, object>(job.Payload) });
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
        public Task<IReadOnlyList<Guid>> RecoverStalledJobsAsync(TimeSpan stallTimeout, CancellationToken ct = default) => Task.FromResult<IReadOnlyList<Guid>>(Array.Empty<Guid>());
        public Task<JobQueueStatistics> GetStatisticsAsync(CancellationToken ct = default) => Task.FromResult(new JobQueueStatistics());
        public Task<IngestJob?> GetLatestForSourceAsync(string sourceId, CancellationToken ct = default) => Task.FromResult<IngestJob?>(null);
        public Task<IngestJob?> GetLatestByJobTypeAsync(string jobType, CancellationToken ct = default) => Task.FromResult<IngestJob?>(null);
        public Task<IReadOnlyList<IngestJob>> GetRecentJobsAsync(int limit = 50, CancellationToken ct = default) => Task.FromResult<IReadOnlyList<IngestJob>>(Array.Empty<IngestJob>());
        public Task<JobStatusDto?> GetJobStatusDtoAsync(string sourceId, CancellationToken ct = default) => Task.FromResult<JobStatusDto?>(null);
    }
}
