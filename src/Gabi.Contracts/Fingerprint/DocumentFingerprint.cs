namespace Gabi.Contracts.Fingerprint;

/// <summary>
/// Algoritmos de hash suportados.
/// </summary>
public enum HashAlgorithm
{
    Sha256,
    Sha512,
    Md5 // Para compatibilidade, não recomendado
}

/// <summary>
/// Fingerprint de um documento.
/// </summary>
public record DocumentFingerprint
{
    /// <summary>Hash do conteúdo.</summary>
    public string Hash { get; init; } = string.Empty;
    
    /// <summary>Algoritmo usado.</summary>
    public HashAlgorithm Algorithm { get; init; } = HashAlgorithm.Sha256;
    
    /// <summary>Tamanho do conteúdo em bytes.</summary>
    public long ContentSize { get; init; }
    
    /// <summary>Data/hora do cálculo.</summary>
    public DateTime ComputedAt { get; init; } = DateTime.UtcNow;
}

/// <summary>
/// Resultado de verificação de duplicata.
/// </summary>
public record DuplicateCheckResult
{
    /// <summary>É duplicata?</summary>
    public bool IsDuplicate { get; init; }
    
    /// <summary>ID do documento existente (se duplicata).</summary>
    public string? ExistingDocumentId { get; init; }
    
    /// <summary>Fingerprint calculado.</summary>
    public DocumentFingerprint Fingerprint { get; init; } = null!;
}
