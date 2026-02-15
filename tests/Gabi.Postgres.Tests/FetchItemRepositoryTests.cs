using FluentAssertions;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Moq;

namespace Gabi.Postgres.Tests;

public class FetchItemRepositoryTests : IDisposable
{
    private readonly GabiDbContext _context;
    private readonly FetchItemRepository _repository;

    public FetchItemRepositoryTests()
    {
        var options = new DbContextOptionsBuilder<GabiDbContext>()
            .UseInMemoryDatabase(Guid.NewGuid().ToString())
            .Options;

        _context = new GabiDbContext(options);
        var loggerMock = new Mock<ILogger<FetchItemRepository>>();
        _repository = new FetchItemRepository(_context, loggerMock.Object);
    }

    [Fact]
    public async Task EnsurePendingForLinksAsync_ShouldCreateOneFetchItemPerLink_AndBeIdempotent()
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

        var links = new[]
        {
            new DiscoveredLinkEntity { SourceId = source.Id, Url = "https://a", UrlHash = "h1" },
            new DiscoveredLinkEntity { SourceId = source.Id, Url = "https://b", UrlHash = "h2" }
        };
        _context.DiscoveredLinks.AddRange(links);
        await _context.SaveChangesAsync();

        var first = await _repository.EnsurePendingForLinksAsync(links);
        var second = await _repository.EnsurePendingForLinksAsync(links);

        first.Should().Be(2);
        second.Should().Be(0);
        (await _context.FetchItems.CountAsync()).Should().Be(2);
        (await _context.FetchItems.CountAsync(i => i.Status == "pending")).Should().Be(2);
    }

    public void Dispose() => _context.Dispose();
}

