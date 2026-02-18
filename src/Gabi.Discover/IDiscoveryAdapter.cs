using Gabi.Contracts.Discovery;

namespace Gabi.Discover;

public interface IDiscoveryAdapter
{
    string StrategyKey { get; }

    IAsyncEnumerable<DiscoveredSource> DiscoverAsync(
        string sourceId,
        DiscoveryConfig config,
        CancellationToken ct = default);
}
