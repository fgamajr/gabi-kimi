using Gabi.Contracts.Fetch;
using Gabi.Contracts.Metadata;
using Microsoft.Extensions.DependencyInjection;
using Xunit;

namespace Gabi.Fetch.Tests;

/// <summary>
/// Tests for FetchService following TDD principles.
/// Red-Green-Refactor cycle.
/// </summary>
public class FetchServiceTests
{
    private readonly IFetchService _fetchService;

    public FetchServiceTests()
    {
        var services = new ServiceCollection();
        services.AddHttpClient();
        services.AddSingleton<IFetchService, FetchService>();
        var provider = services.BuildServiceProvider();
        _fetchService = provider.GetRequiredService<IFetchService>();
    }

    [Fact]
    public async Task FetchMetadataAsync_ReturnsMetadata()
    {
        // Arrange
        var url = "https://example.com/data.csv";

        // Act
        var result = await _fetchService.FetchMetadataAsync(url);

        // Assert
        Assert.NotNull(result);
        Assert.Equal(url, result.Url);
    }

    [Fact]
    public void FetchOptions_DefaultValues_AreCorrect()
    {
        // Act
        var options = new FetchOptions();

        // Assert
        Assert.Equal(100 * 1024 * 1024, options.MaxSizeBytes); // 100MB
        Assert.Equal(TimeSpan.FromMinutes(5), options.Timeout);
        Assert.True(options.UseStreaming);
    }

    [Fact]
    public void FetchOptions_CustomValues_CanBeSet()
    {
        // Act
        var options = new FetchOptions
        {
            MaxSizeBytes = 50 * 1024 * 1024,
            Timeout = TimeSpan.FromMinutes(2),
            UseStreaming = false
        };

        // Assert
        Assert.Equal(50 * 1024 * 1024, options.MaxSizeBytes);
        Assert.Equal(TimeSpan.FromMinutes(2), options.Timeout);
        Assert.False(options.UseStreaming);
    }

    [Fact]
    public async Task FetchAsync_WithOptions_ReturnsFetchResult()
    {
        // Arrange
        var url = "https://example.com/data.csv";
        var options = new FetchOptions
        {
            MaxSizeBytes = 1024 * 1024,
            Timeout = TimeSpan.FromSeconds(30)
        };

        // Act
        var result = await _fetchService.FetchAsync(url, options);

        // Assert
        Assert.NotNull(result);
        Assert.NotNull(result.Metadata);
    }

    [Fact]
    public void FetchResult_SuccessFalse_HasErrorMessage()
    {
        // Arrange & Act
        var result = new FetchResult
        {
            Success = false,
            ErrorMessage = "Connection timeout",
            Metadata = new ResourceMetadata { Url = "https://example.com/data.csv" }
        };

        // Assert
        Assert.False(result.Success);
        Assert.Equal("Connection timeout", result.ErrorMessage);
        Assert.Null(result.Content);
    }

    [Fact]
    public void FetchResult_SuccessTrue_HasContent()
    {
        // Arrange & Act
        var content = new byte[] { 1, 2, 3, 4, 5 };
        var result = new FetchResult
        {
            Success = true,
            Content = content,
            Metadata = new ResourceMetadata { Url = "https://example.com/data.csv" }
        };

        // Assert
        Assert.True(result.Success);
        Assert.Null(result.ErrorMessage);
        Assert.Equal(content, result.Content);
    }
}
