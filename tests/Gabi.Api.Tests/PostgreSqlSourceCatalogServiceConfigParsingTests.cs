using System.Reflection;
using System.Text.Json;
using Gabi.Api.Services;
using Gabi.Contracts.Discovery;
using Xunit;

namespace Gabi.Api.Tests;

public class PostgreSqlSourceCatalogServiceConfigParsingTests
{
    [Fact]
    public void ParseDiscoveryConfig_ShouldPreserveStrategyAndExtraFields()
    {
        const string configJson = """
            {
              "strategy": "web_crawl",
              "driver": "curl_html_v1",
              "root_url": "https://example.org/root",
              "rules": {
                "asset_selector": "a[href$='.pdf']"
              },
              "http": {
                "timeout": "180s",
                "request_delay_ms": 1000
              }
            }
            """;

        var parseMethod = typeof(PostgreSqlSourceCatalogService)
            .GetMethod("ParseDiscoveryConfig", BindingFlags.NonPublic | BindingFlags.Static);

        Assert.NotNull(parseMethod);

        var parsed = parseMethod!.Invoke(null, new object[] { configJson });
        var config = Assert.IsType<DiscoveryConfig>(parsed);

        Assert.Equal("web_crawl", config.Strategy);
        Assert.NotNull(config.Extra);
        Assert.True(config.Extra!.ContainsKey("driver"));
        Assert.True(config.Extra.ContainsKey("http"));
        Assert.Equal("curl_html_v1", config.Extra["driver"].GetString());
        Assert.Equal("180s", config.Extra["http"].GetProperty("timeout").GetString());
        Assert.Equal(1000, config.Extra["http"].GetProperty("request_delay_ms").GetInt32());
    }
}
