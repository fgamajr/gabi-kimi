using System.Text.Json.Serialization;

namespace Gabi.Contracts.Discovery;

/// <summary>
/// Estratégias de descoberta suportadas.
/// </summary>
public enum DiscoveryStrategy
{
    /// <summary>URL estático único.</summary>
    StaticUrl,
    
    /// <summary>Padrão de URL com parâmetros (ex: {year}).</summary>
    UrlPattern,
    
    /// <summary>Crawling de página web.</summary>
    WebCrawl,
    
    /// <summary>API REST paginada.</summary>
    ApiPagination
}

/// <summary>
/// Configuração de detecção de mudanças.
/// </summary>
public record ChangeDetectionConfig
{
    /// <summary>Método de detecção: etag, last_modified, content_hash.</summary>
    public string Method { get; init; } = "etag";
    
    /// <summary>Headers HTTP para fingerprint.</summary>
    public IReadOnlyList<string> FingerprintHeaders { get; init; } = 
        new[] { "etag", "last-modified", "content-length" };
}

/// <summary>
/// Configuração de estratégia de URL pattern.
/// </summary>
public record UrlPatternConfig
{
    /// <summary>Template de URL com placeholders (ex: {year}).</summary>
    public string Template { get; init; } = string.Empty;
    
    /// <summary>Parâmetros do template (legacy - use YearRange for simple year patterns).</summary>
    public IReadOnlyDictionary<string, ParameterRange>? Parameters { get; init; }
    
    /// <summary>Year range for year-based URL patterns.</summary>
    public RangeParameter? YearRange { get; init; }
}

/// <summary>
/// Range de parâmetro para URL pattern.
/// Aceita número (int) ou "current" para ano atual.
/// </summary>
public record ParameterRangeEnd
{
    private readonly object? _value;
    
    public ParameterRangeEnd()
    {
        _value = "current";
    }
    
    public ParameterRangeEnd(int value)
    {
        _value = value;
    }
    
    public ParameterRangeEnd(string value)
    {
        if (value != "current")
            throw new ArgumentException("String value must be 'current'", nameof(value));
        _value = value;
    }
    
    /// <summary>Retorna true se é "current".</summary>
    public bool IsCurrent => _value is string s && s == "current";
    
    /// <summary>Retorna o valor numérico (ou ano atual se for "current").</summary>
    public int Resolve(int? currentYear = null)
    {
        return _value switch
        {
            int i => i,
            string => currentYear ?? DateTime.UtcNow.Year,
            _ => throw new InvalidOperationException("Invalid end value")
        };
    }
    
    public static implicit operator ParameterRangeEnd(int value) => new(value);
    public static implicit operator ParameterRangeEnd(string value) => new(value);
}

/// <summary>
/// Range de parâmetro para URL pattern.
/// </summary>
public record ParameterRange
{
    /// <summary>Tipo do parâmetro.</summary>
    public string Type { get; init; } = "range"; // range, list
    
    /// <summary>Valor inicial.</summary>
    public int Start { get; init; }
    
    /// <summary>Valor final - pode ser número ou "current".</summary>
    public ParameterRangeEnd End { get; init; } = new();
    
    /// <summary>Incremento.</summary>
    public int Step { get; init; } = 1;
}

/// <summary>
/// Modos de discovery disponíveis.
/// </summary>
public enum DiscoveryMode
{
    /// <summary>URL estático único.</summary>
    StaticUrl,
    
    /// <summary>Padrão de URL com parâmetros.</summary>
    UrlPattern,
    
    /// <summary>Crawling de página web.</summary>
    WebCrawl,
    
    /// <summary>API REST paginada.</summary>
    ApiPagination
}

/// <summary>
/// Configuração completa de discovery para uma fonte.
/// </summary>
public record DiscoveryConfig
{
    /// <summary>
    /// Estratégia de descoberta (modo) as string.
    /// Values: "static_url", "url_pattern", "web_crawl", "api_pagination"
    /// </summary>
    public string Strategy { get; init; } = "static_url";
    
    /// <summary>Estratégia de descoberta (modo) como enum.</summary>
    public DiscoveryStrategy StrategyEnum => Strategy.ToLowerInvariant() switch
    {
        "static_url" or "staticurl" => DiscoveryStrategy.StaticUrl,
        "url_pattern" or "urlpattern" => DiscoveryStrategy.UrlPattern,
        "web_crawl" or "webcrawl" => DiscoveryStrategy.WebCrawl,
        "api_pagination" or "apipagination" => DiscoveryStrategy.ApiPagination,
        _ => DiscoveryStrategy.StaticUrl
    };
    
    /// <summary>Modo de descoberta (alias para Strategy).</summary>
    public DiscoveryMode Mode
    {
        get => (DiscoveryMode)StrategyEnum;
        init => Strategy = value.ToString().ToLowerInvariant() switch
        {
            "staticurl" => "static_url",
            "urlpattern" => "url_pattern",
            "webcrawl" => "web_crawl",
            "apipagination" => "api_pagination",
            _ => "static_url"
        };
    }
    
    /// <summary>URL estático (para StaticUrl).</summary>
    public string? StaticUrl { get; init; }
    
    /// <summary>URL estático (alias para StaticUrl).</summary>
    public string? Url
    {
        get => StaticUrl;
        init => StaticUrl = value;
    }
    
    /// <summary>Configuração de URL pattern (para UrlPattern).</summary>
    public UrlPatternConfig? UrlPattern { get; init; }
    
    /// <summary>Template de URL (alias para UrlPattern.Template). Aceita "template" ou "urlTemplate" no JSON.</summary>
    [JsonPropertyName("template")]
    public string? UrlTemplate
    {
        get => UrlPattern?.Template;
        init
        {
            if (UrlPattern == null && value != null)
                UrlPattern = new UrlPatternConfig { Template = value };
            else if (UrlPattern != null && value != null)
                UrlPattern = UrlPattern with { Template = value };
        }
    }
    
    /// <summary>Parâmetros do template (alias dinâmico). Mapeia do JSON "parameters".</summary>
    [JsonPropertyName("parameters")]
    public IReadOnlyDictionary<string, object>? Params { get; set; }
    
    /// <summary>Configuração de detecção de mudanças.</summary>
    public ChangeDetectionConfig ChangeDetection { get; init; } = new();
}
