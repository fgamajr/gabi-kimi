using FluentAssertions;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Moq;

namespace Gabi.Postgres.Tests;

[Collection("Postgres")]
public class FetchItemRepositoryTests : IDisposable
{
    private readonly GabiDbContext _context;
    private readonly FetchItemRepository _repository;
    private readonly DiscoveredLinkRepository _linkRepository;

    public FetchItemRepositoryTests(PostgresFixture fixture)
    {
        var options = new DbContextOptionsBuilder<GabiDbContext>()
            .UseNpgsql(fixture.ConnectionString)
            .Options;

        _context = new GabiDbContext(options);
        var loggerMock = new Mock<ILogger<FetchItemRepository>>();
        _repository = new FetchItemRepository(_context, loggerMock.Object);
        var linkLoggerMock = new Mock<ILogger<DiscoveredLinkRepository>>();
        _linkRepository = new DiscoveredLinkRepository(_context, linkLoggerMock.Object);
    }

    [Fact]
    public async Task EnsurePendingForLinksAsync_ShouldCreateOneFetchItemPerLink_AndBeIdempotent()
    {
        var source = CreateTestSource();
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
        // DB-ISO: scope to this test's source to avoid interference from parallel tests sharing the Postgres fixture
        (await _context.FetchItems.CountAsync(i => i.SourceId == source.Id)).Should().Be(2);
        (await _context.FetchItems.CountAsync(i => i.SourceId == source.Id && i.Status == "pending")).Should().Be(2);
    }

    [Fact]
    public async Task DiscoveryFlow_BulkUpsertThenEnsurePending_ShouldCreateFetchItemsForAllPersistedLinks()
    {
        var source = CreateTestSource();
        _context.SourceRegistries.Add(source);
        await _context.SaveChangesAsync();

        var linksToUpsert = new[]
        {
            new DiscoveredLinkEntity { SourceId = source.Id, Url = "https://example.com/a.csv", Metadata = "{}" },
            new DiscoveredLinkEntity { SourceId = source.Id, Url = "https://example.com/b.csv", Metadata = "{}" }
        }.ToList();

        await _linkRepository.BulkUpsertAsync(linksToUpsert);
        await _context.SaveChangesAsync();

        var urlHashes = linksToUpsert.Select(l => l.UrlHash).ToList();
        var persistedLinks = await _context.DiscoveredLinks
            .Where(l => l.SourceId == source.Id && urlHashes.Contains(l.UrlHash))
            .ToListAsync();

        var created = await _repository.EnsurePendingForLinksAsync(persistedLinks);

        created.Should().Be(2);
        (await _context.FetchItems.CountAsync(i => i.SourceId == source.Id)).Should().Be(2);
    }

    [Fact]
    public async Task GetCandidateIdsBySourceAndStatusesAsync_ShouldReturnOrderedAndLimitedIds()
    {
        var source = CreateTestSource();
        _context.SourceRegistries.Add(source);
        await _context.SaveChangesAsync();

        var links = new[]
        {
            new DiscoveredLinkEntity { SourceId = source.Id, Url = "https://a", UrlHash = $"lh1_{source.Id}" },
            new DiscoveredLinkEntity { SourceId = source.Id, Url = "https://b", UrlHash = $"lh2_{source.Id}" },
            new DiscoveredLinkEntity { SourceId = source.Id, Url = "https://c", UrlHash = $"lh3_{source.Id}" },
            new DiscoveredLinkEntity { SourceId = source.Id, Url = "https://d", UrlHash = $"lh4_{source.Id}" },
        };
        _context.DiscoveredLinks.AddRange(links);
        await _context.SaveChangesAsync();

        var items = new[]
        {
            new FetchItemEntity { SourceId = source.Id, Url = "https://a", UrlHash = "h1", Status = "pending", CreatedAt = DateTime.UtcNow.AddMinutes(-3), DiscoveredLinkId = links[0].Id },
            new FetchItemEntity { SourceId = source.Id, Url = "https://b", UrlHash = "h2", Status = "failed", CreatedAt = DateTime.UtcNow.AddMinutes(-2), DiscoveredLinkId = links[1].Id },
            new FetchItemEntity { SourceId = source.Id, Url = "https://c", UrlHash = "h3", Status = "pending", CreatedAt = DateTime.UtcNow.AddMinutes(-1), DiscoveredLinkId = links[2].Id },
            new FetchItemEntity { SourceId = source.Id, Url = "https://d", UrlHash = "h4", Status = "completed", CreatedAt = DateTime.UtcNow, DiscoveredLinkId = links[3].Id }
        };
        _context.FetchItems.AddRange(items);
        await _context.SaveChangesAsync();

        var ids = await _repository.GetCandidateIdsBySourceAndStatusesAsync(
            source.Id,
            limit: 2,
            statuses: ["pending", "failed"]);

        ids.Should().HaveCount(2);
        ids.Should().ContainInOrder(items[0].Id, items[1].Id);
    }

    [Fact]
    public async Task GetByIdsAsync_ShouldReturnOnlyRequestedIdsInCreatedOrder()
    {
        var source = CreateTestSource();
        _context.SourceRegistries.Add(source);
        await _context.SaveChangesAsync();

        var la = new DiscoveredLinkEntity { SourceId = source.Id, Url = "https://a", UrlHash = $"lha_{source.Id}" };
        var lb = new DiscoveredLinkEntity { SourceId = source.Id, Url = "https://b", UrlHash = $"lhb_{source.Id}" };
        var lc = new DiscoveredLinkEntity { SourceId = source.Id, Url = "https://c", UrlHash = $"lhc_{source.Id}" };
        _context.DiscoveredLinks.AddRange(la, lb, lc);
        await _context.SaveChangesAsync();

        var a = new FetchItemEntity { SourceId = source.Id, Url = "https://a", UrlHash = "h1", Status = "pending", CreatedAt = DateTime.UtcNow.AddMinutes(-3), DiscoveredLinkId = la.Id };
        var b = new FetchItemEntity { SourceId = source.Id, Url = "https://b", UrlHash = "h2", Status = "pending", CreatedAt = DateTime.UtcNow.AddMinutes(-2), DiscoveredLinkId = lb.Id };
        var c = new FetchItemEntity { SourceId = source.Id, Url = "https://c", UrlHash = "h3", Status = "pending", CreatedAt = DateTime.UtcNow.AddMinutes(-1), DiscoveredLinkId = lc.Id };
        _context.FetchItems.AddRange(a, b, c);
        await _context.SaveChangesAsync();

        var batch = await _repository.GetByIdsAsync(source.Id, [c.Id, a.Id]);

        batch.Select(x => x.Id).Should().ContainInOrder(a.Id, c.Id);
        batch.Should().NotContain(x => x.Id == b.Id);
    }

    private static SourceRegistryEntity CreateTestSource()
    {
        var sourceId = $"test_source_{Guid.NewGuid():N}";
        return new SourceRegistryEntity
        {
            Id = sourceId,
            Name = $"Test Source {sourceId}",
            Provider = "TEST",
            DiscoveryStrategy = "url_pattern",
            DiscoveryConfig = "{}"
        };
    }

    public void Dispose() => _context.Dispose();
}
