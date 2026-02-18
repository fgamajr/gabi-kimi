using Gabi.Contracts.Discovery;

namespace Gabi.Discover;

public sealed class StaticUrlDiscoveryAdapter : IDiscoveryAdapter
{
    public string StrategyKey => "static_url";

    public async IAsyncEnumerable<DiscoveredSource> DiscoverAsync(
        string sourceId,
        DiscoveryConfig config,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested();

        if (string.IsNullOrWhiteSpace(config.Url))
            throw new ArgumentException("URL is required for static_url strategy", nameof(config));

        yield return new DiscoveredSource(
            config.Url,
            sourceId,
            new Dictionary<string, object>(),
            DateTime.UtcNow);

        await Task.CompletedTask;
    }
}
