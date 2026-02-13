using Microsoft.EntityFrameworkCore.Storage;
using Microsoft.Extensions.Logging;

namespace Gabi.Postgres.Repositories;

/// <summary>
/// Unit of Work implementation for GabiDbContext.
/// </summary>
public class UnitOfWork : IUnitOfWork
{
    private readonly GabiDbContext _context;
    private readonly ILogger<UnitOfWork> _logger;
    private IDbContextTransaction? _currentTransaction;

    private IDiscoveredLinkRepository? _discoveredLinks;
    private ISourceRegistryRepository? _sourceRegistries;
    private IDocumentRepository? _documents;

    /// <summary>
    /// Initializes a new instance of the UnitOfWork.
    /// </summary>
    public UnitOfWork(
        GabiDbContext context,
        ILogger<UnitOfWork> logger,
        IDiscoveredLinkRepository discoveredLinks,
        ISourceRegistryRepository sourceRegistries,
        IDocumentRepository documents)
    {
        _context = context;
        _logger = logger;
        _discoveredLinks = discoveredLinks;
        _sourceRegistries = sourceRegistries;
        _documents = documents;
    }

    /// <inheritdoc />
    public IDiscoveredLinkRepository DiscoveredLinks => _discoveredLinks!;

    /// <inheritdoc />
    public ISourceRegistryRepository SourceRegistries => _sourceRegistries!;

    /// <inheritdoc />
    public IDocumentRepository Documents => _documents!;

    /// <inheritdoc />
    public Task<int> SaveChangesAsync(CancellationToken ct = default)
    {
        return _context.SaveChangesAsync(ct);
    }

    /// <inheritdoc />
    public async Task<IDbContextTransaction> BeginTransactionAsync(CancellationToken ct = default)
    {
        if (_currentTransaction != null)
        {
            throw new InvalidOperationException("A transaction is already in progress");
        }

        _currentTransaction = await _context.Database.BeginTransactionAsync(ct);
        _logger.LogDebug("Database transaction started");
        return _currentTransaction;
    }

    /// <inheritdoc />
    public async Task CommitAsync(CancellationToken ct = default)
    {
        if (_currentTransaction == null)
        {
            throw new InvalidOperationException("No transaction in progress");
        }

        try
        {
            await _currentTransaction.CommitAsync(ct);
            _logger.LogDebug("Database transaction committed");
        }
        finally
        {
            await _currentTransaction.DisposeAsync();
            _currentTransaction = null;
        }
    }

    /// <inheritdoc />
    public async Task RollbackAsync(CancellationToken ct = default)
    {
        if (_currentTransaction == null)
        {
            throw new InvalidOperationException("No transaction in progress");
        }

        try
        {
            await _currentTransaction.RollbackAsync(ct);
            _logger.LogDebug("Database transaction rolled back");
        }
        finally
        {
            await _currentTransaction.DisposeAsync();
            _currentTransaction = null;
        }
    }

    /// <inheritdoc />
    public async ValueTask DisposeAsync()
    {
        if (_currentTransaction != null)
        {
            await _currentTransaction.DisposeAsync();
            _currentTransaction = null;
        }

        await _context.DisposeAsync();
    }
}
