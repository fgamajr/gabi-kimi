using Gabi.Contracts.Discovery;
using Gabi.Discover.Drivers;

namespace Gabi.Discover;

public sealed class ApiPaginationDiscoveryAdapter : IDiscoveryAdapter
{
    private readonly HttpClient _httpClient;

    public string StrategyKey => "api_pagination";

    public ApiPaginationDiscoveryAdapter(HttpClient? httpClient = null)
    {
        _httpClient = httpClient ?? new HttpClient();
    }

    public async IAsyncEnumerable<DiscoveredSource> DiscoverAsync(
        string sourceId,
        DiscoveryConfig config,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct = default)
    {
        var httpPolicy = DiscoveryHttpRequestPolicy.FromConfig(config);
        var driver = DiscoveryAdapterHelpers.ResolveDriver(config);

        if (driver.Equals("camara_api_v1", StringComparison.OrdinalIgnoreCase))
        {
            await foreach (var d in CamaraDiscoveryDriver.DiscoverCamaraApiAsync(_httpClient, sourceId, StrategyKey, config, httpPolicy, ct))
                yield return d;
            yield break;
        }

        if (driver.Equals("btcu_api_v1", StringComparison.OrdinalIgnoreCase))
        {
            await foreach (var d in BtcuDiscoveryDriver.DiscoverBtcuApiAsync(_httpClient, sourceId, StrategyKey, config, httpPolicy, ct))
                yield return d;
            yield break;
        }

        if (driver.Equals("senado_legislacao_api_v1", StringComparison.OrdinalIgnoreCase))
        {
            await foreach (var d in SenadoDiscoveryDriver.DiscoverSenadoLegislacaoAsync(_httpClient, sourceId, StrategyKey, config, httpPolicy, ct))
                yield return d;
            yield break;
        }

        if (driver.Equals("dou_inlabs_xml_v1", StringComparison.OrdinalIgnoreCase))
        {
            await foreach (var d in DouDiscoveryDriver.DiscoverDouInlabsXmlAsync(_httpClient, sourceId, StrategyKey, config, httpPolicy, ct))
                yield return d;
            yield break;
        }

        if (driver.Equals("dou_monthly_pattern_v1", StringComparison.OrdinalIgnoreCase))
        {
            await foreach (var d in DouDiscoveryDriver.DiscoverDouMonthlyPatternAsync(sourceId, StrategyKey, config, ct))
                yield return d;
            yield break;
        }

        if (driver.Equals("dou_public_monthly_v1", StringComparison.OrdinalIgnoreCase))
        {
            await foreach (var d in DouPublicMonthlyDriver.DiscoverAsync(
                _httpClient, sourceId, StrategyKey, config, httpPolicy, ct))
                yield return d;
            yield break;
        }

        if (driver.Equals("youtube_channel_v1", StringComparison.OrdinalIgnoreCase))
        {
            await foreach (var d in YouTubeDiscoveryDriver.DiscoverYouTubeChannelAsync(_httpClient, sourceId, StrategyKey, config, httpPolicy, ct))
                yield return d;
            yield break;
        }

        var endpoint = DiscoveryAdapterHelpers.ResolveEndpoint(config);
        if (string.IsNullOrWhiteSpace(endpoint))
            throw new ArgumentException("api_pagination requires 'url' or 'endpoint' in discovery config", nameof(config));

        await foreach (var d in GenericPaginatedDiscoveryDriver.DiscoverGenericPaginatedApiAsync(_httpClient, sourceId, StrategyKey, endpoint, httpPolicy, ct))
            yield return d;
    }
}
