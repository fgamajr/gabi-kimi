namespace Gabi.Contracts.Discovery;

/// <summary>
/// Representa uma fonte de dados descoberta durante o processo de discovery.
/// </summary>
/// <param name="Url">URL da fonte de dados.</param>
/// <param name="SourceId">Identificador único da fonte.</param>
/// <param name="Metadata">Metadados adicionais da fonte.</param>
/// <param name="DiscoveredAt">Data/hora da descoberta.</param>
/// <param name="Etag">ETag do recurso (para change detection).</param>
/// <param name="LastModified">Header Last-Modified (para change detection).</param>
public record DiscoveredSource(
    string Url,
    string SourceId,
    IReadOnlyDictionary<string, object> Metadata,
    DateTime DiscoveredAt,
    string? Etag = null,
    string? LastModified = null
);

/// <summary>
/// Cache de detecção de mudanças para uma URL.
/// </summary>
public record ChangeDetectionCache
{
    /// <summary>URL do recurso.</summary>
    public string Url { get; init; } = string.Empty;
    
    /// <summary>ETag cacheado.</summary>
    public string? Etag { get; init; }
    
    /// <summary>Last-Modified cacheado.</summary>
    public string? LastModified { get; init; }
    
    /// <summary>Content-Length cacheado.</summary>
    public long? ContentLength { get; init; }
    
    /// <summary>Hash do conteúdo cacheado.</summary>
    public string? ContentHash { get; init; }
    
    /// <summary>Data da última verificação.</summary>
    public DateTime CheckedAt { get; init; }
}
