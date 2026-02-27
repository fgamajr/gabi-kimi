namespace Gabi.Contracts.Pipeline;

/// <summary>
/// Slim repository interface for Phase 0 link persistence.
/// Uses Contracts-native types (DiscoveredLinkPhase0) so that Layer 4 (Gabi.Sync)
/// can depend on this without referencing Gabi.Postgres.
/// The implementation lives in Gabi.Postgres (Layer 2–3) and is wired in Gabi.Worker (Layer 5).
/// </summary>
public interface IPhase0LinkRepository
{
    /// <summary>
    /// Returns the persisted link for a given source + URL, or null if not yet seen.
    /// </summary>
    Task<DiscoveredLinkPhase0?> GetBySourceAndUrlAsync(string sourceId, string url, CancellationToken ct = default);

    /// <summary>
    /// Inserts or updates a batch of discovered links.
    /// Returns the number of rows affected.
    /// </summary>
    Task<int> BulkUpsertAsync(IEnumerable<DiscoveredLinkPhase0> links, CancellationToken ct = default);
}
