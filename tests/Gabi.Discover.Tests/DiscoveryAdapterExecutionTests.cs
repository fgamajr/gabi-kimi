using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using Gabi.Contracts.Discovery;

namespace Gabi.Discover.Tests;

public class DiscoveryAdapterExecutionTests
{
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

    private sealed class TimeoutStubHttpHandler : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
            => throw new TaskCanceledException("simulated timeout");
    }
}
