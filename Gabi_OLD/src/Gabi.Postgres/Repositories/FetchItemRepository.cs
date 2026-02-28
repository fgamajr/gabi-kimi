using Gabi.Postgres.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage;
using Microsoft.Extensions.Logging;
using Npgsql;

namespace Gabi.Postgres.Repositories;

public interface IFetchItemRepository
{
    Task<int> EnsurePendingForLinksAsync(IReadOnlyList<DiscoveredLinkEntity> links, CancellationToken ct = default);
    Task<IReadOnlyList<FetchItemEntity>> GetBySourceAndStatusesAsync(string sourceId, int limit, string[] statuses, CancellationToken ct = default);
    Task<IReadOnlyList<long>> GetCandidateIdsBySourceAndStatusesAsync(string sourceId, int limit, string[] statuses, CancellationToken ct = default);
    Task<IReadOnlyList<FetchItemEntity>> GetByIdsAsync(string sourceId, IReadOnlyCollection<long> ids, CancellationToken ct = default);
    Task<IReadOnlyList<FetchItemEntity>> ClaimNextBatchAsync(
        string sourceId,
        int limit,
        string[] statuses,
        Guid fetchRunId,
        string updatedBy,
        CancellationToken ct = default);
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

    public async Task<IReadOnlyList<FetchItemEntity>> ClaimNextBatchAsync(
        string sourceId,
        int limit,
        string[] statuses,
        Guid fetchRunId,
        string updatedBy,
        CancellationToken ct = default)
    {
        if (limit <= 0 || statuses.Length == 0)
            return Array.Empty<FetchItemEntity>();

        var conn = (NpgsqlConnection)_context.Database.GetDbConnection();
        var openedHere = false;
        if (conn.State != System.Data.ConnectionState.Open)
        {
            await conn.OpenAsync(ct);
            openedHere = true;
        }

        try
        {
            await using var tx = await _context.Database.BeginTransactionAsync(ct);
            var dbTx = (NpgsqlTransaction)tx.GetDbTransaction();

            var claimedIds = new List<long>(limit);
            await using (var selectCmd = new NpgsqlCommand(@"
                SELECT f.""Id""
                FROM fetch_items f
                WHERE f.""SourceId"" = @sourceId
                  AND f.""Status"" = ANY(@statuses)
                  AND f.""Attempts"" < f.""MaxAttempts""
                ORDER BY f.""CreatedAt"", f.""Id""
                FOR UPDATE SKIP LOCKED
                LIMIT @limit;", conn, dbTx))
            {
                selectCmd.Parameters.AddWithValue("sourceId", sourceId);
                selectCmd.Parameters.AddWithValue("statuses", statuses);
                selectCmd.Parameters.AddWithValue("limit", limit);

                await using var reader = await selectCmd.ExecuteReaderAsync(ct);
                while (await reader.ReadAsync(ct))
                    claimedIds.Add(reader.GetInt64(0));
            }

            if (claimedIds.Count == 0)
            {
                await tx.CommitAsync(ct);
                return Array.Empty<FetchItemEntity>();
            }

            await using (var updateCmd = new NpgsqlCommand(@"
                UPDATE fetch_items
                SET ""Status"" = 'processing',
                    ""Attempts"" = ""Attempts"" + 1,
                    ""StartedAt"" = NOW(),
                    ""FetchRunId"" = @fetchRunId,
                    ""UpdatedAt"" = NOW(),
                    ""UpdatedBy"" = @updatedBy
                WHERE ""Id"" = ANY(@ids);", conn, dbTx))
            {
                updateCmd.Parameters.AddWithValue("fetchRunId", fetchRunId);
                updateCmd.Parameters.AddWithValue("updatedBy", updatedBy);
                updateCmd.Parameters.AddWithValue("ids", claimedIds.ToArray());
                await updateCmd.ExecuteNonQueryAsync(ct);
            }

            await tx.CommitAsync(ct);
            return await GetByIdsAsync(sourceId, claimedIds, ct);
        }
        finally
        {
            if (openedHere && conn.State == System.Data.ConnectionState.Open)
                await conn.CloseAsync();
        }
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
