using System.Text.Json;
using Gabi.Contracts.Discovery;

namespace Gabi.Discover.Drivers;

internal static class CamaraDiscoveryDriver
{
    internal static async IAsyncEnumerable<DiscoveredSource> DiscoverCamaraApiAsync(
        HttpClient httpClient,
        string sourceId,
        string strategyKey,
        DiscoveryConfig config,
        DiscoveryHttpRequestPolicy httpPolicy,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct)
    {
        var (startYear, endYear) = DiscoveryAdapterHelpers.ResolveYearRange(config, "start_year");
        var endpointTemplate = ResolveCamaraEndpointTemplate(config);
        var resumeYear = DiscoveryAdapterHelpers.ReadResumeCursorInt(config, "resume_camara_year", startYear);

        for (var year = startYear; year <= endYear; year++)
        {
            if (year < resumeYear)
                continue; // skip years already fully processed before last checkpoint
            ct.ThrowIfCancellationRequested();
            var endpoint = endpointTemplate.Replace("{year}", year.ToString(), StringComparison.OrdinalIgnoreCase);

            await foreach (var d in GenericPaginatedDiscoveryDriver.DiscoverGenericPaginatedApiAsync(
                httpClient,
                sourceId,
                strategyKey,
                endpoint,
                httpPolicy,
                ct,
                new Dictionary<string, object>
                {
                    ["strategy"] = strategyKey,
                    ["driver"] = "camara_api_v1",
                    ["year"] = year,
                    ["source_family"] = "camara_proposicoes",
                    ["document_kind"] = "proposicao",
                    ["approval_state"] = "em_tramitacao"
                }))
            {
                yield return d;
            }

            if (httpPolicy.RequestDelayMs > 0 && year < endYear)
            {
                var yearDelay = Math.Max(httpPolicy.RequestDelayMs * 2, 2000);
                await Task.Delay(yearDelay, ct);
            }
        }
    }

    internal static string ResolveCamaraEndpointTemplate(DiscoveryConfig config)
    {
        if (config.Extra != null)
        {
            if (config.Extra.TryGetValue("endpoint_template", out var endpointTemplateEl)
                && endpointTemplateEl.ValueKind == JsonValueKind.String
                && !string.IsNullOrWhiteSpace(endpointTemplateEl.GetString()))
            {
                return endpointTemplateEl.GetString()!;
            }

            if (config.Extra.TryGetValue("endpoint", out var endpointEl)
                && endpointEl.ValueKind == JsonValueKind.String
                && !string.IsNullOrWhiteSpace(endpointEl.GetString()))
            {
                return endpointEl.GetString()!;
            }
        }

        throw new ArgumentException(
            "camara_api_v1 requires 'endpoint_template' in discovery config extra. " +
            "Add it to sources_v2.yaml — no URL defaults are allowed in code.",
            nameof(config));
    }

    internal static string? ExtractResourceLink(JsonElement item)
    {
        if (item.ValueKind != JsonValueKind.Object)
            return null;

        if (item.TryGetProperty("uri", out var uriEl) && uriEl.ValueKind == JsonValueKind.String)
            return uriEl.GetString();

        if (item.TryGetProperty("url", out var urlEl) && urlEl.ValueKind == JsonValueKind.String)
            return urlEl.GetString();

        if (item.TryGetProperty("id", out var idEl) && idEl.ValueKind == JsonValueKind.Number && idEl.TryGetInt64(out var id))
            return $"https://dadosabertos.camara.leg.br/api/v2/proposicoes/{id}";

        return null;
    }
}
