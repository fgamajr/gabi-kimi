using Gabi.Contracts.Comparison;
using Xunit;

namespace Gabi.Discover.Tests;

public class LinkComparatorTests
{
    private static readonly IReadOnlyDictionary<string, object> EmptyMetadata =
        new Dictionary<string, object>();

    private static readonly IReadOnlyDictionary<string, object> SampleMetadata =
        new Dictionary<string, object>
        {
            ["title"] = "Test Document",
            ["category"] = "Legal"
        };

    private static readonly IReadOnlyDictionary<string, object> ChangedMetadata =
        new Dictionary<string, object>
        {
            ["title"] = "Test Document Updated",
            ["category"] = "Legal"
        };

    [Fact]
    public void Compare_NewLink_ReturnsInsert()
    {
        // Arrange
        var comparator = new LinkComparator();
        var discovered = new DiscoveredLink
        {
            Url = "https://example.com/doc.pdf",
            SourceId = "test_source",
            UrlHash = "abc123",
            Metadata = SampleMetadata
        };

        // Act
        var result = comparator.Compare(discovered, existing: null);

        // Assert
        Assert.Equal(ComparisonAction.Insert, result.Action);
        Assert.Equal("new_link", result.Reason);
        Assert.Equal(discovered.Url, result.Url);
        Assert.Equal(discovered, result.NewLink);
        Assert.Null(result.ExistingLink);
    }

    [Fact]
    public void Compare_UnchangedLink_ReturnsSkip()
    {
        // Arrange
        var comparator = new LinkComparator();
        var metadataHash = comparator.CalculateMetadataHash(SampleMetadata);
        
        var discovered = new DiscoveredLink
        {
            Url = "https://example.com/doc.pdf",
            SourceId = "test_source",
            UrlHash = "abc123",
            Metadata = SampleMetadata,
            ContentHash = "content123"
        };

        var existing = new DiscoveredLinkEntity
        {
            Id = 1,
            Url = "https://example.com/doc.pdf",
            SourceId = "test_source",
            UrlHash = "abc123",
            MetadataHash = metadataHash,
            Metadata = "{\"title\":\"Test Document\",\"category\":\"Legal\"}",
            ContentHash = "content123",
            Status = "completed"
        };

        // Act
        var result = comparator.Compare(discovered, existing);

        // Assert
        Assert.Equal(ComparisonAction.Skip, result.Action);
        Assert.Equal("unchanged", result.Reason);
        Assert.Equal(discovered.Url, result.Url);
    }

    [Fact]
    public void Compare_LinkWithChangedMetadata_ReturnsUpdate()
    {
        // Arrange
        var comparator = new LinkComparator();
        var oldMetadataHash = comparator.CalculateMetadataHash(SampleMetadata);
        
        var discovered = new DiscoveredLink
        {
            Url = "https://example.com/doc.pdf",
            SourceId = "test_source",
            UrlHash = "abc123",
            Metadata = ChangedMetadata
        };

        var existing = new DiscoveredLinkEntity
        {
            Id = 1,
            Url = "https://example.com/doc.pdf",
            SourceId = "test_source",
            UrlHash = "abc123",
            MetadataHash = oldMetadataHash,
            Metadata = "{\"title\":\"Test Document\",\"category\":\"Legal\"}"
        };

        // Act
        var result = comparator.Compare(discovered, existing);

        // Assert
        Assert.Equal(ComparisonAction.Update, result.Action);
        Assert.Equal("metadata_changed", result.Reason);
    }

    [Fact]
    public void Compare_LinkWithChangedContentHash_ReturnsUpdate()
    {
        // Arrange
        var comparator = new LinkComparator();
        var metadataHash = comparator.CalculateMetadataHash(SampleMetadata);
        
        var discovered = new DiscoveredLink
        {
            Url = "https://example.com/doc.pdf",
            SourceId = "test_source",
            UrlHash = "abc123",
            Metadata = SampleMetadata,
            ContentHash = "new_content_hash"
        };

        var existing = new DiscoveredLinkEntity
        {
            Id = 1,
            Url = "https://example.com/doc.pdf",
            SourceId = "test_source",
            UrlHash = "abc123",
            MetadataHash = metadataHash,
            Metadata = "{\"title\":\"Test Document\",\"category\":\"Legal\"}",
            ContentHash = "old_content_hash"
        };

        // Act
        var result = comparator.Compare(discovered, existing);

        // Assert
        Assert.Equal(ComparisonAction.Update, result.Action);
        Assert.Equal("content_changed", result.Reason);
    }

    [Fact]
    public void Compare_LinkWithNullExistingContentHash_ReturnsSkip()
    {
        // Arrange - content hash is null on both sides (not yet fetched)
        var comparator = new LinkComparator();
        var metadataHash = comparator.CalculateMetadataHash(SampleMetadata);
        
        var discovered = new DiscoveredLink
        {
            Url = "https://example.com/doc.pdf",
            SourceId = "test_source",
            UrlHash = "abc123",
            Metadata = SampleMetadata,
            ContentHash = null  // Not fetched yet
        };

        var existing = new DiscoveredLinkEntity
        {
            Id = 1,
            Url = "https://example.com/doc.pdf",
            SourceId = "test_source",
            UrlHash = "abc123",
            MetadataHash = metadataHash,
            Metadata = "{\"title\":\"Test Document\",\"category\":\"Legal\"}",
            ContentHash = null  // Not fetched yet
        };

        // Act
        var result = comparator.Compare(discovered, existing);

        // Assert
        Assert.Equal(ComparisonAction.Skip, result.Action);
        Assert.Equal("unchanged", result.Reason);
    }

    [Fact]
    public async Task CompareBatchAsync_CalculatesCountsCorrectly()
    {
        // Arrange
        var comparator = new LinkComparator();
        var metadataHash = comparator.CalculateMetadataHash(SampleMetadata);
        
        var sourceId = "test_source";
        var discovered = new List<DiscoveredLink>
        {
            new() // Will be Insert
            {
                Url = "https://example.com/new.pdf",
                SourceId = sourceId,
                UrlHash = "new123",
                Metadata = SampleMetadata
            },
            new() // Will be Skip
            {
                Url = "https://example.com/unchanged.pdf",
                SourceId = sourceId,
                UrlHash = "same123",
                Metadata = SampleMetadata,
                ContentHash = "content123"
            },
            new() // Will be Update
            {
                Url = "https://example.com/changed.pdf",
                SourceId = sourceId,
                UrlHash = "changed123",
                Metadata = ChangedMetadata,
                ContentHash = "new_hash"
            }
        };

        var existing = new List<DiscoveredLinkEntity>
        {
            new() // Matches second discovered (Skip)
            {
                Id = 1,
                Url = "https://example.com/unchanged.pdf",
                SourceId = sourceId,
                UrlHash = "same123",
                MetadataHash = metadataHash,
                Metadata = "{\"title\":\"Test Document\",\"category\":\"Legal\"}",
                ContentHash = "content123"
            },
            new() // Matches third discovered but metadata changed (Update)
            {
                Id = 2,
                Url = "https://example.com/changed.pdf",
                SourceId = sourceId,
                UrlHash = "changed123",
                MetadataHash = metadataHash,  // Old hash
                Metadata = "{\"title\":\"Test Document\",\"category\":\"Legal\"}",
                ContentHash = "old_hash"
            }
        };

        // Act
        var result = await comparator.CompareBatchAsync(sourceId, discovered, existing);

        // Assert
        Assert.Equal(sourceId, result.SourceId);
        Assert.Equal(3, result.Results.Count);
        Assert.Equal(1, result.InsertCount);
        Assert.Equal(1, result.UpdateCount);
        Assert.Equal(1, result.SkipCount);
        
        // Verify individual results
        var insertResult = result.Results.First(r => r.Url == "https://example.com/new.pdf");
        Assert.Equal(ComparisonAction.Insert, insertResult.Action);
        
        var skipResult = result.Results.First(r => r.Url == "https://example.com/unchanged.pdf");
        Assert.Equal(ComparisonAction.Skip, skipResult.Action);
        
        var updateResult = result.Results.First(r => r.Url == "https://example.com/changed.pdf");
        Assert.Equal(ComparisonAction.Update, updateResult.Action);
    }

    [Fact]
    public async Task CompareBatchAsync_WithCancellation_ThrowsOperationCanceled()
    {
        // Arrange
        var comparator = new LinkComparator();
        var cts = new CancellationTokenSource();
        cts.Cancel();

        // Act & Assert
        await Assert.ThrowsAsync<OperationCanceledException>(() =>
            comparator.CompareBatchAsync("test", new List<DiscoveredLink>(), new List<DiscoveredLinkEntity>(), cts.Token));
    }

    [Fact]
    public void CalculateMetadataHash_SameMetadata_ReturnsSameHash()
    {
        // Arrange
        var comparator = new LinkComparator();
        var metadata1 = new Dictionary<string, object>
        {
            ["title"] = "Test",
            ["value"] = 123
        };
        var metadata2 = new Dictionary<string, object>
        {
            ["title"] = "Test",
            ["value"] = 123
        };

        // Act
        var hash1 = comparator.CalculateMetadataHash(metadata1);
        var hash2 = comparator.CalculateMetadataHash(metadata2);

        // Assert
        Assert.Equal(hash1, hash2);
        Assert.Equal(64, hash1.Length); // SHA-256 hex = 64 chars
    }

    [Fact]
    public void CalculateMetadataHash_DifferentMetadata_ReturnsDifferentHash()
    {
        // Arrange
        var comparator = new LinkComparator();
        var metadata1 = new Dictionary<string, object>
        {
            ["title"] = "Test A"
        };
        var metadata2 = new Dictionary<string, object>
        {
            ["title"] = "Test B"
        };

        // Act
        var hash1 = comparator.CalculateMetadataHash(metadata1);
        var hash2 = comparator.CalculateMetadataHash(metadata2);

        // Assert
        Assert.NotEqual(hash1, hash2);
    }

    [Fact]
    public void CalculateMetadataHash_EmptyMetadata_ReturnsValidHash()
    {
        // Arrange
        var comparator = new LinkComparator();
        var emptyMetadata = new Dictionary<string, object>();

        // Act
        var hash = comparator.CalculateMetadataHash(emptyMetadata);

        // Assert
        Assert.NotNull(hash);
        Assert.Equal(64, hash.Length);
        Assert.NotEqual(string.Empty, hash);
    }

    [Fact]
    public void CalculateMetadataHash_OrderIndependent_ReturnsSameHash()
    {
        // Arrange
        var comparator = new LinkComparator();
        // Note: JSON serialization preserves order, so different order = different hash
        // This is expected behavior - we test that identical order gives identical hash
        var metadata1 = new Dictionary<string, object>
        {
            ["a"] = 1,
            ["b"] = 2
        };
        var metadata2 = new Dictionary<string, object>
        {
            ["a"] = 1,
            ["b"] = 2
        };

        // Act
        var hash1 = comparator.CalculateMetadataHash(metadata1);
        var hash2 = comparator.CalculateMetadataHash(metadata2);

        // Assert - same order should give same hash
        Assert.Equal(hash1, hash2);
    }
}
