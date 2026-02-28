namespace Gabi.Contracts.Comparison;

/// <summary>
/// Interface for comparing discovered links with existing database entries.
/// </summary>
public interface ILinkComparator
{
    /// <summary>
    /// Compares a discovered link with existing database entry.
    /// </summary>
    /// <param name="discovered">The newly discovered link.</param>
    /// <param name="existing">The existing link from database (null if new).</param>
    /// <returns>Comparison result with recommended action.</returns>
    LinkComparisonResult Compare(DiscoveredLink discovered, DiscoveredLinkEntity? existing);

    /// <summary>
    /// Batch compare all discovered links against existing database state.
    /// </summary>
    /// <param name="sourceId">The source ID being processed.</param>
    /// <param name="discovered">List of newly discovered links.</param>
    /// <param name="existing">List of existing links from database.</param>
    /// <param name="ct">Cancellation token.</param>
    /// <returns>Batch comparison result with counts.</returns>
    Task<BatchComparisonResult> CompareBatchAsync(
        string sourceId,
        IReadOnlyList<DiscoveredLink> discovered,
        IReadOnlyList<DiscoveredLinkEntity> existing,
        CancellationToken ct = default);
}
