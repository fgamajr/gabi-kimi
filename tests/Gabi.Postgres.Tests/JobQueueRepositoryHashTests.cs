using FluentAssertions;
using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Moq;

namespace Gabi.Postgres.Tests;

[Collection("Postgres")]
public class JobQueueRepositoryHashTests : IDisposable
{
    private const string TestSourceId = "test_source_hash";
    private readonly GabiDbContext _context;
    private readonly JobQueueRepository _repository;

    public JobQueueRepositoryHashTests(PostgresFixture fixture)
    {
        var options = new DbContextOptionsBuilder<GabiDbContext>()
            .UseNpgsql(fixture.ConnectionString)
            .Options;

        _context = new GabiDbContext(options);
        var loggerMock = new Mock<ILogger<JobQueueRepository>>();
        _repository = new JobQueueRepository(_context, loggerMock.Object);
    }

    [Fact]
    public async Task EnqueueAsync_SameSourceAndJobTypeDifferentPayload_ShouldGenerateDifferentPayloadHash()
    {
        var source = new SourceRegistryEntity
        {
            Id = TestSourceId,
            Name = "Test Source Hash",
            Provider = "TEST",
            DiscoveryStrategy = "url_pattern",
            DiscoveryConfig = "{}"
        };
        _context.SourceRegistries.Add(source);
        await _context.SaveChangesAsync();

        var first = new IngestJob
        {
            Id = Guid.NewGuid(),
            JobType = "source_discovery",
            SourceId = TestSourceId,
            Payload = new Dictionary<string, object> { ["force"] = true, ["request_id"] = "a" },
            Status = JobStatus.Pending
        };

        var second = new IngestJob
        {
            Id = Guid.NewGuid(),
            JobType = "source_discovery",
            SourceId = TestSourceId,
            Payload = new Dictionary<string, object> { ["force"] = false, ["request_id"] = "b" },
            Status = JobStatus.Pending
        };

        await _repository.EnqueueAsync(first);
        await _repository.EnqueueAsync(second);

        var hashes = await _context.IngestJobs
            .OrderBy(x => x.CreatedAt)
            .Select(x => x.PayloadHash)
            .ToListAsync();

        hashes.Should().HaveCount(2);
        hashes[0].Should().NotBe(hashes[1]);
    }

    [Fact]
    public async Task GetLatestForSourceAsync_HangfireLikePayloadShape_ShouldMaterializeDiscoveryConfig()
    {
        var source = new SourceRegistryEntity
        {
            Id = TestSourceId,
            Name = "Test Source Discovery Payload",
            Provider = "TEST",
            DiscoveryStrategy = "url_pattern",
            DiscoveryConfig = "{}"
        };
        _context.SourceRegistries.Add(source);
        await _context.SaveChangesAsync();

        var discoveryConfigJson =
            """
            {
              "url": null,
              "template": "https://example.com/file-{year}.csv",
              "parameters": {
                "year": { "start": 1992, "end": "current", "step": 1 }
              }
            }
            """;

        var job = new IngestJob
        {
            Id = Guid.NewGuid(),
            JobType = "source_discovery",
            SourceId = TestSourceId,
            Payload = new Dictionary<string, object>
            {
                ["force"] = true,
                ["year"] = null!,
                // Mirrors persisted queue shape where discovery config is nested as JSON string.
                ["discoveryConfig"] = discoveryConfigJson
            },
            Status = JobStatus.Pending
        };

        await _repository.EnqueueAsync(job);

        var latest = await _repository.GetLatestForSourceAsync(TestSourceId);

        latest.Should().NotBeNull();
        latest!.DiscoveryConfig.Should().NotBeNull();
        latest.DiscoveryConfig.Strategy.Should().Be("url_pattern");
        latest.DiscoveryConfig.UrlTemplate.Should().Be("https://example.com/file-{year}.csv");
    }

    public void Dispose() => _context.Dispose();
}
