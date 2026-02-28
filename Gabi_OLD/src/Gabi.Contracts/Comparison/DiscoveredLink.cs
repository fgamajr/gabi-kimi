namespace Gabi.Contracts.Comparison;

/// <summary>
/// A link discovered during source refresh (contract for comparison service).
/// </summary>
public record DiscoveredLink
{
    /// <summary>
    /// URL of the discovered link.
    /// </summary>
    public string Url { get; init; } = string.Empty;

    /// <summary>
    /// Source ID this link belongs to.
    /// </summary>
    public string SourceId { get; init; } = string.Empty;

    /// <summary>
    /// SHA256 hash of the URL.
    /// </summary>
    public string UrlHash { get; init; } = string.Empty;

    /// <summary>
    /// ETag header for change detection.
    /// </summary>
    public string? Etag { get; init; }

    /// <summary>
    /// Last-Modified header for change detection.
    /// </summary>
    public DateTime? LastModified { get; init; }

    /// <summary>
    /// Content length if available.
    /// </summary>
    public long? ContentLength { get; init; }

    /// <summary>
    /// Hash of the content (if already fetched).
    /// </summary>
    public string? ContentHash { get; init; }

    /// <summary>
    /// Document count if known from metadata (null for pattern-based discovery).
    /// </summary>
    public int? DocumentCount { get; init; }

    /// <summary>
    /// Total size in bytes if known.
    /// </summary>
    public long? TotalSizeBytes { get; init; }

    /// <summary>
    /// Flexible metadata dictionary.
    /// </summary>
    public IReadOnlyDictionary<string, object> Metadata { get; init; } = 
        new Dictionary<string, object>();

    /// <summary>
    /// When the link was discovered.
    /// </summary>
    public DateTime DiscoveredAt { get; init; } = DateTime.UtcNow;
}
