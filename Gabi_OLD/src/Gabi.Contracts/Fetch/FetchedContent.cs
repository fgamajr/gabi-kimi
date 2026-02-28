namespace Gabi.Contracts.Fetch;

/// <summary>
/// Conteúdo fetchado (não-streaming).
/// </summary>
public record FetchedContent
{
    /// <summary>URL da fonte.</summary>
    public string Url { get; init; } = string.Empty;
    
    /// <summary>ID da fonte.</summary>
    public string SourceId { get; init; } = string.Empty;
    
    /// <summary>Conteúdo em bytes.</summary>
    public byte[] Content { get; init; } = Array.Empty<byte>();
    
    /// <summary>Tamanho em bytes.</summary>
    public long SizeBytes { get; init; }
    
    /// <summary>Content-Type do response.</summary>
    public string ContentType { get; init; } = string.Empty;
    
    /// <summary>Formato detectado: csv, pdf, html, etc. (via magic bytes).</summary>
    public string DetectedFormat { get; init; } = string.Empty;
    
    /// <summary>Encoding detectado.</summary>
    public string Encoding { get; init; } = "utf-8";
    
    /// <summary>Headers HTTP da resposta.</summary>
    public IReadOnlyDictionary<string, string> Headers { get; init; } = 
        new Dictionary<string, string>();
    
    /// <summary>Status code HTTP.</summary>
    public int HttpStatus { get; init; }
    
    /// <summary>ETag (para change detection).</summary>
    public string? Etag { get; init; }
    
    /// <summary>Last-Modified.</summary>
    public string? LastModified { get; init; }
    
    /// <summary>Hash SHA256 do conteúdo bruto.</summary>
    public string ContentHash { get; init; } = string.Empty;
    
    /// <summary>Metadados adicionais.</summary>
    public IReadOnlyDictionary<string, object> Metadata { get; init; } = 
        new Dictionary<string, object>();
}

/// <summary>
/// Conteúdo fetchado via streaming.
/// </summary>
public record StreamingFetchedContent
{
    /// <summary>URL da fonte.</summary>
    public string Url { get; init; } = string.Empty;
    
    /// <summary>ID da fonte.</summary>
    public string SourceId { get; init; } = string.Empty;
    
    /// <summary>Stream de texto (chunks de string).</summary>
    public IAsyncEnumerable<string>? TextChunks { get; init; }
    
    /// <summary>Tamanho estimado (se disponível).</summary>
    public long? EstimatedSizeBytes { get; init; }
    
    /// <summary>Content-Type.</summary>
    public string ContentType { get; init; } = string.Empty;
    
    /// <summary>Formato detectado.</summary>
    public string DetectedFormat { get; init; } = string.Empty;
    
    /// <summary>Encoding.</summary>
    public string Encoding { get; init; } = "utf-8";
    
    /// <summary>Headers HTTP.</summary>
    public IReadOnlyDictionary<string, string> Headers { get; init; } = 
        new Dictionary<string, string>();
    
    /// <summary>Status code HTTP.</summary>
    public int HttpStatus { get; init; }
    
    /// <summary>ETag (para change detection).</summary>
    public string? Etag { get; init; }
    
    /// <summary>Last-Modified.</summary>
    public string? LastModified { get; init; }
    
    /// <summary>Hash SHA256 (se conhecido).</summary>
    public string? ContentHash { get; init; }
}
