using FluentAssertions;
using Gabi.Contracts.Jobs;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Hangfire;
using Hangfire.Common;
using Hangfire.States;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Moq;

namespace Gabi.Postgres.Tests;

public sealed class HangfireJobQueueRepositoryConcurrencyTests : IDisposable
{
    private readonly SqliteConnection _connection;
    private readonly GabiDbContext _context;

    public HangfireJobQueueRepositoryConcurrencyTests()
    {
        _connection = new SqliteConnection("Data Source=:memory:");
        _connection.Open();
        _connection.CreateFunction("pg_advisory_xact_lock", (long _) => 1L);

        var options = new DbContextOptionsBuilder<GabiDbContext>()
            .UseSqlite(_connection)
            .Options;

        _context = new GabiDbContext(options);
        _context.Database.EnsureCreated();
    }

    [Fact]
    public async Task EnqueueAsync_ShouldReturnExistingJob_WhenSameSourceAndJobTypeAlreadyActive()
    {
        const string sourceId = "source-a";
        var existingId = Guid.NewGuid();

        _context.JobRegistry.Add(new JobRegistryEntity
        {
            JobId = existingId,
            SourceId = sourceId,
            JobType = "fetch",
            Status = "processing",
            CreatedAt = DateTime.UtcNow
        });
        await _context.SaveChangesAsync();

        var clientMock = new Mock<IBackgroundJobClient>(MockBehavior.Strict);
        var loggerMock = new Mock<ILogger<HangfireJobQueueRepository>>();
        var repository = new HangfireJobQueueRepository(_context, clientMock.Object, loggerMock.Object);

        var jobId = await repository.EnqueueAsync(new IngestJob
        {
            Id = Guid.NewGuid(),
            SourceId = sourceId,
            JobType = "fetch",
            Payload = new Dictionary<string, object>()
        });

        jobId.Should().Be(existingId);
        (await _context.JobRegistry.CountAsync(r => r.SourceId == sourceId && r.JobType == "fetch")).Should().Be(1);
        clientMock.Verify(c => c.Create(It.IsAny<Job>(), It.IsAny<IState>()), Times.Never);
    }

    [Fact]
    public async Task EnqueueAsync_ShouldCreateNewJob_WhenActiveJobIsDifferentTypeForSameSource()
    {
        const string sourceId = "source-b";
        var existingId = Guid.NewGuid();

        _context.JobRegistry.Add(new JobRegistryEntity
        {
            JobId = existingId,
            SourceId = sourceId,
            JobType = "source_discovery",
            Status = "pending",
            CreatedAt = DateTime.UtcNow
        });
        await _context.SaveChangesAsync();

        var clientMock = new Mock<IBackgroundJobClient>();
        clientMock
            .Setup(c => c.Create(It.IsAny<Job>(), It.IsAny<IState>()))
            .Returns("hf-1");
        var loggerMock = new Mock<ILogger<HangfireJobQueueRepository>>();
        var repository = new HangfireJobQueueRepository(_context, clientMock.Object, loggerMock.Object);

        var newId = await repository.EnqueueAsync(new IngestJob
        {
            Id = Guid.NewGuid(),
            SourceId = sourceId,
            JobType = "fetch",
            Payload = new Dictionary<string, object>()
        });

        newId.Should().NotBe(existingId);
        (await _context.JobRegistry.CountAsync(r => r.SourceId == sourceId)).Should().Be(2);
        clientMock.Verify(c => c.Create(It.IsAny<Job>(), It.IsAny<IState>()), Times.Once);
    }

    public void Dispose()
    {
        _context.Dispose();
        _connection.Dispose();
    }
}
