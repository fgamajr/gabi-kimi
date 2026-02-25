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
            new TestSemanticDiscoveryAdapter(),
            new TestManyDiscoveryAdapter()
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

    [Fact]
    public async Task ExecuteAsync_WithMaxDocsPerSourcePayload_ShouldCapDiscovery()
    {
        var sourceId = $"source_{Guid.NewGuid():N}";
        _context.SourceRegistries.Add(new SourceRegistryEntity
        {
            Id = sourceId,
            Name = "Source Cap",
            Provider = "TEST",
            DiscoveryStrategy = "test_many",
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
                Strategy = "test_many"
            },
            Payload = new Dictionary<string, object>
            {
                ["max_docs_per_source"] = 10
            }
        };

        await _executor.ExecuteAsync(job, new Progress<JobProgress>(_ => { }), CancellationToken.None);

        var linkCount = await _context.DiscoveredLinks.CountAsync(l => l.SourceId == sourceId);
        var fetchItemCount = await _context.FetchItems.CountAsync(f => f.SourceId == sourceId);
        var discoveryRun = await _context.DiscoveryRuns
            .Where(r => r.SourceId == sourceId)
            .OrderByDescending(r => r.StartedAt)
            .FirstAsync();

        Assert.Equal(10, linkCount);
        Assert.Equal(10, fetchItemCount);
        Assert.Equal(10, discoveryRun.LinksTotal);
        Assert.Equal("completed", discoveryRun.Status);
        Assert.Equal("capped at max_docs_per_source=10", discoveryRun.ErrorSummary);
    }

    [Fact]
    public async Task ExecuteAsync_WithStrictCoverageAndCapReached_ShouldBeInconclusive()
    {
        var sourceId = $"source_{Guid.NewGuid():N}";
        _context.SourceRegistries.Add(new SourceRegistryEntity
        {
            Id = sourceId,
            Name = "Source Strict Cap",
            Provider = "TEST",
            DiscoveryStrategy = "test_many",
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
                Strategy = "test_many"
            },
            Payload = new Dictionary<string, object>
            {
                ["max_docs_per_source"] = 10,
                ["strict_coverage"] = true
            }
        };

        var result = await _executor.ExecuteAsync(job, new Progress<JobProgress>(_ => { }), CancellationToken.None);

        var linkCount = await _context.DiscoveredLinks.CountAsync(l => l.SourceId == sourceId);
        var discoveryRun = await _context.DiscoveryRuns
            .Where(r => r.SourceId == sourceId)
            .OrderByDescending(r => r.StartedAt)
            .FirstAsync();

        Assert.False(result.Success);
        Assert.Equal(10, linkCount);
        Assert.Equal("inconclusive", discoveryRun.Status);
        Assert.Equal("capped at max_docs_per_source=10 (strict_coverage=true)", discoveryRun.ErrorSummary);
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

    private sealed class TestManyDiscoveryAdapter : IDiscoveryAdapter
    {
        public string StrategyKey => "test_many";

        public async IAsyncEnumerable<DiscoveredSource> DiscoverAsync(
            string sourceId,
            DiscoveryConfig config,
            [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct = default)
        {
            for (var i = 0; i < 100; i++)
            {
                ct.ThrowIfCancellationRequested();
                await Task.Yield();
                yield return new DiscoveredSource(
                    $"https://example.test/many/{i}",
                    sourceId,
                    new Dictionary<string, object> { ["i"] = i },
                    DateTime.UtcNow);
            }
        }
    }
}
