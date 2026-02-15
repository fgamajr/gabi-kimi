using FluentAssertions;
using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Moq;

namespace Gabi.Postgres.Tests;

public class JobQueueRepositoryHashTests : IDisposable
{
    private readonly GabiDbContext _context;
    private readonly JobQueueRepository _repository;

    public JobQueueRepositoryHashTests()
    {
        var options = new DbContextOptionsBuilder<GabiDbContext>()
            .UseInMemoryDatabase(Guid.NewGuid().ToString())
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
            Id = "tcu_acordaos",
            Name = "TCU - Acordaos",
            Provider = "TCU",
            DiscoveryStrategy = "url_pattern",
            DiscoveryConfig = "{}"
        };
        _context.SourceRegistries.Add(source);
        await _context.SaveChangesAsync();

        var first = new IngestJob
        {
            Id = Guid.NewGuid(),
            JobType = "source_discovery",
            SourceId = "tcu_acordaos",
            Payload = new Dictionary<string, object> { ["force"] = true, ["request_id"] = "a" },
            Status = JobStatus.Pending
        };

        var second = new IngestJob
        {
            Id = Guid.NewGuid(),
            JobType = "source_discovery",
            SourceId = "tcu_acordaos",
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

    public void Dispose() => _context.Dispose();
}
