using Gabi.Postgres.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace Gabi.Postgres.Repositories;

/// <summary>
/// Repository for source registry operations.
/// </summary>
public class SourceRegistryRepository : ISourceRegistryRepository
{
    private readonly GabiDbContext _context;
    private readonly ILogger<SourceRegistryRepository> _logger;

    public SourceRegistryRepository(GabiDbContext context, ILogger<SourceRegistryRepository> logger)
    {
        _context = context;
        _logger = logger;
    }

    /// <inheritdoc />
    public async Task<IReadOnlyList<SourceRegistryEntity>> GetAllAsync(CancellationToken ct = default)
    {
        return await _context.SourceRegistries
            .AsNoTracking()
            .OrderBy(s => s.Name)
            .ToListAsync(ct);
    }

    /// <inheritdoc />
    public async Task<SourceRegistryEntity?> GetByIdAsync(string id, CancellationToken ct = default)
    {
        return await _context.SourceRegistries
            .AsNoTracking()
            .FirstOrDefaultAsync(s => s.Id == id, ct);
    }

    /// <inheritdoc />
    public async Task UpdateLastRefreshAsync(string id, DateTime refreshTime, int linkCount, CancellationToken ct = default)
    {
        var source = await _context.SourceRegistries
            .FirstOrDefaultAsync(s => s.Id == id, ct);

        if (source == null)
        {
            _logger.LogWarning("Source registry {SourceId} not found for refresh update", id);
            throw new InvalidOperationException($"Source registry '{id}' not found");
        }

        source.LastRefresh = refreshTime;
        source.TotalLinks = linkCount;
        source.UpdatedAt = DateTime.UtcNow;
        source.UpdatedBy = "system";

        _context.SourceRegistries.Update(source);
        
        _logger.LogInformation(
            "Updated source {SourceId} last refresh at {RefreshTime} with {LinkCount} links",
            id, refreshTime, linkCount);
    }

    /// <inheritdoc />
    public async Task UpsertAsync(SourceRegistryEntity source, CancellationToken ct = default)
    {
        var existing = await _context.SourceRegistries.FindAsync(new object[] { source.Id }, ct);

        if (existing == null)
        {
            await _context.SourceRegistries.AddAsync(source, ct);
            _logger.LogInformation("Created source registry entry for {SourceId}", source.Id);
        }
        else
        {
            // Update existing
            existing.Name = source.Name;
            existing.Description = source.Description;
            existing.Provider = source.Provider;
            existing.Domain = source.Domain;
            existing.Jurisdiction = source.Jurisdiction;
            existing.Category = source.Category;
            existing.CanonicalType = source.CanonicalType;
            existing.DiscoveryStrategy = source.DiscoveryStrategy;
            existing.DiscoveryConfig = source.DiscoveryConfig;
            existing.FetchProtocol = source.FetchProtocol;
            existing.FetchConfig = source.FetchConfig;
            existing.PipelineConfig = source.PipelineConfig;
            existing.Enabled = source.Enabled;
            existing.UpdatedAt = DateTime.UtcNow;

            _context.SourceRegistries.Update(existing);
            _logger.LogInformation("Updated source registry entry for {SourceId}", source.Id);
        }

        await _context.SaveChangesAsync(ct);
    }
}
