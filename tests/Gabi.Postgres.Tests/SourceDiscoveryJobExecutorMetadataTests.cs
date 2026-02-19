using System.Text.Json;
using Gabi.Contracts.Discovery;
using Gabi.Contracts.Jobs;
using Gabi.Discover;
using Gabi.Postgres;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Gabi.Worker.Jobs;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Moq;

namespace Gabi.Postgres.Tests;

public class SourceDiscoveryJobExecutorMetadataTests : IDisposable
{
    private readonly GabiDbContext _context;
    private readonly SourceDiscoveryJobExecutor _executor;

    public SourceDiscoveryJobExecutorMetadataTests()
    {
        var options = new DbContextOptionsBuilder<GabiDbContext>()
            .UseInMemoryDatabase(Guid.NewGuid().ToString())
            .Options;

        _context = new GabiDbContext(options);

        var linkRepoLogger = new Mock<ILogger<DiscoveredLinkRepository>>();
        var fetchRepoLogger = new Mock<ILogger<FetchItemRepository>>();
        var executorLogger = new Mock<ILogger<SourceDiscoveryJobExecutor>>();

        var linkRepository = new DiscoveredLinkRepository(_context, linkRepoLogger.Object);
        var fetchItemRepository = new FetchItemRepository(_context, fetchRepoLogger.Object);

        var adapterRegistry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new TestSemanticDiscoveryAdapter()
        });
        var discoveryEngine = new DiscoveryEngine(adapterRegistry);

        _executor = new SourceDiscoveryJobExecutor(
            linkRepository,
            fetchItemRepository,
            _context,
            discoveryEngine,
            executorLogger.Object);
    }

    [Fact]
    public async Task ExecuteAsync_ShouldPersistDiscoveredMetadataIntoDiscoveredLinks()
    {
        var sourceId = $"source_{Guid.NewGuid():N}";
        _context.SourceRegistries.Add(new SourceRegistryEntity
        {
            Id = sourceId,
            Name = "Source",
            Provider = "TEST",
            DiscoveryStrategy = "test_semantic",
            DiscoveryConfig = "{}"
        });
        await _context.SaveChangesAsync();

        var job = new IngestJob
        {
            Id = Guid.NewGuid(),
            SourceId = sourceId,
            JobType = "source_discovery",
            DiscoveryConfig = new DiscoveryConfig
            {
                Strategy = "test_semantic"
            }
        };

        await _executor.ExecuteAsync(job, new Progress<JobProgress>(_ => { }), CancellationToken.None);

        var link = await _context.DiscoveredLinks.SingleAsync(l => l.SourceId == sourceId);
        using var metadata = JsonDocument.Parse(link.Metadata);

        Assert.Equal("norma", metadata.RootElement.GetProperty("document_kind").GetString());
        Assert.Equal("aprovada", metadata.RootElement.GetProperty("approval_state").GetString());
        Assert.Equal("senado_legislacao", metadata.RootElement.GetProperty("source_family").GetString());
    }

    public void Dispose() => _context.Dispose();

    private sealed class TestSemanticDiscoveryAdapter : IDiscoveryAdapter
    {
        public string StrategyKey => "test_semantic";

        public async IAsyncEnumerable<DiscoveredSource> DiscoverAsync(
            string sourceId,
            DiscoveryConfig config,
            [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct = default)
        {
            await Task.Yield();
            yield return new DiscoveredSource(
                "https://example.test/norma/1",
                sourceId,
                new Dictionary<string, object>
                {
                    ["document_kind"] = "norma",
                    ["approval_state"] = "aprovada",
                    ["source_family"] = "senado_legislacao"
                },
                DateTime.UtcNow);
        }
    }
}
