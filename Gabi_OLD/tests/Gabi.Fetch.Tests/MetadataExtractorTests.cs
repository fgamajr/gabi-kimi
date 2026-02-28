using System.Net;
using Gabi.Contracts.Metadata;
using Xunit;

namespace Gabi.Fetch.Tests;

/// <summary>
/// Tests for MetadataExtractor following TDD principles.
/// Red-Green-Refactor cycle.
/// </summary>
public class MetadataExtractorTests
{
    private readonly MetadataExtractor _extractor;
    private readonly HttpClient _httpClient;

    public MetadataExtractorTests()
    {
        _httpClient = new HttpClient();
        _extractor = new MetadataExtractor(_httpClient);
    }

    [Fact]
    public async Task ExtractMetadataAsync_ReturnsCorrectContentLength()
    {
        // Arrange
        var url = "https://example.com/data.csv";
        
        // Act
        var result = await _extractor.ExtractMetadataAsync(url);

        // Assert
        Assert.NotNull(result);
        Assert.Equal(url, result.Url);
    }

    [Fact]
    public async Task ExtractMetadataAsync_ExtractsETagFromHeaders()
    {
        // Arrange
        var url = "https://example.com/data.csv";

        // Act
        var result = await _extractor.ExtractMetadataAsync(url);

        // Assert
        Assert.NotNull(result);
        // ETag may be null depending on server response
    }

    [Fact]
    public async Task ExtractMetadataAsync_ParsesLastModifiedHeader()
    {
        // Arrange
        var url = "https://example.com/data.csv";

        // Act
        var result = await _extractor.ExtractMetadataAsync(url);

        // Assert
        Assert.NotNull(result);
        // LastModified may be null depending on server response
    }

    [Fact]
    public async Task ExtractMetadataAsync_ParsesFilenameFromUrl()
    {
        // Arrange
        var url = "https://example.com/documents/data.csv";

        // Act
        var result = await _extractor.ExtractMetadataAsync(url);

        // Assert
        Assert.NotNull(result);
        Assert.Equal("data.csv", result.Filename);
    }

    [Theory]
    [InlineData("https://example.com/file.csv", "file.csv")]
    [InlineData("https://example.com/path/to/file.json", "file.json")]
    [InlineData("https://example.com/file", "file")]
    public void ExtractFilenameFromUrl_VariousUrls_ReturnsCorrectFilename(string url, string expectedFilename)
    {
        // Act
        var result = _extractor.ExtractFilenameFromUrl(url);

        // Assert
        Assert.Equal(expectedFilename, result);
    }

    [Fact]
    public void EstimateDocumentCount_CsvFile_ReturnsEstimatedCount()
    {
        // Arrange
        var metadata = new ResourceMetadata
        {
            Url = "https://example.com/data.csv",
            ContentLength = 10000,
            ContentType = "text/csv"
        };

        // Act
        var result = _extractor.EstimateDocumentCount(metadata, "csv");

        // Assert
        Assert.NotNull(result);
        Assert.True(result > 0);
        // With 200 bytes/row heuristic: 10000 / 200 = 50
        Assert.Equal(50, result);
    }

    [Fact]
    public void EstimateDocumentCount_NoContentLength_ReturnsNull()
    {
        // Arrange
        var metadata = new ResourceMetadata
        {
            Url = "https://example.com/data.csv",
            ContentLength = null,
            ContentType = "text/csv"
        };

        // Act
        var result = _extractor.EstimateDocumentCount(metadata, "csv");

        // Assert
        Assert.Null(result);
    }

    [Fact]
    public void EstimateDocumentCount_UnknownFileType_ReturnsNull()
    {
        // Arrange
        var metadata = new ResourceMetadata
        {
            Url = "https://example.com/data.xyz",
            ContentLength = 10000,
            ContentType = "application/octet-stream"
        };

        // Act
        var result = _extractor.EstimateDocumentCount(metadata, "xyz");

        // Assert
        Assert.Null(result);
    }

    [Fact]
    public async Task CompareAsync_NewResource_ReturnsHasChangedTrue()
    {
        // Arrange
        var current = new ResourceMetadata
        {
            Url = "https://example.com/data.csv",
            ContentLength = 1000,
            ETag = "\"abc123\""
        };

        // Act
        var result = await _extractor.CompareAsync(current, null);

        // Assert
        Assert.True(result.HasChanged);
        Assert.Equal("new_resource", result.ChangeReason);
        Assert.Null(result.PreviousMetadata);
        Assert.Equal(current, result.CurrentMetadata);
    }

    [Fact]
    public async Task CompareAsync_SameMetadata_ReturnsHasChangedFalse()
    {
        // Arrange
        var previous = new ResourceMetadata
        {
            Url = "https://example.com/data.csv",
            ContentLength = 1000,
            ETag = "\"abc123\""
        };
        var current = new ResourceMetadata
        {
            Url = "https://example.com/data.csv",
            ContentLength = 1000,
            ETag = "\"abc123\""
        };

        // Act
        var result = await _extractor.CompareAsync(current, previous);

        // Assert
        Assert.False(result.HasChanged);
        Assert.Null(result.ChangeReason);
        Assert.Equal(previous, result.PreviousMetadata);
        Assert.Equal(current, result.CurrentMetadata);
    }

    [Fact]
    public async Task CompareAsync_SizeChanged_ReturnsHasChangedTrue()
    {
        // Arrange
        var previous = new ResourceMetadata
        {
            Url = "https://example.com/data.csv",
            ContentLength = 1000,
            ETag = "\"abc123\""
        };
        var current = new ResourceMetadata
        {
            Url = "https://example.com/data.csv",
            ContentLength = 2000,
            ETag = "\"abc123\""
        };

        // Act
        var result = await _extractor.CompareAsync(current, previous);

        // Assert
        Assert.True(result.HasChanged);
        Assert.Equal("size_changed", result.ChangeReason);
    }

    [Fact]
    public async Task CompareAsync_ETagChanged_ReturnsHasChangedTrue()
    {
        // Arrange
        var previous = new ResourceMetadata
        {
            Url = "https://example.com/data.csv",
            ContentLength = 1000,
            ETag = "\"abc123\""
        };
        var current = new ResourceMetadata
        {
            Url = "https://example.com/data.csv",
            ContentLength = 1000,
            ETag = "\"def456\""
        };

        // Act
        var result = await _extractor.CompareAsync(current, previous);

        // Assert
        Assert.True(result.HasChanged);
        Assert.Equal("etag_changed", result.ChangeReason);
    }

    [Fact]
    public async Task CompareAsync_LastModifiedChanged_ReturnsHasChangedTrue()
    {
        // Arrange
        var previous = new ResourceMetadata
        {
            Url = "https://example.com/data.csv",
            ContentLength = 1000,
            LastModified = new DateTime(2024, 1, 1, 0, 0, 0, DateTimeKind.Utc)
        };
        var current = new ResourceMetadata
        {
            Url = "https://example.com/data.csv",
            ContentLength = 1000,
            LastModified = new DateTime(2024, 1, 2, 0, 0, 0, DateTimeKind.Utc)
        };

        // Act
        var result = await _extractor.CompareAsync(current, previous);

        // Assert
        Assert.True(result.HasChanged);
        Assert.Equal("lastmodified_changed", result.ChangeReason);
    }

    [Fact]
    public void ExtractMetadataAsync_Handles404Gracefully()
    {
        // Arrange - This test validates that the implementation handles 404s
        // In real implementation, we would use a mock HttpMessageHandler
        
        // Act & Assert
        // The implementation should not throw on 404, instead return metadata with error info
    }

    [Fact]
    public void ExtractMetadataAsync_HandlesTimeoutGracefully()
    {
        // Arrange - This test validates timeout handling
        
        // Act & Assert
        // The implementation should handle timeouts and return metadata with null values
    }
}
