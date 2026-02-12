using Gabi.Contracts.Enums;

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
}

/// <summary>
/// Entidade de documento (simplificada para início).
/// </summary>
public class DocumentEntity
{
    public Guid Id { get; set; }
    public string SourceId { get; set; } = string.Empty;
    public string DocumentId { get; set; } = string.Empty;
    public string Title { get; set; } = string.Empty;
    public string ContentPreview { get; set; } = string.Empty;
    public string Fingerprint { get; set; } = string.Empty;
    public string ContentHash { get; set; } = string.Empty;
    public DocumentStatus Status { get; set; } = DocumentStatus.Active;
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;
}
