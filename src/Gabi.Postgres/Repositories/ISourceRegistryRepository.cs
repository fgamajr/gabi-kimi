using Gabi.Postgres.Entities;

namespace Gabi.Postgres.Repositories;

/// <summary>
/// Repository for source registry operations.
/// </summary>
public interface ISourceRegistryRepository
{
    /// <summary>
    /// Gets all source registries.
    /// </summary>
    Task<IReadOnlyList<SourceRegistryEntity>> GetAllAsync(CancellationToken ct = default);

    /// <summary>
    /// Gets a source registry by ID.
    /// </summary>
    Task<SourceRegistryEntity?> GetByIdAsync(string id, CancellationToken ct = default);

    /// <summary>
    /// Updates the last refresh timestamp and link count for a source.
    /// </summary>
    Task UpdateLastRefreshAsync(string id, DateTime refreshTime, int linkCount, CancellationToken ct = default);

    /// <summary>
    /// Upserts a source registry entry (insert or update).
    /// </summary>
    Task UpsertAsync(SourceRegistryEntity entity, CancellationToken ct = default);
}
