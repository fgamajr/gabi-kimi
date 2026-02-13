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
    
    /// <summary>
    /// Busca documento pelo ExternalId (natural key from source).
    /// </summary>
    Task<DocumentEntity?> GetByExternalIdAsync(string sourceId, string externalId, CancellationToken ct = default);
    
    /// <summary>
    /// Busca documentos ativos (não removidos) por source.
    /// </summary>
    Task<IReadOnlyList<DocumentEntity>> GetActiveBySourceAsync(string sourceId, CancellationToken ct = default);
    
    /// <summary>
    /// Marca documento como removido da fonte (soft delete from source).
    /// </summary>
    Task MarkAsRemovedAsync(string sourceId, string externalId, string reason, CancellationToken ct = default);
}
