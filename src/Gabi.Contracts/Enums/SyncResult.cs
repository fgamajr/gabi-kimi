namespace Gabi.Contracts.Enums;

/// <summary>
/// Resultado da operação de sincronização de um documento.
/// </summary>
public enum SyncResult
{
    /// <summary>Documento não mudou, nenhuma ação necessária.</summary>
    Bypassed,
    
    /// <summary>Novo documento inserido.</summary>
    Inserted,
    
    /// <summary>Documento existente atualizado.</summary>
    Updated,
    
    /// <summary>Documento removido (soft delete).</summary>
    Deleted,
    
    /// <summary>Falha durante sincronização.</summary>
    Failed
}
