using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using Gabi.Contracts.Discovery;

namespace Gabi.Discover.Tests;

public class DiscoveryAdapterExecutionTests
{
    private const string BtcuApiTemplate = "https://btcu.example.test/api/filtrarBtcuPublicados/page/{page}";
    private const string BtcuPdfTemplate = "https://btcu.example.test/api/obterDocumentoPdf/{id}";
    private const string SenadoApiTemplate = "https://legis.example.test/dadosabertos/legislacao/lista?tipo={tipo}&ano={year}";
    private const string DouApiTemplate = "https://inlabs.example.test/dou/{date}/{section}.xml";
    private const string DouMonthlyTemplate = "https://dados.example.test/dou/{year}/{month}/{section}.zip";
    private const string YouTubeChannelsApiTemplate = "https://www.googleapis.com/youtube/v3/channels?part=contentDetails&id={channelId}&key={apiKey}";
    private const string YouTubePlaylistApiTemplate = "https://www.googleapis.com/youtube/v3/playlistItems?part=snippet,contentDetails&playlistId={playlistId}&maxResults=50&key={apiKey}";

    [Fact]
    public async Task WebCrawlAdapter_ShouldDiscoverPdfAssetsAcrossDepth()
    {
        var responses = new Dictionary<string, HttpResponseMessage>(StringComparer.OrdinalIgnoreCase)
        {
            ["https://example.org/root"] = Html("""
                <html><body>
                  <a href="/docs/detail">Detail</a>
                  <a href="/files/a.pdf">A</a>
                </body></html>
                """),
            ["https://example.org/docs/detail"] = Html("""
                <html><body>
                  <a href="/files/b.pdf">B</a>
                </body></html>
                """)
        };

        var client = new HttpClient(new StubHttpHandler(responses));
        var adapter = new WebCrawlDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        using var cfgDoc = JsonDocument.Parse("""
            {
              "root_url": "https://example.org/root",
              "rules": {
                "asset_selector": "a[href$='.pdf']",
                "link_selector": "a[href*='/docs/']",
                "max_depth": 2
              }
            }
            """);

        var config = new DiscoveryConfig
        {
            Strategy = "web_crawl",
            Extra = cfgDoc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone())
        };

        var urls = (await engine.DiscoverAsync("source_web", config).ToListAsync())
            .Select(x => x.Url)
            .OrderBy(x => x)
            .ToList();

        Assert.Equal(2, urls.Count);
        Assert.Equal("https://example.org/files/a.pdf", urls[0]);
        Assert.Equal("https://example.org/files/b.pdf", urls[1]);
    }

    [Fact]
    public async Task WebCrawlAdapter_ShouldFollowPaginationParamPagesAndCollectAssets()
    {
        var responses = new Dictionary<string, HttpResponseMessage>(StringComparer.OrdinalIgnoreCase)
        {
            ["https://portal.example.org/publicacoes/todas"] = Html("""
                <html><body>
                  <a href="/publicacoes/todas?pagina=2">Próxima</a>
                  <a href="/publicacoes-institucionais/doc-1">Doc 1</a>
                </body></html>
                """),
            ["https://portal.example.org/publicacoes/todas?pagina=2"] = Html("""
                <html><body>
                  <a href="/publicacoes-institucionais/doc-2">Doc 2</a>
                </body></html>
                """),
            ["https://portal.example.org/publicacoes-institucionais/doc-1"] = Html("""
                <html><body><a href="/files/one.pdf">PDF 1</a></body></html>
                """),
            ["https://portal.example.org/publicacoes-institucionais/doc-2"] = Html("""
                <html><body><a href="/files/two.pdf">PDF 2</a></body></html>
                """)
        };

        var client = new HttpClient(new StubHttpHandler(responses));
        var adapter = new WebCrawlDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        using var cfgDoc = JsonDocument.Parse("""
            {
              "root_url": "https://portal.example.org/publicacoes/todas",
              "rules": {
                "pagination_param": "pagina",
                "link_selector": "a[href*='/publicacoes-institucionais/']",
                "asset_selector": "a[href$='.pdf']",
                "max_depth": 3
              }
            }
            """);

        var config = new DiscoveryConfig
        {
            Strategy = "web_crawl",
            Extra = cfgDoc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone())
        };

        var urls = (await engine.DiscoverAsync("source_web", config).ToListAsync())
            .Select(x => x.Url)
            .OrderBy(x => x)
            .ToList();

        Assert.Equal(2, urls.Count);
        Assert.Equal("https://portal.example.org/files/one.pdf", urls[0]);
        Assert.Equal("https://portal.example.org/files/two.pdf", urls[1]);
    }

    [Fact]
    public async Task WebCrawlAdapter_LinkSelectorWithNotSuffix_ShouldStillFollowAllowedDetailLinks()
    {
        var responses = new Dictionary<string, HttpResponseMessage>(StringComparer.OrdinalIgnoreCase)
        {
            ["https://portal.example.org/publicacoes/todas"] = Html("""
                <html><body>
                  <a href="/publicacoes-institucionais/todas">Index</a>
                  <a href="/publicacoes-institucionais/doc-1">Doc 1</a>
                </body></html>
                """),
            ["https://portal.example.org/publicacoes-institucionais/doc-1"] = Html("""
                <html><body><a href="/files/one.pdf">PDF 1</a></body></html>
                """)
        };

        var client = new HttpClient(new StubHttpHandler(responses));
        var adapter = new WebCrawlDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        using var cfgDoc = JsonDocument.Parse("""
            {
              "root_url": "https://portal.example.org/publicacoes/todas",
              "rules": {
                "link_selector": "a[href*='/publicacoes-institucionais/']:not([href$='todas'])",
                "asset_selector": "a[href$='.pdf']",
                "max_depth": 2
              }
            }
            """);

        var config = new DiscoveryConfig
        {
            Strategy = "web_crawl",
            Extra = cfgDoc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone())
        };

        var urls = (await engine.DiscoverAsync("source_web", config).ToListAsync())
            .Select(x => x.Url)
            .OrderBy(x => x)
            .ToList();

        Assert.Single(urls);
        Assert.Equal("https://portal.example.org/files/one.pdf", urls[0]);
    }

    [Fact]
    public async Task WebCrawlAdapter_ShouldFailExplicitly_WhenRootPageIsUnavailable()
    {
        var responses = new Dictionary<string, HttpResponseMessage>(StringComparer.OrdinalIgnoreCase)
        {
            ["https://portal.example.org/publicacoes/todas"] = new HttpResponseMessage(HttpStatusCode.GatewayTimeout)
        };

        var client = new HttpClient(new StubHttpHandler(responses));
        var adapter = new WebCrawlDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        using var cfgDoc = JsonDocument.Parse("""
            {
              "root_url": "https://portal.example.org/publicacoes/todas",
              "rules": {
                "asset_selector": "a[href$='.pdf']",
                "max_depth": 1
              }
            }
            """);

        var config = new DiscoveryConfig
        {
            Strategy = "web_crawl",
            Extra = cfgDoc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone())
        };

        var ex = await Assert.ThrowsAsync<InvalidOperationException>(async () =>
        {
            await engine.DiscoverAsync("source_web", config).ToListAsync();
        });

        Assert.Contains("root", ex.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task ApiPaginationAdapter_ShouldFollowNextLinksAndCollectUris()
    {
        var responses = new Dictionary<string, HttpResponseMessage>(StringComparer.OrdinalIgnoreCase)
        {
            ["https://api.example.org/items?page=1"] = Json("""
                {
                  "dados": [
                    { "uri": "https://api.example.org/items/1" },
                    { "uri": "https://api.example.org/items/2" }
                  ],
                  "links": [
                    { "rel": "next", "href": "https://api.example.org/items?page=2" }
                  ]
                }
                """),
            ["https://api.example.org/items?page=2"] = Json("""
                {
                  "dados": [
                    { "uri": "https://api.example.org/items/3" }
                  ],
                  "links": []
                }
                """)
        };

        var client = new HttpClient(new StubHttpHandler(responses));
        var adapter = new ApiPaginationDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        var config = new DiscoveryConfig
        {
            Strategy = "api_pagination",
            Url = "https://api.example.org/items?page=1"
        };

        var urls = (await engine.DiscoverAsync("source_api", config).ToListAsync())
            .Select(x => x.Url)
            .OrderBy(x => x)
            .ToList();

        Assert.Equal(3, urls.Count);
        Assert.Contains("https://api.example.org/items/1", urls);
        Assert.Contains("https://api.example.org/items/2", urls);
        Assert.Contains("https://api.example.org/items/3", urls);
    }

    [Fact]
    public async Task ApiPaginationAdapter_CamaraDriver_ShouldParseStringYearRange()
    {
        const string endpoint2025 = "https://dadosabertos.camara.leg.br/api/v2/proposicoes?siglaTipo=PL&ano=2025&itens=100&ordem=ASC&ordenarPor=id";
        var responses = new Dictionary<string, HttpResponseMessage>(StringComparer.OrdinalIgnoreCase)
        {
            [endpoint2025] = Json("""
                {
                  "dados": [
                    { "uri": "https://dadosabertos.camara.leg.br/api/v2/proposicoes/123" }
                  ],
                  "links": []
                }
                """)
        };

        var client = new HttpClient(new StubHttpHandler(responses));
        var adapter = new ApiPaginationDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        using var cfgDoc = JsonDocument.Parse("""
            {
              "driver": "camara_api_v1"
            }
            """);
        using var paramsDoc = JsonDocument.Parse("""
            {
              "start_year": {
                "start": "2025",
                "end": "2025"
              }
            }
            """);

        var config = new DiscoveryConfig
        {
            Strategy = "api_pagination",
            Extra = cfgDoc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone()),
            Params = paramsDoc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => (object)p.Value.Clone())
        };

        var urls = (await engine.DiscoverAsync("camara", config).ToListAsync()).Select(x => x.Url).ToList();

        Assert.Single(urls);
        Assert.Equal("https://dadosabertos.camara.leg.br/api/v2/proposicoes/123", urls[0]);
    }

    [Fact]
    public async Task ApiPaginationAdapter_CamaraDriver_ShouldUseConfiguredEndpointTemplate()
    {
        const string endpoint2024 = "https://api.camara.example/proposicoes?siglaTipo=PL&ano=2024&itens=50";
        var responses = new Dictionary<string, HttpResponseMessage>(StringComparer.OrdinalIgnoreCase)
        {
            [endpoint2024] = Json("""
                {
                  "dados": [
                    { "uri": "https://api.camara.example/proposicoes/999" }
                  ],
                  "links": []
                }
                """)
        };

        var client = new HttpClient(new StubHttpHandler(responses));
        var adapter = new ApiPaginationDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        using var cfgDoc = JsonDocument.Parse("""
            {
              "driver": "camara_api_v1",
              "endpoint_template": "https://api.camara.example/proposicoes?siglaTipo=PL&ano={year}&itens=50"
            }
            """);
        using var paramsDoc = JsonDocument.Parse("""
            {
              "start_year": {
                "start": "2024",
                "end": "2024"
              }
            }
            """);

        var config = new DiscoveryConfig
        {
            Strategy = "api_pagination",
            Extra = cfgDoc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone()),
            Params = paramsDoc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => (object)p.Value.Clone())
        };

        var urls = (await engine.DiscoverAsync("camara", config).ToListAsync()).Select(x => x.Url).ToList();

        Assert.Single(urls);
        Assert.Equal("https://api.camara.example/proposicoes/999", urls[0]);
    }

    [Fact]
    public async Task ApiPaginationAdapter_CamaraDriver_ShouldTagAsProposicaoInMetadata()
    {
        const string endpoint2024 = "https://api.camara.example/proposicoes?siglaTipo=PL&ano=2024&itens=50";
        var responses = new Dictionary<string, HttpResponseMessage>(StringComparer.OrdinalIgnoreCase)
        {
            [endpoint2024] = Json("""
                {
                  "dados": [
                    { "uri": "https://api.camara.example/proposicoes/1000" }
                  ],
                  "links": []
                }
                """)
        };

        var client = new HttpClient(new StubHttpHandler(responses));
        var adapter = new ApiPaginationDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        using var cfgDoc = JsonDocument.Parse("""
            {
              "driver": "camara_api_v1",
              "endpoint_template": "https://api.camara.example/proposicoes?siglaTipo=PL&ano={year}&itens=50"
            }
            """);
        using var paramsDoc = JsonDocument.Parse("""
            {
              "start_year": {
                "start": "2024",
                "end": "2024"
              }
            }
            """);

        var config = new DiscoveryConfig
        {
            Strategy = "api_pagination",
            Extra = cfgDoc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone()),
            Params = paramsDoc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => (object)p.Value.Clone())
        };

        var discovered = await engine.DiscoverAsync("camara", config).ToListAsync();

        Assert.Single(discovered);
        Assert.Equal("proposicao", discovered[0].Metadata["document_kind"]);
        Assert.Equal("em_tramitacao", discovered[0].Metadata["approval_state"]);
        Assert.Equal("camara_api_v1", discovered[0].Metadata["driver"]);
    }

    [Fact]
    public async Task ApiPaginationAdapter_ShouldApplyConfiguredUserAgentFromList()
    {
        var responses = new Dictionary<string, HttpResponseMessage>(StringComparer.OrdinalIgnoreCase)
        {
            ["https://api.example.org/items?page=1"] = Json("""
                {
                  "dados": [
                    { "uri": "https://api.example.org/items/1" }
                  ],
                  "links": []
                }
                """)
        };

        var handler = new RecordingStubHttpHandler(responses);
        var client = new HttpClient(handler);
        var adapter = new ApiPaginationDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        using var cfgDoc = JsonDocument.Parse("""
            {
              "endpoint": "https://api.example.org/items?page=1",
              "http": {
                "user_agents": [
                  "GabiBot/1.0 (+https://example.org/bot)",
                  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                ],
                "user_agent_mode": "rotate"
              }
            }
            """);

        var config = new DiscoveryConfig
        {
            Strategy = "api_pagination",
            Extra = cfgDoc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone())
        };

        var discovered = await engine.DiscoverAsync("source_api", config).ToListAsync();
        Assert.Single(discovered);

        var userAgent = handler.Requests
            .SelectMany(r => r.Headers.UserAgent)
            .Select(h => h.ToString())
            .FirstOrDefault();

        Assert.False(string.IsNullOrWhiteSpace(userAgent));
        Assert.Contains("GabiBot/1.0", userAgent);
    }

    [Fact]
    public async Task ApiPaginationAdapter_ShouldPreservePartialResults_WhenNextPageFails()
    {
        var responses = new Dictionary<string, HttpResponseMessage>(StringComparer.OrdinalIgnoreCase)
        {
            ["https://api.example.org/items?page=1"] = Json("""
                {
                  "dados": [
                    { "uri": "https://api.example.org/items/1" }
                  ],
                  "links": [
                    { "rel": "next", "href": "https://api.example.org/items?page=2" }
                  ]
                }
                """),
            ["https://api.example.org/items?page=2"] = new HttpResponseMessage(HttpStatusCode.GatewayTimeout)
        };

        var client = new HttpClient(new StubHttpHandler(responses));
        var adapter = new ApiPaginationDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        var config = new DiscoveryConfig
        {
            Strategy = "api_pagination",
            Url = "https://api.example.org/items?page=1"
        };

        var discovered = await engine.DiscoverAsync("source_api", config).ToListAsync();

        Assert.Single(discovered);
        Assert.Equal("https://api.example.org/items/1", discovered[0].Url);
    }

    [Fact]
    public async Task ApiPaginationAdapter_ShouldNotThrow_WhenRequestsAlwaysTimeout()
    {
        var client = new HttpClient(new TimeoutStubHttpHandler());
        var adapter = new ApiPaginationDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        var config = new DiscoveryConfig
        {
            Strategy = "api_pagination",
            Url = "https://api.example.org/items?page=1"
        };

        var discovered = await engine.DiscoverAsync("source_api", config).ToListAsync();

        Assert.Empty(discovered);
    }

    [Fact]
    public async Task ApiPaginationAdapter_BtcuDriver_ShouldDiscoverPdfLinksFromPaginatedPost()
    {
        var responses = new Dictionary<string, HttpResponseMessage>(StringComparer.OrdinalIgnoreCase)
        {
            [BtcuPageUrl(0)] = Json("""
                {
                  "content": [
                    { "codigoDocumentoTramitavel": 79783929, "numero": 5 },
                    { "codigoDocumentoTramitavel": 79783930, "numero": 6 }
                  ],
                  "totalPages": 2,
                  "number": 0
                }
                """),
            [BtcuPageUrl(1)] = Json("""
                {
                  "content": [
                    { "codigoDocumentoTramitavel": 79783931, "numero": 7 }
                  ],
                  "totalPages": 2,
                  "number": 1
                }
                """)
        };

        var handler = new BtcuStubHttpHandler(responses);
        var client = new HttpClient(handler);
        var adapter = new ApiPaginationDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        var config = BuildBtcuConfig(tipo: "1");

        var urls = (await engine.DiscoverAsync("tcu_btcu", config).ToListAsync())
            .Select(x => x.Url)
            .OrderBy(x => x)
            .ToList();

        Assert.Equal(3, urls.Count);
        Assert.Equal(BtcuPdfUrl(79783929), urls[0]);
        Assert.Equal(BtcuPdfUrl(79783930), urls[1]);
        Assert.Equal(BtcuPdfUrl(79783931), urls[2]);
        Assert.All(handler.Requests, request => Assert.Equal(HttpMethod.Post, request.Method));
        Assert.Contains(handler.Bodies, body =>
            body.Contains("\"tipo\"", StringComparison.Ordinal)
            && body.Contains("\"1\"", StringComparison.Ordinal));
    }

    [Fact]
    public async Task ApiPaginationAdapter_BtcuDriver_ShouldStopGracefullyOnHttpErrorAfterPartialResults()
    {
        var responses = new Dictionary<string, HttpResponseMessage>(StringComparer.OrdinalIgnoreCase)
        {
            [BtcuPageUrl(0)] = Json("""
                {
                  "content": [
                    { "codigoDocumentoTramitavel": 79783929, "numero": 5 }
                  ],
                  "totalPages": 3,
                  "number": 0
                }
                """),
            [BtcuPageUrl(1)] = new HttpResponseMessage(HttpStatusCode.InternalServerError)
        };

        var client = new HttpClient(new BtcuStubHttpHandler(responses));
        var adapter = new ApiPaginationDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        var config = BuildBtcuConfig(tipo: "1");

        var discovered = await engine.DiscoverAsync("tcu_btcu", config).ToListAsync();

        Assert.Single(discovered);
        Assert.Equal(BtcuPdfUrl(79783929), discovered[0].Url);
    }

    [Fact]
    public async Task ApiPaginationAdapter_BtcuDriver_ShouldRespectMaxPages()
    {
        var responses = new Dictionary<string, HttpResponseMessage>(StringComparer.OrdinalIgnoreCase)
        {
            [BtcuPageUrl(0)] = Json("""
                { "content": [{ "codigoDocumentoTramitavel": 1 }], "totalPages": 100, "number": 0 }
                """),
            [BtcuPageUrl(1)] = Json("""
                { "content": [{ "codigoDocumentoTramitavel": 2 }], "totalPages": 100, "number": 1 }
                """),
            [BtcuPageUrl(2)] = Json("""
                { "content": [{ "codigoDocumentoTramitavel": 3 }], "totalPages": 100, "number": 2 }
                """)
        };

        var handler = new BtcuStubHttpHandler(responses);
        var client = new HttpClient(handler);
        var adapter = new ApiPaginationDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        var config = BuildBtcuConfig(tipo: "1", maxPages: 2);

        var urls = (await engine.DiscoverAsync("tcu_btcu", config).ToListAsync()).Select(x => x.Url).ToList();

        Assert.Equal(2, urls.Count);
        Assert.DoesNotContain(BtcuPdfUrl(3), urls);
        Assert.Equal(2, handler.Requests.Count);
    }

    [Fact]
    public async Task ApiPaginationAdapter_BtcuDriver_ShouldEnrichMetadata()
    {
        var responses = new Dictionary<string, HttpResponseMessage>(StringComparer.OrdinalIgnoreCase)
        {
            [BtcuPageUrl(0)] = Json("""
                {
                  "content": [
                    {
                      "codigo": 92612,
                      "codigoDocumentoTramitavel": 79783929,
                      "indTipo": 1,
                      "descricaoTipo": "BTCU Administrativo",
                      "dataPublicacao": "13/02/2026",
                      "numero": 30,
                      "descricao": "BTCU Administrativo | Ano 59 | n° 30"
                    }
                  ],
                  "totalPages": 1,
                  "number": 0
                }
                """)
        };

        var client = new HttpClient(new BtcuStubHttpHandler(responses));
        var adapter = new ApiPaginationDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        var config = BuildBtcuConfig(tipo: "1");

        var discovered = await engine.DiscoverAsync("tcu_btcu", config).ToListAsync();

        Assert.Single(discovered);
        var metadata = discovered[0].Metadata;
        Assert.Equal("btcu_api_v1", metadata["driver"]);
        Assert.Equal(92612L, metadata["btcu_codigo"]);
        Assert.Equal(1L, metadata["btcu_tipo"]);
        Assert.Equal("BTCU Administrativo", metadata["btcu_tipo_descricao"]);
        Assert.Equal("13/02/2026", metadata["btcu_data_publicacao"]);
        Assert.Equal(30L, metadata["btcu_numero"]);
        Assert.Equal("BTCU Administrativo | Ano 59 | n° 30", metadata["btcu_descricao"]);
    }

    [Fact]
    public async Task ApiPaginationAdapter_BtcuDriver_ShouldRetryWhenHtmlPayloadReturnedBeforeJson()
    {
        var responses = new Dictionary<string, Queue<HttpResponseMessage>>(StringComparer.OrdinalIgnoreCase)
        {
            [BtcuPageUrl(0)] = new Queue<HttpResponseMessage>(new[]
            {
                Html("<html><body>temporary protection page</body></html>"),
                Json("""
                    {
                      "content": [
                        { "codigoDocumentoTramitavel": 79783929, "numero": 5 }
                      ],
                      "totalPages": 1,
                      "number": 0
                    }
                    """)
            })
        };

        var handler = new BtcuSequenceStubHttpHandler(responses);
        var client = new HttpClient(handler);
        var adapter = new ApiPaginationDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        var config = BuildBtcuConfig(tipo: "1");

        var discovered = await engine.DiscoverAsync("tcu_btcu", config).ToListAsync();

        Assert.Single(discovered);
        Assert.Equal(BtcuPdfUrl(79783929), discovered[0].Url);
        Assert.Equal(2, handler.Requests.Count);
    }

    [Fact]
    public async Task ApiPaginationAdapter_SenadoDriver_ShouldDiscoverNormsAcrossYearRange()
    {
        var responses = new Dictionary<string, HttpResponseMessage>(StringComparer.OrdinalIgnoreCase)
        {
            [SenadoYearUrl("LEI", 2025)] = Json("""
                {
                  "ListaDocumento": {
                    "documentos": {
                      "documento": [
                        {
                          "id": "1001",
                          "tipo": "LEI-n",
                          "numero": "15000",
                          "norma": "LEI-15000-2025-03-01",
                          "normaNome": "Lei nº 15.000 de 01/03/2025",
                          "ementa": "Ementa A",
                          "dataassinatura": "01/03/2025",
                          "anoassinatura": "2025"
                        }
                      ]
                    }
                  }
                }
                """),
            [SenadoYearUrl("LEI", 2026)] = Json("""
                {
                  "ListaDocumento": {
                    "documentos": {
                      "documento": [
                        {
                          "id": "1002",
                          "tipo": "LEI-n",
                          "numero": "15347",
                          "norma": "LEI-15347-2026-02-06",
                          "normaNome": "Lei nº 15.347 de 06/02/2026",
                          "ementa": "Ementa B",
                          "dataassinatura": "06/02/2026",
                          "anoassinatura": "2026"
                        }
                      ]
                    }
                  }
                }
                """)
        };

        var client = new HttpClient(new StubHttpHandler(responses));
        var adapter = new ApiPaginationDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        var config = BuildSenadoConfig("LEI", 2025, 2026);

        var discovered = await engine.DiscoverAsync("senado_legislacao", config).ToListAsync();
        var urls = discovered.Select(x => x.Url).OrderBy(x => x).ToList();

        Assert.Equal(2, urls.Count);
        Assert.Equal("https://legis.senado.leg.br/dadosabertos/legislacao/1001", urls[0]);
        Assert.Equal("https://legis.senado.leg.br/dadosabertos/legislacao/1002", urls[1]);
        Assert.All(discovered, item =>
        {
            Assert.Equal("norma", item.Metadata["document_kind"]);
            Assert.Equal("aprovada", item.Metadata["approval_state"]);
            Assert.Equal("senado_legislacao_api_v1", item.Metadata["driver"]);
        });
    }

    [Fact]
    public async Task ApiPaginationAdapter_SenadoDriver_ShouldKeepPartialResultsWhenOneYearFails()
    {
        var responses = new Dictionary<string, HttpResponseMessage>(StringComparer.OrdinalIgnoreCase)
        {
            [SenadoYearUrl("LEI", 2025)] = Json("""
                {
                  "ListaDocumento": {
                    "documentos": {
                      "documento": [
                        { "id": "2001", "norma": "LEI-15010-2025-01-01", "anoassinatura": "2025" }
                      ]
                    }
                  }
                }
                """),
            [SenadoYearUrl("LEI", 2026)] = new HttpResponseMessage(HttpStatusCode.GatewayTimeout)
        };

        var client = new HttpClient(new StubHttpHandler(responses));
        var adapter = new ApiPaginationDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        var config = BuildSenadoConfig("LEI", 2025, 2026);

        var discovered = await engine.DiscoverAsync("senado_legislacao", config).ToListAsync();

        Assert.Single(discovered);
        Assert.Equal("https://legis.senado.leg.br/dadosabertos/legislacao/2001", discovered[0].Url);
    }

    [Fact]
    public async Task ApiPaginationAdapter_DouDriver_ShouldDiscoverLinksAndEnrichMetadata()
    {
        var responses = new Dictionary<string, HttpResponseMessage>(StringComparer.OrdinalIgnoreCase)
        {
            [DouDateSectionUrl("2026-02-13", "do1")] = Xml("""
                <articles>
                  <article id="123" orgao="TCU" edicao="31" pagina="10" tipo="nomeacao">
                    <titulo>Portaria de Nomeação</titulo>
                    <url>https://www.in.gov.br/web/dou/-/portaria-123</url>
                  </article>
                  <article id="456" orgao="TCU" edicao="31" pagina="11" tipo="extrato_contrato">
                    <titulo>Extrato de Contrato</titulo>
                    <url>https://www.in.gov.br/web/dou/-/extrato-456</url>
                  </article>
                </articles>
                """)
        };

        var client = new HttpClient(new StubHttpHandler(responses));
        var adapter = new ApiPaginationDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        var config = BuildDouConfig(
            startDate: "2026-02-13",
            endDate: "2026-02-13",
            sections: ["do1"]);

        var discovered = await engine.DiscoverAsync("dou_inlabs_secao1_atos", config).ToListAsync();

        Assert.Equal(2, discovered.Count);
        Assert.All(discovered, item =>
        {
            Assert.Equal("dou_inlabs_xml_v1", item.Metadata["driver"]);
            Assert.Equal("DOU", item.Metadata["diario_tipo"]);
            Assert.Equal("ato_administrativo", item.Metadata["document_kind"]);
            Assert.Equal("do1", item.Metadata["secao"]);
            Assert.Equal("2026-02-13", item.Metadata["data_publicacao"]);
        });
        Assert.Equal("nomeacao", discovered[0].Metadata["ato_tipo"]);
        Assert.Equal("TCU", discovered[0].Metadata["orgao"]);
    }

    [Fact]
    public async Task ApiPaginationAdapter_DouDriver_ShouldKeepPartialResultsWhenOneSectionFails()
    {
        var responses = new Dictionary<string, HttpResponseMessage>(StringComparer.OrdinalIgnoreCase)
        {
            [DouDateSectionUrl("2026-02-13", "do1")] = Xml("""
                <articles>
                  <article id="123">
                    <url>https://www.in.gov.br/web/dou/-/portaria-123</url>
                  </article>
                </articles>
                """),
            [DouDateSectionUrl("2026-02-13", "do2")] = new HttpResponseMessage(HttpStatusCode.GatewayTimeout)
        };

        var client = new HttpClient(new StubHttpHandler(responses));
        var adapter = new ApiPaginationDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        var config = BuildDouConfig(
            startDate: "2026-02-13",
            endDate: "2026-02-13",
            sections: ["do1", "do2"]);

        var discovered = await engine.DiscoverAsync("dou_inlabs_secao1_atos", config).ToListAsync();

        Assert.Single(discovered);
        Assert.Equal("https://www.in.gov.br/web/dou/-/portaria-123", discovered[0].Url);
    }

    [Fact]
    public async Task ApiPaginationAdapter_DouDriver_ShouldFailExplicitly_WhenInlabsCookieHeaderIsMissing()
    {
        var client = new HttpClient(new StubHttpHandler(new Dictionary<string, HttpResponseMessage>()));
        var adapter = new ApiPaginationDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        var payload = new Dictionary<string, object?>
        {
            ["driver"] = "dou_inlabs_xml_v1",
            ["endpoint_template"] = "https://inlabs.in.gov.br/index.php?p={date}&dl={section}",
            ["sections"] = new[] { "do1" }
        };
        using var cfgDoc = JsonDocument.Parse(JsonSerializer.Serialize(payload));
        using var paramsDoc = JsonDocument.Parse("""
            {
              "date_range": { "start": "2026-02-13", "end": "2026-02-13" }
            }
            """);

        var config = new DiscoveryConfig
        {
            Strategy = "api_pagination",
            Extra = cfgDoc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone()),
            Params = paramsDoc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => (object)p.Value.Clone())
        };

        var ex = await Assert.ThrowsAsync<ArgumentException>(async () =>
        {
            await engine.DiscoverAsync("dou_inlabs_secao1_atos", config).ToListAsync();
        });

        Assert.Contains("GABI_INLABS_COOKIE", ex.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task ApiPaginationAdapter_DouMonthlyPatternDriver_ShouldGenerateMonthlyLinks()
    {
        var client = new HttpClient(new StubHttpHandler(new Dictionary<string, HttpResponseMessage>()));
        var adapter = new ApiPaginationDiscoveryAdapter(client);
        var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            adapter
        });
        var engine = new DiscoveryEngine(registry);

        using var cfgDoc = JsonDocument.Parse("""
            {
              "driver": "dou_monthly_pattern_v1",
              "url_template": "https://dados.example.test/dou/{year}/{month}/{section}.zip",
              "start_year": 2025,
              "end_year": 2025,
              "start_month": 1,
              "end_month": 3,
              "sections": ["do1", "do3"]
            }
            """);

        var config = new DiscoveryConfig
        {
            Strategy = "api_pagination",
            Extra = cfgDoc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone())
        };

        var discovered = await engine.DiscoverAsync("dou_dados_abertos_mensal", config).ToListAsync();
        var urls = discovered.Select(x => x.Url).OrderBy(x => x).ToList();

        Assert.Equal(6, discovered.Count);
        Assert.Contains("https://dados.example.test/dou/2025/01/do1.zip", urls);
        Assert.Contains("https://dados.example.test/dou/2025/03/do3.zip", urls);
        Assert.All(discovered, d =>
        {
            Assert.Equal("dou_monthly_pattern_v1", d.Metadata["driver"]);
            Assert.Equal("DOU", d.Metadata["diario_tipo"]);
            Assert.Equal("ato_administrativo", d.Metadata["document_kind"]);
        });
    }

    [Fact]
    public async Task ApiPaginationAdapter_YouTubeDriver_ShouldDiscoverVideosAcrossPages()
    {
        const string apiKey = "yt-key-test";
        const string channelId = "UC_TEST_CHANNEL";
        const string uploadsPlaylistId = "UU_TEST_UPLOADS";

        var responses = new Dictionary<string, HttpResponseMessage>(StringComparer.OrdinalIgnoreCase)
        {
            [YouTubeChannelsUrl(channelId, apiKey)] = Json($$"""
                {
                  "items": [
                    {
                      "contentDetails": {
                        "relatedPlaylists": {
                          "uploads": "{{uploadsPlaylistId}}"
                        }
                      }
                    }
                  ]
                }
                """),
            [YouTubePlaylistUrl(uploadsPlaylistId, apiKey)] = Json("""
                {
                  "items": [
                    {
                      "contentDetails": { "videoId": "vid1" },
                      "snippet": {
                        "title": "Video 1",
                        "description": "Description 1",
                        "publishedAt": "2026-02-20T10:00:00Z",
                        "channelTitle": "TCU Oficial",
                        "thumbnails": { "high": { "url": "https://img.example/vid1.jpg" } }
                      }
                    }
                  ],
                  "nextPageToken": "TOKEN_2"
                }
                """),
            [YouTubePlaylistUrl(uploadsPlaylistId, apiKey, "TOKEN_2")] = Json("""
                {
                  "items": [
                    {
                      "contentDetails": { "videoId": "vid1" },
                      "snippet": {
                        "title": "Video 1 duplicated",
                        "description": "Duplicate should be ignored",
                        "publishedAt": "2026-02-20T10:00:00Z",
                        "channelTitle": "TCU Oficial",
                        "thumbnails": { "high": { "url": "https://img.example/vid1.jpg" } }
                      }
                    },
                    {
                      "contentDetails": { "videoId": "vid2" },
                      "snippet": {
                        "title": "Video 2",
                        "description": "Description 2",
                        "publishedAt": "2026-02-21T10:00:00Z",
                        "channelTitle": "TCU Oficial",
                        "thumbnails": { "maxres": { "url": "https://img.example/vid2.jpg" } }
                      }
                    }
                  ]
                }
                """)
        };

        var oldApiKey = Environment.GetEnvironmentVariable("YOUTUBE_API_KEY");
        Environment.SetEnvironmentVariable("YOUTUBE_API_KEY", apiKey);
        try
        {
            var client = new HttpClient(new StubHttpHandler(responses));
            var adapter = new ApiPaginationDiscoveryAdapter(client);
            var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
            {
                new StaticUrlDiscoveryAdapter(),
                new UrlPatternDiscoveryAdapter(),
                adapter
            });
            var engine = new DiscoveryEngine(registry);

            using var cfgDoc = JsonDocument.Parse($$"""
                {
                  "driver": "youtube_channel_v1",
                  "channel_id": "{{channelId}}"
                }
                """);

            var config = new DiscoveryConfig
            {
                Strategy = "api_pagination",
                Extra = cfgDoc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone())
            };

            var discovered = await engine.DiscoverAsync("tcu_youtube_videos", config).ToListAsync();
            var urls = discovered.Select(x => x.Url).OrderBy(x => x).ToList();

            Assert.Equal(2, discovered.Count);
            Assert.Equal("https://www.youtube.com/watch?v=vid1", urls[0]);
            Assert.Equal("https://www.youtube.com/watch?v=vid2", urls[1]);

            Assert.All(discovered, d =>
            {
                Assert.Equal("youtube_channel_v1", d.Metadata["driver"]);
                Assert.Equal("multimedia_record", d.Metadata["document_kind"]);
                Assert.Equal("video", d.Metadata["media_kind"]);
                Assert.Equal("UC_TEST_CHANNEL", d.Metadata["channel_id"]);
            });
        }
        finally
        {
            Environment.SetEnvironmentVariable("YOUTUBE_API_KEY", oldApiKey);
        }
    }

    [Fact]
    public async Task ApiPaginationAdapter_YouTubeDriver_ShouldUseChannelIdFromEnvironment()
    {
        const string apiKey = "yt-key-test";
        const string channelId = "UC_ENV_CHANNEL";
        const string uploadsPlaylistId = "UU_ENV_UPLOADS";

        var responses = new Dictionary<string, HttpResponseMessage>(StringComparer.OrdinalIgnoreCase)
        {
            [YouTubeChannelsUrl(channelId, apiKey)] = Json($$"""
                {
                  "items": [
                    {
                      "contentDetails": {
                        "relatedPlaylists": {
                          "uploads": "{{uploadsPlaylistId}}"
                        }
                      }
                    }
                  ]
                }
                """),
            [YouTubePlaylistUrl(uploadsPlaylistId, apiKey)] = Json("""
                {
                  "items": [
                    {
                      "contentDetails": { "videoId": "vid_env_1" },
                      "snippet": {
                        "title": "Video Env 1",
                        "description": "Description Env 1",
                        "publishedAt": "2026-02-20T10:00:00Z",
                        "channelTitle": "TCU Oficial",
                        "thumbnails": { "high": { "url": "https://img.example/vid_env_1.jpg" } }
                      }
                    }
                  ]
                }
                """)
        };

        var oldApiKey = Environment.GetEnvironmentVariable("YOUTUBE_API_KEY");
        var oldChannelId = Environment.GetEnvironmentVariable("YOUTUBE_CHANNEL_ID");
        Environment.SetEnvironmentVariable("YOUTUBE_API_KEY", apiKey);
        Environment.SetEnvironmentVariable("YOUTUBE_CHANNEL_ID", channelId);

        try
        {
            var client = new HttpClient(new StubHttpHandler(responses));
            var adapter = new ApiPaginationDiscoveryAdapter(client);
            var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
            {
                new StaticUrlDiscoveryAdapter(),
                new UrlPatternDiscoveryAdapter(),
                adapter
            });
            var engine = new DiscoveryEngine(registry);

            using var cfgDoc = JsonDocument.Parse("""
                {
                  "driver": "youtube_channel_v1"
                }
                """);

            var config = new DiscoveryConfig
            {
                Strategy = "api_pagination",
                Extra = cfgDoc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone())
            };

            var discovered = await engine.DiscoverAsync("tcu_youtube_videos", config).ToListAsync();

            Assert.Single(discovered);
            Assert.Equal("https://www.youtube.com/watch?v=vid_env_1", discovered[0].Url);
            Assert.Equal(channelId, discovered[0].Metadata["channel_id"]);
        }
        finally
        {
            Environment.SetEnvironmentVariable("YOUTUBE_API_KEY", oldApiKey);
            Environment.SetEnvironmentVariable("YOUTUBE_CHANNEL_ID", oldChannelId);
        }
    }

    [Fact]
    public async Task ApiPaginationAdapter_YouTubeDriver_ShouldFailExplicitly_WhenApiKeyMissing()
    {
        var oldApiKey = Environment.GetEnvironmentVariable("YOUTUBE_API_KEY");
        Environment.SetEnvironmentVariable("YOUTUBE_API_KEY", null);
        try
        {
            var client = new HttpClient(new StubHttpHandler(new Dictionary<string, HttpResponseMessage>()));
            var adapter = new ApiPaginationDiscoveryAdapter(client);
            var registry = new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
            {
                new StaticUrlDiscoveryAdapter(),
                new UrlPatternDiscoveryAdapter(),
                adapter
            });
            var engine = new DiscoveryEngine(registry);

            using var cfgDoc = JsonDocument.Parse("""
                {
                  "driver": "youtube_channel_v1",
                  "channel_id": "UC_TEST_CHANNEL"
                }
                """);

            var config = new DiscoveryConfig
            {
                Strategy = "api_pagination",
                Extra = cfgDoc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone())
            };

            var ex = await Assert.ThrowsAsync<ArgumentException>(async () =>
            {
                await engine.DiscoverAsync("tcu_youtube_videos", config).ToListAsync();
            });

            Assert.Contains("YOUTUBE_API_KEY", ex.Message, StringComparison.OrdinalIgnoreCase);
        }
        finally
        {
            Environment.SetEnvironmentVariable("YOUTUBE_API_KEY", oldApiKey);
        }
    }

    private static string BtcuPageUrl(int page)
        => BtcuApiTemplate.Replace("{page}", page.ToString(), StringComparison.Ordinal);

    private static string BtcuPdfUrl(long id)
        => BtcuPdfTemplate.Replace("{id}", id.ToString(), StringComparison.Ordinal);

    private static string SenadoYearUrl(string tipo, int year)
        => SenadoApiTemplate
            .Replace("{tipo}", tipo, StringComparison.Ordinal)
            .Replace("{year}", year.ToString(), StringComparison.Ordinal);

    private static string DouDateSectionUrl(string date, string section)
        => DouApiTemplate
            .Replace("{date}", date, StringComparison.Ordinal)
            .Replace("{section}", section, StringComparison.Ordinal);

    private static string YouTubeChannelsUrl(string channelId, string apiKey)
        => YouTubeChannelsApiTemplate
            .Replace("{channelId}", Uri.EscapeDataString(channelId), StringComparison.Ordinal)
            .Replace("{apiKey}", Uri.EscapeDataString(apiKey), StringComparison.Ordinal);

    private static string YouTubePlaylistUrl(string playlistId, string apiKey, string? pageToken = null)
    {
        var baseUrl = YouTubePlaylistApiTemplate
            .Replace("{playlistId}", Uri.EscapeDataString(playlistId), StringComparison.Ordinal)
            .Replace("{apiKey}", Uri.EscapeDataString(apiKey), StringComparison.Ordinal);
        if (!string.IsNullOrWhiteSpace(pageToken))
            baseUrl += "&pageToken=" + Uri.EscapeDataString(pageToken);
        return baseUrl;
    }

    private static DiscoveryConfig BuildBtcuConfig(string tipo, int pageStart = 0, int? maxPages = null)
    {
        var payload = new Dictionary<string, object?>
        {
            ["driver"] = "btcu_api_v1",
            ["endpoint_template"] = BtcuApiTemplate,
            ["pdf_endpoint_template"] = BtcuPdfTemplate,
            ["request_body"] = new Dictionary<string, string> { ["tipo"] = tipo },
            ["page_start"] = pageStart
        };

        if (maxPages.HasValue)
            payload["max_pages"] = maxPages.Value;

        var json = JsonSerializer.Serialize(payload);
        using var doc = JsonDocument.Parse(json);

        return new DiscoveryConfig
        {
            Strategy = "api_pagination",
            Extra = doc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone())
        };
    }

    private static DiscoveryConfig BuildSenadoConfig(string tipo, int startYear, int endYear)
    {
        var payload = new Dictionary<string, object?>
        {
            ["driver"] = "senado_legislacao_api_v1",
            ["endpoint_template"] = SenadoApiTemplate,
            ["tipo"] = tipo
        };

        using var cfgDoc = JsonDocument.Parse(JsonSerializer.Serialize(payload));
        using var paramsDoc = JsonDocument.Parse($$"""
            {
              "start_year": {
                "start": "{{startYear}}",
                "end": "{{endYear}}"
              }
            }
            """);

        return new DiscoveryConfig
        {
            Strategy = "api_pagination",
            Extra = cfgDoc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone()),
            Params = paramsDoc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => (object)p.Value.Clone())
        };
    }

    private static DiscoveryConfig BuildDouConfig(string startDate, string endDate, string[] sections)
    {
        var payload = new Dictionary<string, object?>
        {
            ["driver"] = "dou_inlabs_xml_v1",
            ["endpoint_template"] = DouApiTemplate,
            ["sections"] = sections
        };

        using var cfgDoc = JsonDocument.Parse(JsonSerializer.Serialize(payload));
        using var paramsDoc = JsonDocument.Parse($$"""
            {
              "date_range": {
                "start": "{{startDate}}",
                "end": "{{endDate}}"
              }
            }
            """);

        return new DiscoveryConfig
        {
            Strategy = "api_pagination",
            Extra = cfgDoc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone()),
            Params = paramsDoc.RootElement.EnumerateObject().ToDictionary(p => p.Name, p => (object)p.Value.Clone())
        };
    }

    private static HttpResponseMessage Html(string body)
        => new(HttpStatusCode.OK)
        {
            Content = new StringContent(body, Encoding.UTF8, "text/html")
        };

    private static HttpResponseMessage Json(string body)
        => new(HttpStatusCode.OK)
        {
            Content = new StringContent(body, Encoding.UTF8, "application/json")
        };

    private static HttpResponseMessage Xml(string body)
        => new(HttpStatusCode.OK)
        {
            Content = new StringContent(body, Encoding.UTF8, "application/xml")
        };

    private sealed class StubHttpHandler : HttpMessageHandler
    {
        private readonly IReadOnlyDictionary<string, HttpResponseMessage> _responses;

        public StubHttpHandler(IReadOnlyDictionary<string, HttpResponseMessage> responses)
        {
            _responses = responses;
        }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var key = request.RequestUri?.ToString() ?? string.Empty;
            if (_responses.TryGetValue(key, out var response))
                return Task.FromResult(response);

            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound)
            {
                Content = new StringContent("not found")
            });
        }
    }

    private sealed class RecordingStubHttpHandler : HttpMessageHandler
    {
        private readonly IReadOnlyDictionary<string, HttpResponseMessage> _responses;
        public List<HttpRequestMessage> Requests { get; } = new();

        public RecordingStubHttpHandler(IReadOnlyDictionary<string, HttpResponseMessage> responses)
        {
            _responses = responses;
        }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Requests.Add(request);
            var key = request.RequestUri?.ToString() ?? string.Empty;
            if (_responses.TryGetValue(key, out var response))
                return Task.FromResult(response);

            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound)
            {
                Content = new StringContent("not found")
            });
        }
    }

    private sealed class BtcuStubHttpHandler : HttpMessageHandler
    {
        private readonly IReadOnlyDictionary<string, HttpResponseMessage> _responses;
        public List<HttpRequestMessage> Requests { get; } = new();
        public List<string> Bodies { get; } = new();

        public BtcuStubHttpHandler(IReadOnlyDictionary<string, HttpResponseMessage> responses)
        {
            _responses = responses;
        }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Requests.Add(request);
            Bodies.Add(request.Content is null ? string.Empty : await request.Content.ReadAsStringAsync(cancellationToken));
            var key = request.RequestUri?.ToString() ?? string.Empty;
            if (_responses.TryGetValue(key, out var response))
                return response;

            return new HttpResponseMessage(HttpStatusCode.NotFound)
            {
                Content = new StringContent("not found")
            };
        }
    }

    private sealed class TimeoutStubHttpHandler : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
            => throw new TaskCanceledException("simulated timeout");
    }

    private sealed class BtcuSequenceStubHttpHandler : HttpMessageHandler
    {
        private readonly Dictionary<string, Queue<HttpResponseMessage>> _responses;
        public List<HttpRequestMessage> Requests { get; } = new();

        public BtcuSequenceStubHttpHandler(Dictionary<string, Queue<HttpResponseMessage>> responses)
        {
            _responses = responses;
        }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Requests.Add(request);
            var key = request.RequestUri?.ToString() ?? string.Empty;
            if (_responses.TryGetValue(key, out var queue) && queue.Count > 0)
                return Task.FromResult(queue.Dequeue());

            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound)
            {
                Content = new StringContent("not found")
            });
        }
    }
}
