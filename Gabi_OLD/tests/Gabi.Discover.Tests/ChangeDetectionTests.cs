using Gabi.Contracts.Discovery;
using Xunit;

namespace Gabi.Discover.Tests;

public class ChangeDetectionTests
{
    private static readonly IReadOnlyDictionary<string, object> EmptyMeta =
        new Dictionary<string, object>();

    [Fact]
    public async Task CheckAsync_NewUrl_ReturnsChangedTrue()
    {
        // Arrange
        var changeDetector = new ChangeDetector();
        var discovered = new DiscoveredSource(
            Url: "https://example.com/doc.pdf",
            SourceId: "test_source",
            Metadata: EmptyMeta,
            DiscoveredAt: DateTime.UtcNow);

        // Act
        var verdict = await changeDetector.CheckAsync(discovered, cache: null);

        // Assert
        Assert.True(verdict.Changed);
        Assert.Equal("new", verdict.Reason);
        Assert.Equal("https://example.com/doc.pdf", verdict.Url);
    }

    [Fact]
    public async Task CheckAsync_UrlWithSameEtag_ReturnsChangedFalse()
    {
        // Arrange
        var changeDetector = new ChangeDetector();
        var discovered = new DiscoveredSource(
            Url: "https://example.com/doc.pdf",
            SourceId: "test_source",
            Metadata: EmptyMeta,
            DiscoveredAt: DateTime.UtcNow,
            Etag: "\"abc123\"");
        var cache = new ChangeDetectionCache
        {
            Url = "https://example.com/doc.pdf",
            Etag = "\"abc123\"",
            CheckedAt = DateTime.UtcNow.AddDays(-1)
        };

        // Act
        var verdict = await changeDetector.CheckAsync(discovered, cache);

        // Assert
        Assert.False(verdict.Changed);
        Assert.Equal("etag_unchanged", verdict.Reason);
    }

    [Fact]
    public async Task CheckAsync_UrlWithDifferentEtag_ReturnsChangedTrue()
    {
        // Arrange
        var changeDetector = new ChangeDetector();
        var discovered = new DiscoveredSource(
            Url: "https://example.com/doc.pdf",
            SourceId: "test_source",
            Metadata: EmptyMeta,
            DiscoveredAt: DateTime.UtcNow,
            Etag: "\"new-etag\"");
        var cache = new ChangeDetectionCache
        {
            Url = "https://example.com/doc.pdf",
            Etag = "\"old-etag\"",
            CheckedAt = DateTime.UtcNow.AddDays(-1)
        };

        // Act
        var verdict = await changeDetector.CheckAsync(discovered, cache);

        // Assert
        Assert.True(verdict.Changed);
        Assert.Equal("etag_changed", verdict.Reason);
        Assert.Equal("\"old-etag\"", verdict.CachedEtag);
    }

    [Fact]
    public async Task CheckAsync_UrlWithDifferentLastModified_ReturnsChangedTrue()
    {
        // Arrange
        var changeDetector = new ChangeDetector();
        var discovered = new DiscoveredSource(
            Url: "https://example.com/doc.pdf",
            SourceId: "test_source",
            Metadata: EmptyMeta,
            DiscoveredAt: DateTime.UtcNow,
            LastModified: "Wed, 15 Jan 2025 10:00:00 GMT");
        var cache = new ChangeDetectionCache
        {
            Url = "https://example.com/doc.pdf",
            LastModified = "Tue, 14 Jan 2025 10:00:00 GMT",
            CheckedAt = DateTime.UtcNow.AddDays(-1)
        };

        // Act
        var verdict = await changeDetector.CheckAsync(discovered, cache);

        // Assert
        Assert.True(verdict.Changed);
        Assert.Equal("last_modified_changed", verdict.Reason);
    }

    [Fact]
    public async Task CheckBatchAsync_MixedChanges_ReturnsCorrectBatch()
    {
        // Arrange
        var changeDetector = new ChangeDetector();
        var sources = new[]
        {
            new DiscoveredSource("https://example.com/new.pdf", "test", EmptyMeta, DateTime.UtcNow),
            new DiscoveredSource("https://example.com/same.pdf", "test", EmptyMeta, DateTime.UtcNow, Etag: "\"same\"")
        };
        var caches = new ChangeDetectionCache?[]
        {
            null,
            new ChangeDetectionCache { Url = "https://example.com/same.pdf", Etag = "\"same\"" }
        };

        // Act
        var batch = await changeDetector.CheckBatchAsync(sources, caches.ToAsyncEnumerable());

        // Assert
        Assert.Single(batch.ToProcess);
        Assert.Single(batch.Skipped);
        Assert.Equal("https://example.com/new.pdf", batch.ToProcess[0].Url);
        Assert.Equal("https://example.com/same.pdf", batch.Skipped[0].Url);
    }

    [Fact]
    public void ComputeContentHash_SameContent_ReturnsSameHash()
    {
        // Arrange
        var changeDetector = new ChangeDetector();
        var content1 = "Conteúdo de teste"u8.ToArray();
        var content2 = "Conteúdo de teste"u8.ToArray();

        // Act
        var hash1 = changeDetector.ComputeContentHash(content1);
        var hash2 = changeDetector.ComputeContentHash(content2);

        // Assert
        Assert.Equal(hash1, hash2);
        Assert.Equal(64, hash1.Length); // SHA-256 hex = 64 chars
    }

    [Fact]
    public void ComputeContentHash_DifferentContent_ReturnsDifferentHash()
    {
        // Arrange
        var changeDetector = new ChangeDetector();
        var content1 = "Conteúdo A"u8.ToArray();
        var content2 = "Conteúdo B"u8.ToArray();

        // Act
        var hash1 = changeDetector.ComputeContentHash(content1);
        var hash2 = changeDetector.ComputeContentHash(content2);

        // Assert
        Assert.NotEqual(hash1, hash2);
    }
}
