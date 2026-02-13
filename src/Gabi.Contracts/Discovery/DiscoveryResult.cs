using Gabi.Contracts.Comparison;

namespace Gabi.Contracts.Discovery;

/// <summary>
/// Resultado completo de uma operação de discovery.
/// </summary>
public record DiscoveryResult
{
    /// <summary>ID da fonte.</summary>
    public string SourceId { get; init; } = string.Empty;
    
    /// <summary>URLs descobertas (legacy - use Links for new code).</summary>
    public IReadOnlyList<DiscoveredSource> Urls { get; init; } = 
        new List<DiscoveredSource>();
    
    /// <summary>Links descobertos com hash e metadata.</summary>
    public IReadOnlyList<DiscoveredLink> Links { get; init; } = 
        new List<DiscoveredLink>();
    
    /// <summary>Total descoberto.</summary>
    public int TotalDiscovered => Links.Count > 0 ? Links.Count : Urls.Count;
    
    /// <summary>Erros durante discovery.</summary>
    public IReadOnlyList<string> Errors { get; init; } = 
        new List<string>();
}

/// <summary>
/// Veredito de detecção de mudanças.
/// </summary>
public record ChangeDetectionVerdict
{
    /// <summary>URL verificada.</summary>
    public string Url { get; init; } = string.Empty;
    
    /// <summary>ID da fonte.</summary>
    public string SourceId { get; init; } = string.Empty;
    
    /// <summary>Mudou?</summary>
    public bool Changed { get; init; }
    
    /// <summary>Razão da mudança: new, etag_changed, last_modified_changed, content_hash_changed, forced, unknown.</summary>
    public string Reason { get; init; } = "unknown";
    
    /// <summary>ETag cacheado.</summary>
    public string? CachedEtag { get; init; }
    
    /// <summary>Last-Modified cacheado.</summary>
    public string? CachedLastModified { get; init; }
    
    /// <summary>Hash de conteúdo cacheado.</summary>
    public string? CachedContentHash { get; init; }
    
    /// <summary>Metadados adicionais.</summary>
    public IReadOnlyDictionary<string, object> Metadata { get; init; } = 
        new Dictionary<string, object>();
}

/// <summary>
/// Resultado de detecção de mudanças em batch.
/// </summary>
public record ChangeDetectionBatch
{
    /// <summary>URLs a processar (changed=true).</summary>
    public IReadOnlyList<ChangeDetectionVerdict> ToProcess { get; init; } = 
        new List<ChangeDetectionVerdict>();
    
    /// <summary>URLs ignoradas (changed=false).</summary>
    public IReadOnlyList<ChangeDetectionVerdict> Skipped { get; init; } = 
        new List<ChangeDetectionVerdict>();
    
    /// <summary>Erros.</summary>
    public IReadOnlyList<Dictionary<string, string>> Errors { get; init; } = 
        new List<Dictionary<string, string>>();
}
