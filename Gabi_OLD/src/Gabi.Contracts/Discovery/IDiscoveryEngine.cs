namespace Gabi.Contracts.Discovery;

/// <summary>
/// Interface para engine de descoberta de fontes.
/// </summary>
public interface IDiscoveryEngine
{
    /// <summary>
    /// Descobre todas as fontes disponíveis para um source_id.
    /// </summary>
    IAsyncEnumerable<DiscoveredSource> DiscoverAsync(
        string sourceId,
        DiscoveryConfig config,
        CancellationToken ct = default);
    
    /// <summary>
    /// Verifica se fonte mudou desde última verificação.
    /// </summary>
    Task<ChangeDetectionResult> CheckChangesAsync(
        DiscoveredSource source,
        ChangeDetectionConfig config,
        CancellationToken ct = default);
}

/// <summary>
/// Resultado de detecção de mudanças.
/// </summary>
public record ChangeDetectionResult
{
    /// <summary>Mudou?</summary>
    public bool HasChanged { get; init; }
    
    /// <summary>Fingerprint anterior.</summary>
    public string? PreviousFingerprint { get; init; }
    
    /// <summary>Novo fingerprint.</summary>
    public string? CurrentFingerprint { get; init; }
    
    /// <summary>Tipo de mudança.</summary>
    public string ChangeType { get; init; } = "unknown"; // modified, new, deleted
}
