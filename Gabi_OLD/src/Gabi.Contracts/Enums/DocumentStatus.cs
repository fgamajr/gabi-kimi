namespace Gabi.Contracts.Enums;

/// <summary>
/// Status de um documento no sistema.
/// </summary>
public enum DocumentStatus
{
    /// <summary>Documento ativo e indexado.</summary>
    Active,
    
    /// <summary>Documento marcado para reprocessamento.</summary>
    PendingReprocess,
    
    /// <summary>Documento em processamento.</summary>
    Processing,
    
    /// <summary>Documento com erro.</summary>
    Error,

    /// <summary>Documento concluído apenas com metadados (sem texto completo indexável). Terminal state; não conta no acervo text-complete.</summary>
    CompletedMetadataOnly,

    /// <summary>Documento removido (soft delete).</summary>
    Deleted
}
