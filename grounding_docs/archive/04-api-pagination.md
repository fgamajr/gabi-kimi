# Plano 04: API Pagination Consumer Design

## Overview

Design de um consumidor genérico de APIs REST com suporte a paginação para o GABI Sync. Este componente é essencial para integração com a API da Câmara dos Deputados e outras fontes de dados paginadas.

**Status**: Draft  
**Target**: GABI v2.0  
**Priority**: High

---

## 1. Context & Requirements

### 1.1 Current State

O arquivo `sources_v2.yaml` define o source `camara_leis_ordinarias` com estratégia `api_pagination`:

```yaml
camara_leis_ordinarias:
  discovery:
    strategy: api_pagination
    config:
      driver: camara_api_v1
      parameters:
        start_year:
          type: range
          start: 1980
          end: current
```

A implementação atual (`DiscoveryEngine.cs`) lança `NotImplementedException` para `ApiPagination` mode.

### 1.2 Câmara dos Deputados API Analysis

**Base URL**: `https://dadosabertos.camara.leg.br/api/v2`

**Pagination Parameters**:
- `itens`: Quantidade de itens por página (1-100, default: 15)
- `pagina`: Número da página (default: 1)

**Response Structure**:
```json
{
  "dados": [...],
  "links": [
    {"rel": "self", "href": "..."},
    {"rel": "next", "href": "..."},
    {"rel": "previous", "href": "..."},
    {"rel": "first", "href": "..."},
    {"rel": "last", "href": "..."}
  ]
}
```

**Link Relations (HATEOAS)**:
- `self`: URL atual da requisição
- `next`: Próxima página (ausente se for última)
- `previous`: Página anterior (ausente se for primeira)
- `first`: Primeira página
- `last`: Última página

**Rate Limiting**: Não documentado explicitamente, mas práticas recomendadas sugerem ~1 req/s.

### 1.3 Requirements

1. **Generic Design**: Suportar múltiplas APIs, não apenas Câmara dos Deputados
2. **Pagination Strategies**: Offset/limit, cursor-based, page-based
3. **Rate Limiting**: Throttling configurável com token bucket
4. **Authentication**: Bearer tokens, API keys
5. **Response Caching**: Evitar requisições duplicadas
6. **Retry Logic**: Exponential backoff com jitter
7. **Resilience**: Circuit breaker para falhas transitórias

---

## 2. Architecture Design

### 2.1 Component Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    ApiPaginationDiscovery                       │
│                        (Strategy)                               │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │    Driver    │  │  Paginator   │  │   RateLimiter        │   │
│  │   (Factory)  │  │  (Strategy)  │  │  (Token Bucket)      │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
│         │                 │                    │                │
│         ▼                 ▼                    ▼                │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                  ApiHttpClient                           │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │   │
│  │  │  Retry   │ │  Cache   │ │  Circuit │ │  Auth    │    │   │
│  │  │  Policy  │ │  Handler │ │  Breaker │ │ Handler  │    │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Contracts

```csharp
// ============================================================================
// Core Contracts
// ============================================================================

/// <summary>
/// Configuration for API pagination discovery.
/// </summary>
public record ApiPaginationConfig
{
    /// <summary>Driver identifier (e.g., "camara_api_v1").</summary>
    public required string Driver { get; init; }
    
    /// <summary>Query parameters for the API.</summary>
    public IReadOnlyDictionary<string, object> Parameters { get; init; } = 
        new Dictionary<string, object>();
    
    /// <summary>Pagination configuration.</summary>
    public PaginationConfig Pagination { get; init; } = new();
    
    /// <summary>Rate limiting configuration.</summary>
    public RateLimitConfig RateLimit { get; init; } = new();
    
    /// <summary>Authentication configuration.</summary>
    public AuthConfig? Authentication { get; init; }
    
    /// <summary>Retry configuration.</summary>
    public RetryConfig Retry { get; init; } = new();
    
    /// <summary>Cache configuration.</summary>
    public CacheConfig? Cache { get; init; }
}

/// <summary>
/// Pagination configuration.
/// </summary>
public record PaginationConfig
{
    /// <summary>Pagination strategy.</summary>
    public PaginationStrategy Strategy { get; init; } = PaginationStrategy.PageBased;
    
    /// <summary>Items per page (default/max depends on API).</summary>
    public int PageSize { get; init; } = 100;
    
    /// <summary>Maximum number of pages to fetch (null = unlimited).</summary>
    public int? MaxPages { get; init; }
    
    /// <summary>Maximum total items to fetch (null = unlimited).</summary>
    public int? MaxItems { get; init; }
    
    /// <summary>Parameter name for page number (page-based).</summary>
    public string PageParam { get; init; } = "pagina";
    
    /// <summary>Parameter name for items per page (offset/limit).</summary>
    public string ItemsPerPageParam { get; init; } = "itens";
    
    /// <summary>Parameter name for offset (offset/limit).</summary>
    public string OffsetParam { get; init; } = "offset";
    
    /// <summary>Parameter name for cursor (cursor-based).</summary>
    public string CursorParam { get; init; } = "cursor";
    
    /// <summary>Path to data array in response (JSONPath).</summary>
    public string DataPath { get; init; } = "dados";
    
    /// <summary>Path to pagination links in response (JSONPath).</summary>
    public string LinksPath { get; init; } = "links";
    
    /// <summary>Field name for 'next' link in HATEOAS.</summary>
    public string NextLinkRel { get; init; } = "next";
}

/// <summary>
/// Pagination strategies supported.
/// </summary>
public enum PaginationStrategy
{
    /// <summary>Page number based (page=1,2,3).</summary>
    PageBased,
    
    /// <summary>Offset and limit (offset=0,100,200).</summary>
    OffsetLimit,
    
    /// <summary>Cursor/token based (cursor=abc123).</summary>
    CursorBased,
    
    /// <summary>HATEOAS links (follow 'next' link).</summary>
    Hateoas
}

/// <summary>
/// Rate limiting configuration.
/// </summary>
public record RateLimitConfig
{
    /// <summary>Requests per second.</summary>
    public float RequestsPerSecond { get; init; } = 1.0f;
    
    /// <summary>Burst capacity.</summary>
    public int Burst { get; init; } = 1;
    
    /// <summary>Timeout to acquire token.</summary>
    public TimeSpan Timeout { get; init; } = TimeSpan.FromSeconds(30);
}

/// <summary>
/// Authentication configuration.
/// </summary>
public record AuthConfig
{
    /// <summary>Authentication type.</summary>
    public AuthType Type { get; init; } = AuthType.None;
    
    /// <summary>API key or token value.</summary>
    public string? Key { get; init; }
    
    /// <summary>Header name for API key.</summary>
    public string ApiKeyHeader { get; init; } = "X-API-Key";
    
    /// <summary>Query parameter name for API key.</summary>
    public string ApiKeyQueryParam { get; init; } = "api_key";
    
    /// <summary>Token location (header or query).</summary>
    public TokenLocation TokenLocation { get; init; } = TokenLocation.Header;
    
    /// <summary>Token prefix (e.g., "Bearer ").</summary>
    public string TokenPrefix { get; init; } = "Bearer ";
}

/// <summary>
/// Authentication types.
/// </summary>
public enum AuthType
{
    None,
    Bearer,
    ApiKeyHeader,
    ApiKeyQuery,
    Basic
}

/// <summary>
/// Token location.
/// </summary>
public enum TokenLocation
{
    Header,
    Query
}

/// <summary>
/// Retry configuration.
/// </summary>
public record RetryConfig
{
    /// <summary>Maximum retry attempts.</summary>
    public int MaxAttempts { get; init; } = 3;
    
    /// <summary>Initial delay.</summary>
    public TimeSpan InitialDelay { get; init; } = TimeSpan.FromSeconds(1);
    
    /// <summary>Maximum delay.</summary>
    public TimeSpan MaxDelay { get; init; } = TimeSpan.FromSeconds(60);
    
    /// <summary>Backoff multiplier.</summary>
    public double BackoffMultiplier { get; init; } = 2.0;
    
    /// <summary>Use jitter to avoid thundering herd.</summary>
    public bool UseJitter { get; init; } = true;
    
    /// <summary>HTTP status codes to retry.</summary>
    public IReadOnlyList<int> RetryStatusCodes { get; init; } = 
        new[] { 408, 429, 500, 502, 503, 504 };
}

/// <summary>
/// Cache configuration.
/// </summary>
public record CacheConfig
{
    /// <summary>Enable caching.</summary>
    public bool Enabled { get; init; } = true;
    
    /// <summary>Cache duration.</summary>
    public TimeSpan Duration { get; init; } = TimeSpan.FromMinutes(5);
    
    /// <summary>Maximum cache size (items).</summary>
    public int MaxSize { get; init; } = 1000;
}
```

### 2.3 Interfaces

```csharp
/// <summary>
/// Interface for API drivers.
/// </summary>
public interface IApiDriver
{
    /// <summary>Driver identifier.</summary>
    string DriverId { get; }
    
    /// <summary>Base URL for the API.</summary>
    string BaseUrl { get; }
    
    /// <summary>
    /// Builds the initial request URL with parameters.
    /// </summary>
    string BuildInitialUrl(ApiPaginationConfig config);
    
    /// <summary>
    /// Extracts items from API response.
    /// </summary>
    IReadOnlyList<ApiItem> ExtractItems(JsonDocument response);
    
    /// <summary>
    /// Gets the next page URL/info from response.
    /// </summary>
    PaginationCursor? GetNextPage(JsonDocument response, PaginationConfig config);
    
    /// <summary>
    /// Transforms an API item to a DiscoveredSource.
    /// </summary>
    DiscoveredSource TransformItem(ApiItem item);
}

/// <summary>
/// Represents an item from an API response.
/// </summary>
public record ApiItem
{
    /// <summary>Original JSON element.</summary>
    public required JsonElement Data { get; init; }
    
    /// <summary>Unique identifier.</summary>
    public string? Id { get; init; }
    
    /// <summary>Item URL.</summary>
    public string? Url { get; init; }
    
    /// <summary>Extracted metadata.</summary>
    public IReadOnlyDictionary<string, object> Metadata { get; init; } = 
        new Dictionary<string, object>();
}

/// <summary>
/// Pagination cursor for next page.
/// </summary>
public record PaginationCursor
{
    /// <summary>Cursor type.</summary>
    public required CursorType Type { get; init; }
    
    /// <summary>Next page URL (for HATEOAS).</summary>
    public string? NextUrl { get; init; }
    
    /// <summary>Next page number (for page-based).</summary>
    public int? NextPage { get; init; }
    
    /// <summary>Next offset (for offset-based).</summary>
    public int? NextOffset { get; init; }
    
    /// <summary>Cursor token (for cursor-based).</summary>
    public string? Cursor { get; init; }
    
    /// <summary>Whether there are more pages.</summary>
    public bool HasMore { get; init; }
}

public enum CursorType
{
    None,
    Page,
    Offset,
    Cursor,
    Url
}

/// <summary>
/// Interface for paginators.
/// </summary>
public interface IPaginator
{
    /// <summary>
    /// Iterates through all pages asynchronously.
    /// </summary>
    IAsyncEnumerable<ApiPage> PaginateAsync(
        string initialUrl,
        ApiPaginationConfig config,
        IApiHttpClient client,
        CancellationToken ct = default);
}

/// <summary>
/// Represents a page of API results.
/// </summary>
public record ApiPage
{
    /// <summary>Page number (0-based).</summary>
    public required int PageNumber { get; init; }
    
    /// <summary>Items in this page.</summary>
    public required IReadOnlyList<ApiItem> Items { get; init; }
    
    /// <summary>Total items (if available).</summary>
    public int? TotalItems { get; init; }
    
    /// <summary>Response metadata.</summary>
    public IReadOnlyDictionary<string, object> Metadata { get; init; } = 
        new Dictionary<string, object>();
}

/// <summary>
/// Interface for HTTP client with resilience features.
/// </summary>
public interface IApiHttpClient
{
    /// <summary>
    /// Sends GET request with retry and rate limiting.
    /// </summary>
    Task<HttpResponseMessage> GetAsync(
        string url, 
        ApiPaginationConfig config,
        CancellationToken ct = default);
    
    /// <summary>
    /// Sends request with full control.
    /// </summary>
    Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        ApiPaginationConfig config,
        CancellationToken ct = default);
}

/// <summary>
/// Interface for rate limiters.
/// </summary>
public interface IRateLimiter
{
    /// <summary>
    /// Acquires permission to make a request.
    /// </summary>
    Task AcquireAsync(CancellationToken ct = default);
    
    /// <summary>
    /// Tries to acquire without waiting.
    /// </summary>
    bool TryAcquire();
}
```

---

## 3. Implementation

### 3.1 ApiPaginationDiscovery (Strategy)

```csharp
/// <summary>
/// Discovery strategy for API pagination.
/// </summary>
public class ApiPaginationDiscovery : IDiscoveryStrategy
{
    private readonly IApiDriverRegistry _driverRegistry;
    private readonly IApiHttpClient _httpClient;
    private readonly IPaginatorFactory _paginatorFactory;
    private readonly ILogger<ApiPaginationDiscovery> _logger;

    public ApiPaginationDiscovery(
        IApiDriverRegistry driverRegistry,
        IApiHttpClient httpClient,
        IPaginatorFactory paginatorFactory,
        ILogger<ApiPaginationDiscovery> logger)
    {
        _driverRegistry = driverRegistry;
        _httpClient = httpClient;
        _paginatorFactory = paginatorFactory;
        _logger = logger;
    }

    public async IAsyncEnumerable<DiscoveredSource> DiscoverAsync(
        string sourceId,
        DiscoveryConfig config,
        [EnumeratorCancellation] CancellationToken ct = default)
    {
        var apiConfig = ParseConfig(config);
        var driver = _driverRegistry.GetDriver(apiConfig.Driver);
        var paginator = _paginatorFactory.Create(apiConfig.Pagination.Strategy);
        
        var initialUrl = driver.BuildInitialUrl(apiConfig);
        var totalItems = 0;
        var pageCount = 0;
        
        await foreach (var page in paginator.PaginateAsync(initialUrl, apiConfig, _httpClient, ct))
        {
            pageCount++;
            
            foreach (var item in page.Items)
            {
                var source = driver.TransformItem(item);
                yield return source with 
                { 
                    SourceId = sourceId,
                    DiscoveredAt = DateTime.UtcNow 
                };
                
                totalItems++;
            }
            
            // Check limits
            if (apiConfig.Pagination.MaxItems.HasValue && 
                totalItems >= apiConfig.Pagination.MaxItems.Value)
            {
                _logger.LogInformation(
                    "Max items limit ({MaxItems}) reached for {SourceId}",
                    apiConfig.Pagination.MaxItems.Value, sourceId);
                yield break;
            }
            
            if (apiConfig.Pagination.MaxPages.HasValue && 
                pageCount >= apiConfig.Pagination.MaxPages.Value)
            {
                _logger.LogInformation(
                    "Max pages limit ({MaxPages}) reached for {SourceId}",
                    apiConfig.Pagination.MaxPages.Value, sourceId);
                yield break;
            }
        }
        
        _logger.LogInformation(
            "Discovery completed for {SourceId}: {TotalItems} items from {PageCount} pages",
            sourceId, totalItems, pageCount);
    }
    
    private static ApiPaginationConfig ParseConfig(DiscoveryConfig config)
    {
        // Parse from config.Params or config.ApiPagination
        // Implementation details...
        throw new NotImplementedException();
    }
}
```

### 3.2 Paginator Implementations

```csharp
/// <summary>
/// HATEOAS-based paginator (used by Câmara dos Deputados).
/// </summary>
public class HateoasPaginator : IPaginator
{
    public async IAsyncEnumerable<ApiPage> PaginateAsync(
        string initialUrl,
        ApiPaginationConfig config,
        IApiHttpClient client,
        [EnumeratorCancellation] CancellationToken ct = default)
    {
        var currentUrl = initialUrl;
        var pageNumber = 0;
        
        while (!string.IsNullOrEmpty(currentUrl))
        {
            var response = await client.GetAsync(currentUrl, config, ct);
            response.EnsureSuccessStatusCode();
            
            var content = await response.Content.ReadAsStringAsync(ct);
            using var doc = JsonDocument.Parse(content);
            
            var items = ExtractItems(doc, config);
            var nextUrl = ExtractNextUrl(doc, config);
            
            yield return new ApiPage
            {
                PageNumber = pageNumber,
                Items = items,
                TotalItems = ExtractTotalCount(doc)
            };
            
            currentUrl = nextUrl;
            pageNumber++;
        }
    }
    
    private static IReadOnlyList<ApiItem> ExtractItems(JsonDocument doc, ApiPaginationConfig config)
    {
        var items = new List<ApiItem>();
        var dataPath = config.Pagination.DataPath.Split('.');
        
        var element = doc.RootElement;
        foreach (var path in dataPath)
        {
            if (element.TryGetProperty(path, out var child))
            {
                element = child;
            }
            else
            {
                return items;
            }
        }
        
        foreach (var item in element.EnumerateArray())
        {
            items.Add(new ApiItem
            {
                Data = item,
                Id = item.TryGetProperty("id", out var id) ? id.GetString() : null,
                Url = item.TryGetProperty("uri", out var uri) ? uri.GetString() : null
            });
        }
        
        return items;
    }
    
    private static string? ExtractNextUrl(JsonDocument doc, ApiPaginationConfig config)
    {
        var linksPath = config.Pagination.LinksPath.Split('.');
        
        var element = doc.RootElement;
        foreach (var path in linksPath)
        {
            if (element.TryGetProperty(path, out var child))
            {
                element = child;
            }
            else
            {
                return null;
            }
        }
        
        foreach (var link in element.EnumerateArray())
        {
            if (link.TryGetProperty("rel", out var rel) && 
                rel.GetString() == config.Pagination.NextLinkRel &&
                link.TryGetProperty("href", out var href))
            {
                return href.GetString();
            }
        }
        
        return null;
    }
    
    private static int? ExtractTotalCount(JsonDocument doc)
    {
        // Check common patterns for total count
        if (doc.RootElement.TryGetProperty("total", out var total))
        {
            return total.GetInt32();
        }
        return null;
    }
}

/// <summary>
/// Page-based paginator (page=1,2,3...).
/// </summary>
public class PageBasedPaginator : IPaginator
{
    public async IAsyncEnumerable<ApiPage> PaginateAsync(
        string initialUrl,
        ApiPaginationConfig config,
        IApiHttpClient client,
        [EnumeratorCancellation] CancellationToken ct = default)
    {
        var pageNumber = 1;
        var hasMore = true;
        
        var uriBuilder = new UriBuilder(initialUrl);
        var query = HttpUtility.ParseQueryString(uriBuilder.Query);
        query[config.Pagination.ItemsPerPageParam] = config.Pagination.PageSize.ToString();
        
        while (hasMore)
        {
            query[config.Pagination.PageParam] = pageNumber.ToString();
            uriBuilder.Query = query.ToString();
            
            var response = await client.GetAsync(uriBuilder.ToString(), config, ct);
            response.EnsureSuccessStatusCode();
            
            var content = await response.Content.ReadAsStringAsync(ct);
            using var doc = JsonDocument.Parse(content);
            
            var items = ExtractItems(doc, config);
            
            if (items.Count == 0)
            {
                hasMore = false;
            }
            else
            {
                yield return new ApiPage
                {
                    PageNumber = pageNumber - 1,
                    Items = items
                };
                
                pageNumber++;
                hasMore = items.Count >= config.Pagination.PageSize;
            }
        }
    }
    
    // ExtractItems implementation similar to HateoasPaginator
    private static IReadOnlyList<ApiItem> ExtractItems(JsonDocument doc, ApiPaginationConfig config)
    {
        // Implementation...
        throw new NotImplementedException();
    }
}

/// <summary>
/// Offset-based paginator (offset=0,100,200...).
/// </summary>
public class OffsetLimitPaginator : IPaginator
{
    public async IAsyncEnumerable<ApiPage> PaginateAsync(
        string initialUrl,
        ApiPaginationConfig config,
        IApiHttpClient client,
        [EnumeratorCancellation] CancellationToken ct = default)
    {
        var offset = 0;
        var pageNumber = 0;
        var hasMore = true;
        
        var uriBuilder = new UriBuilder(initialUrl);
        var query = HttpUtility.ParseQueryString(uriBuilder.Query);
        query[config.Pagination.ItemsPerPageParam] = config.Pagination.PageSize.ToString();
        
        while (hasMore)
        {
            query[config.Pagination.OffsetParam] = offset.ToString();
            uriBuilder.Query = query.ToString();
            
            var response = await client.GetAsync(uriBuilder.ToString(), config, ct);
            response.EnsureSuccessStatusCode();
            
            var content = await response.Content.ReadAsStringAsync(ct);
            using var doc = JsonDocument.Parse(content);
            
            var items = ExtractItems(doc, config);
            
            if (items.Count == 0)
            {
                hasMore = false;
            }
            else
            {
                yield return new ApiPage
                {
                    PageNumber = pageNumber,
                    Items = items
                };
                
                offset += items.Count;
                pageNumber++;
                hasMore = items.Count >= config.Pagination.PageSize;
            }
        }
    }
    
    private static IReadOnlyList<ApiItem> ExtractItems(JsonDocument doc, ApiPaginationConfig config)
    {
        // Implementation...
        throw new NotImplementedException();
    }
}
```

### 3.3 CamaraAPIDriver

```csharp
/// <summary>
/// Driver for Câmara dos Deputados API v2.
/// </summary>
public class CamaraApiDriver : IApiDriver
{
    public string DriverId => "camara_api_v1";
    public string BaseUrl => "https://dadosabertos.camara.leg.br/api/v2";
    
    private readonly ILogger<CamaraApiDriver> _logger;

    public CamaraApiDriver(ILogger<CamaraApiDriver> logger)
    {
        _logger = logger;
    }

    public string BuildInitialUrl(ApiPaginationConfig config)
    {
        var queryParams = new List<string>();
        
        // Handle year range
        if (config.Parameters.TryGetValue("start_year", out var startYearObj) &&
            startYearObj is JsonElement startYearElem &&
            startYearElem.TryGetInt32(out var startYear))
        {
            // Add year filter
            var endYear = DateTime.UtcNow.Year;
            if (config.Parameters.TryGetValue("end_year", out var endYearObj) &&
                endYearObj is JsonElement endYearElem &&
                endYearElem.TryGetInt32(out var endYearValue))
            {
                endYear = endYearValue;
            }
            
            // For simplicity, start with the first year
            queryParams.Add($"ano={startYear}");
        }
        
        // Handle siglas (bill types)
        var siglas = config.Parameters.TryGetValue("siglas", out var siglasObj)
            ? ParseSiglas(siglasObj)
            : new[] { "PL" }; // Default to Projetos de Lei
            
        if (siglas.Any())
        {
            queryParams.Add($"siglaTipo={siglas.First()}");
        }
        
        // Add pagination params
        queryParams.Add($"itens={config.Pagination.PageSize}");
        queryParams.Add("ordem=DESC");
        queryParams.Add("ordenarPor=id");
        
        var queryString = string.Join("&", queryParams);
        return $"{BaseUrl}/proposicoes?{queryString}";
    }

    public IReadOnlyList<ApiItem> ExtractItems(JsonDocument response)
    {
        var items = new List<ApiItem>();
        
        if (!response.RootElement.TryGetProperty("dados", out var dados))
        {
            return items;
        }
        
        foreach (var prop in dados.EnumerateArray())
        {
            var metadata = new Dictionary<string, object>();
            
            if (prop.TryGetProperty("siglaTipo", out var sigla))
                metadata["siglaTipo"] = sigla.GetString()!;
            if (prop.TryGetProperty("numero", out var numero))
                metadata["numero"] = numero.GetInt32();
            if (prop.TryGetProperty("ano", out var ano))
                metadata["ano"] = ano.GetInt32();
            if (prop.TryGetProperty("ementa", out var ementa))
                metadata["ementa"] = ementa.GetString()?[..Math.Min(200, ementa.GetString()?.Length ?? 0)] ?? "";
            
            items.Add(new ApiItem
            {
                Data = prop,
                Id = prop.TryGetProperty("id", out var id) ? id.GetInt32().ToString() : null,
                Url = prop.TryGetProperty("uri", out var uri) ? uri.GetString() : null,
                Metadata = metadata
            });
        }
        
        return items;
    }

    public PaginationCursor? GetNextPage(JsonDocument response, PaginationConfig config)
    {
        if (!response.RootElement.TryGetProperty("links", out var links))
        {
            return null;
        }
        
        foreach (var link in links.EnumerateArray())
        {
            if (link.TryGetProperty("rel", out var rel) && 
                rel.GetString() == "next" &&
                link.TryGetProperty("href", out var href))
            {
                return new PaginationCursor
                {
                    Type = CursorType.Url,
                    NextUrl = href.GetString(),
                    HasMore = true
                };
            }
        }
        
        return new PaginationCursor { Type = CursorType.None, HasMore = false };
    }

    public DiscoveredSource TransformItem(ApiItem item)
    {
        var url = item.Url ?? throw new InvalidOperationException("Item URL is required");
        var id = item.Id ?? Guid.NewGuid().ToString();
        
        // Extract year and number for document ID
        var year = item.Metadata.TryGetValue("ano", out var anoObj) ? (int)anoObj : 0;
        var number = item.Metadata.TryGetValue("numero", out var numObj) ? numObj.ToString() : "0";
        
        return new DiscoveredSource(
            Url: url,
            SourceId: $"camara_lei_{id}",
            Metadata: new Dictionary<string, object>(item.Metadata)
            {
                ["document_id"] = $"lei-{number}/{year}",
                ["title"] = $"Lei nº {number}/{year}",
                ["year"] = year,
                ["number"] = number
            },
            DiscoveredAt: DateTime.UtcNow
        );
    }
    
    private static string[] ParseSiglas(object siglasObj)
    {
        if (siglasObj is JsonElement elem)
        {
            if (elem.ValueKind == JsonValueKind.Array)
            {
                return elem.EnumerateArray()
                    .Select(e => e.GetString())
                    .Where(s => s != null)
                    .Cast<string>()
                    .ToArray();
            }
            if (elem.ValueKind == JsonValueKind.String)
            {
                return new[] { elem.GetString()! };
            }
        }
        return Array.Empty<string>();
    }
}
```

### 3.4 Resilient HTTP Client

```csharp
/// <summary>
/// HTTP client with retry, rate limiting, caching, and circuit breaker.
/// </summary>
public class ResilientApiHttpClient : IApiHttpClient, IDisposable
{
    private readonly HttpClient _httpClient;
    private readonly IRateLimiter _rateLimiter;
    private readonly IResponseCache? _cache;
    private readonly ILogger<ResilientApiHttpClient> _logger;
    private readonly Random _jitter = new();

    public ResilientApiHttpClient(
        HttpClient httpClient,
        IRateLimiter rateLimiter,
        IResponseCache? cache,
        ILogger<ResilientApiHttpClient> logger)
    {
        _httpClient = httpClient;
        _rateLimiter = rateLimiter;
        _cache = cache;
        _logger = logger;
    }

    public async Task<HttpResponseMessage> GetAsync(
        string url, 
        ApiPaginationConfig config,
        CancellationToken ct = default)
    {
        var request = new HttpRequestMessage(HttpMethod.Get, url);
        return await SendAsync(request, config, ct);
    }

    public async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        ApiPaginationConfig config,
        CancellationToken ct = default)
    {
        // Check cache for GET requests
        if (request.Method == HttpMethod.Get && _cache != null && config.Cache?.Enabled == true)
        {
            var cacheKey = ComputeCacheKey(request);
            var cached = await _cache.GetAsync(cacheKey, ct);
            if (cached != null)
            {
                _logger.LogDebug("Cache hit for {Url}", request.RequestUri);
                return new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent(cached)
                };
            }
        }
        
        // Apply authentication
        ApplyAuthentication(request, config.Authentication);
        
        // Execute with retry
        var attempt = 0;
        var delay = config.Retry.InitialDelay;
        
        while (true)
        {
            // Acquire rate limit token
            await _rateLimiter.AcquireAsync(ct);
            
            try
            {
                var response = await _httpClient.SendAsync(request, ct);
                
                if (response.IsSuccessStatusCode)
                {
                    // Cache successful GET responses
                    if (request.Method == HttpMethod.Get && _cache != null && config.Cache?.Enabled == true)
                    {
                        var content = await response.Content.ReadAsStringAsync(ct);
                        await _cache.SetAsync(ComputeCacheKey(request), content, config.Cache.Duration, ct);
                        
                        // Return new response with cached content
                        return new HttpResponseMessage(response.StatusCode)
                        {
                            Content = new StringContent(content)
                        };
                    }
                    
                    return response;
                }
                
                // Check if should retry
                if (!ShouldRetry(response.StatusCode, config.Retry) || 
                    attempt >= config.Retry.MaxAttempts)
                {
                    return response;
                }
                
                _logger.LogWarning(
                    "Request to {Url} failed with {StatusCode}, attempt {Attempt}/{MaxAttempts}",
                    request.RequestUri, response.StatusCode, attempt + 1, config.Retry.MaxAttempts);
                
            }
            catch (HttpRequestException ex) when (attempt < config.Retry.MaxAttempts)
            {
                _logger.LogWarning(
                    "Request to {Url} failed with exception: {Message}, attempt {Attempt}/{MaxAttempts}",
                    request.RequestUri, ex.Message, attempt + 1, config.Retry.MaxAttempts);
            }
            
            // Calculate delay with jitter
            var jitteredDelay = config.Retry.UseJitter 
                ? delay.Add(TimeSpan.FromMilliseconds(_jitter.Next(0, 1000)))
                : delay;
            
            _logger.LogDebug("Waiting {DelayMs}ms before retry", jitteredDelay.TotalMilliseconds);
            await Task.Delay(jitteredDelay, ct);
            
            // Exponential backoff
            delay = TimeSpan.FromTicks(
                Math.Min(
                    (long)(delay.Ticks * config.Retry.BackoffMultiplier),
                    config.Retry.MaxDelay.Ticks));
            
            attempt++;
            
            // Clone request for retry
            if (request.Content != null)
            {
                // Need to dispose and recreate for retry
            }
        }
    }
    
    private static void ApplyAuthentication(HttpRequestMessage request, AuthConfig? auth)
    {
        if (auth == null) return;
        
        switch (auth.Type)
        {
            case AuthType.Bearer:
                request.Headers.Authorization = 
                    new AuthenticationHeaderValue("Bearer", auth.Key);
                break;
                
            case AuthType.ApiKeyHeader:
                request.Headers.Add(auth.ApiKeyHeader, auth.Key);
                break;
                
            case AuthType.ApiKeyQuery:
                var uri = new UriBuilder(request.RequestUri!);
                var query = HttpUtility.ParseQueryString(uri.Query);
                query[auth.ApiKeyQueryParam] = auth.Key;
                uri.Query = query.ToString();
                request.RequestUri = uri.Uri;
                break;
                
            case AuthType.Basic:
                // Implementation for basic auth
                break;
        }
    }
    
    private static bool ShouldRetry(HttpStatusCode statusCode, RetryConfig config)
    {
        return config.RetryStatusCodes.Contains((int)statusCode);
    }
    
    private static string ComputeCacheKey(HttpRequestMessage request)
    {
        return $"api:{request.Method}:{request.RequestUri}";
    }
    
    public void Dispose()
    {
        _httpClient?.Dispose();
    }
}

/// <summary>
/// Token bucket rate limiter.
/// </summary>
public class TokenBucketRateLimiter : IRateLimiter
{
    private readonly float _rate;
    private readonly int _burst;
    private readonly TimeSpan _timeout;
    private float _tokens;
    private DateTime _lastUpdate;
    private readonly SemaphoreSlim _lock = new(1, 1);

    public TokenBucketRateLimiter(RateLimitConfig config)
    {
        _rate = config.RequestsPerSecond;
        _burst = config.Burst;
        _timeout = config.Timeout;
        _tokens = config.Burst;
        _lastUpdate = DateTime.UtcNow;
    }

    public async Task AcquireAsync(CancellationToken ct = default)
    {
        await _lock.WaitAsync(_timeout, ct);
        try
        {
            var now = DateTime.UtcNow;
            var elapsed = (now - _lastUpdate).TotalSeconds;
            _tokens = Math.Min(_burst, _tokens + (float)(elapsed * _rate));
            _lastUpdate = now;
            
            if (_tokens < 1)
            {
                var waitTime = (1 - _tokens) / _rate;
                _lock.Release();
                await Task.Delay(TimeSpan.FromSeconds(waitTime), ct);
                await AcquireAsync(ct); // Recurse to retry
                return;
            }
            
            _tokens -= 1;
        }
        finally
        {
            if (_lock.CurrentCount == 0)
            {
                _lock.Release();
            }
        }
    }

    public bool TryAcquire()
    {
        if (!_lock.Wait(0))
            return false;
        
        try
        {
            var now = DateTime.UtcNow;
            var elapsed = (now - _lastUpdate).TotalSeconds;
            _tokens = Math.Min(_burst, _tokens + (float)(elapsed * _rate));
            _lastUpdate = now;
            
            if (_tokens < 1)
                return false;
            
            _tokens -= 1;
            return true;
        }
        finally
        {
            _lock.Release();
        }
    }
}

/// <summary>
/// Simple in-memory response cache.
/// </summary>
public class InMemoryResponseCache : IResponseCache
{
    private readonly IMemoryCache _cache;
    private readonly ILogger<InMemoryResponseCache> _logger;

    public InMemoryResponseCache(CacheConfig config, ILogger<InMemoryResponseCache> logger)
    {
        _logger = logger;
        _cache = new MemoryCache(new MemoryCacheOptions
        {
            SizeLimit = config.MaxSize
        });
    }

    public Task<string?> GetAsync(string key, CancellationToken ct = default)
    {
        _cache.TryGetValue(key, out string? value);
        return Task.FromResult(value);
    }

    public Task SetAsync(string key, string value, TimeSpan duration, CancellationToken ct = default)
    {
        var options = new MemoryCacheEntryOptions()
            .SetAbsoluteExpiration(duration)
            .SetSize(1);
        
        _cache.Set(key, value, options);
        return Task.CompletedTask;
    }
}
```

---

## 4. Dependency Injection & Registration

```csharp
/// <summary>
/// Extension methods for DI registration.
/// </summary>
public static class ApiPaginationExtensions
{
    public static IServiceCollection AddApiPagination(
        this IServiceCollection services,
        Action<ApiPaginationOptions>? configure = null)
    {
        var options = new ApiPaginationOptions();
        configure?.Invoke(options);
        
        // Register core services
        services.AddSingleton<IApiDriverRegistry, ApiDriverRegistry>();
        services.AddSingleton<IPaginatorFactory, PaginatorFactory>();
        services.AddSingleton<IRateLimiter>(sp => 
            new TokenBucketRateLimiter(new RateLimitConfig()));
        
        // Register HTTP client with resilience
        services.AddHttpClient<IApiHttpClient, ResilientApiHttpClient>(client =>
        {
            client.DefaultRequestHeaders.Add(
                "User-Agent", 
                options.UserAgent ?? "GABI-Sync/2.0");
            client.Timeout = options.DefaultTimeout;
        });
        
        // Register cache if enabled
        if (options.EnableCache)
        {
            services.AddSingleton<IResponseCache, InMemoryResponseCache>();
        }
        else
        {
            services.AddSingleton<IResponseCache, NullResponseCache>();
        }
        
        // Register default drivers
        services.AddSingleton<IApiDriver, CamaraApiDriver>();
        
        return services;
    }
    
    public static IServiceCollection AddApiDriver<T>(this IServiceCollection services) 
        where T : class, IApiDriver
    {
        services.AddSingleton<IApiDriver, T>();
        return services;
    }
}

/// <summary>
/// Configuration options for API pagination.
/// </summary>
public class ApiPaginationOptions
{
    public string? UserAgent { get; set; }
    public TimeSpan DefaultTimeout { get; set; } = TimeSpan.FromSeconds(30);
    public bool EnableCache { get; set; } = true;
}

/// <summary>
/// Driver registry implementation.
/// </summary>
public class ApiDriverRegistry : IApiDriverRegistry
{
    private readonly IReadOnlyDictionary<string, IApiDriver> _drivers;

    public ApiDriverRegistry(IEnumerable<IApiDriver> drivers)
    {
        _drivers = drivers.ToDictionary(d => d.DriverId);
    }

    public IApiDriver GetDriver(string driverId)
    {
        if (!_drivers.TryGetValue(driverId, out var driver))
        {
            throw new ArgumentException($"Driver not found: {driverId}", nameof(driverId));
        }
        return driver;
    }

    public bool HasDriver(string driverId) => _drivers.ContainsKey(driverId);
}

/// <summary>
/// Paginator factory.
/// </summary>
public class PaginatorFactory : IPaginatorFactory
{
    private readonly IServiceProvider _serviceProvider;

    public PaginatorFactory(IServiceProvider serviceProvider)
    {
        _serviceProvider = serviceProvider;
    }

    public IPaginator Create(PaginationStrategy strategy)
    {
        return strategy switch
        {
            PaginationStrategy.PageBased => new PageBasedPaginator(),
            PaginationStrategy.OffsetLimit => new OffsetLimitPaginator(),
            PaginationStrategy.Hateoas => new HateoasPaginator(),
            PaginationStrategy.CursorBased => new CursorBasedPaginator(),
            _ => throw new ArgumentException($"Unknown strategy: {strategy}")
        };
    }
}
```

---

## 5. Integration with sources_v2.yaml

### 5.1 Updated Configuration

```yaml
camara_leis_ordinarias:
  identity:
    name: "Câmara dos Deputados - Leis Ordinárias"
    description: "Leis ordinárias da Câmara dos Deputados (1980-current)"
    provider: CAMARA
    domain: legal
    jurisdiction: BR
    category: legislation
    canonical_type: legislation

  discovery:
    strategy: api_pagination
    config:
      driver: camara_api_v1
      parameters:
        start_year:
          type: range
          start: 1980
          end: current
        siglas: ["PL", "PEC", "MPV"]  # Tipos de proposições
      
      pagination:
        strategy: hateoas          # Usar links HATEOAS
        page_size: 100             # Máximo por página
        max_pages: null            # Sem limite de páginas
        max_items: null            # Sem limite de itens
        data_path: "dados"         # Caminho para dados
        links_path: "links"        # Caminho para links
        next_link_rel: "next"      # Rel do link next
      
      rate_limit:
        requests_per_second: 1.0   # 1 req/s para respeitar API
        burst: 1
        timeout: 30s
      
      retry:
        max_attempts: 3
        initial_delay: 1s
        max_delay: 60s
        backoff_multiplier: 2.0
        use_jitter: true
        retry_status_codes: [408, 429, 500, 502, 503, 504]
      
      cache:
        enabled: true
        duration: 5m
        max_size: 1000

  fetch:
    protocol: https
    method: GET
    format:
      type: json
    timeout: 30s

  parse:
    strategy: api_response
    fields:
      document_id:
        source: metadata.document_id
        required: true
      title:
        source: metadata.title
        required: true
      year:
        source: metadata.year
        transforms: [parse_int]
      number:
        source: metadata.number
      content:
        source: api_content_fetch  # Requer fetch adicional
        required: true
      metadata:
        ementa: {source: metadata.ementa}
        sigla_tipo: {source: metadata.siglaTipo}

  pipeline:
    enabled: true
    schedule: "0 7 * * 0"  # Weekly on Sunday
    mode: incremental
```

---

## 6. Testing Strategy

### 6.1 Unit Tests

```csharp
public class ApiPaginationTests
{
    [Fact]
    public async Task HateoasPaginator_FollowsNextLinks()
    {
        // Arrange
        var httpClient = Substitute.For<IApiHttpClient>();
        var config = new ApiPaginationConfig
        {
            Pagination = new PaginationConfig { Strategy = PaginationStrategy.Hateoas }
        };
        
        // Setup mock responses
        var page1 = CreateResponse(new[] { "item1", "item2" }, "http://api/page2");
        var page2 = CreateResponse(new[] { "item3" }, null);
        
        httpClient.GetAsync("http://api/start", config, Arg.Any<CancellationToken>())
            .Returns(page1);
        httpClient.GetAsync("http://api/page2", config, Arg.Any<CancellationToken>())
            .Returns(page2);
        
        var paginator = new HateoasPaginator();
        
        // Act
        var pages = await paginator.PaginateAsync("http://api/start", config, httpClient)
            .ToListAsync();
        
        // Assert
        Assert.Equal(2, pages.Count);
        Assert.Equal(2, pages[0].Items.Count);
        Assert.Equal(1, pages[1].Items.Count);
    }
    
    [Fact]
    public async Task TokenBucketRateLimiter_RespectsRate()
    {
        // Arrange
        var config = new RateLimitConfig 
        { 
            RequestsPerSecond = 2.0f, 
            Burst = 1 
        };
        var limiter = new TokenBucketRateLimiter(config);
        
        // Act
        var sw = Stopwatch.StartNew();
        await limiter.AcquireAsync();
        await limiter.AcquireAsync();
        sw.Stop();
        
        // Assert - should take at least 500ms between requests
        Assert.True(sw.ElapsedMilliseconds >= 400);
    }
    
    [Fact]
    public async Task ResilientHttpClient_RetriesOnFailure()
    {
        // Arrange
        var innerClient = Substitute.For<HttpClient>();
        var rateLimiter = Substitute.For<IRateLimiter>();
        var logger = Substitute.For<ILogger<ResilientApiHttpClient>>();
        
        var config = new ApiPaginationConfig
        {
            Retry = new RetryConfig 
            { 
                MaxAttempts = 3,
                InitialDelay = TimeSpan.FromMilliseconds(10),
                RetryStatusCodes = new[] { 503 }
            }
        };
        
        // Setup failing then success
        var calls = 0;
        var handler = new TestHttpMessageHandler(request =>
        {
            calls++;
            return calls < 3 
                ? new HttpResponseMessage(HttpStatusCode.ServiceUnavailable)
                : new HttpResponseMessage(HttpStatusCode.OK);
        });
        
        var client = new HttpClient(handler);
        var resilientClient = new ResilientApiHttpClient(
            client, rateLimiter, null, logger);
        
        // Act
        var response = await resilientClient.GetAsync("http://test", config);
        
        // Assert
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal(3, calls);
    }
}
```

### 6.2 Integration Tests

```csharp
public class CamaraApiIntegrationTests : IAsyncLifetime
{
    private readonly CamaraApiDriver _driver;
    private readonly ResilientApiHttpClient _httpClient;

    [Fact(Skip = "Requires network access")]
    public async Task Discover_RealApi_ReturnsProposicoes()
    {
        // Arrange
        var config = new ApiPaginationConfig
        {
            Parameters = new Dictionary<string, object>
            {
                ["start_year"] = JsonDocument.Parse("2024").RootElement,
                ["siglas"] = JsonDocument.Parse("[\"PL\"]").RootElement
            },
            Pagination = new PaginationConfig 
            { 
                PageSize = 10,
                MaxPages = 1  // Limit for test
            },
            RateLimit = new RateLimitConfig { RequestsPerSecond = 1.0f }
        };
        
        // Act
        var url = _driver.BuildInitialUrl(config);
        var response = await _httpClient.GetAsync(url, config);
        var content = await response.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(content);
        var items = _driver.ExtractItems(doc);
        
        // Assert
        Assert.True(items.Count > 0);
        Assert.All(items, item =>
        {
            Assert.NotNull(item.Id);
            Assert.NotNull(item.Url);
            Assert.True(item.Metadata.ContainsKey("siglaTipo"));
        });
    }
}
```

---

## 7. Deployment & Configuration

### 7.1 appsettings.json

```json
{
  "ApiPagination": {
    "UserAgent": "GABI-Sync/2.0 (Legal Data Ingestion)",
    "DefaultTimeout": "00:00:30",
    "EnableCache": true,
    "Drivers": {
      "camara_api_v1": {
        "BaseUrl": "https://dadosabertos.camara.leg.br/api/v2",
        "RateLimit": {
          "RequestsPerSecond": 1.0,
          "Burst": 1
        }
      }
    }
  }
}
```

---

## 8. Migration Path

### 8.1 From Python Implementation

| Python (Legacy) | C# (New) |
|-----------------|----------|
|`APIQueryDiscovery`|`ApiPaginationDiscovery`|
|`CamaraAPIDriver`|`CamaraApiDriver`|
|`RateLimiter`|`TokenBucketRateLimiter`|
|`httpx.AsyncClient`|`IApiHttpClient` / `HttpClient`|
|`backoff`|`ResilientApiHttpClient` (built-in)|

### 8.2 Phase 1: Core Implementation
1. Implement `ApiPaginationConfig` and contracts
2. Implement `HateoasPaginator` (for Câmara dos Deputados)
3. Implement `CamaraApiDriver`
4. Implement `TokenBucketRateLimiter`
5. Implement `ResilientApiHttpClient`

### 8.3 Phase 2: Integration
1. Update `DiscoveryEngine` to support `ApiPagination` mode
2. Add DI registration extensions
3. Add configuration binding from YAML
4. Write unit and integration tests

### 8.4 Phase 3: Deployment
1. Deploy to staging environment
2. Run discovery for `camara_leis_ordinarias`
3. Monitor rate limits and performance
4. Production rollout

---

## 9. Future Enhancements

1. **Webhook Support**: Para APIs que suportam webhooks de notificação
2. **GraphQL Support**: Adaptador para APIs GraphQL com pagination
3. **Distributed Cache**: Redis para cache distribuído
4. **Metrics**: Prometheus metrics para rate limiting, retries, cache hits
5. **Circuit Breaker**: Polly integration para circuit breaker pattern
6. **OAuth2**: Suporte completo a OAuth2 com refresh tokens

---

## 10. References

- [Câmara dos Deputados API Docs](https://dadosabertos.camara.leg.br/swagger/api.html)
- [HATEOAS - RESTful API Design](https://restfulapi.net/hateoas/)
- [RFC 5988 - Web Linking](https://tools.ietf.org/html/rfc5988)
- [Token Bucket Algorithm](https://en.wikipedia.org/wiki/Token_bucket)
