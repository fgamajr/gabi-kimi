using Microsoft.EntityFrameworkCore.Storage;

namespace Gabi.Postgres.Repositories;

/// <summary>
/// Unit of Work pattern for transaction management.
/// </summary>
public interface IUnitOfWork : IAsyncDisposable
{
    /// <summary>
    /// Repository for discovered links.
    /// </summary>
    IDiscoveredLinkRepository DiscoveredLinks { get; }

    /// <summary>
    /// Repository for source registries.
    /// </summary>
    ISourceRegistryRepository SourceRegistries { get; }

    /// <summary>
    /// Repository for documents.
    /// </summary>
    IDocumentRepository Documents { get; }

    /// <summary>
    /// Saves all pending changes to the database.
    /// </summary>
    Task<int> SaveChangesAsync(CancellationToken ct = default);

    /// <summary>
    /// Begins a new database transaction.
    /// </summary>
    Task<IDbContextTransaction> BeginTransactionAsync(CancellationToken ct = default);

    /// <summary>
    /// Commits the current transaction.
    /// </summary>
    Task CommitAsync(CancellationToken ct = default);

    /// <summary>
    /// Rolls back the current transaction.
    /// </summary>
    Task RollbackAsync(CancellationToken ct = default);
}
