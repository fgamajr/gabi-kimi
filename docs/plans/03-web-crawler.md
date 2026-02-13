# Plano 03: WebCrawler para Discovery Phase

## Resumo Executivo

Este documento define a arquitetura e implementação do **WebCrawler** para GABI-Sync, responsável por executar a estratégia `web_crawl` na fase de Discovery. O crawler será capaz de navegar páginas do portal TCU, extrair links para PDFs de publicações e notas técnicas, respeitando limites de taxa e deduplicação.

**Fontes Alvo:**
| Source ID | URL Raiz | Estratégia |
|-----------|----------|------------|
| `tcu_publicacoes` | https://portal.tcu.gov.br/publicacoes-institucionais/todas | web_crawl |
| `tcu_notas_tecnicas_ti` | https://portal.tcu.gov.br/tecnologia-da-informacao/notas-tecnicas | web_crawl |

---

## 1. Arquitetura do WebCrawler

### 1.1 Componentes Principais

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         WebCrawlerEngine                                    │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │  RobotsChecker │  │  RateLimiter    │  │  UrlDeduplicator│             │
│  │  (robots.txt)  │  │  (Token Bucket) │  │  (Bloom Filter) │             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
│           └─────────────────────┼─────────────────────┘                    │
│                                 ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                    HttpCrawlerClient                                │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │  │
│  │  │ HttpClient   │  │ AngleSharp   │  │ Playwright   │ (opcional)   │  │
│  │  │ (básico)     │  │ (parsing)    │  │ (JS render)  │              │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                 │                                          │
│                                 ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                   CrawlOrchestrator                                 │  │
│  │     (BFS/DFS traversal, depth control, link extraction)             │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Fluxo de Discovery com WebCrawl

```
sources_v2.yaml (web_crawl config)
         │
         ▼
┌─────────────────────┐
│  DiscoveryEngine    │──► Identifica strategy = web_crawl
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  WebCrawlerEngine   │──► Recebe WebCrawlConfig
│  .CrawlAsync()      │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────────────────────────┐
│  1. Robots.txt check                    │
│  2. Rate limit acquire                  │
│  3. HTTP GET page                       │
│  4. Parse HTML (AngleSharp)             │
│  5. Extract links (CSS selectors)       │
│  6. Filter: depth, dedup, MIME type     │
│  7. Emit DiscoveredSource para assets   │
│  8. Queue novos links para crawl        │
└─────────────────────────────────────────┘
           │
           ▼
   IAsyncEnumerable<DiscoveredSource>
```

---

## 2. Contratos e Configurações

### 2.1 Extensão dos Contratos de Discovery

```csharp
// Gabi.Contracts/Discovery/WebCrawlConfig.cs
namespace Gabi.Contracts.Discovery;

/// <summary>
/// Configuração específica para crawling de páginas web.
/// Mapeia diretamente da seção discovery.config do sources_v2.yaml.
/// </summary>
public record WebCrawlConfig
{
    /// <summary>URL inicial do crawling.</summary>
    public string RootUrl { get; init; } = string.Empty;
    
    /// <summary>Regras de extração e limitação.</summary>
    public WebCrawlRules Rules { get; init; } = new();
    
    /// <summary>Configuração de comportamento do crawler.</summary>
    public CrawlBehavior Behavior { get; init; } = new();
    
    /// <summary>Configuração de User-Agent.</summary>
    public UserAgentConfig UserAgent { get; init; } = new();
}

/// <summary>
/// Regras para extração de links e assets.
/// </summary>
public record WebCrawlRules
{
    /// <summary>Seletor CSS para links de navegação/paginação.</summary>
    public string? PaginationSelector { get; init; }
    
    /// <summary>Nome do parâmetro de página (ex: "pagina").</summary>
    public string? PaginationParam { get; init; }
    
    /// <summary>Seletor CSS para links de detalhe (páginas intermediárias).</summary>
    public string? LinkSelector { get; init; }
    
    /// <summary>Seletor CSS para assets finais (PDFs, etc).</summary>
    public required string AssetSelector { get; init; }
    
    /// <summary>Pattern regex para filtrar URLs (inclusão).</summary>
    public string? IncludePattern { get; init; }
    
    /// <summary>Pattern regex para filtrar URLs (exclusão).</summary>
    public string? ExcludePattern { get; init; }
    
    /// <summary>Profundidade máxima de crawl.</summary>
    public int MaxDepth { get; init; } = 2;
    
    /// <summary>Limite máximo de páginas a visitar.</summary>
    public int? MaxPages { get; init; }
    
    /// <summary>Delay entre requisições em segundos.</summary>
    public double RateLimit { get; init; } = 1.0;
    
    /// <summary>MIME types aceitos para assets.</summary>
    public IReadOnlyList<string> AllowedAssetTypes { get; init; } = 
        new[] { "application/pdf" };
}

/// <summary>
/// Comportamento do crawler.
/// </summary>
public record CrawlBehavior
{
    /// <summary>Respeitar robots.txt.</summary>
    public bool RespectRobotsTxt { get; init; } = true;
    
    /// <summary>Delay adicional entre requisições (ms).</summary>
    public int PoliteDelayMs { get; init; } = 1000;
    
    /// <summary>Timeout de requisição.</summary>
    public TimeSpan RequestTimeout { get; init; } = TimeSpan.FromSeconds(30);
    
    /// <summary>Máximo de retries.</summary>
    public int MaxRetries { get; init; } = 3;
    
    /// <summary>Usar JavaScript rendering quando necessário.</summary>
    public bool EnableJsRendering { get; init; } = false;
    
    /// <summary>UserAgents para rotação.</summary>
    public IReadOnlyList<string>? UserAgentRotation { get; init; }
}

/// <summary>
/// Configuração de User-Agent.
/// </summary>
public record UserAgentConfig
{
    /// <summary>User-Agent padrão.</summary>
    public string Default { get; init; } = "GABI-Sync/2.0 (TCU Data Ingestion; +https://github.com/gabi-sync)";
    
    /// <summary>Rotacionar User-Agents.</summary>
    public bool Rotate { get; init; } = false;
    
    /// <summary>Lista de User-Agents para rotação.</summary>
    public IReadOnlyList<string> Pool { get; init; } = new[]
    {
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    };
}
```

### 2.2 Resultados de Crawl

```csharp
// Gabi.Contracts/Discovery/CrawlResult.cs
namespace Gabi.Contracts.Discovery;

/// <summary>
/// Resultado de uma operação de crawl completa.
/// </summary>
public record CrawlResult
{
    /// <summary>URL raiz.</summary>
    public string RootUrl { get; init; } = string.Empty;
    
    /// <summary>Assets descobertos.</summary>
    public IReadOnlyList<DiscoveredAsset> Assets { get; init; } = new List<DiscoveredAsset>();
    
    /// <summary>Páginas visitadas.</summary>
    public int PagesVisited { get; init; }
    
    /// <summary>Profundidade máxima alcançada.</summary>
    public int MaxDepthReached { get; init; }
    
    /// <summary>Tempo total.</summary>
    public TimeSpan Duration { get; init; }
    
    /// <summary>Erros ocorridos.</summary>
    public IReadOnlyList<CrawlError> Errors { get; init; } = new List<CrawlError>();
}

/// <summary>
/// Asset descoberto (PDF, documento, etc).
/// </summary>
public record DiscoveredAsset
{
    /// <summary>URL do asset.</summary>
    public string Url { get; init; } = string.Empty;
    
    /// <summary>Tipo MIME.</summary>
    public string MimeType { get; init; } = string.Empty;
    
    /// <summary>Título/Descrição extraído.</summary>
    public string? Title { get; init; }
    
    /// <summary>Texto do link.</summary>
    public string? LinkText { get; init; }
    
    /// <summary>Profundidade onde foi encontrado.</summary>
    public int Depth { get; init; }
    
    /// <summary>URL da página onde foi encontrado.</summary>
    public string ParentUrl { get; init; } = string.Empty;
    
    /// <summary>Metadados extras.</summary>
    public IReadOnlyDictionary<string, object> Metadata { get; init; } = 
        new Dictionary<string, object>();
}

/// <summary>
/// Erro durante crawling.
/// </summary>
public record CrawlError
{
    /// <summary>URL onde ocorreu.</summary>
    public string Url { get; init; } = string.Empty;
    
    /// <summary>Mensagem de erro.</summary>
    public string Message { get; init; } = string.Empty;
    
    /// <summary>Tipo de erro.</summary>
    public CrawlErrorType Type { get; init; }
    
    /// <summary>Timestamp.</summary>
    public DateTime Timestamp { get; init; } = DateTime.UtcNow;
}

public enum CrawlErrorType
{
    HttpError,
    ParseError,
    RobotsDisallowed,
    Timeout,
    RateLimited,
    Unknown
}
```

---

## 3. Implementação dos Componentes

### 3.1 RobotsChecker - Conformidade com robots.txt

```csharp
// Gabi.Discover/Crawler/RobotsChecker.cs
using System.Text.RegularExpressions;

namespace Gabi.Discover.Crawler;

/// <summary>
/// Parser e verificador de robots.txt conforme o padrão de 1994.
/// </summary>
public class RobotsChecker
{
    private readonly HttpClient _httpClient;
    private readonly Dictionary<string, RobotsRules> _cache = new();
    private readonly TimeSpan _cacheTtl = TimeSpan.FromHours(1);
    private readonly Dictionary<string, DateTime> _cacheTimestamps = new();
    
    private const string DefaultUserAgent = "*";
    
    public RobotsChecker(HttpClient httpClient)
    {
        _httpClient = httpClient;
    }
    
    /// <summary>
    /// Verifica se uma URL é permitida pelo robots.txt.
    /// </summary>
    public async Task<bool> IsAllowedAsync(string url, string userAgent = "GABI-Sync", CancellationToken ct = default)
    {
        var uri = new Uri(url);
        var robotsUrl = new Uri(uri, "/robots.txt").ToString();
        
        var rules = await GetRulesAsync(robotsUrl, ct);
        return rules.IsAllowed(uri.PathAndQuery, userAgent);
    }
    
    /// <summary>
    /// Obtém o Crawl-delay especificado no robots.txt.
    /// </summary>
    public async Task<double?> GetCrawlDelayAsync(string url, string userAgent = "GABI-Sync", CancellationToken ct = default)
    {
        var uri = new Uri(url);
        var robotsUrl = new Uri(uri, "/robots.txt").ToString();
        
        var rules = await GetRulesAsync(robotsUrl, ct);
        return rules.GetCrawlDelay(userAgent);
    }
    
    private async Task<RobotsRules> GetRulesAsync(string robotsUrl, CancellationToken ct)
    {
        // Cache check
        if (_cache.TryGetValue(robotsUrl, out var cached) && 
            _cacheTimestamps.TryGetValue(robotsUrl, out var timestamp))
        {
            if (DateTime.UtcNow - timestamp < _cacheTtl)
                return cached;
        }
        
        try
        {
            var response = await _httpClient.GetAsync(robotsUrl, ct);
            
            if (response.StatusCode == System.Net.HttpStatusCode.NotFound)
            {
                // Sem robots.txt = tudo permitido
                var allowAll = new RobotsRules();
                CacheRules(robotsUrl, allowAll);
                return allowAll;
            }
            
            response.EnsureSuccessStatusCode();
            var content = await response.Content.ReadAsStringAsync(ct);
            var rules = ParseRobotsTxt(content);
            
            CacheRules(robotsUrl, rules);
            return rules;
        }
        catch
        {
            // Em caso de erro, assume permissivo
            var permissive = new RobotsRules();
            return permissive;
        }
    }
    
    private void CacheRules(string url, RobotsRules rules)
    {
        _cache[url] = rules;
        _cacheTimestamps[url] = DateTime.UtcNow;
    }
    
    private static RobotsRules ParseRobotsTxt(string content)
    {
        var rules = new RobotsRules();
        var lines = content.Split('\n', StringSplitOptions.RemoveEmptyEntries);
        
        string? currentUserAgent = null;
        
        foreach (var rawLine in lines)
        {
            var line = rawLine.Trim();
            
            // Ignora comentários e linhas vazias
            if (string.IsNullOrEmpty(line) || line.StartsWith('#'))
                continue;
            
            // Remove comentários inline
            var commentIndex = line.IndexOf('#');
            if (commentIndex >= 0)
                line = line[..commentIndex].Trim();
            
            if (line.StartsWith("User-agent:", StringComparison.OrdinalIgnoreCase))
            {
                currentUserAgent = line["User-agent:".Length..].Trim();
                rules.EnsureUserAgent(currentUserAgent);
            }
            else if (line.StartsWith("Disallow:", StringComparison.OrdinalIgnoreCase) && currentUserAgent != null)
            {
                var path = line["Disallow:".Length..].Trim();
                rules.AddDisallow(currentUserAgent, path);
            }
            else if (line.StartsWith("Allow:", StringComparison.OrdinalIgnoreCase) && currentUserAgent != null)
            {
                var path = line["Allow:".Length..].Trim();
                rules.AddAllow(currentUserAgent, path);
            }
            else if (line.StartsWith("Crawl-delay:", StringComparison.OrdinalIgnoreCase) && currentUserAgent != null)
            {
                var delayStr = line["Crawl-delay:".Length..].Trim();
                if (double.TryParse(delayStr, out var delay))
                    rules.SetCrawlDelay(currentUserAgent, delay);
            }
            else if (line.StartsWith("Sitemap:", StringComparison.OrdinalIgnoreCase))
            {
                var sitemap = line["Sitemap:".Length..].Trim();
                rules.AddSitemap(sitemap);
            }
        }
        
        return rules;
    }
}

/// <summary>
/// Regras parseadas do robots.txt.
/// </summary>
internal class RobotsRules
{
    private readonly Dictionary<string, UserAgentRules> _rules = new();
    private readonly List<string> _sitemaps = new();
    
    public void EnsureUserAgent(string userAgent)
    {
        if (!_rules.ContainsKey(userAgent))
            _rules[userAgent] = new UserAgentRules();
    }
    
    public void AddDisallow(string userAgent, string path)
    {
        EnsureUserAgent(userAgent);
        _rules[userAgent].DisallowPatterns.Add(path);
    }
    
    public void AddAllow(string userAgent, string path)
    {
        EnsureUserAgent(userAgent);
        _rules[userAgent].AllowPatterns.Add(path);
    }
    
    public void SetCrawlDelay(string userAgent, double delay)
    {
        EnsureUserAgent(userAgent);
        _rules[userAgent].CrawlDelay = delay;
    }
    
    public void AddSitemap(string sitemap)
    {
        _sitemaps.Add(sitemap);
    }
    
    public bool IsAllowed(string path, string userAgent)
    {
        // Primeiro verifica regras específicas
        if (_rules.TryGetValue(userAgent, out var specificRules))
        {
            return IsAllowedByRules(path, specificRules);
        }
        
        // Depois verifica wildcard
        if (_rules.TryGetValue("*", out var defaultRules))
        {
            return IsAllowedByRules(path, defaultRules);
        }
        
        // Sem regras = permitido
        return true;
    }
    
    private static bool IsAllowedByRules(string path, UserAgentRules rules)
    {
        // Verifica allows primeiro (mais específico)
        foreach (var allowPattern in rules.AllowPatterns.OrderByDescending(p => p.Length))
        {
            if (MatchesPattern(path, allowPattern))
                return true;
        }
        
        // Depois verifica disallows
        foreach (var disallowPattern in rules.DisallowPatterns)
        {
            if (MatchesPattern(path, disallowPattern))
                return false;
        }
        
        return true;
    }
    
    private static bool MatchesPattern(string path, string pattern)
    {
        // Conversão simples de padrão robots.txt para regex
        var regex = "^" + Regex.Escape(pattern).Replace("\\*", ".*").Replace("\\$", "$") + ".*$";
        return Regex.IsMatch(path, regex, RegexOptions.IgnoreCase);
    }
    
    public double? GetCrawlDelay(string userAgent)
    {
        if (_rules.TryGetValue(userAgent, out var specific) && specific.CrawlDelay.HasValue)
            return specific.CrawlDelay;
        
        if (_rules.TryGetValue("*", out var defaultRules) && defaultRules.CrawlDelay.HasValue)
            return defaultRules.CrawlDelay;
        
        return null;
    }
}

internal class UserAgentRules
{
    public List<string> DisallowPatterns { get; } = new();
    public List<string> AllowPatterns { get; } = new();
    public double? CrawlDelay { get; set; }
}
```

### 3.2 RateLimiter - Controle de Taxa (Token Bucket)

```csharp
// Gabi.Discover/Crawler/RateLimiter.cs
using System.Threading.Tasks.Dataflow;

namespace Gabi.Discover.Crawler;

/// <summary>
/// Implementação de Token Bucket para rate limiting.
/// </summary>
public class RateLimiter : IDisposable
{
    private readonly BufferBlock<DateTime> _bucket;
    private readonly Timer _refillTimer;
    private readonly double _tokensPerSecond;
    private readonly int _maxTokens;
    private int _currentTokens;
    private readonly SemaphoreSlim _semaphore = new(1, 1);
    private readonly TimeSpan _minDelay;
    private DateTime _lastRequest = DateTime.MinValue;
    
    public RateLimiter(double requestsPerSecond, int burstSize = 1)
    {
        _tokensPerSecond = requestsPerSecond;
        _maxTokens = burstSize;
        _currentTokens = burstSize;
        _minDelay = TimeSpan.FromSeconds(1.0 / requestsPerSecond);
        
        // Timer para reabastecer tokens
        var interval = (int)(1000 / requestsPerSecond);
        _refillTimer = new Timer(RefillTokens, null, interval, interval);
        _bucket = new BufferBlock<DateTime>();
    }
    
    /// <summary>
    /// Aguarda até que um token esteja disponível.
    /// </summary>
    public async Task AcquireAsync(CancellationToken ct = default)
    {
        await _semaphore.WaitAsync(ct);
        try
        {
            // Garante delay mínimo entre requisições
            var timeSinceLastRequest = DateTime.UtcNow - _lastRequest;
            if (timeSinceLastRequest < _minDelay)
            {
                var delay = _minDelay - timeSinceLastRequest;
                await Task.Delay(delay, ct);
            }
            
            // Aguarda token disponível
            while (_currentTokens <= 0)
            {
                _semaphore.Release();
                await Task.Delay(50, ct);
                await _semaphore.WaitAsync(ct);
            }
            
            _currentTokens--;
            _lastRequest = DateTime.UtcNow;
        }
        finally
        {
            _semaphore.Release();
        }
    }
    
    private void RefillTokens(object? state)
    {
        _semaphore.Wait();
        try
        {
            if (_currentTokens < _maxTokens)
                _currentTokens++;
        }
        finally
        {
            _semaphore.Release();
        }
    }
    
    public void Dispose()
    {
        _refillTimer.Dispose();
        _semaphore.Dispose();
    }
}

/// <summary>
/// Rate limiter por domínio.
/// </summary>
public class DomainRateLimiter : IDisposable
{
    private readonly Dictionary<string, RateLimiter> _limiters = new();
    private readonly SemaphoreSlim _semaphore = new(1, 1);
    private readonly double _defaultRequestsPerSecond;
    
    public DomainRateLimiter(double defaultRequestsPerSecond = 1.0)
    {
        _defaultRequestsPerSecond = defaultRequestsPerSecond;
    }
    
    public async Task AcquireAsync(string url, CancellationToken ct = default)
    {
        var domain = new Uri(url).Host;
        
        await _semaphore.WaitAsync(ct);
        try
        {
            if (!_limiters.TryGetValue(domain, out var limiter))
            {
                limiter = new RateLimiter(_defaultRequestsPerSecond);
                _limiters[domain] = limiter;
            }
            
            _semaphore.Release();
            await limiter.AcquireAsync(ct);
        }
        finally
        {
            if (_semaphore.CurrentCount == 0)
                _semaphore.Release();
        }
    }
    
    public void Dispose()
    {
        foreach (var limiter in _limiters.Values)
            limiter.Dispose();
        _semaphore.Dispose();
    }
}
```

### 3.3 UrlDeduplicator - Deduplicação com Bloom Filter

```csharp
// Gabi.Discover/Crawler/UrlDeduplicator.cs
using System.Security.Cryptography;
using System.Text;

namespace Gabi.Discover.Crawler;

/// <summary>
/// Filtro de Bloom para deduplicação eficiente de URLs.
/// </summary>
public class BloomFilter
{
    private readonly BitArray _bits;
    private readonly int _size;
    private readonly int _hashFunctions;
    private readonly object _lock = new();
    
    // Parâmetros ótimos para 1M URLs com 1% de falso positivo
    // m = -n * ln(p) / (ln(2)^2) ≈ 9.6M bits
    // k = m/n * ln(2) ≈ 7 hash functions
    public BloomFilter(int expectedElements = 1_000_000, double falsePositiveRate = 0.01)
    {
        _size = (int)(-expectedElements * Math.Log(falsePositiveRate) / (Math.Log(2) * Math.Log(2)));
        _hashFunctions = (int)((_size / (double)expectedElements) * Math.Log(2));
        _bits = new BitArray(_size);
    }
    
    public void Add(string item)
    {
        var hashes = GetHashes(item);
        
        lock (_lock)
        {
            foreach (var hash in hashes)
                _bits[hash % _size] = true;
        }
    }
    
    public bool MightContain(string item)
    {
        var hashes = GetHashes(item);
        
        lock (_lock)
        {
            foreach (var hash in hashes)
            {
                if (!_bits[hash % _size])
                    return false;
            }
        }
        
        return true;
    }
    
    private int[] GetHashes(string item)
    {
        var hashes = new int[_hashFunctions];
        var bytes = Encoding.UTF8.GetBytes(item);
        
        // Usa dois hashes independentes para gerar k hashes
        var hash1 = MurmurHash3.Hash32(bytes, 0);
        var hash2 = MurmurHash3.Hash32(bytes, 1);
        
        for (int i = 0; i < _hashFunctions; i++)
        {
            hashes[i] = Math.Abs(hash1 + (i * hash2)) % int.MaxValue;
        }
        
        return hashes;
    }
}

/// <summary>
/// Deduplicador de URLs usando Bloom Filter + HashSet para confirmação.
/// </summary>
public class UrlDeduplicator
{
    private readonly BloomFilter _bloom;
    private readonly HashSet<string> _confirmed = new();
    private readonly object _lock = new();
    private long _falsePositives = 0;
    
    public UrlDeduplicator(int expectedUrls = 1_000_000)
    {
        _bloom = new BloomFilter(expectedUrls);
    }
    
    /// <summary>
    /// Verifica se URL já foi vista. Retorna true se é nova.
    /// </summary>
    public bool TryAdd(string url)
    {
        var normalized = NormalizeUrl(url);
        
        // Teste rápido com Bloom Filter
        if (!_bloom.MightContain(normalized))
        {
            // Definitivamente nova
            lock (_lock)
            {
                _bloom.Add(normalized);
                _confirmed.Add(normalized);
            }
            return true;
        }
        
        // Possível falso positivo - verifica no HashSet
        lock (_lock)
        {
            if (_confirmed.Contains(normalized))
            {
                _falsePositives++;
                return false;
            }
            
            _bloom.Add(normalized);
            _confirmed.Add(normalized);
            return true;
        }
    }
    
    /// <summary>
    /// Verifica se URL já foi vista (sem adicionar).
    /// </summary>
    public bool Contains(string url)
    {
        var normalized = NormalizeUrl(url);
        
        if (!_bloom.MightContain(normalized))
            return false;
        
        lock (_lock)
            return _confirmed.Contains(normalized);
    }
    
    public int Count 
    { 
        get 
        { 
            lock (_lock) 
                return _confirmed.Count; 
        } 
    }
    
    public long FalsePositives => Interlocked.Read(ref _falsePositives);
    
    private static string NormalizeUrl(string url)
    {
        var uri = new Uri(url);
        
        // Normaliza: lowercase host, remove fragment, ordena query params
        var builder = new UriBuilder(uri)
        {
            Host = uri.Host.ToLowerInvariant(),
            Fragment = ""
        };
        
        // Ordena query parameters para canonicalização
        if (!string.IsNullOrEmpty(uri.Query))
        {
            var query = System.Web.HttpUtility.ParseQueryString(uri.Query);
            var sorted = query.AllKeys
                .Where(k => k != null)
                .OrderBy(k => k)
                .SelectMany(k => query.GetValues(k!)?.Select(v => $"{k}={v}") ?? Enumerable.Empty<string>());
            builder.Query = string.Join("&", sorted);
        }
        
        return builder.Uri.ToString().TrimEnd('/', '?');
    }
}

/// <summary>
/// Implementação simples de MurmurHash3 para .NET.
/// </summary>
internal static class MurmurHash3
{
    public static int Hash32(byte[] data, uint seed)
    {
        const uint c1 = 0xcc9e2d51;
        const uint c2 = 0x1b873593;
        
        uint h1 = seed;
        uint k1;
        int length = data.Length;
        
        // Processa em blocos de 4 bytes
        for (int i = 0; i < length - 3; i += 4)
        {
            k1 = (uint)(data[i] | (data[i + 1] << 8) | (data[i + 2] << 16) | (data[i + 3] << 24));
            
            k1 *= c1;
            k1 = Rotl32(k1, 15);
            k1 *= c2;
            
            h1 ^= k1;
            h1 = Rotl32(h1, 13);
            h1 = h1 * 5 + 0xe6546b64;
        }
        
        // Processa bytes restantes
        k1 = 0;
        int tail = length - (length % 4);
        switch (length & 3)
        {
            case 3: k1 ^= (uint)(data[tail + 2] << 16); goto case 2;
            case 2: k1 ^= (uint)(data[tail + 1] << 8); goto case 1;
            case 1: k1 ^= data[tail];
                k1 *= c1;
                k1 = Rotl32(k1, 15);
                k1 *= c2;
                h1 ^= k1;
                break;
        }
        
        // Finalização
        h1 ^= (uint)length;
        h1 = Fmix32(h1);
        
        return (int)h1;
    }
    
    private static uint Rotl32(uint x, int r) => (x << r) | (x >> (32 - r));
    
    private static uint Fmix32(uint h)
    {
        h ^= h >> 16;
        h *= 0x85ebca6b;
        h ^= h >> 13;
        h *= 0xc2b2ae35;
        h ^= h >> 16;
        return h;
    }
}
```

### 3.4 HttpCrawlerClient - Cliente HTTP com AngleSharp

```csharp
// Gabi.Discover/Crawler/HttpCrawlerClient.cs
using System.Net;
using System.Text.RegularExpressions;
using AngleSharp;
using AngleSharp.Dom;
using AngleSharp.Io;
using AngleSharp.Io.Network;

namespace Gabi.Discover.Crawler;

/// <summary>
/// Cliente HTTP otimizado para crawling com AngleSharp.
/// </summary>
public class HttpCrawlerClient : IDisposable
{
    private readonly HttpClient _httpClient;
    private readonly IBrowsingContext _browsingContext;
    private readonly DomainRateLimiter _rateLimiter;
    private readonly RobotsChecker _robotsChecker;
    private readonly UrlDeduplicator _urlDeduplicator;
    private readonly CrawlBehavior _behavior;
    private readonly UserAgentConfig _userAgentConfig;
    private int _userAgentIndex = 0;
    
    public HttpCrawlerClient(
        CrawlBehavior behavior,
        UserAgentConfig userAgentConfig,
        DomainRateLimiter rateLimiter,
        RobotsChecker robotsChecker,
        UrlDeduplicator urlDeduplicator)
    {
        _behavior = behavior;
        _userAgentConfig = userAgentConfig;
        _rateLimiter = rateLimiter;
        _robotsChecker = robotsChecker;
        _urlDeduplicator = urlDeduplicator;
        
        // Configura HttpClient
        var handler = new SocketsHttpHandler
        {
            AllowAutoRedirect = true,
            MaxAutomaticRedirections = 5,
            ConnectTimeout = behavior.RequestTimeout,
            PooledConnectionLifetime = TimeSpan.FromMinutes(5),
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate
        };
        
        _httpClient = new HttpClient(handler)
        {
            Timeout = behavior.RequestTimeout.Add(TimeSpan.FromSeconds(10)) // buffer extra
        };
        
        // Configura AngleSharp
        var config = Configuration.Default
            .WithDefaultLoader(new LoaderOptions
            {
                IsResourceLoadingEnabled = false,
                IsNavigationDisabled = true,
                Filter = _ => false // não carrega resources externos
            })
            .WithRequester(new HttpClientRequester(_httpClient));
        
        _browsingContext = BrowsingContext.New(config);
    }
    
    /// <summary>
    /// Busca e parseia uma página.
    /// </summary>
    public async Task<CrawledPage?> FetchPageAsync(string url, int depth, CancellationToken ct = default)
    {
        // Verifica deduplicação
        if (_urlDeduplicator.Contains(url))
            return null;
        
        // Verifica robots.txt
        if (_behavior.RespectRobotsTxt && !await _robotsChecker.IsAllowedAsync(url, ct: ct))
        {
            return new CrawledPage
            {
                Url = url,
                IsAllowed = false,
                Depth = depth,
                Error = "Disallowed by robots.txt"
            };
        }
        
        // Rate limiting
        await _rateLimiter.AcquireAsync(url, ct);
        
        // Delay adicional de politeness
        if (_behavior.PoliteDelayMs > 0)
            await Task.Delay(_behavior.PoliteDelayMs, ct);
        
        // Executa request
        var request = new HttpRequestMessage(HttpMethod.Get, url);
        request.Headers.Add("User-Agent", GetNextUserAgent());
        request.Headers.Add("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8");
        request.Headers.Add("Accept-Language", "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7");
        request.Headers.Add("Accept-Encoding", "gzip, deflate, br");
        request.Headers.Add("Cache-Control", "no-cache");
        
        try
        {
            using var response = await _httpClient.SendAsync(request, ct);
            
            if (!response.IsSuccessStatusCode)
            {
                return new CrawledPage
                {
                    Url = url,
                    StatusCode = (int)response.StatusCode,
                    Depth = depth,
                    Error = $"HTTP {(int)response.StatusCode}: {response.ReasonPhrase}"
                };
            }
            
            var content = await response.Content.ReadAsStringAsync(ct);
            var document = await _browsingContext.OpenAsync(req => req.Content(content), ct);
            
            _urlDeduplicator.TryAdd(url);
            
            return new CrawledPage
            {
                Url = url,
                Document = document,
                Content = content,
                StatusCode = (int)response.StatusCode,
                Depth = depth,
                ContentType = response.Content.Headers.ContentType?.MediaType,
                IsAllowed = true
            };
        }
        catch (TaskCanceledException) when (ct.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception ex)
        {
            return new CrawledPage
            {
                Url = url,
                Depth = depth,
                Error = ex.Message,
                IsAllowed = false
            };
        }
    }
    
    /// <summary>
    /// Extrai links de uma página usando seletores CSS.
    /// </summary>
    public static IEnumerable<ExtractedLink> ExtractLinks(
        IDocument document, 
        string url, 
        WebCrawlRules rules)
    {
        var baseUri = new Uri(url);
        var links = new List<ExtractedLink>();
        
        // Links de navegação/paginação
        if (!string.IsNullOrEmpty(rules.PaginationSelector))
        {
            var paginationLinks = document.QuerySelectorAll(rules.PaginationSelector)
                .Select(e => e.GetAttribute("href"))
                .Where(h => !string.IsNullOrEmpty(h))
                .Select(h => ResolveUrl(h!, baseUri))
                .Where(u => u != null)
                .Select(u => new ExtractedLink
                {
                    Url = u!,
                    Type = LinkType.Navigation,
                    SourceElement = rules.PaginationSelector
                });
            
            links.AddRange(paginationLinks);
        }
        
        // Links de detalhe
        if (!string.IsNullOrEmpty(rules.LinkSelector))
        {
            var detailLinks = document.QuerySelectorAll(rules.LinkSelector)
                .Select(e => new
                {
                    Href = e.GetAttribute("href"),
                    Text = e.TextContent?.Trim()
                })
                .Where(x => !string.IsNullOrEmpty(x.Href))
                .Select(x => new ExtractedLink
                {
                    Url = ResolveUrl(x.Href!, baseUri)!,
                    Type = LinkType.Detail,
                    LinkText = x.Text,
                    SourceElement = rules.LinkSelector
                })
                .Where(l => l.Url != null);
            
            links.AddRange(detailLinks!);
        }
        
        // Assets (PDFs, etc)
        if (!string.IsNullOrEmpty(rules.AssetSelector))
        {
            var assets = document.QuerySelectorAll(rules.AssetSelector)
                .Select(e => new
                {
                    Href = e.GetAttribute("href"),
                    Text = e.TextContent?.Trim(),
                    Title = e.GetAttribute("title")
                })
                .Where(x => !string.IsNullOrEmpty(x.Href))
                .Select(x => new ExtractedLink
                {
                    Url = ResolveUrl(x.Href!, baseUri)!,
                    Type = LinkType.Asset,
                    LinkText = x.Text,
                    Title = x.Title,
                    SourceElement = rules.AssetSelector,
                    MimeType = InferMimeType(x.Href!)
                })
                .Where(l => l.Url != null)
                .Where(l => IsAllowedAssetType(l.MimeType, rules.AllowedAssetTypes));
            
            links.AddRange(assets!);
        }
        
        return links.DistinctBy(l => l.Url);
    }
    
    private string GetNextUserAgent()
    {
        if (!_userAgentConfig.Rotate || _userAgentConfig.Pool.Count == 0)
            return _userAgentConfig.Default;
        
        var index = Interlocked.Increment(ref _userAgentIndex) % _userAgentConfig.Pool.Count;
        return _userAgentConfig.Pool[index];
    }
    
    private static string? ResolveUrl(string href, Uri baseUri)
    {
        if (Uri.TryCreate(baseUri, href, out var resolved))
            return resolved.ToString();
        return null;
    }
    
    private static string InferMimeType(string url)
    {
        var extension = Path.GetExtension(url).ToLowerInvariant();
        return extension switch
        {
            ".pdf" => "application/pdf",
            ".html" or ".htm" => "text/html",
            ".txt" => "text/plain",
            ".doc" => "application/msword",
            ".docx" => "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            _ => "application/octet-stream"
        };
    }
    
    private static bool IsAllowedAssetType(string mimeType, IReadOnlyList<string> allowedTypes)
    {
        if (allowedTypes.Count == 0) return true;
        return allowedTypes.Any(a => mimeType.Contains(a, StringComparison.OrdinalIgnoreCase));
    }
    
    public void Dispose()
    {
        _httpClient.Dispose();
        _browsingContext.Dispose();
    }
}

/// <summary>
/// Página crawlada.
/// </summary>
public class CrawledPage
{
    public string Url { get; init; } = string.Empty;
    public IDocument? Document { get; init; }
    public string? Content { get; init; }
    public int StatusCode { get; init; }
    public int Depth { get; init; }
    public string? ContentType { get; init; }
    public bool IsAllowed { get; init; } = true;
    public string? Error { get; init; }
}

/// <summary>
/// Link extraído.
/// </summary>
public class ExtractedLink
{
    public string Url { get; init; } = string.Empty;
    public LinkType Type { get; init; }
    public string? LinkText { get; init; }
    public string? Title { get; init; }
    public string? MimeType { get; init; }
    public string? SourceElement { get; init; }
}

public enum LinkType
{
    Navigation,
    Detail,
    Asset
}
```

### 3.5 WebCrawlerEngine - Orquestrador Principal

```csharp
// Gabi.Discover/Crawler/WebCrawlerEngine.cs
using System.Collections.Concurrent;
using System.Runtime.CompilerServices;
using Gabi.Contracts.Discovery;

namespace Gabi.Discover.Crawler;

/// <summary>
/// Engine principal de crawling para a fase Discovery.
/// </summary>
public class WebCrawlerEngine
{
    private readonly HttpCrawlerClient _client;
    private readonly ILogger<WebCrawlerEngine>? _logger;
    
    public WebCrawlerEngine(HttpCrawlerClient client, ILogger<WebCrawlerEngine>? logger = null)
    {
        _client = client;
        _logger = logger;
    }
    
    /// <summary>
    /// Executa crawling a partir de uma URL raiz.
    /// </summary>
    public async IAsyncEnumerable<DiscoveredSource> CrawlAsync(
        string sourceId,
        WebCrawlConfig config,
        [EnumeratorCancellation] CancellationToken ct = default)
    {
        var startTime = DateTime.UtcNow;
        var visited = new UrlDeduplicator(config.Behavior.MaxPages ?? 100_000);
        var queue = new ConcurrentQueue<(string Url, int Depth)>();
        var errors = new List<CrawlError>();
        var assetCount = 0;
        int maxDepthReached = 0;
        int pagesVisited = 0;
        
        // Inicia com URL raiz
        queue.Enqueue((config.RootUrl, 0));
        visited.TryAdd(config.RootUrl);
        
        _logger?.LogInformation("Iniciando crawl de {RootUrl} para source {SourceId}", 
            config.RootUrl, sourceId);
        
        while (!queue.IsEmpty && !ct.IsCancellationRequested)
        {
            if (!queue.TryDequeue(out var item))
                continue;
            
            var (url, depth) = item;
            
            // Verifica limite de profundidade
            if (depth > config.Rules.MaxDepth)
                continue;
            
            // Verifica limite de páginas
            if (config.Rules.MaxPages.HasValue && pagesVisited >= config.Rules.MaxPages.Value)
            {
                _logger?.LogWarning("Limite de páginas atingido: {MaxPages}", config.Rules.MaxPages);
                break;
            }
            
            maxDepthReached = Math.Max(maxDepthReached, depth);
            
            _logger?.LogDebug("Visitando {Url} (depth: {Depth})", url, depth);
            
            // Fetch página
            var page = await _client.FetchPageAsync(url, depth, ct);
            
            if (page == null)
                continue; // URL já visitada
            
            pagesVisited++;
            
            if (!string.IsNullOrEmpty(page.Error))
            {
                errors.Add(new CrawlError
                {
                    Url = url,
                    Message = page.Error,
                    Type = CrawlErrorType.Unknown
                });
                continue;
            }
            
            if (page.Document == null)
                continue;
            
            // Extrai links
            var links = HttpCrawlerClient.ExtractLinks(page.Document, url, config.Rules);
            
            foreach (var link in links)
            {
                ct.ThrowIfCancellationRequested();
                
                switch (link.Type)
                {
                    case LinkType.Asset:
                        // Emite asset como DiscoveredSource
                        if (visited.TryAdd(link.Url))
                        {
                            assetCount++;
                            yield return new DiscoveredSource(
                                link.Url,
                                sourceId,
                                new Dictionary<string, object>
                                {
                                    ["title"] = link.Title ?? link.LinkText ?? "",
                                    ["parent_url"] = url,
                                    ["depth"] = depth,
                                    ["mime_type"] = link.MimeType ?? "application/octet-stream"
                                },
                                DateTime.UtcNow
                            );
                        }
                        break;
                    
                    case LinkType.Navigation:
                    case LinkType.Detail:
                        // Adiciona à fila se dentro do limite de profundidade
                        if (depth < config.Rules.MaxDepth && visited.TryAdd(link.Url))
                        {
                            queue.Enqueue((link.Url, depth + 1));
                        }
                        break;
                }
            }
        }
        
        var duration = DateTime.UtcNow - startTime;
        
        _logger?.LogInformation(
            "Crawl finalizado para {SourceId}. Páginas: {Pages}, Assets: {Assets}, " +
            "Profundidade máxima: {MaxDepth}, Duração: {Duration}",
            sourceId, pagesVisited, assetCount, maxDepthReached, duration);
    }
}
```

---

## 4. Integração com DiscoveryEngine

### 4.1 Extensão do DiscoveryEngine

```csharp
// Gabi.Discover/DiscoveryEngine.cs (atualização parcial)
public class DiscoveryEngine : IDiscoveryEngine
{
    private readonly IServiceProvider _serviceProvider;
    private readonly ILogger<DiscoveryEngine> _logger;
    
    public DiscoveryEngine(IServiceProvider serviceProvider, ILogger<DiscoveryEngine> logger)
    {
        _serviceProvider = serviceProvider;
        _logger = logger;
    }
    
    public async IAsyncEnumerable<DiscoveredSource> DiscoverAsync(
        string sourceId,
        DiscoveryConfig config,
        [EnumeratorCancellation] CancellationToken ct = default)
    {
        switch (config.Mode)
        {
            // ... casos existentes ...
            
            case DiscoveryMode.WebCrawl:
                var webCrawlConfig = ParseWebCrawlConfig(config);
                await foreach (var source in CrawlWebAsync(sourceId, webCrawlConfig, ct))
                    yield return source;
                break;
                
            // ... outros casos ...
        }
    }
    
    private async IAsyncEnumerable<DiscoveredSource> CrawlWebAsync(
        string sourceId,
        WebCrawlConfig config,
        [EnumeratorCancellation] CancellationToken ct)
    {
        // Resolva dependências
        var rateLimiter = new DomainRateLimiter(config.Rules.RateLimit);
        var robotsChecker = new RobotsChecker(new HttpClient());
        var deduplicator = new UrlDeduplicator(config.Behavior.MaxPages ?? 100_000);
        
        using var client = new HttpCrawlerClient(
            config.Behavior,
            config.UserAgent,
            rateLimiter,
            robotsChecker,
            deduplicator);
        
        var engine = new WebCrawlerEngine(client, _logger);
        
        await foreach (var source in engine.CrawlAsync(sourceId, config, ct))
            yield return source;
    }
    
    private static WebCrawlConfig ParseWebCrawlConfig(DiscoveryConfig config)
    {
        // Parse da configuração YAML para objeto C#
        var yamlConfig = config.Params?["config"] as Dictionary<string, object>;
        
        return new WebCrawlConfig
        {
            RootUrl = config.Url ?? throw new ArgumentException("URL is required for WebCrawl"),
            Rules = ParseRules(yamlConfig?["rules"] as Dictionary<string, object>),
            Behavior = ParseBehavior(yamlConfig?["behavior"] as Dictionary<string, object>),
            UserAgent = ParseUserAgent(yamlConfig?["user_agent"] as Dictionary<string, object>)
        };
    }
    
    private static WebCrawlRules ParseRules(Dictionary<string, object>? rules)
    {
        if (rules == null) return new WebCrawlRules { AssetSelector = "a[href$='.pdf']" };
        
        return new WebCrawlRules
        {
            PaginationSelector = GetValue<string>(rules, "pagination_selector"),
            PaginationParam = GetValue<string>(rules, "pagination_param"),
            LinkSelector = GetValue<string>(rules, "link_selector"),
            AssetSelector = GetValue<string>(rules, "asset_selector") ?? "a[href$='.pdf']",
            IncludePattern = GetValue<string>(rules, "include_pattern"),
            ExcludePattern = GetValue<string>(rules, "exclude_pattern"),
            MaxDepth = GetValue<int>(rules, "max_depth", 2),
            MaxPages = GetValue<int?>(rules, "max_pages"),
            RateLimit = GetValue<double>(rules, "rate_limit", 1.0),
            AllowedAssetTypes = GetValue<IReadOnlyList<string>>(rules, "allowed_asset_types") 
                ?? new[] { "application/pdf" }
        };
    }
    
    private static CrawlBehavior ParseBehavior(Dictionary<string, object>? behavior)
    {
        if (behavior == null) return new CrawlBehavior();
        
        return new CrawlBehavior
        {
            RespectRobotsTxt = GetValue(behavior, "respect_robots_txt", true),
            PoliteDelayMs = GetValue(behavior, "polite_delay_ms", 1000),
            RequestTimeout = TimeSpan.FromSeconds(GetValue(behavior, "request_timeout_seconds", 30)),
            MaxRetries = GetValue(behavior, "max_retries", 3),
            EnableJsRendering = GetValue(behavior, "enable_js_rendering", false)
        };
    }
    
    private static UserAgentConfig ParseUserAgent(Dictionary<string, object>? ua)
    {
        if (ua == null) return new UserAgentConfig();
        
        return new UserAgentConfig
        {
            Default = GetValue<string>(ua, "default") ?? "GABI-Sync/2.0",
            Rotate = GetValue<bool>(ua, "rotate", false),
            Pool = GetValue<IReadOnlyList<string>>(ua, "pool") ?? new UserAgentConfig().Pool
        };
    }
    
    private static T? GetValue<T>(Dictionary<string, object> dict, string key, T? defaultValue = default)
    {
        if (dict.TryGetValue(key, out var value) && value is T typed)
            return typed;
        return defaultValue;
    }
}
```

---

## 5. JavaScript Rendering (Opcional)

### 5.1 PlaywrightRenderer

```csharp
// Gabi.Discover/Crawler/PlaywrightRenderer.cs
using Microsoft.Playwright;

namespace Gabi.Discover.Crawler;

/// <summary>
/// Renderizador JavaScript usando Playwright.
/// Usado quando sites requerem execução de JS para carregar conteúdo.
/// </summary>
public class PlaywrightRenderer : IAsyncDisposable
{
    private IPlaywright? _playwright;
    private IBrowser? _browser;
    private readonly ILogger<PlaywrightRenderer>? _logger;
    private bool _initialized = false;
    
    public PlaywrightRenderer(ILogger<PlaywrightRenderer>? logger = null)
    {
        _logger = logger;
    }
    
    private async Task EnsureInitializedAsync()
    {
        if (_initialized) return;
        
        _logger?.LogInformation("Inicializando Playwright...");
        
        _playwright = await Playwright.CreateAsync();
        _browser = await _playwright.Chromium.LaunchAsync(new BrowserTypeLaunchOptions
        {
            Headless = true,
            Args = new[] { "--no-sandbox", "--disable-dev-shm-usage" }
        });
        
        _initialized = true;
        _logger?.LogInformation("Playwright inicializado com sucesso");
    }
    
    /// <summary>
    /// Renderiza uma página com JavaScript.
    /// </summary>
    public async Task<string> RenderPageAsync(string url, TimeSpan? waitFor = null, CancellationToken ct = default)
    {
        await EnsureInitializedAsync();
        
        var page = await _browser!.NewPageAsync();
        try
        {
            await page.GotoAsync(url, new PageGotoOptions
            {
                WaitUntil = WaitUntilState.NetworkIdle,
                Timeout = 30000
            });
            
            // Aguarda carregamento adicional se necessário
            if (waitFor.HasValue)
                await Task.Delay(waitFor.Value, ct);
            
            // Aguarda seletores específicos se necessário
            // await page.WaitForSelectorAsync(".content-loaded");
            
            var html = await page.ContentAsync();
            return html;
        }
        finally
        {
            await page.CloseAsync();
        }
    }
    
    public async ValueTask DisposeAsync()
    {
        if (_browser != null)
            await _browser.CloseAsync();
        _playwright?.Dispose();
    }
}
```

### 5.2 Uso Condicional no Crawler

```csharp
// Modificação em HttpCrawlerClient para suportar JS rendering
public class HttpCrawlerClient : IDisposable
{
    private readonly PlaywrightRenderer? _jsRenderer;
    
    public async Task<CrawledPage?> FetchPageAsync(string url, int depth, CancellationToken ct = default)
    {
        // ... código existente ...
        
        // Se JS rendering estiver habilitado e for necessário
        if (_behavior.EnableJsRendering && RequiresJsRendering(url))
        {
            var html = await _jsRenderer!.RenderPageAsync(url, ct: ct);
            var document = await _browsingContext.OpenAsync(req => req.Content(html), ct);
            
            return new CrawledPage
            {
                Url = url,
                Document = document,
                Content = html,
                Depth = depth,
                IsAllowed = true
            };
        }
        
        // ... resto do código ...
    }
    
    private bool RequiresJsRendering(string url)
    {
        // Heurísticas para detectar necessidade de JS:
        // - Presença de frameworks SPA conhecidos
        // - History API
        // - etc.
        // Por padrão, desativado para TCU (sites estáticos)
        return false;
    }
}
```

---

## 6. Configuração no sources_v2.yaml

```yaml
# Configuração completa para fontes com web_crawl
sources:
  tcu_publicacoes:
    identity:
      name: "TCU - Publicações Institucionais"
      description: "Publicações institucionais em PDF do TCU"
      provider: TCU
      domain: legal
      
    discovery:
      strategy: web_crawl
      config:
        root_url: "https://portal.tcu.gov.br/publicacoes-institucionais/todas"
        rules:
          # Seletores CSS para extração
          pagination_selector: "a[href*='pagina='], .pagination a, .nav-next a"
          link_selector: "a[href*='/publicacoes-institucionais/']:not([href$='todas'])"
          asset_selector: "a[href$='.pdf']"
          
          # Limites
          max_depth: 2
          max_pages: 100
          rate_limit: 1.0  # req/s
          
          # Filtros
          allowed_asset_types:
            - "application/pdf"
          
        behavior:
          respect_robots_txt: true
          polite_delay_ms: 1000
          request_timeout_seconds: 30
          max_retries: 3
          enable_js_rendering: false
          
        user_agent:
          default: "GABI-Sync/2.0 (TCU Data Ingestion; +https://github.com/gabi-sync)"
          rotate: false

  tcu_notas_tecnicas_ti:
    identity:
      name: "TCU - Notas Técnicas SEFTI"
      description: "Notas técnicas da Secretaria de Fiscalização de TI"
      
    discovery:
      strategy: web_crawl
      config:
        root_url: "https://portal.tcu.gov.br/tecnologia-da-informacao/notas-tecnicas"
        rules:
          # Página única, apenas extrai PDFs
          asset_selector: "a[href$='.pdf']"
          max_depth: 1
          rate_limit: 0.5  # mais conservador
          
        behavior:
          respect_robots_txt: true
          polite_delay_ms: 2000
```

---

## 7. Testes Unitários

```csharp
// tests/Gabi.Discover.Tests/Crawler/RobotsCheckerTests.cs
using Xunit;
using Gabi.Discover.Crawler;

namespace Gabi.Discover.Tests.Crawler;

public class RobotsCheckerTests
{
    [Fact]
    public void ParseRobotsTxt_AllowsAllWhenNoDisallow()
    {
        var robotsTxt = @"
User-agent: *
Disallow:
";
        var rules = Parse(robotsTxt);
        
        Assert.True(rules.IsAllowed("/", "GABI-Sync"));
        Assert.True(rules.IsAllowed("/public", "GABI-Sync"));
    }
    
    [Fact]
    public void ParseRobotsTxt_RespectsDisallow()
    {
        var robotsTxt = @"
User-agent: *
Disallow: /admin/
Disallow: /private
";
        var rules = Parse(robotsTxt);
        
        Assert.True(rules.IsAllowed("/", "GABI-Sync"));
        Assert.True(rules.IsAllowed("/public", "GABI-Sync"));
        Assert.False(rules.IsAllowed("/admin/", "GABI-Sync"));
        Assert.False(rules.IsAllowed("/admin/users", "GABI-Sync"));
        Assert.False(rules.IsAllowed("/private", "GABI-Sync"));
        Assert.False(rules.IsAllowed("/private/data", "GABI-Sync"));
    }
    
    [Fact]
    public void ParseRobotsTxt_RespectsSpecificUserAgent()
    {
        var robotsTxt = @"
User-agent: BadBot
Disallow: /

User-agent: *
Disallow: /admin
";
        var rules = Parse(robotsTxt);
        
        Assert.False(rules.IsAllowed("/", "BadBot"));
        Assert.True(rules.IsAllowed("/", "GABI-Sync"));
        Assert.False(rules.IsAllowed("/admin", "GABI-Sync"));
    }
    
    private static RobotsRules Parse(string content)
    {
        // Usa reflection ou método internal para teste
        var method = typeof(RobotsChecker).GetMethod("ParseRobotsTxt", 
            System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static);
        return (RobotsRules)method!.Invoke(null, new[] { content })!;
    }
}

// tests/Gabi.Discover.Tests/Crawler/BloomFilterTests.cs
public class BloomFilterTests
{
    [Fact]
    public void BloomFilter_NoFalseNegatives()
    {
        var filter = new BloomFilter(expectedElements: 1000, falsePositiveRate: 0.01);
        var urls = Enumerable.Range(0, 500).Select(i => $"https://example.com/page{i}").ToList();
        
        foreach (var url in urls)
            filter.Add(url);
        
        // Nenhum URL adicionado deve ser reportado como ausente
        foreach (var url in urls)
            Assert.True(filter.MightContain(url), $"URL {url} deveria estar presente");
    }
    
    [Fact]
    public void UrlDeduplicator_NormalizesUrls()
    {
        var dedup = new UrlDeduplicator(expectedUrls: 100);
        
        Assert.True(dedup.TryAdd("https://EXAMPLE.com/Page"));
        Assert.False(dedup.TryAdd("https://example.com/Page")); // já existe
        Assert.False(dedup.TryAdd("https://example.com/Page#section")); // fragment ignora
    }
}
```

---

## 8. Exemplo Completo: Crawling TCU Publicações

```csharp
// Exemplo de uso standalone para crawling de publicações TCU
using Gabi.Discover.Crawler;
using Gabi.Contracts.Discovery;
using Microsoft.Extensions.Logging;

class Program
{
    static async Task Main(string[] args)
    {
        using var loggerFactory = LoggerFactory.Create(builder => builder.AddConsole());
        var logger = loggerFactory.CreateLogger<Program>();
        
        // Configuração para TCU Publicações
        var config = new WebCrawlConfig
        {
            RootUrl = "https://portal.tcu.gov.br/publicacoes-institucionais/todas",
            Rules = new WebCrawlRules
            {
                PaginationSelector = "a[href*='pagina=']",
                LinkSelector = "a[href*='/publicacoes-institucionais/']",
                AssetSelector = "a[href$='.pdf']",
                MaxDepth = 2,
                MaxPages = 50,
                RateLimit = 1.0,
                AllowedAssetTypes = new[] { "application/pdf" }
            },
            Behavior = new CrawlBehavior
            {
                RespectRobotsTxt = true,
                PoliteDelayMs = 1000,
                RequestTimeout = TimeSpan.FromSeconds(30),
                MaxRetries = 3,
                EnableJsRendering = false
            },
            UserAgent = new UserAgentConfig
            {
                Default = "GABI-Sync/2.0 (TCU Data Ingestion)"
            }
        };
        
        // Inicializa componentes
        var httpClient = new HttpClient();
        var rateLimiter = new DomainRateLimiter(config.Rules.RateLimit);
        var robotsChecker = new RobotsChecker(httpClient);
        var deduplicator = new UrlDeduplicator(config.Rules.MaxPages ?? 10_000);
        
        using var crawlerClient = new HttpCrawlerClient(
            config.Behavior,
            config.UserAgent,
            rateLimiter,
            robotsChecker,
            deduplicator);
        
        var engine = new WebCrawlerEngine(crawlerClient, loggerFactory.CreateLogger<WebCrawlerEngine>());
        
        // Executa crawl
        logger.LogInformation("Iniciando crawl de publicações TCU...");
        
        var assets = new List<DiscoveredSource>();
        await foreach (var source in engine.CrawlAsync("tcu_publicacoes", config))
        {
            logger.LogInformation("PDF encontrado: {Url}", source.Url);
            logger.LogInformation("  Título: {Title}", source.Metadata.GetValueOrDefault("title", "N/A"));
            logger.LogInformation("  Profundidade: {Depth}", source.Metadata.GetValueOrDefault("depth", 0));
            
            assets.Add(source);
        }
        
        logger.LogInformation("\n=== RESUMO ===");
        logger.LogInformation("Total de PDFs encontrados: {Count}", assets.Count);
        logger.LogInformation("URLs únicas: {Unique}", deduplicator.Count);
    }
}
```

---

## 9. Dependências NuGet

```xml
<!-- Gabi.Discover.csproj -->
<ItemGroup>
  <!-- AngleSharp para parsing HTML -->
  <PackageReference Include="AngleSharp" Version="1.1.0" />
  <PackageReference Include="AngleSharp.Io" Version="1.0.0" />
  
  <!-- Playwright para JS rendering (opcional) -->
  <PackageReference Include="Microsoft.Playwright" Version="1.41.2" />
  
  <!-- System.Collections para BitArray -->
  <PackageReference Include="System.Collections" Version="4.3.0" />
  
  <!-- System.Threading.Tasks.Dataflow -->
  <PackageReference Include="System.Threading.Tasks.Dataflow" Version="8.0.0" />
</ItemGroup>
```

---

## 10. Considerações de Produção

### 10.1 Checklist de Deploy

- [ ] Verificar conformidade com robots.txt do portal.tcu.gov.br
- [ ] Configurar rate limiting conservador (max 1 req/s)
- [ ] Monitorar métricas: páginas/min, erros/hora, falso positivos no bloom filter
- [ ] Configurar alertas para bloqueios (HTTP 403, captchas)
- [ ] Implementar circuit breaker para falhas consecutivas
- [ ] Configurar retry com backoff exponencial
- [ ] Usar User-Agent identificável com contato

### 10.2 Troubleshooting

| Problema | Causa Provável | Solução |
|----------|---------------|---------|
| HTTP 403 Forbidden | Bloqueio por WAF | Aumentar delay, verificar User-Agent, usar proxy rotativo |
| Timeout frequentes | Servidor lento | Aumentar RequestTimeout, reduzir concorrência |
| Links não encontrados | Seletores CSS desatualizados | Inspecionar página, atualizar seletores |
| PDFs duplicados | URLs com parâmetros diferentes | Normalização mais agressiva no UrlDeduplicator |
| Falsos positivos no Bloom | Capacidade excedida | Aumentar expectedElements ou limpar cache |

---

## 11. Próximos Passos

1. **Implementar contratos** (`WebCrawlConfig`, `CrawlResult`)
2. **Criar componentes core** (`RobotsChecker`, `RateLimiter`, `BloomFilter`)
3. **Implementar `HttpCrawlerClient`** com AngleSharp
4. **Criar `WebCrawlerEngine`**
5. **Integrar com `DiscoveryEngine`**
6. **Adicionar testes unitários**
7. **Criar testes de integração** contra TCU (modo dry-run)
8. **Documentar uso** no AGENTS.md

---

**Document Version:** 1.0  
**Created:** 2024-02-12  
**Status:** Design Ready for Implementation
