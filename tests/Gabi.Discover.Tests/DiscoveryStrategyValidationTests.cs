using Gabi.Contracts.Discovery;

namespace Gabi.Discover.Tests;

public class DiscoveryStrategyValidationTests
{
    [Fact]
    public async Task DiscoverAsync_WebCrawlInDefaultEngine_ShouldThrowArgumentExceptionWhenConfigIsIncomplete()
    {
        var engine = new DiscoveryEngine();
        var config = new DiscoveryConfig
        {
            Strategy = "web_crawl"
        };

        var ex = await Assert.ThrowsAsync<ArgumentException>(async () =>
        {
            await engine.DiscoverAsync("test_source", config).ToListAsync();
        });

        Assert.Contains("web_crawl", ex.Message);
    }

    [Fact]
    public void SourceCatalogStrategyValidator_ShouldReturnUnsupportedEnabledSources()
    {
        const string yaml = """
            apiVersion: gabi.io/v2
            kind: SourceCatalog
            sources:
              source_supported:
                enabled: true
                discovery:
                  strategy: static_url
              source_unsupported_enabled:
                enabled: true
                discovery:
                  strategy: web_crawl
              source_unsupported_disabled:
                enabled: false
                discovery:
                  strategy: api_pagination
            """;

        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter()
        });
        var validator = new SourceCatalogStrategyValidator(registry);

        var unsupported = validator.FindUnsupportedEnabledStrategies(yaml);

        Assert.Single(unsupported);
        Assert.Equal("source_unsupported_enabled", unsupported[0].SourceId);
        Assert.Equal("web_crawl", unsupported[0].Strategy);
    }

    [Fact]
    public async Task DiscoverAsync_WebCrawlWithoutRootUrl_ShouldThrowArgumentException()
    {
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            new WebCrawlDiscoveryAdapter(),
        });
        var engine = new DiscoveryEngine(registry);
        var config = new DiscoveryConfig { Strategy = "web_crawl" };

        var ex = await Assert.ThrowsAsync<ArgumentException>(async () =>
        {
            await engine.DiscoverAsync("web_source", config).ToListAsync();
        });

        Assert.Contains("web_crawl", ex.Message);
    }

    [Fact]
    public async Task DiscoverAsync_ApiPaginationWithoutEndpoint_ShouldThrowArgumentException()
    {
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            new ApiPaginationDiscoveryAdapter(),
        });
        var engine = new DiscoveryEngine(registry);
        var config = new DiscoveryConfig { Strategy = "api_pagination" };

        var ex = await Assert.ThrowsAsync<ArgumentException>(async () =>
        {
            await engine.DiscoverAsync("api_source", config).ToListAsync();
        });

        Assert.Contains("api_pagination", ex.Message);
    }
}
