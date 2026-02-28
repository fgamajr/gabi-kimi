using System.Text.Json;
using Gabi.Contracts.Discovery;

namespace Gabi.Discover.Drivers;

internal static class GenericPaginatedDiscoveryDriver
{
    internal static async IAsyncEnumerable<DiscoveredSource> DiscoverGenericPaginatedApiAsync(
        HttpClient httpClient,
        string sourceId,
        string strategyKey,
        string initialEndpoint,
        DiscoveryHttpRequestPolicy httpPolicy,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct,
        Dictionary<string, object>? baseMetadata = null)
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var next = initialEndpoint;
        var pages = 0;
        const int maxPages = 500;

        while (!string.IsNullOrWhiteSpace(next) && pages < maxPages)
        {
            ct.ThrowIfCancellationRequested();
            pages++;

            using var resp = await DiscoveryAdapterHelpers.SendWithRetryAsync(httpClient, next, httpPolicy, ct);
            if (resp == null || !resp.IsSuccessStatusCode)
            {
                var statusCode = resp?.StatusCode.ToString() ?? "null";
                throw new HttpRequestException(
                    $"GenericPaginatedDiscoveryDriver: page {pages}/{maxPages} failed with status {statusCode} for URL {next}");
            }

            await using var stream = await resp.Content.ReadAsStreamAsync(ct);
            using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: ct);
            var root = doc.RootElement;

            if (root.TryGetProperty("dados", out var dados) && dados.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in dados.EnumerateArray())
                {
                    var link = CamaraDiscoveryDriver.ExtractResourceLink(item);
                    if (string.IsNullOrWhiteSpace(link))
                        continue;

                    if (!seen.Add(link))
                        continue;

                    var metadata = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase)
                    {
                        ["strategy"] = strategyKey,
                        ["api_page"] = pages
                    };

                    if (baseMetadata != null)
                    {
                        foreach (var (k, v) in baseMetadata)
                            metadata[k] = v;
                    }

                    yield return new DiscoveredSource(link, sourceId, metadata, DateTime.UtcNow);
                }
            }

            next = ExtractNextPage(root);

            if (!string.IsNullOrWhiteSpace(next) && httpPolicy.RequestDelayMs > 0)
                await Task.Delay(httpPolicy.RequestDelayMs, ct);
        }
    }

    internal static string? ExtractNextPage(JsonElement root)
    {
        if (!root.TryGetProperty("links", out var links) || links.ValueKind != JsonValueKind.Array)
            return null;

        foreach (var link in links.EnumerateArray())
        {
            if (link.ValueKind != JsonValueKind.Object)
                continue;

            var rel = link.TryGetProperty("rel", out var relEl) && relEl.ValueKind == JsonValueKind.String
                ? relEl.GetString()
                : null;
            if (!string.Equals(rel, "next", StringComparison.OrdinalIgnoreCase))
                continue;

            if (link.TryGetProperty("href", out var hrefEl) && hrefEl.ValueKind == JsonValueKind.String)
                return hrefEl.GetString();
        }

        return null;
    }
}
