using Gabi.Contracts.Enums;
using Gabi.Postgres.Entities;

namespace Gabi.Postgres.Repositories;

/// <summary>
/// Interface para operações de repositório de documentos.
/// </summary>
public interface IDocumentRepository
{
    /// <summary>
    /// Busca documento pelo fingerprint (hash do conteúdo).
    /// </summary>
    Task<DocumentEntity?> GetByFingerprintAsync(string fingerprint, CancellationToken ct = default);
    
    /// <summary>
    /// Verifica se documento existe pelo ID.
    /// </summary>
    Task<bool> ExistsAsync(string documentId, CancellationToken ct = default);
    
    /// <summary>
    /// Adiciona novo documento.
    /// </summary>
    Task AddAsync(DocumentEntity document, CancellationToken ct = default);
    
    /// <summary>
    /// Atualiza documento existente.
    /// </summary>
    Task UpdateAsync(DocumentEntity document, CancellationToken ct = default);
    
    /// <summary>
    /// Soft delete de documento.
    /// </summary>
    Task SoftDeleteAsync(string documentId, CancellationToken ct = default);
    
    /// <summary>
    /// Conta documentos por source.
    /// </summary>
    Task<int> CountBySourceAsync(string sourceId, CancellationToken ct = default);
    
    /// <summary>
    /// Conta documentos por link.
    /// </summary>
    Task<int> CountByLinkAsync(long linkId, CancellationToken ct = default);
    
    /// <summary>
    /// Busca documentos por link.
    /// </summary>
    Task<IReadOnlyList<DocumentEntity>> GetByLinkAsync(long linkId, CancellationToken ct = default);
}
