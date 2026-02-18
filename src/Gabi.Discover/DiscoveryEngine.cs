using System.Runtime.CompilerServices;
using Gabi.Contracts.Discovery;

namespace Gabi.Discover;

/// <summary>
/// Engine de discovery que descobre URLs a partir de configurações.
/// </summary>
public class DiscoveryEngine : IDiscoveryEngine
{
    private readonly DiscoveryAdapterRegistry _adapterRegistry;

    public DiscoveryEngine()
        : this(new DiscoveryAdapterRegistry(new IDiscoveryAdapter[]
        {
            new StaticUrlDiscoveryAdapter(),
            new UrlPatternDiscoveryAdapter(),
            new WebCrawlDiscoveryAdapter(),
            new ApiPaginationDiscoveryAdapter()
        }))
    {
    }

    public DiscoveryEngine(DiscoveryAdapterRegistry adapterRegistry)
    {
        _adapterRegistry = adapterRegistry;
    }

    /// <inheritdoc />
    public Task<ChangeDetectionResult> CheckChangesAsync(
        DiscoveredSource source,
        ChangeDetectionConfig config,
        CancellationToken ct = default)
    {
        // Simplified implementation - in real scenario would check cache
        return Task.FromResult(new ChangeDetectionResult
        {
            HasChanged = true,
            ChangeType = "new"
        });
    }

    /// <inheritdoc />
    public async IAsyncEnumerable<DiscoveredSource> DiscoverAsync(
        string sourceId,
        DiscoveryConfig config,
        [EnumeratorCancellation] CancellationToken ct = default)
    {
        var adapter = _adapterRegistry.ResolveOrThrow(config.Strategy);
        await foreach (var discovered in adapter.DiscoverAsync(sourceId, config, ct))
            yield return discovered;
    }
}
