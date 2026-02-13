namespace Gabi.Contracts.Comparison;

/// <summary>
/// Action to take based on comparison.
/// </summary>
public enum ComparisonAction
{
    /// <summary>
    /// Same data, no action needed.
    /// </summary>
    Skip,

    /// <summary>
    /// New link, needs to be added.
    /// </summary>
    Insert,

    /// <summary>
    /// Metadata changed, needs refresh.
    /// </summary>
    Update,

    /// <summary>
    /// Link no longer in source (for future reconcile).
    /// </summary>
    Delete
}

/// <summary>
/// Comparison result for a single link.
/// </summary>
public record LinkComparisonResult
{
    /// <summary>
    /// URL being compared.
    /// </summary>
    public string Url { get; init; } = null!;

    /// <summary>
    /// Action to take.
    /// </summary>
    public ComparisonAction Action { get; init; }

    /// <summary>
    /// Reason for the action.
    /// </summary>
    public string? Reason { get; init; }

    /// <summary>
    /// The newly discovered link data.
    /// </summary>
    public DiscoveredLink? NewLink { get; init; }

    /// <summary>
    /// The existing link from database (null if new).
    /// </summary>
    public DiscoveredLinkEntity? ExistingLink { get; init; }
}

/// <summary>
/// Batch comparison result.
/// </summary>
public record BatchComparisonResult
{
    /// <summary>
    /// Source ID for this comparison batch.
    /// </summary>
    public string SourceId { get; init; } = null!;

    /// <summary>
    /// Individual comparison results.
    /// </summary>
    public IReadOnlyList<LinkComparisonResult> Results { get; init; } = Array.Empty<LinkComparisonResult>();

    /// <summary>
    /// Number of links to insert.
    /// </summary>
    public int InsertCount { get; init; }

    /// <summary>
    /// Number of links to update.
    /// </summary>
    public int UpdateCount { get; init; }

    /// <summary>
    /// Number of links to skip.
    /// </summary>
    public int SkipCount { get; init; }

    /// <summary>
    /// When the comparison was performed.
    /// </summary>
    public DateTime ComparedAt { get; init; } = DateTime.UtcNow;
}

/// <summary>
/// Simplified entity representation for comparison (contract version).
/// This mirrors the database entity but is kept in contracts for service boundary.
/// </summary>
public record DiscoveredLinkEntity
{
    /// <summary>
    /// Database ID.
    /// </summary>
    public long Id { get; init; }

    /// <summary>
    /// Source ID.
    /// </summary>
    public string SourceId { get; init; } = string.Empty;

    /// <summary>
    /// URL.
    /// </summary>
    public string Url { get; init; } = string.Empty;

    /// <summary>
    /// SHA256 hash of URL.
    /// </summary>
    public string UrlHash { get; init; } = string.Empty;

    /// <summary>
    /// ETag header.
    /// </summary>
    public string? Etag { get; init; }

    /// <summary>
    /// Last-Modified header.
    /// </summary>
    public DateTime? LastModified { get; init; }

    /// <summary>
    /// Content length.
    /// </summary>
    public long? ContentLength { get; init; }

    /// <summary>
    /// Content hash.
    /// </summary>
    public string? ContentHash { get; init; }

    /// <summary>
    /// Hash of metadata for quick comparison.
    /// </summary>
    public string? MetadataHash { get; init; }

    /// <summary>
    /// Metadata as JSON string.
    /// </summary>
    public string Metadata { get; init; } = "{}";

    /// <summary>
    /// Current status.
    /// </summary>
    public string Status { get; init; } = "pending";

    /// <summary>
    /// When first seen.
    /// </summary>
    public DateTime FirstSeenAt { get; init; }

    /// <summary>
    /// When last discovered.
    /// </summary>
    public DateTime DiscoveredAt { get; init; }
}
