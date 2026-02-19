using Gabi.Postgres.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace Gabi.Postgres.Repositories;

public interface IFetchItemRepository
{
    Task<int> EnsurePendingForLinksAsync(IReadOnlyList<DiscoveredLinkEntity> links, CancellationToken ct = default);
    Task<IReadOnlyList<FetchItemEntity>> GetBySourceAndStatusesAsync(string sourceId, int limit, string[] statuses, CancellationToken ct = default);
    Task<IReadOnlyList<long>> GetCandidateIdsBySourceAndStatusesAsync(string sourceId, int limit, string[] statuses, CancellationToken ct = default);
    Task<IReadOnlyList<FetchItemEntity>> GetByIdsAsync(string sourceId, IReadOnlyCollection<long> ids, CancellationToken ct = default);
    Task<int> CountBySourceAndStatusesAsync(string sourceId, string[] statuses, CancellationToken ct = default);
    Task<int> CountBySourceAndStatusAsync(string sourceId, string status, CancellationToken ct = default);
}

public class FetchItemRepository : IFetchItemRepository
{
    private readonly GabiDbContext _context;
    private readonly ILogger<FetchItemRepository> _logger;

    public FetchItemRepository(GabiDbContext context, ILogger<FetchItemRepository> logger)
    {
        _context = context;
        _logger = logger;
    }

    public async Task<int> EnsurePendingForLinksAsync(IReadOnlyList<DiscoveredLinkEntity> links, CancellationToken ct = default)
    {
        if (links.Count == 0) return 0;

        var linkIds = links.Select(l => l.Id).ToList();
        var existing = await _context.FetchItems
            .Where(i => linkIds.Contains(i.DiscoveredLinkId))
            .Select(i => i.DiscoveredLinkId)
            .Distinct()
            .ToListAsync(ct);
        var existingSet = existing.ToHashSet();

        var toCreate = links
            .Where(l => !existingSet.Contains(l.Id))
            .Select(l => new FetchItemEntity
            {
                DiscoveredLinkId = l.Id,
                SourceId = l.SourceId,
                Url = l.Url,
                UrlHash = l.UrlHash,
                Status = "pending"
            })
            .ToList();

        if (toCreate.Count == 0) return 0;

        await _context.FetchItems.AddRangeAsync(toCreate, ct);
        await _context.SaveChangesAsync(ct);
        _logger.LogInformation("Created {Count} fetch_items from discovery links", toCreate.Count);
        return toCreate.Count;
    }

    public async Task<IReadOnlyList<FetchItemEntity>> GetBySourceAndStatusesAsync(string sourceId, int limit, string[] statuses, CancellationToken ct = default)
    {
        return await _context.FetchItems
            .Where(i => i.SourceId == sourceId && statuses.Contains(i.Status))
            .OrderBy(i => i.CreatedAt)
            .Take(limit)
            .ToListAsync(ct);
    }

    public async Task<IReadOnlyList<long>> GetCandidateIdsBySourceAndStatusesAsync(string sourceId, int limit, string[] statuses, CancellationToken ct = default)
    {
        return await _context.FetchItems
            .AsNoTracking()
            .Where(i => i.SourceId == sourceId && statuses.Contains(i.Status))
            .OrderBy(i => i.CreatedAt)
            .Select(i => i.Id)
            .Take(limit)
            .ToListAsync(ct);
    }

    public async Task<IReadOnlyList<FetchItemEntity>> GetByIdsAsync(string sourceId, IReadOnlyCollection<long> ids, CancellationToken ct = default)
    {
        if (ids.Count == 0)
            return Array.Empty<FetchItemEntity>();

        return await _context.FetchItems
            .Where(i => i.SourceId == sourceId && ids.Contains(i.Id))
            .OrderBy(i => i.CreatedAt)
            .ToListAsync(ct);
    }

    public Task<int> CountBySourceAndStatusesAsync(string sourceId, string[] statuses, CancellationToken ct = default)
    {
        return _context.FetchItems.CountAsync(i => i.SourceId == sourceId && statuses.Contains(i.Status), ct);
    }

    public Task<int> CountBySourceAndStatusAsync(string sourceId, string status, CancellationToken ct = default)
    {
        return _context.FetchItems.CountAsync(i => i.SourceId == sourceId && i.Status == status, ct);
    }
}
