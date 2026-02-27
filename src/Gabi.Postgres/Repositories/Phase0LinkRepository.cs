using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Gabi.Contracts.Pipeline;
using Microsoft.EntityFrameworkCore;

namespace Gabi.Postgres.Repositories;

/// <summary>
/// Postgres implementation of IPhase0LinkRepository.
/// Maps between DiscoveredLinkPhase0 (Contracts) and DiscoveredLinkEntity (Postgres)
/// so that Layer 4 (Gabi.Sync) does not need to reference Gabi.Postgres.
/// </summary>
public class Phase0LinkRepository : IPhase0LinkRepository
{
    private readonly GabiDbContext _context;

    public Phase0LinkRepository(GabiDbContext context)
    {
        _context = context;
    }

    public async Task<DiscoveredLinkPhase0?> GetBySourceAndUrlAsync(
        string sourceId,
        string url,
        CancellationToken ct = default)
    {
        var entity = await _context.DiscoveredLinks
            .AsNoTracking()
            .FirstOrDefaultAsync(l => l.SourceId == sourceId && l.Url == url, ct);

        return entity is null ? null : MapToContract(entity);
    }

    public async Task<int> BulkUpsertAsync(
        IEnumerable<DiscoveredLinkPhase0> links,
        CancellationToken ct = default)
    {
        var entities = links.Select(MapToEntity).ToList();
        if (entities.Count == 0) return 0;

        var count = 0;
        foreach (var entity in entities)
        {
            var existing = await _context.DiscoveredLinks
                .FirstOrDefaultAsync(l => l.SourceId == entity.SourceId && l.UrlHash == entity.UrlHash, ct);

            if (existing is null)
            {
                _context.DiscoveredLinks.Add(entity);
            }
            else
            {
                existing.Etag = entity.Etag;
                existing.LastModified = entity.LastModified;
                existing.ContentLength = entity.ContentLength;
                existing.ContentHash = entity.ContentHash;
                existing.DiscoveredAt = entity.DiscoveredAt;
                existing.Metadata = entity.Metadata;
                existing.Status = entity.Status;
            }
            count++;
        }

        await _context.SaveChangesAsync(ct);
        return count;
    }

    private static DiscoveredLinkPhase0 MapToContract(Entities.DiscoveredLinkEntity entity)
    {
        return new DiscoveredLinkPhase0
        {
            Id = entity.Id,
            SourceId = entity.SourceId,
            Url = entity.Url,
            UrlHash = entity.UrlHash,
            Etag = entity.Etag,
            LastModified = entity.LastModified,
            ContentLength = entity.ContentLength,
            ContentHash = entity.ContentHash,
            Status = LinkDiscoveryStatus.Unchanged,
            FirstSeenAt = entity.FirstSeenAt,
            DiscoveredAt = entity.DiscoveredAt,
            Metadata = DeserializeMetadata(entity.Metadata)
        };
    }

    private static Entities.DiscoveredLinkEntity MapToEntity(DiscoveredLinkPhase0 link)
    {
        return new Entities.DiscoveredLinkEntity
        {
            Id = link.Id,
            SourceId = link.SourceId,
            Url = link.Url,
            UrlHash = string.IsNullOrEmpty(link.UrlHash) ? ComputeHash(link.Url) : link.UrlHash,
            Etag = link.Etag,
            LastModified = link.LastModified,
            ContentLength = link.ContentLength,
            ContentHash = link.ContentHash,
            FirstSeenAt = link.FirstSeenAt == default ? DateTime.UtcNow : link.FirstSeenAt,
            DiscoveredAt = DateTime.UtcNow,
            Metadata = SerializeMetadata(link.Metadata),
            Status = "pending"
        };
    }

    private static IReadOnlyDictionary<string, object> DeserializeMetadata(string json)
    {
        if (string.IsNullOrEmpty(json) || json == "{}")
            return new Dictionary<string, object>();

        try
        {
            return JsonSerializer.Deserialize<Dictionary<string, object>>(json)
                ?? new Dictionary<string, object>();
        }
        catch
        {
            return new Dictionary<string, object>();
        }
    }

    private static string SerializeMetadata(IReadOnlyDictionary<string, object> metadata)
    {
        if (metadata is null || metadata.Count == 0)
            return "{}";

        return JsonSerializer.Serialize(metadata);
    }

    private static string ComputeHash(string input)
    {
        using var sha256 = SHA256.Create();
        var bytes = sha256.ComputeHash(Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }
}
