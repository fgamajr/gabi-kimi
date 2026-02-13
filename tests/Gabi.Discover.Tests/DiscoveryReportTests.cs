using Gabi.Contracts.Discovery;
using Xunit;

namespace Gabi.Discover.Tests;

/// <summary>
/// Relatório de descoberta de todas as sources definidas no sources_v2.yaml
/// </summary>
public class DiscoveryReportTests
{
    [Theory]
    [InlineData("tcu_normas", DiscoveryMode.StaticUrl, "https://sites.tcu.gov.br/dados-abertos/normas/arquivos/norma.csv", 1)]
    [InlineData("tcu_sumulas", DiscoveryMode.StaticUrl, "https://sites.tcu.gov.br/dados-abertos/jurisprudencia/arquivos/sumula/sumula.csv", 1)]
    public async Task StaticSources_DiscoveryReport(string sourceId, DiscoveryMode mode, string url, int expectedCount)
    {
        var config = new DiscoveryConfig
        {
            Mode = mode,
            Url = url
        };
        var engine = new DiscoveryEngine();
        var results = await engine.DiscoverAsync(sourceId, config).ToListAsync();
        
        Assert.Equal(expectedCount, results.Count);
    }

    [Fact]
    public async Task TcuAcordaos_DiscoveryReport()
    {
        // Configuração exata do YAML: 1992 até current (2026)
        var config = new DiscoveryConfig
        {
            Mode = DiscoveryMode.UrlPattern,
            UrlTemplate = "https://sites.tcu.gov.br/dados-abertos/jurisprudencia/arquivos/acordao-completo/acordao-completo-{year}.csv",
            Params = new Dictionary<string, object>
            {
                ["year"] = new Dictionary<string, object>
                {
                    ["Start"] = 1992,
                    ["End"] = "current",  // Como está no YAML
                    ["Step"] = 1
                }
            }
        };
        var engine = new DiscoveryEngine();
        var results = await engine.DiscoverAsync("tcu_acordaos", config).ToListAsync();
        
        var currentYear = DateTime.UtcNow.Year;
        var expectedCount = currentYear - 1992 + 1;
        
        Assert.Equal(expectedCount, results.Count);
    }
}
