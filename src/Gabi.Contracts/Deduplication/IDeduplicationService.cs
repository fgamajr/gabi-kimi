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
}
