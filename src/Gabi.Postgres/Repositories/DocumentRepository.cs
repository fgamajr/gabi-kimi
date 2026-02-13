using Gabi.Postgres.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace Gabi.Postgres.Repositories;

/// <summary>
/// Repository for document operations.
/// </summary>
public class DocumentRepository : IDocumentRepository
{
    private readonly GabiDbContext _context;
    private readonly ILogger<DocumentRepository> _logger;

    public DocumentRepository(GabiDbContext context, ILogger<DocumentRepository> logger)
    {
        _context = context;
        _logger = logger;
    }

    /// <inheritdoc />
    public async Task<DocumentEntity?> GetByFingerprintAsync(string fingerprint, CancellationToken ct = default)
    {
        return await _context.Documents
            .AsNoTracking()
            .FirstOrDefaultAsync(d => d.ContentHash == fingerprint && d.Status != "deleted", ct);
    }

    /// <inheritdoc />
    public async Task<bool> ExistsAsync(string documentId, CancellationToken ct = default)
    {
        if (string.IsNullOrEmpty(documentId))
            return false;
            
        return await _context.Documents
            .AsNoTracking()
            .AnyAsync(d => d.DocumentId == documentId && d.Status != "deleted", ct);
    }

    /// <inheritdoc />
    public async Task AddAsync(DocumentEntity document, CancellationToken ct = default)
    {
        document.CreatedAt = DateTime.UtcNow;
        document.UpdatedAt = DateTime.UtcNow;
        document.Status = "pending";

        await _context.Documents.AddAsync(document, ct);
        _logger.LogDebug("Added document {DocumentId} with content hash {ContentHash}", 
            document.DocumentId, document.ContentHash);
    }

    /// <inheritdoc />
    public Task UpdateAsync(DocumentEntity document, CancellationToken ct = default)
    {
        document.UpdatedAt = DateTime.UtcNow;
        _context.Documents.Update(document);
        
        _logger.LogDebug("Updated document {DocumentId}", document.DocumentId);
        return Task.CompletedTask;
    }

    /// <inheritdoc />
    public async Task SoftDeleteAsync(string documentId, CancellationToken ct = default)
    {
        if (string.IsNullOrEmpty(documentId))
            return;
            
        var document = await _context.Documents
            .FirstOrDefaultAsync(d => d.DocumentId == documentId, ct);

        if (document == null)
        {
            _logger.LogWarning("Document {DocumentId} not found for soft delete", documentId);
            return;
        }

        document.Status = "deleted";
        document.UpdatedAt = DateTime.UtcNow;

        _context.Documents.Update(document);
        _logger.LogInformation("Soft deleted document {DocumentId}", documentId);
    }

    /// <inheritdoc />
    public async Task<int> CountBySourceAsync(string sourceId, CancellationToken ct = default)
    {
        return await _context.Documents
            .AsNoTracking()
            .CountAsync(d => d.SourceId == sourceId && d.Status != "deleted", ct);
    }

    /// <inheritdoc />
    public async Task<int> CountByLinkAsync(long linkId, CancellationToken ct = default)
    {
        return await _context.Documents
            .AsNoTracking()
            .CountAsync(d => d.LinkId == linkId && d.Status != "deleted", ct);
    }

    /// <inheritdoc />
    public async Task<IReadOnlyList<DocumentEntity>> GetByLinkAsync(long linkId, CancellationToken ct = default)
    {
        return await _context.Documents
            .AsNoTracking()
            .Where(d => d.LinkId == linkId && d.Status != "deleted")
            .OrderByDescending(d => d.CreatedAt)
            .ToListAsync(ct);
    }

    /// <inheritdoc />
    public async Task<DocumentEntity?> GetByExternalIdAsync(string sourceId, string externalId, CancellationToken ct = default)
    {
        if (string.IsNullOrEmpty(sourceId) || string.IsNullOrEmpty(externalId))
            return null;

        return await _context.Documents
            .AsNoTracking()
            .FirstOrDefaultAsync(d => 
                d.SourceId == sourceId && 
                d.ExternalId == externalId && 
                d.RemovedFromSourceAt == null, ct);
    }

    /// <inheritdoc />
    public async Task<IReadOnlyList<DocumentEntity>> GetActiveBySourceAsync(string sourceId, CancellationToken ct = default)
    {
        if (string.IsNullOrEmpty(sourceId))
            return Array.Empty<DocumentEntity>();

        return await _context.Documents
            .AsNoTracking()
            .Where(d => 
                d.SourceId == sourceId && 
                d.RemovedFromSourceAt == null)
            .OrderByDescending(d => d.CreatedAt)
            .ToListAsync(ct);
    }

    /// <inheritdoc />
    public async Task MarkAsRemovedAsync(string sourceId, string externalId, string reason, CancellationToken ct = default)
    {
        if (string.IsNullOrEmpty(sourceId) || string.IsNullOrEmpty(externalId))
            return;

        var document = await _context.Documents
            .FirstOrDefaultAsync(d => 
                d.SourceId == sourceId && 
                d.ExternalId == externalId && 
                d.RemovedFromSourceAt == null, ct);

        if (document == null)
        {
            _logger.LogWarning("Document with ExternalId {ExternalId} from source {SourceId} not found for removal", 
                externalId, sourceId);
            return;
        }

        document.RemovedFromSourceAt = DateTime.UtcNow;
        document.RemovedReason = reason;
        document.UpdatedAt = DateTime.UtcNow;

        _context.Documents.Update(document);
        _logger.LogInformation("Marked document {ExternalId} from source {SourceId} as removed from source", 
            externalId, sourceId);
    }
}
