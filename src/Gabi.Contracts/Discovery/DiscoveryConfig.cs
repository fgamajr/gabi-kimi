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
    
    /// <summary>Parâmetros do template.</summary>
    public IReadOnlyDictionary<string, ParameterRange> Parameters { get; init; } = 
        new Dictionary<string, ParameterRange>();
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
    
    /// <summary>Valor final (ou "current" para ano atual).</summary>
    public string End { get; init; } = "current";
    
    /// <summary>Incremento.</summary>
    public int Step { get; init; } = 1;
}

/// <summary>
/// Configuração completa de discovery para uma fonte.
/// </summary>
public record DiscoveryConfig
{
    /// <summary>Estratégia de descoberta.</summary>
    public DiscoveryStrategy Strategy { get; init; } = DiscoveryStrategy.StaticUrl;
    
    /// <summary>URL estático (para StaticUrl).</summary>
    public string? StaticUrl { get; init; }
    
    /// <summary>Configuração de URL pattern (para UrlPattern).</summary>
    public UrlPatternConfig? UrlPattern { get; init; }
    
    /// <summary>Configuração de detecção de mudanças.</summary>
    public ChangeDetectionConfig ChangeDetection { get; init; } = new();
}
