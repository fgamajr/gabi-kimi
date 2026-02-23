using Gabi.Contracts.Comparison;

namespace Gabi.Contracts.Deduplication;

/// <summary>
/// Service for deduplication operations.
/// </summary>
public interface IDeduplicationService
{
    /// <summary>
    /// Checks if a link is already in database.
    /// </summary>
    /// <param name="urlHash">SHA256 hash of the URL.</param>
    /// <param name="ct">Cancellation token.</param>
    /// <returns>True if link exists, false otherwise.</returns>
    Task<bool> ExistsAsync(string urlHash, CancellationToken ct = default);

    /// <summary>
    /// Gets existing link if present.
    /// </summary>
    /// <param name="urlHash">SHA256 hash of the URL.</param>
    /// <param name="ct">Cancellation token.</param>
    /// <returns>Existing link entity or null if not found.</returns>
    Task<DiscoveredLinkEntity?> GetExistingAsync(string urlHash, CancellationToken ct = default);

    /// <summary>
    /// Deduplicates a batch of discovered links against the database.
    /// </summary>
    /// <param name="sourceId">The source ID.</param>
    /// <param name="discovered">The list of discovered links.</param>
    /// <param name="ct">Cancellation token.</param>
    /// <returns>Batch comparison result containing counts and individual actions.</returns>
    Task<BatchComparisonResult> DeduplicateBatchAsync(string sourceId, IReadOnlyList<DiscoveredLink> discovered, CancellationToken ct = default);

    /// <summary>
    /// Deduplicates a single discovered link against the database.
    /// </summary>
    /// <param name="sourceId">The source ID.</param>
    /// <param name="discovered">The discovered link.</param>
    /// <param name="ct">Cancellation token.</param>
    /// <returns>Link comparison result.</returns>
    Task<LinkComparisonResult> DeduplicateAsync(string sourceId, DiscoveredLink discovered, CancellationToken ct = default);
}
