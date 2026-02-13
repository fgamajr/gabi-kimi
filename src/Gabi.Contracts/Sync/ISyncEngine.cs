using Gabi.Contracts.Enums;
using Gabi.Contracts.Parse;

namespace Gabi.Contracts.Sync;

/// <summary>
/// Interface para engine de sincronização.
/// </summary>
public interface ISyncEngine
{
    /// <summary>
    /// Sincroniza um documento parseado.
    /// </summary>
    Task<SyncResult> SynchronizeAsync(
        ParsedDocument document,
        CancellationToken ct = default);
    
    /// <summary>
    /// Verifica estado de um documento na base.
    /// </summary>
    Task<DocumentState> GetDocumentStateAsync(
        string documentId,
        CancellationToken ct = default);
}

/// <summary>
/// Estado de um documento na base.
/// </summary>
public record DocumentState
{
    /// <summary>Existe?</summary>
    public bool Exists { get; init; }
    
    /// <summary>Fingerprint armazenado.</summary>
    public string? StoredFingerprint { get; init; }
    
    /// <summary>Status.</summary>
    public string? Status { get; init; }
    
    /// <summary>Data de última atualização.</summary>
    public DateTime? LastUpdated { get; init; }
    
    /// <summary>Precisa de sync?</summary>
    public bool NeedsSync => !Exists || Status == "pending_reprocess";
}

/// <summary>
/// Estratégia de merge.
/// </summary>
public enum MergeStrategy
{
    /// <summary>Substituir completamente.</summary>
    Replace,
    
    /// <summary>Mesclar campos.</summary>
    Merge,
    
    /// <summary>Manter existente.</summary>
    KeepExisting
}
