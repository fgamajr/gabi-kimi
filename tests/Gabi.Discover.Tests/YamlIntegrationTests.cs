using Gabi.Contracts.Discovery;
using Xunit;

namespace Gabi.Discover.Tests;

/// <summary>
/// Testes de integração com configurações do sources_v2.yaml real.
/// </summary>
public class YamlIntegrationTests
{
    [Fact]
    public async Task TcuNormas_StaticUrl_DiscoversSingleUrl()
    {
        // Arrange: config from YAML
        var config = new DiscoveryConfig
        {
            Mode = DiscoveryMode.StaticUrl,
            Url = "https://sites.tcu.gov.br/dados-abertos/normas/arquivos/norma.csv"
        };
        var engine = new DiscoveryEngine();

        // Act
        var results = await engine.DiscoverAsync("tcu_normas", config).ToListAsync();

        // Assert
        Assert.Single(results);
        Assert.Equal("https://sites.tcu.gov.br/dados-abertos/normas/arquivos/norma.csv", results[0].Url);
        Assert.Equal("tcu_normas", results[0].SourceId);
    }

    [Fact]
    public async Task TcuSumulas_StaticUrl_DiscoversSingleUrl()
    {
        // Arrange: config from YAML  
        var config = new DiscoveryConfig
        {
            Mode = DiscoveryMode.StaticUrl,
            Url = "https://sites.tcu.gov.br/dados-abertos/jurisprudencia/arquivos/sumula/sumula.csv"
        };
        var engine = new DiscoveryEngine();

        // Act
        var results = await engine.DiscoverAsync("tcu_sumulas", config).ToListAsync();

        // Assert
        Assert.Single(results);
        Assert.Equal("https://sites.tcu.gov.br/dados-abertos/jurisprudencia/arquivos/sumula/sumula.csv", results[0].Url);
    }

    [Fact]
    public async Task TcuAcordaos_UrlPattern_DiscoversYearRange()
    {
        // Arrange: config from YAML (year: 1992 to current)
        var currentYear = DateTime.UtcNow.Year;
        var config = new DiscoveryConfig
        {
            Mode = DiscoveryMode.UrlPattern,
            UrlTemplate = "https://sites.tcu.gov.br/dados-abertos/jurisprudencia/arquivos/acordao-completo/acordao-completo-{year}.csv",
            Params = new Dictionary<string, object>
            {
                ["year"] = new { Start = 1992, End = currentYear, Step = 1 }
            }
        };
        var engine = new DiscoveryEngine();

        // Act
        var results = await engine.DiscoverAsync("tcu_acordaos", config).ToListAsync();

        // Assert
        var expectedCount = currentYear - 1992 + 1; // 1992 to current inclusive
        Assert.Equal(expectedCount, results.Count);
        
        // Check first and last
        Assert.Contains(results, r => r.Url.Contains("acordao-completo-1992.csv"));
        Assert.Contains(results, r => r.Url.Contains($"acordao-completo-{currentYear}.csv"));
        
        // Check metadata
        var firstResult = results.First(r => r.Url.Contains("1992"));
        Assert.Equal(1992, firstResult.Metadata["year"]);
    }

    [Theory]
    [InlineData("tcu_normas", "https://sites.tcu.gov.br/dados-abertos/normas/arquivos/norma.csv")]
    [InlineData("tcu_sumulas", "https://sites.tcu.gov.br/dados-abertos/jurisprudencia/arquivos/sumula/sumula.csv")]
    public async Task StaticUrlSources_DiscoverCorrectly(string sourceId, string expectedUrl)
    {
        var config = new DiscoveryConfig
        {
            Mode = DiscoveryMode.StaticUrl,
            Url = expectedUrl
        };
        var engine = new DiscoveryEngine();

        var results = await engine.DiscoverAsync(sourceId, config).ToListAsync();

        Assert.Single(results);
        Assert.Equal(expectedUrl, results[0].Url);
        Assert.Equal(sourceId, results[0].SourceId);
    }

    [Fact]
    public async Task TcuAcordaos_UrlPattern_WithSimulatedYamlParsing()
    {
        // Simulates how YAML parsing would work (handling "current" keyword)
        var yamlConfig = new
        {
            Strategy = "url_pattern",
            Config = new
            {
                Template = "https://sites.tcu.gov.br/dados-abertos/jurisprudencia/arquivos/acordao-completo/acordao-completo-{year}.csv",
                Parameters = new Dictionary<string, object>
                {
                    ["year"] = new Dictionary<string, object>
                    {
                        ["type"] = "range",
                        ["start"] = 1992,
                        ["end"] = "current",  // YAML keyword
                        ["step"] = 1
                    }
                }
            }
        };

        // Parse YAML-like config (this would be done by a YAML parser in real code)
        var currentYear = DateTime.UtcNow.Year;
        var yearParam = (Dictionary<string, object>)yamlConfig.Config.Parameters["year"];
        var endValue = yearParam["end"] is string s && s == "current" 
            ? currentYear 
            : Convert.ToInt32(yearParam["end"]);

        var config = new DiscoveryConfig
        {
            Mode = DiscoveryMode.UrlPattern,
            UrlTemplate = yamlConfig.Config.Template,
            Params = new Dictionary<string, object>
            {
                ["year"] = new 
                { 
                    Start = Convert.ToInt32(yearParam["start"]), 
                    End = endValue, 
                    Step = Convert.ToInt32(yearParam["step"]) 
                }
            }
        };

        var engine = new DiscoveryEngine();
        var results = await engine.DiscoverAsync("tcu_acordaos", config).ToListAsync();

        var expectedCount = currentYear - 1992 + 1;
        Assert.Equal(expectedCount, results.Count);
        Assert.All(results, r => Assert.StartsWith("https://sites.tcu.gov.br/", r.Url));
    }

    [Fact]
    public async Task TcuAcordaos_UrlPattern_WithEndAsStringCurrent()
    {
        // Test: End as string "current" should resolve to current year
        var config = new DiscoveryConfig
        {
            Mode = DiscoveryMode.UrlPattern,
            UrlTemplate = "https://example.com/data-{year}.csv",
            Params = new Dictionary<string, object>
            {
                ["year"] = new Dictionary<string, object>
                {
                    ["Start"] = 2020,
                    ["End"] = "current",  // String "current"
                    ["Step"] = 1
                }
            }
        };
        var engine = new DiscoveryEngine();
        var currentYear = DateTime.UtcNow.Year;

        var results = await engine.DiscoverAsync("test", config).ToListAsync();

        var expectedCount = currentYear - 2020 + 1;
        Assert.Equal(expectedCount, results.Count);
        Assert.Contains(results, r => r.Url.Contains($"data-{currentYear}.csv"));
    }

    [Fact]
    public async Task TcuAcordaos_UrlPattern_WithEndAsInt()
    {
        // Test: End as specific int (not "current")
        var config = new DiscoveryConfig
        {
            Mode = DiscoveryMode.UrlPattern,
            UrlTemplate = "https://example.com/data-{year}.csv",
            Params = new Dictionary<string, object>
            {
                ["year"] = new Dictionary<string, object>
                {
                    ["Start"] = 2020,
                    ["End"] = 2025,  // Specific year
                    ["Step"] = 1
                }
            }
        };
        var engine = new DiscoveryEngine();

        var results = await engine.DiscoverAsync("test", config).ToListAsync();

        Assert.Equal(6, results.Count); // 2020, 2021, 2022, 2023, 2024, 2025
        Assert.Contains(results, r => r.Url.Contains("data-2020.csv"));
        Assert.Contains(results, r => r.Url.Contains("data-2025.csv"));
    }

    [Fact]
    public async Task TcuAcordaos_UrlPattern_WithParameterRangeRecord()
    {
        // Test: Using ParameterRange record directly with ParameterRangeEnd
        var currentYear = DateTime.UtcNow.Year;
        var config = new DiscoveryConfig
        {
            Mode = DiscoveryMode.UrlPattern,
            UrlTemplate = "https://example.com/data-{year}.csv",
            Params = new Dictionary<string, object>
            {
                ["year"] = new ParameterRange
                {
                    Type = "range",
                    Start = 2022,
                    End = "current",  // Implicit conversion to ParameterRangeEnd
                    Step = 1
                }
            }
        };
        var engine = new DiscoveryEngine();

        var results = await engine.DiscoverAsync("test", config).ToListAsync();

        var expectedCount = currentYear - 2022 + 1;
        Assert.Equal(expectedCount, results.Count);
        Assert.Contains(results, r => r.Url.Contains("data-2022.csv"));
        Assert.Contains(results, r => r.Url.Contains($"data-{currentYear}.csv"));
    }

    [Fact]
    public void ParameterRangeEnd_ImplicitConversions_Work()
    {
        // Test implicit conversions
        ParameterRangeEnd fromInt = 2025;
        ParameterRangeEnd fromString = "current";

        Assert.Equal(2025, fromInt.Resolve(2026));
        Assert.Equal(2026, fromString.Resolve(2026));
        Assert.True(fromString.IsCurrent);
        Assert.False(fromInt.IsCurrent);
    }

    [Fact]
    public void ParameterRangeEnd_Resolve_UsesCurrentYearWhenNotSpecified()
    {
        var current = new ParameterRangeEnd("current");
        var resolved = current.Resolve(); // No parameter = uses DateTime.UtcNow.Year
        
        Assert.Equal(DateTime.UtcNow.Year, resolved);
    }
}
