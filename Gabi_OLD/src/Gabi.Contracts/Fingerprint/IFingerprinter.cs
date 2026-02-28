using Gabi.Contracts.Parse;

namespace Gabi.Contracts.Fingerprint;

/// <summary>
/// Interface para cálculo de fingerprint.
/// </summary>
public interface IFingerprinter
{
    /// <summary>
    /// Calcula fingerprint de um documento.
    /// </summary>
    DocumentFingerprint Compute(ParsedDocument document);
    
    /// <summary>
    /// Calcula fingerprint de texto raw.
    /// </summary>
    DocumentFingerprint ComputeRaw(string content, HashAlgorithm algorithm = HashAlgorithm.Sha256);
    
    /// <summary>
    /// Verifica se dois fingerprints são iguais.
    /// </summary>
    bool Equals(DocumentFingerprint a, DocumentFingerprint b);
}

/// <summary>
/// Interface para verificação de duplicatas.
/// </summary>
public interface IDeduplicator
{
    /// <summary>
    /// Verifica se documento é duplicata.
    /// </summary>
    Task<DuplicateCheckResult> CheckAsync(
        DocumentFingerprint fingerprint,
        CancellationToken ct = default);
}
