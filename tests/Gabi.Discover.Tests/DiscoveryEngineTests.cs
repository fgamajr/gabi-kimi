using Gabi.Contracts.Discovery;
using Xunit;

namespace Gabi.Discover.Tests;

public class DiscoveryEngineTests
{
    [Fact]
    public async Task DiscoverAsync_WithStaticUrl_ReturnsSingleSource()
    {
        // Arrange
        var config = new DiscoveryConfig
        {
            Mode = DiscoveryMode.StaticUrl,
            Url = "https://example.com/data.csv"
        };
        var engine = new DiscoveryEngine();

        // Act
        var results = await engine.DiscoverAsync("test_source", config).ToListAsync();

        // Assert
        Assert.Single(results);
        Assert.Equal("https://example.com/data.csv", results[0].Url);
        Assert.Equal("test_source", results[0].SourceId);
    }

    [Fact]
    public async Task DiscoverAsync_WithUrlPattern_GeneratesUrlsForYearRange()
    {
        // Arrange
        var config = new DiscoveryConfig
        {
            Mode = DiscoveryMode.UrlPattern,
            UrlTemplate = "https://example.com/data-{year}.csv",
            Params = new Dictionary<string, object>
            {
                ["year"] = new { Start = 2022, End = 2024 }
            }
        };
        var engine = new DiscoveryEngine();

        // Act
        var results = await engine.DiscoverAsync("test_source", config).ToListAsync();

        // Assert
        Assert.Equal(3, results.Count);
        Assert.Contains(results, r => r.Url == "https://example.com/data-2022.csv");
        Assert.Contains(results, r => r.Url == "https://example.com/data-2023.csv");
        Assert.Contains(results, r => r.Url == "https://example.com/data-2024.csv");
    }

    [Fact]
    public async Task DiscoverAsync_WithUrlPattern_WithStep_GeneratesCorrectUrls()
    {
        // Arrange
        var config = new DiscoveryConfig
        {
            Mode = DiscoveryMode.UrlPattern,
            UrlTemplate = "https://example.com/page-{num}.html",
            Params = new Dictionary<string, object>
            {
                ["num"] = new { Start = 1, End = 5, Step = 2 }
            }
        };
        var engine = new DiscoveryEngine();

        // Act
        var results = await engine.DiscoverAsync("test_source", config).ToListAsync();

        // Assert
        Assert.Equal(3, results.Count);
        Assert.Contains(results, r => r.Url == "https://example.com/page-1.html");
        Assert.Contains(results, r => r.Url == "https://example.com/page-3.html");
        Assert.Contains(results, r => r.Url == "https://example.com/page-5.html");
    }

    [Fact]
    public async Task DiscoverAsync_WithInvalidUrlPattern_ThrowsArgumentException()
    {
        // Arrange
        var config = new DiscoveryConfig
        {
            Mode = DiscoveryMode.UrlPattern,
            UrlTemplate = "https://example.com/data-{invalid}.csv",
            Params = new Dictionary<string, object>
            {
                ["year"] = new { Start = 2022, End = 2024 }
            }
        };
        var engine = new DiscoveryEngine();

        // Act & Assert
        await Assert.ThrowsAsync<ArgumentException>(
            async () => await engine.DiscoverAsync("test_source", config).ToListAsync());
    }
}
