using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Gabi.Contracts.Comparison;

namespace Gabi.Discover;

/// <summary>
/// Compares discovered links with existing database entries.
/// </summary>
public class LinkComparator : ILinkComparator
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = false
    };

    /// <summary>
    /// Compares a discovered link with existing database entry.
    /// </summary>
    public LinkComparisonResult Compare(DiscoveredLink discovered, DiscoveredLinkEntity? existing)
    {
        // New link - no existing entry
        if (existing == null)
        {
            return new LinkComparisonResult
            {
                Url = discovered.Url,
                Action = ComparisonAction.Insert,
                Reason = "new_link",
                NewLink = discovered,
                ExistingLink = null
            };
        }

        // Check if metadata changed
        var currentMetadataHash = CalculateMetadataHash(discovered.Metadata);
        if (existing.MetadataHash != currentMetadataHash)
        {
            return new LinkComparisonResult
            {
                Url = discovered.Url,
                Action = ComparisonAction.Update,
                Reason = "metadata_changed",
                NewLink = discovered,
                ExistingLink = existing
            };
        }

        // Check if content hash changed (only if both have content hashes)
        if (!string.IsNullOrEmpty(discovered.ContentHash) && 
            !string.IsNullOrEmpty(existing.ContentHash) &&
            existing.ContentHash != discovered.ContentHash)
        {
            return new LinkComparisonResult
            {
                Url = discovered.Url,
                Action = ComparisonAction.Update,
                Reason = "content_changed",
                NewLink = discovered,
                ExistingLink = existing
            };
        }

        // No changes detected - skip
        return new LinkComparisonResult
        {
            Url = discovered.Url,
            Action = ComparisonAction.Skip,
            Reason = "unchanged",
            NewLink = discovered,
            ExistingLink = existing
        };
    }

    /// <summary>
    /// Batch compare all discovered links against existing database state.
    /// </summary>
    public Task<BatchComparisonResult> CompareBatchAsync(
        string sourceId,
        IReadOnlyList<DiscoveredLink> discovered,
        IReadOnlyList<DiscoveredLinkEntity> existing,
        CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested();

        // Build lookup map for existing links by URL hash
        var existingMap = existing.ToDictionary(e => e.UrlHash);

        var results = new List<LinkComparisonResult>();
        int insertCount = 0;
        int updateCount = 0;
        int skipCount = 0;

        foreach (var link in discovered)
        {
            ct.ThrowIfCancellationRequested();

            existingMap.TryGetValue(link.UrlHash, out var existingLink);
            var result = Compare(link, existingLink);
            results.Add(result);

            switch (result.Action)
            {
                case ComparisonAction.Insert:
                    insertCount++;
                    break;
                case ComparisonAction.Update:
                    updateCount++;
                    break;
                case ComparisonAction.Skip:
                    skipCount++;
                    break;
            }
        }

        return Task.FromResult(new BatchComparisonResult
        {
            SourceId = sourceId,
            Results = results,
            InsertCount = insertCount,
            UpdateCount = updateCount,
            SkipCount = skipCount,
            ComparedAt = DateTime.UtcNow
        });
    }

    /// <summary>
    /// Calculates SHA256 hash of metadata dictionary for quick comparison.
    /// </summary>
    public string CalculateMetadataHash(IReadOnlyDictionary<string, object> metadata)
    {
        // Serialize metadata to JSON
        var json = JsonSerializer.Serialize(metadata, JsonOptions);

        // Compute SHA256 hash
        using var sha256 = SHA256.Create();
        var bytes = sha256.ComputeHash(Encoding.UTF8.GetBytes(json));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }
}
