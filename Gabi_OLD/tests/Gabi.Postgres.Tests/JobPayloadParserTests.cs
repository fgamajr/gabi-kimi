using Gabi.Postgres;

namespace Gabi.Postgres.Tests;

public class JobPayloadParserTests
{
    [Fact]
    public void ParseDiscoveryConfigFromPayload_TemplateWithoutStrategy_InferUrlPattern()
    {
        var payloadJson =
            """
            {
              "force": true,
              "discoveryConfig": "{\"url\":null,\"template\":\"https://example.com/file-{year}.csv\",\"parameters\":{\"year\":{\"Start\":2020,\"End\":\"current\",\"Step\":1}}}"
            }
            """;

        var config = JobPayloadParser.ParseDiscoveryConfigFromPayload(payloadJson);

        Assert.NotNull(config);
        Assert.Equal("url_pattern", config!.Strategy);
        Assert.Equal("https://example.com/file-{year}.csv", config.UrlTemplate);
    }

    [Fact]
    public void ParseDiscoveryConfigFromPayload_DoubleEncodedPayload_InferUrlPattern()
    {
        var inner =
            """
            {"force":true,"year":null,"discoveryConfig":"{\"url\": null, \"template\": \"https://example.com/file-{year}.csv\", \"parameters\": {\"year\": {\"End\": \"current\", \"Step\": 1, \"Start\": 1992}}}"}
            """;
        var payloadJson = System.Text.Json.JsonSerializer.Serialize(inner);

        var config = JobPayloadParser.ParseDiscoveryConfigFromPayload(payloadJson);

        Assert.NotNull(config);
        Assert.Equal("url_pattern", config!.Strategy);
        Assert.Equal("https://example.com/file-{year}.csv", config.UrlTemplate);
    }

    [Fact]
    public void ParseDiscoveryConfigFromPayload_FromHangfireArgumentsShape_InferUrlPattern()
    {
        var hangfireArgumentsJson =
            """
            ["\"job-id\"","\"source_discovery\"","\"test_source_payload\"","\"{\\\"force\\\":true,\\\"year\\\":null,\\\"discoveryConfig\\\":\\\"{\\\\u0022url\\\\u0022: null, \\\\u0022template\\\\u0022: \\\\u0022https://example.com/file-{year}.csv\\\\u0022, \\\\u0022parameters\\\\u0022: {\\\\u0022year\\\\u0022: {\\\\u0022End\\\\u0022: \\\\u0022current\\\\u0022, \\\\u0022Step\\\\u0022: 1, \\\\u0022Start\\\\u0022: 1992}}}\\\"}\"",null]
            """;

        var args = System.Text.Json.JsonSerializer.Deserialize<System.Text.Json.JsonElement>(hangfireArgumentsJson);
        var payloadFromQueue = args[3].GetString();

        var config = JobPayloadParser.ParseDiscoveryConfigFromPayload(payloadFromQueue);

        Assert.NotNull(config);
        Assert.Equal("url_pattern", config!.Strategy);
        Assert.Equal("https://example.com/file-{year}.csv", config.UrlTemplate);
    }

    [Fact]
    public void ParseDiscoveryConfigFromPayload_WebCrawlPayload_PreservesRootRulesAndHttp()
    {
        var payloadJson =
            """
            {
              "force": true,
              "year": null,
              "discoveryConfig": "{\"strategy\":\"web_crawl\",\"driver\":\"curl_html_v1\",\"root_url\":\"https://portal.tcu.gov.br/publicacoes-institucionais/todas\",\"rules\":{\"max_depth\":\"2\",\"link_selector\":\"a[href*='/publicacoes-institucionais/']:not([href$='todas'])\",\"asset_selector\":\"a[href$='.pdf']\"},\"http\":{\"timeout\":\"180s\",\"user_agents\":[\"Mozilla/5.0\"],\"user_agent_mode\":\"rotate\"}}"
            }
            """;

        var config = JobPayloadParser.ParseDiscoveryConfigFromPayload(payloadJson);

        Assert.NotNull(config);
        Assert.Equal("web_crawl", config!.Strategy);
        Assert.NotNull(config.Extra);
        Assert.True(config.Extra!.ContainsKey("root_url"));
        Assert.Equal("https://portal.tcu.gov.br/publicacoes-institucionais/todas", config.Extra["root_url"].GetString());
        Assert.True(config.Extra.ContainsKey("driver"));
        Assert.Equal("curl_html_v1", config.Extra["driver"].GetString());
        Assert.True(config.Extra.ContainsKey("rules"));
        Assert.True(config.Extra.ContainsKey("http"));
    }

    [Fact]
    public void ParseDiscoveryConfigFromPayload_ApiPaginationPayload_PreservesDriverAndEndpointTemplate()
    {
        var payloadJson =
            """
            {
              "force": true,
              "year": null,
              "discoveryConfig": "{\"strategy\":\"api_pagination\",\"driver\":\"camara_api_v1\",\"endpoint_template\":\"https://dadosabertos.camara.leg.br/api/v2/proposicoes?siglaTipo=PL&ano={year}&itens=100\",\"parameters\":{\"start_year\":{\"start\":\"2024\",\"end\":\"2024\"}}}"
            }
            """;

        var config = JobPayloadParser.ParseDiscoveryConfigFromPayload(payloadJson);

        Assert.NotNull(config);
        Assert.Equal("api_pagination", config!.Strategy);
        Assert.NotNull(config.Extra);
        Assert.True(config.Extra!.ContainsKey("driver"));
        Assert.Equal("camara_api_v1", config.Extra["driver"].GetString());
        Assert.True(config.Extra.ContainsKey("endpoint_template"));
        Assert.Equal(
            "https://dadosabertos.camara.leg.br/api/v2/proposicoes?siglaTipo=PL&ano={year}&itens=100",
            config.Extra["endpoint_template"].GetString());
    }
}
