using Gabi.Contracts.Api;
using Gabi.Contracts.Dashboard;
using Gabi.Contracts.Discovery;
using Gabi.Contracts.Pipeline;
using Gabi.Postgres.Entities;
using Gabi.Postgres.Repositories;
using Gabi.Sync.Phase0;
using Microsoft.Extensions.Logging;
using Moq;

namespace Gabi.Sync.Tests;

/// <summary>
/// Extension to convert IEnumerable to IAsyncEnumerable for testing.
/// </summary>
public static class AsyncEnumerableExtensions
{
    public static async IAsyncEnumerable<T> ToAsyncEnumerable<T>(this IEnumerable<T> source)
    {
        foreach (var item in source)
        {
            yield return item;
            await Task.Yield();
        }
    }
}

public class Phase0OrchestratorTests
{
    private readonly Mock<ISourceCatalog> _sourceCatalogMock;
    private readonly Mock<IDiscoveryEngine> _discoveryEngineMock;
    private readonly Mock<IMetadataFetcher> _metadataFetcherMock;
    private readonly Mock<IDiscoveredLinkRepository> _linkRepositoryMock;
    private readonly Mock<ILogger<Phase0Orchestrator>> _loggerMock;
    private readonly IPhase0LinkComparator _linkComparator;
    private readonly Phase0Orchestrator _orchestrator;

    public Phase0OrchestratorTests()
    {
        _sourceCatalogMock = new Mock<ISourceCatalog>();
        _discoveryEngineMock = new Mock<IDiscoveryEngine>();
        _metadataFetcherMock = new Mock<IMetadataFetcher>();
        _linkRepositoryMock = new Mock<IDiscoveredLinkRepository>();
        _loggerMock = new Mock<ILogger<Phase0Orchestrator>>();

        // Use real implementations for comparator to test actual logic
        _linkComparator = new LinkComparator();

        _orchestrator = new Phase0Orchestrator(
            _sourceCatalogMock.Object,
            _discoveryEngineMock.Object,
            _linkComparator,
            _metadataFetcherMock.Object,
            _linkRepositoryMock.Object,
            _loggerMock.Object
        );
    }

    [Fact]
    public async Task RunAsync_DiscoversLinks_ForSource()
    {
        // Arrange
        var sourceId = "test-source";
        var options = new Phase0Options();
        
        SetupSourceCatalog(sourceId);
        SetupDiscoveryEngine(sourceId, new[]
        {
            new DiscoveredSource("http://example.com/1", sourceId, new Dictionary<string, object>(), DateTime.UtcNow),
            new DiscoveredSource("http://example.com/2", sourceId, new Dictionary<string, object>(), DateTime.UtcNow)
        });

        // Act
        var result = await _orchestrator.RunAsync(sourceId, options);

        // Assert
        Assert.True(result.Success);
        Assert.Equal(2, result.DiscoveredLinksCount);
    }

    [Fact]
    public async Task RunAsync_SkipsExistingLinks_WhenSkipExistingIsTrue()
    {
        // Arrange
        var sourceId = "test-source";
        var url = "http://example.com/doc.pdf";
        var options = new Phase0Options { SkipExisting = true };
        
        SetupSourceCatalog(sourceId);
        SetupDiscoveryEngine(sourceId, new[]
        {
            new DiscoveredSource(url, sourceId, new Dictionary<string, object>(), DateTime.UtcNow)
        });
        
        // Simulate existing link in database
        SetupExistingLink(sourceId, url, unchanged: true);
        
        // LinkComparator is now real implementation, behavior determined by database state

        // Act
        var result = await _orchestrator.RunAsync(sourceId, options);

        // Assert
        Assert.True(result.Success);
        Assert.Equal(1, result.DiscoveredLinksCount);
        Assert.Equal(1, result.SkippedLinksCount);
        Assert.Equal(0, result.NewLinksCount);
        Assert.Empty(result.LinksToProcess);
    }

    [Fact]
    public async Task RunAsync_FetchesMetadata_ForNewLinks()
    {
        // Arrange
        var sourceId = "test-source";
        var url = "http://example.com/doc.pdf";
        var options = new Phase0Options { SkipExisting = true };
        
        SetupSourceCatalog(sourceId);
        SetupDiscoveryEngine(sourceId, new[]
        {
            new DiscoveredSource(url, sourceId, new Dictionary<string, object>(), DateTime.UtcNow)
        });
        
        // No existing link
        SetupNoExistingLink(sourceId, url);
        
        var metadataResult = new MetadataFetchResult
        {
            Success = true,
            ContentLength = 1024,
            Etag = "abc123",
            LastModified = DateTime.UtcNow.AddDays(-1)
        };
        
        _metadataFetcherMock
            .Setup(x => x.FetchAsync(url, It.IsAny<CancellationToken>()))
            .ReturnsAsync(metadataResult);
            
        // LinkComparator is now real implementation

        // Act
        var result = await _orchestrator.RunAsync(sourceId, options);

        // Assert
        Assert.True(result.Success);
        Assert.Equal(1, result.MetadataFetchedCount);
        Assert.Equal(1, result.NewLinksCount);
        Assert.Equal(1024, result.TotalEstimatedSizeBytes);
        _metadataFetcherMock.Verify(x => x.FetchAsync(url, It.IsAny<CancellationToken>()), Times.Once);
    }

    [Fact]
    public async Task RunAsync_ReturnsCorrectCounts()
    {
        // Arrange
        var sourceId = "test-source";
        var options = new Phase0Options { SkipExisting = true };
        
        SetupSourceCatalog(sourceId);
        SetupDiscoveryEngine(sourceId, new[]
        {
            new DiscoveredSource("http://example.com/new1", sourceId, new Dictionary<string, object>(), DateTime.UtcNow),
            new DiscoveredSource("http://example.com/new2", sourceId, new Dictionary<string, object>(), DateTime.UtcNow),
            new DiscoveredSource("http://example.com/changed", sourceId, new Dictionary<string, object>(), DateTime.UtcNow),
            new DiscoveredSource("http://example.com/unchanged", sourceId, new Dictionary<string, object>(), DateTime.UtcNow)
        });

        // No existing links for new ones
        SetupNoExistingLink(sourceId, "http://example.com/new1");
        SetupNoExistingLink(sourceId, "http://example.com/new2");
        // Changed link has existing entry with different metadata (will be detected as changed)
        SetupExistingLink(sourceId, "http://example.com/changed", unchanged: false);
        SetupExistingLink(sourceId, "http://example.com/unchanged", unchanged: true);

        SetupMetadataFetcher("http://example.com/new1", 1000);
        SetupMetadataFetcher("http://example.com/new2", 2000);
        SetupMetadataFetcher("http://example.com/changed", 1500);

        // LinkComparator is real implementation - behavior determined by existing link state

        // Act
        var result = await _orchestrator.RunAsync(sourceId, options);

        // Assert
        Assert.True(result.Success);
        Assert.Equal(4, result.DiscoveredLinksCount);
        Assert.Equal(3, result.MetadataFetchedCount);
        Assert.Equal(2, result.NewLinksCount);
        Assert.Equal(1, result.UpdatedLinksCount);
        Assert.Equal(1, result.SkippedLinksCount);
        Assert.Equal(4500, result.TotalEstimatedSizeBytes);
        Assert.Equal(3, result.LinksToProcess.Count);
    }

    [Fact]
    public async Task RunAsync_PopulatesLinksToProcess()
    {
        // Arrange
        var sourceId = "test-source";
        var url = "http://example.com/doc.pdf";
        var options = new Phase0Options();
        
        SetupSourceCatalog(sourceId);
        SetupDiscoveryEngine(sourceId, new[]
        {
            new DiscoveredSource(url, sourceId, new Dictionary<string, object>(), DateTime.UtcNow)
        });
        
        SetupNoExistingLink(sourceId, url);
        
        var metadataResult = new MetadataFetchResult
        {
            Success = true,
            ContentLength = 2048,
            Etag = "etag123"
        };
        
        _metadataFetcherMock
            .Setup(x => x.FetchAsync(url, It.IsAny<CancellationToken>()))
            .ReturnsAsync(metadataResult);
            
        // Act
        var result = await _orchestrator.RunAsync(sourceId, options);

        // Assert
        Assert.True(result.Success);
        Assert.Single(result.LinksToProcess);
        Assert.Equal(url, result.LinksToProcess[0].Url);
        Assert.Equal(LinkDiscoveryStatus.MarkedForProcessing, result.LinksToProcess[0].Status);
        Assert.Equal(2048, result.LinksToProcess[0].ContentLength);
    }

    [Fact]
    public async Task RunAsync_RespectsMaxLinksOption()
    {
        // Arrange
        var sourceId = "test-source";
        var options = new Phase0Options { MaxLinks = 2 };
        
        SetupSourceCatalog(sourceId);
        SetupDiscoveryEngine(sourceId, new[]
        {
            new DiscoveredSource("http://example.com/1", sourceId, new Dictionary<string, object>(), DateTime.UtcNow),
            new DiscoveredSource("http://example.com/2", sourceId, new Dictionary<string, object>(), DateTime.UtcNow),
            new DiscoveredSource("http://example.com/3", sourceId, new Dictionary<string, object>(), DateTime.UtcNow),
            new DiscoveredSource("http://example.com/4", sourceId, new Dictionary<string, object>(), DateTime.UtcNow)
        });

        // Act
        var result = await _orchestrator.RunAsync(sourceId, options);

        // Assert
        Assert.True(result.Success);
        Assert.Equal(2, result.DiscoveredLinksCount);
    }

    [Fact]
    public async Task RunAsync_ReturnsFailure_WhenSourceNotFound()
    {
        // Arrange
        var sourceId = "non-existent-source";
        var options = new Phase0Options();
        
        _sourceCatalogMock
            .Setup(x => x.GetSourceAsync(sourceId, It.IsAny<CancellationToken>()))
            .ReturnsAsync((SourceDetailDto?)null);

        // Act
        var result = await _orchestrator.RunAsync(sourceId, options);

        // Assert
        Assert.False(result.Success);
        Assert.Contains("not found", result.ErrorMessage, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task RunAsync_SetsTimingInformation()
    {
        // Arrange
        var sourceId = "test-source";
        var options = new Phase0Options();
        
        SetupSourceCatalog(sourceId);
        SetupDiscoveryEngine(sourceId, Array.Empty<DiscoveredSource>());

        var beforeStart = DateTime.UtcNow;

        // Act
        var result = await _orchestrator.RunAsync(sourceId, options);

        var afterEnd = DateTime.UtcNow;

        // Assert
        Assert.True(result.Success);
        Assert.True(result.StartedAt >= beforeStart || result.StartedAt >= beforeStart.AddSeconds(-1));
        Assert.True(result.CompletedAt <= afterEnd || result.CompletedAt <= afterEnd.AddSeconds(1));
        Assert.True(result.Duration >= TimeSpan.Zero);
    }

    [Fact]
    public async Task RunAsync_PersistsNewLinksToDatabase()
    {
        // Arrange
        var sourceId = "test-source";
        var url = "http://example.com/doc.pdf";
        var options = new Phase0Options();
        
        SetupSourceCatalog(sourceId);
        SetupDiscoveryEngine(sourceId, new[]
        {
            new DiscoveredSource(url, sourceId, new Dictionary<string, object>(), DateTime.UtcNow)
        });
        
        SetupNoExistingLink(sourceId, url);
        
        var metadataResult = new MetadataFetchResult
        {
            Success = true,
            ContentLength = 1024
        };
        
        _metadataFetcherMock
            .Setup(x => x.FetchAsync(url, It.IsAny<CancellationToken>()))
            .ReturnsAsync(metadataResult);
            
        // LinkComparator is real implementation

        // Act
        var result = await _orchestrator.RunAsync(sourceId, options);

        // Assert
        _linkRepositoryMock.Verify(x => x.BulkUpsertAsync(
            It.Is<IEnumerable<DiscoveredLinkEntity>>(entities => entities.Count() == 1),
            It.IsAny<CancellationToken>()), 
            Times.Once);
    }

    // Helper methods

    private void SetupSourceCatalog(string sourceId)
    {
        var links = new List<DiscoveredLinkDto>();
        var metadata = new SourceMetadataDto(null, null, null, null, 0);
        var source = new SourceDetailDto(
            sourceId,
            "Test Source",
            null,
            "test",
            "static_url",
            true,
            links,
            metadata
        )
        {
            DiscoveryConfig = new DiscoveryConfig { Mode = DiscoveryMode.StaticUrl, Url = "http://example.com" }
        };
        
        _sourceCatalogMock
            .Setup(x => x.GetSourceAsync(sourceId, It.IsAny<CancellationToken>()))
            .ReturnsAsync(source);
    }

    private void SetupDiscoveryEngine(string sourceId, IEnumerable<DiscoveredSource> sources)
    {
        _discoveryEngineMock
            .Setup(x => x.DiscoverAsync(sourceId, It.IsAny<DiscoveryConfig>(), It.IsAny<CancellationToken>()))
            .Returns(sources.ToAsyncEnumerable());
    }

    private void SetupExistingLink(string sourceId, string url, bool unchanged)
    {
        var existingEntity = new DiscoveredLinkEntity
        {
            Id = 1,
            SourceId = sourceId,
            Url = url,
            UrlHash = ComputeHash(url),
            Etag = unchanged ? "existing-etag" : "old-etag",
            Status = "pending"
        };

        _linkRepositoryMock
            .Setup(x => x.GetBySourceAndUrlAsync(sourceId, url, It.IsAny<CancellationToken>()))
            .ReturnsAsync(existingEntity);
    }

    private void SetupNoExistingLink(string sourceId, string url)
    {
        _linkRepositoryMock
            .Setup(x => x.GetBySourceAndUrlAsync(sourceId, url, It.IsAny<CancellationToken>()))
            .ReturnsAsync((DiscoveredLinkEntity?)null);
    }

    private void SetupMetadataFetcher(string url, long contentLength)
    {
        _metadataFetcherMock
            .Setup(x => x.FetchAsync(url, It.IsAny<CancellationToken>()))
            .ReturnsAsync(new MetadataFetchResult
            {
                Success = true,
                ContentLength = contentLength,
                Etag = $"etag-{contentLength}"
            });
    }

    private static Gabi.Contracts.Pipeline.DiscoveredLinkPhase0 CreateDiscoveredLink(
        string sourceId, 
        string url, 
        LinkDiscoveryStatus status,
        MetadataFetchResult? metadata = null)
    {
        return new DiscoveredLinkPhase0
        {
            Id = status == LinkDiscoveryStatus.New ? 0 : 1,
            SourceId = sourceId,
            Url = url,
            UrlHash = ComputeHash(url),
            Status = status,
            ContentLength = metadata?.ContentLength,
            Etag = metadata?.Etag,
            LastModified = metadata?.LastModified
        };
    }

    private static string ComputeHash(string input)
    {
        using var sha256 = System.Security.Cryptography.SHA256.Create();
        var bytes = sha256.ComputeHash(System.Text.Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }

    private void SetupExistingLinkWithEtag(string sourceId, string url, string etag, long contentLength)
    {
        var existingEntity = new DiscoveredLinkEntity
        {
            Id = 1,
            SourceId = sourceId,
            Url = url,
            UrlHash = ComputeHash(url),
            Etag = etag,
            ContentLength = contentLength,
            Status = "pending"
        };

        _linkRepositoryMock
            .Setup(x => x.GetBySourceAndUrlAsync(sourceId, url, It.IsAny<CancellationToken>()))
            .ReturnsAsync(existingEntity);
    }
}
