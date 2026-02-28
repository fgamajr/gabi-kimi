namespace Gabi.Contracts.Fetch;

/// <summary>
/// Interface para fetcher de conteúdo HTTP.
/// </summary>
public interface IContentFetcher
{
    /// <summary>
    /// Faz download do conteúdo (não-streaming).
    /// </summary>
    Task<FetchedContent> FetchAsync(
        string url, 
        FetchConfig config, 
        CancellationToken ct = default);
    
    /// <summary>
    /// Faz download via streaming.
    /// </summary>
    Task<StreamingFetchedContent> FetchStreamingAsync(
        string url, 
        FetchConfig config, 
        CancellationToken ct = default);
    
    /// <summary>
    /// Faz HEAD request para metadados.
    /// </summary>
    Task<FetchMetadata> HeadAsync(
        string url, 
        CancellationToken ct = default);
}

/// <summary>
/// Metadados de fetch (HEAD request).
/// </summary>
public record FetchMetadata
{
    /// <summary>URL.</summary>
    public string Url { get; init; } = string.Empty;
    
    /// <summary>Content-Type.</summary>
    public string ContentType { get; init; } = string.Empty;
    
    /// <summary>Tamanho (se disponível).</summary>
    public long? ContentLength { get; init; }
    
    /// <summary>ETag.</summary>
    public string? ETag { get; init; }
    
    /// <summary>Last-Modified.</summary>
    public DateTime? LastModified { get; init; }
    
    /// <summary>Status code.</summary>
    public int StatusCode { get; init; }
    
    /// <summary>Headers.</summary>
    public IReadOnlyDictionary<string, string> Headers { get; init; } = 
        new Dictionary<string, string>();
}
