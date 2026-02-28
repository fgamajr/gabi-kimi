using System.Security.Cryptography;
using System.Text;
using Gabi.Postgres.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace Gabi.Postgres.Repositories;

/// <summary>
/// Repository for discovered link operations.
/// </summary>
public interface IDiscoveredLinkRepository
{
    /// <summary>
    /// Gets all discovered links for a source.
    /// </summary>
    Task<IReadOnlyList<DiscoveredLinkEntity>> GetBySourceAsync(string sourceId, CancellationToken ct = default);

    /// <summary>
    /// Gets a discovered link by ID.
    /// </summary>
    Task<DiscoveredLinkEntity?> GetByIdAsync(long id, CancellationToken ct = default);

    /// <summary>
    /// Gets pending links for a source with limit.
    /// </summary>
    Task<IReadOnlyList<DiscoveredLinkEntity>> GetPendingBySourceAsync(string sourceId, int limit, CancellationToken ct = default);

    /// <summary>
    /// Gets a discovered link by source ID and URL.
    /// </summary>
    Task<DiscoveredLinkEntity?> GetBySourceAndUrlAsync(string sourceId, string url, CancellationToken ct = default);

    /// <summary>
    /// Gets a discovered link by source ID and URL (alias).
    /// </summary>
    Task<DiscoveredLinkEntity?> GetByUrlAsync(string sourceId, string url, CancellationToken ct = default);

    /// <summary>
    /// Gets a discovered link by URL hash only.
    /// </summary>
    Task<DiscoveredLinkEntity?> GetByUrlHashAsync(string urlHash, CancellationToken ct = default);

    /// <summary>
    /// Counts links by status for a source.
    /// </summary>
    Task<int> CountByStatusAsync(string sourceId, string status, CancellationToken ct = default);

    /// <summary>
    /// Upserts a single discovered link (insert or update).
    /// </summary>
    Task<DiscoveredLinkEntity> UpsertAsync(DiscoveredLinkEntity link, CancellationToken ct = default);

    /// <summary>
    /// Bulk upserts multiple discovered links (insert or update).
    /// </summary>
    Task<int> BulkUpsertAsync(IEnumerable<DiscoveredLinkEntity> links, CancellationToken ct = default);

    /// <summary>
    /// Alias for BulkUpsertAsync for batch operations.
    /// </summary>
    Task<int> UpsertBatchAsync(IEnumerable<DiscoveredLinkEntity> links, CancellationToken ct = default);

    /// <summary>
    /// Bulk inserts multiple discovered links (insert or update).
    /// Alias for BulkUpsertAsync.
    /// </summary>
    Task BulkInsertAsync(IEnumerable<DiscoveredLinkEntity> links, CancellationToken ct = default);

    /// <summary>
    /// Updates the status of a link.
    /// </summary>
    Task UpdateStatusAsync(long linkId, string status, string? contentHash = null, CancellationToken ct = default);

    /// <summary>
    /// Counts all links for a source.
    /// </summary>
    Task<int> CountBySourceAsync(string sourceId, CancellationToken ct = default);

    /// <summary>
    /// Counts all discovered links (total global).
    /// </summary>
    Task<int> GetTotalCountAsync(CancellationToken ct = default);

    /// <summary>
    /// Lista links paginados por source com filtros.
    /// </summary>
    Task<PaginatedResult<DiscoveredLinkEntity>> GetBySourcePaginatedAsync(
        string sourceId,
        int page,
        int pageSize,
        string? status = null,
        string? sortBy = null,
        CancellationToken ct = default);

    /// <summary>
    /// Obtém estatísticas de links por status.
    /// </summary>
    Task<Dictionary<string, int>> GetStatusCountsAsync(string sourceId, CancellationToken ct = default);

    /// <summary>
    /// Obtém um link específico com contagem de documentos.
    /// </summary>
    Task<DiscoveredLinkEntity?> GetByIdWithStatsAsync(long linkId, CancellationToken ct = default);

    /// <summary>
    /// Conta documentos associados a um link.
    /// </summary>
    Task<int> GetDocumentCountAsync(long linkId, CancellationToken ct = default);

    /// <summary>
    /// Obtém a data da última descoberta para uma source.
    /// </summary>
    Task<DateTime?> GetLatestDiscoveryAsync(string sourceId, CancellationToken ct = default);

    /// <summary>
    /// Gets all discovered links for multiple sources in a single query.
    /// </summary>
    Task<IReadOnlyList<DiscoveredLinkEntity>> GetBySourcesAsync(IReadOnlyList<string> sourceIds, CancellationToken ct = default);

    /// <summary>
    /// Updates metadata and metadata hash for a link.
    /// </summary>
    Task UpdateMetadataAsync(long linkId, string metadataHash, Dictionary<string, object> metadata, CancellationToken ct = default);

    /// <summary>
    /// Counts documents for multiple links in a single query.
    /// </summary>
    Task<Dictionary<long, int>> GetDocumentCountBulkAsync(IReadOnlyList<long> linkIds, CancellationToken ct = default);
}

/// <summary>
/// Implementation of discovered links repository.
/// </summary>
public class DiscoveredLinkRepository : IDiscoveredLinkRepository
{
    private readonly GabiDbContext _context;
    private readonly ILogger<DiscoveredLinkRepository> _logger;

    public DiscoveredLinkRepository(GabiDbContext context, ILogger<DiscoveredLinkRepository> logger)
    {
        _context = context;
        _logger = logger;
    }

    public async Task<IReadOnlyList<DiscoveredLinkEntity>> GetBySourceAsync(string sourceId, CancellationToken ct = default)
    {
        return await _context.DiscoveredLinks
            .AsNoTracking()
            .Where(l => l.SourceId == sourceId)
            .OrderByDescending(l => l.DiscoveredAt)
            .ToListAsync(ct);
    }

    public async Task<IReadOnlyList<DiscoveredLinkEntity>> GetBySourcesAsync(IReadOnlyList<string> sourceIds, CancellationToken ct = default)
    {
        if (sourceIds.Count == 0)
            return Array.Empty<DiscoveredLinkEntity>();

        return await _context.DiscoveredLinks
            .AsNoTracking()
            .Where(l => sourceIds.Contains(l.SourceId))
            .OrderByDescending(l => l.DiscoveredAt)
            .ToListAsync(ct);
    }

    public async Task<DiscoveredLinkEntity?> GetByIdAsync(long id, CancellationToken ct = default)
    {
        return await _context.DiscoveredLinks
            .AsNoTracking()
            .FirstOrDefaultAsync(l => l.Id == id, ct);
    }

    public async Task<IReadOnlyList<DiscoveredLinkEntity>> GetPendingBySourceAsync(string sourceId, int limit, CancellationToken ct = default)
    {
        return await _context.DiscoveredLinks
            .Where(l => l.SourceId == sourceId && l.Status == "pending")
            .OrderBy(l => l.DiscoveredAt)
            .Take(limit)
            .ToListAsync(ct);
    }

    public async Task<DiscoveredLinkEntity?> GetBySourceAndUrlAsync(string sourceId, string url, CancellationToken ct = default)
    {
        var urlHash = ComputeHash(url);
        return await _context.DiscoveredLinks
            .AsNoTracking()
            .FirstOrDefaultAsync(l => l.SourceId == sourceId && l.UrlHash == urlHash, ct);
    }

    public Task<DiscoveredLinkEntity?> GetByUrlAsync(string sourceId, string url, CancellationToken ct = default)
    {
        return GetBySourceAndUrlAsync(sourceId, url, ct);
    }

    public async Task<int> CountByStatusAsync(string sourceId, string status, CancellationToken ct = default)
    {
        return await _context.DiscoveredLinks
            .CountAsync(l => l.SourceId == sourceId && l.Status == status, ct);
    }

    public async Task<DiscoveredLinkEntity> UpsertAsync(DiscoveredLinkEntity link, CancellationToken ct = default)
    {
        // Ensure URL hash is computed
        if (string.IsNullOrEmpty(link.UrlHash))
        {
            link.UrlHash = ComputeHash(link.Url);
        }

        // Check if link already exists
        var existing = await _context.DiscoveredLinks
            .FirstOrDefaultAsync(l => l.SourceId == link.SourceId && l.UrlHash == link.UrlHash, ct);

        if (existing != null)
        {
            // Update existing
            existing.Url = link.Url;
            existing.Etag = link.Etag ?? existing.Etag;
            existing.LastModified = link.LastModified ?? existing.LastModified;
            existing.ContentLength = link.ContentLength ?? existing.ContentLength;
            existing.ContentHash = link.ContentHash ?? existing.ContentHash;
            existing.Metadata = link.Metadata;
            existing.Status = link.Status;
            existing.DiscoveryStatus = link.DiscoveryStatus;
            existing.FetchStatus = link.FetchStatus;
            existing.IngestStatus = link.IngestStatus;
            existing.UpdatedAt = DateTime.UtcNow;
            existing.DiscoveredAt = DateTime.UtcNow;

            _context.DiscoveredLinks.Update(existing);
            _logger.LogDebug("Updated existing link {LinkId} for source {SourceId}", existing.Id, link.SourceId);
            return existing;
        }
        else
        {
            // Insert new
            link.FirstSeenAt = DateTime.UtcNow;
            link.DiscoveredAt = DateTime.UtcNow;
            link.CreatedAt = DateTime.UtcNow;
            link.UpdatedAt = DateTime.UtcNow;

            await _context.DiscoveredLinks.AddAsync(link, ct);
            _logger.LogDebug("Inserted new link for source {SourceId}", link.SourceId);
            return link;
        }
    }

    public async Task<int> BulkUpsertAsync(IEnumerable<DiscoveredLinkEntity> links, CancellationToken ct = default)
    {
        var linkList = links.ToList();
        if (linkList.Count == 0)
        {
            return 0;
        }

        var sourceId = linkList.First().SourceId;
        int insertedCount = 0;
        int updatedCount = 0;

        // Ensure all links have URL hashes
        foreach (var link in linkList)
        {
            if (string.IsNullOrEmpty(link.UrlHash))
            {
                link.UrlHash = ComputeHash(link.Url);
            }
        }

        // Get all URL hashes for this batch
        var urlHashes = linkList.Select(l => l.UrlHash).ToList();

        // Find existing links in a single query
        var existingLinks = await _context.DiscoveredLinks
            .Where(l => l.SourceId == sourceId && urlHashes.Contains(l.UrlHash))
            .ToListAsync(ct);

        var existingMap = existingLinks.ToDictionary(l => l.UrlHash);

        var newLinks = new List<DiscoveredLinkEntity>();

        foreach (var link in linkList)
        {
            if (existingMap.TryGetValue(link.UrlHash, out var existing))
            {
                // Update existing
                existing.Url = link.Url;
                existing.Etag = link.Etag ?? existing.Etag;
                existing.LastModified = link.LastModified ?? existing.LastModified;
                existing.ContentLength = link.ContentLength ?? existing.ContentLength;
                existing.ContentHash = link.ContentHash ?? existing.ContentHash;
                existing.Metadata = link.Metadata;
                existing.Status = link.Status;
                existing.DiscoveryStatus = link.DiscoveryStatus;
                existing.FetchStatus = link.FetchStatus;
                existing.IngestStatus = link.IngestStatus;
                existing.UpdatedAt = DateTime.UtcNow;
                existing.DiscoveredAt = DateTime.UtcNow;

                _context.DiscoveredLinks.Update(existing);
                updatedCount++;
            }
            else
            {
                // Prepare new link
                link.FirstSeenAt = DateTime.UtcNow;
                link.DiscoveredAt = DateTime.UtcNow;
                link.CreatedAt = DateTime.UtcNow;
                link.UpdatedAt = DateTime.UtcNow;
                newLinks.Add(link);
            }
        }

        // Bulk insert new links
        if (newLinks.Count > 0)
        {
            await _context.DiscoveredLinks.AddRangeAsync(newLinks, ct);
            insertedCount = newLinks.Count;
        }

        _logger.LogInformation(
            "Bulk upsert completed for source {SourceId}: {Inserted} inserted, {Updated} updated",
            sourceId, insertedCount, updatedCount);

        return insertedCount + updatedCount;
    }

    /// <summary>
    /// Alias for BulkUpsertAsync for batch operations.
    /// </summary>
    public Task<int> UpsertBatchAsync(IEnumerable<DiscoveredLinkEntity> links, CancellationToken ct = default) => BulkUpsertAsync(links, ct);

    /// <summary>
    /// Bulk inserts multiple discovered links (insert or update).
    /// Alias for BulkUpsertAsync.
    /// </summary>
    public Task BulkInsertAsync(IEnumerable<DiscoveredLinkEntity> links, CancellationToken ct = default) => BulkUpsertAsync(links, ct);

    public async Task UpdateStatusAsync(long linkId, string status, string? contentHash = null, CancellationToken ct = default)
    {
        var link = await _context.DiscoveredLinks
            .FirstOrDefaultAsync(l => l.Id == linkId, ct);

        if (link == null)
        {
            _logger.LogWarning("Link {LinkId} not found for status update", linkId);
            return;
        }

        link.Status = status;
        
        if (contentHash != null)
        {
            link.LastContentHash = link.ContentHash;
            link.ContentHash = contentHash;
        }

        if (status == "processing")
        {
            link.LastProcessedAt = DateTime.UtcNow;
        }
        else if (status == "failed")
        {
            link.ProcessAttempts++;
        }

        link.UpdatedAt = DateTime.UtcNow;
        _context.DiscoveredLinks.Update(link);
        
        _logger.LogDebug("Updated link {LinkId} status to {Status}", linkId, status);
    }

    public async Task<int> CountBySourceAsync(string sourceId, CancellationToken ct = default)
    {
        return await _context.DiscoveredLinks.CountAsync(l => l.SourceId == sourceId, ct);
    }

    public async Task<int> GetTotalCountAsync(CancellationToken ct = default)
    {
        return await _context.DiscoveredLinks.CountAsync(ct);
    }

    public async Task<PaginatedResult<DiscoveredLinkEntity>> GetBySourcePaginatedAsync(
        string sourceId,
        int page,
        int pageSize,
        string? status = null,
        string? sortBy = null,
        CancellationToken ct = default)
    {
        // Validações
        if (page < 1) page = 1;
        if (pageSize < 1) pageSize = 10;
        if (pageSize > 100) pageSize = 100;

        var query = _context.DiscoveredLinks
            .AsNoTracking()
            .Where(l => l.SourceId == sourceId);

        // Aplicar filtro de status
        if (!string.IsNullOrEmpty(status))
        {
            query = query.Where(l => l.Status == status.ToLower());
        }

        // Aplicar ordenação
        query = sortBy?.ToLower() switch
        {
            "discoveredat_asc" => query.OrderBy(l => l.DiscoveredAt),
            "discoveredat_desc" => query.OrderByDescending(l => l.DiscoveredAt),
            "status" => query.OrderBy(l => l.Status).ThenByDescending(l => l.DiscoveredAt),
            "url" => query.OrderBy(l => l.Url),
            _ => query.OrderByDescending(l => l.DiscoveredAt) // default
        };

        // Contar total
        var totalItems = await query.CountAsync(ct);

        // Aplicar paginação
        var items = await query
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .ToListAsync(ct);

        return new PaginatedResult<DiscoveredLinkEntity>
        {
            Items = items,
            Page = page,
            PageSize = pageSize,
            TotalItems = totalItems
        };
    }

    public async Task<Dictionary<string, int>> GetStatusCountsAsync(
        string sourceId,
        CancellationToken ct = default)
    {
        return await _context.DiscoveredLinks
            .AsNoTracking()
            .Where(l => l.SourceId == sourceId)
            .GroupBy(l => l.Status)
            .Select(g => new { Status = g.Key, Count = g.Count() })
            .ToDictionaryAsync(x => x.Status, x => x.Count, ct);
    }

    public async Task<DiscoveredLinkEntity?> GetByIdWithStatsAsync(
        long linkId,
        CancellationToken ct = default)
    {
        return await _context.DiscoveredLinks
            .AsNoTracking()
            .Include(l => l.Documents)
            .FirstOrDefaultAsync(l => l.Id == linkId, ct);
    }

    public async Task<int> GetDocumentCountAsync(long linkId, CancellationToken ct = default)
    {
        return await _context.Documents.CountAsync(d => d.LinkId == linkId, ct);
    }

    public async Task<DateTime?> GetLatestDiscoveryAsync(string sourceId, CancellationToken ct = default)
    {
        return await _context.DiscoveredLinks
            .Where(l => l.SourceId == sourceId)
            .OrderByDescending(l => l.DiscoveredAt)
            .Select(l => (DateTime?)l.DiscoveredAt)
            .FirstOrDefaultAsync(ct);
    }

    public async Task<DiscoveredLinkEntity?> GetByUrlHashAsync(string urlHash, CancellationToken ct = default)
    {
        return await _context.DiscoveredLinks
            .AsNoTracking()
            .FirstOrDefaultAsync(l => l.UrlHash == urlHash, ct);
    }

    public async Task UpdateMetadataAsync(long linkId, string metadataHash, Dictionary<string, object> metadata, CancellationToken ct = default)
    {
        var link = await _context.DiscoveredLinks
            .FirstOrDefaultAsync(l => l.Id == linkId, ct);

        if (link == null)
        {
            _logger.LogWarning("Link {LinkId} not found for metadata update", linkId);
            return;
        }

        // Serialize metadata to JSON
        var metadataJson = System.Text.Json.JsonSerializer.Serialize(metadata);
        
        link.Metadata = metadataJson;
        link.UpdatedAt = DateTime.UtcNow;

        _context.DiscoveredLinks.Update(link);
        
        _logger.LogDebug("Updated metadata for link {LinkId}", linkId);
    }

    public async Task<Dictionary<long, int>> GetDocumentCountBulkAsync(IReadOnlyList<long> linkIds, CancellationToken ct = default)
    {
        if (linkIds.Count == 0)
            return new Dictionary<long, int>();

        return await _context.Documents
            .AsNoTracking()
            .Where(d => linkIds.Contains(d.LinkId))
            .GroupBy(d => d.LinkId)
            .Select(g => new { LinkId = g.Key, Count = g.Count() })
            .ToDictionaryAsync(x => x.LinkId, x => x.Count, ct);
    }

    private static string ComputeHash(string input)
    {
        using var sha256 = SHA256.Create();
        var bytes = sha256.ComputeHash(Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }
}

/// <summary>
/// Classe de resultado paginado.
/// </summary>
/// <typeparam name="T">Tipo dos itens.</typeparam>
public record PaginatedResult<T>
{
    public IReadOnlyList<T> Items { get; init; } = Array.Empty<T>();
    public int Page { get; init; }
    public int PageSize { get; init; }
    public int TotalItems { get; init; }
    public int TotalPages => (int)Math.Ceiling(TotalItems / (double)PageSize);
    public bool HasNextPage => Page < TotalPages;
    public bool HasPreviousPage => Page > 1;
}
