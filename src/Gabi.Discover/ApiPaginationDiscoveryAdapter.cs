using System.Text.Json;
using System.Net;
using System.Net.Sockets;
using Gabi.Contracts.Discovery;

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
        var driver = ResolveDriver(config);

        if (driver.Equals("camara_api_v1", StringComparison.OrdinalIgnoreCase))
        {
            await foreach (var d in DiscoverCamaraApiAsync(sourceId, config, httpPolicy, ct))
                yield return d;
            yield break;
        }

        var endpoint = ResolveEndpoint(config);
        if (string.IsNullOrWhiteSpace(endpoint))
            throw new ArgumentException("api_pagination requires 'url' or 'endpoint' in discovery config", nameof(config));

        await foreach (var d in DiscoverGenericPaginatedApiAsync(sourceId, endpoint, httpPolicy, ct))
            yield return d;
    }

    private async IAsyncEnumerable<DiscoveredSource> DiscoverCamaraApiAsync(
        string sourceId,
        DiscoveryConfig config,
        DiscoveryHttpRequestPolicy httpPolicy,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct)
    {
        var (startYear, endYear) = ResolveYearRange(config, "start_year");
        var endpointTemplate = ResolveCamaraEndpointTemplate(config);

        for (var year = startYear; year <= endYear; year++)
        {
            ct.ThrowIfCancellationRequested();
            var endpoint = endpointTemplate.Replace("{year}", year.ToString(), StringComparison.OrdinalIgnoreCase);

            await foreach (var d in DiscoverGenericPaginatedApiAsync(sourceId, endpoint, httpPolicy, ct, new Dictionary<string, object>
            {
                ["strategy"] = StrategyKey,
                ["driver"] = "camara_api_v1",
                ["year"] = year
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

    private static string ResolveCamaraEndpointTemplate(DiscoveryConfig config)
    {
        const string defaultTemplate = "https://dadosabertos.camara.leg.br/api/v2/proposicoes?siglaTipo=PL&ano={year}&itens=100&ordem=ASC&ordenarPor=id";

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

        return defaultTemplate;
    }

    private async IAsyncEnumerable<DiscoveredSource> DiscoverGenericPaginatedApiAsync(
        string sourceId,
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

            using var resp = await SendWithRetryAsync(next, httpPolicy, ct);
            if (resp == null || !resp.IsSuccessStatusCode)
                yield break;

            await using var stream = await resp.Content.ReadAsStreamAsync(ct);
            using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: ct);
            var root = doc.RootElement;

            if (root.TryGetProperty("dados", out var dados) && dados.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in dados.EnumerateArray())
                {
                    var link = ExtractResourceLink(item);
                    if (string.IsNullOrWhiteSpace(link))
                        continue;

                    if (!seen.Add(link))
                        continue;

                    var metadata = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase)
                    {
                        ["strategy"] = StrategyKey,
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

    private async Task<HttpResponseMessage?> SendWithRetryAsync(
        string url,
        DiscoveryHttpRequestPolicy httpPolicy,
        CancellationToken ct)
    {
        const int maxRetries = 3;
        for (var attempt = 1; attempt <= maxRetries; attempt++)
        {
            HttpResponseMessage? response = null;
            try
            {
                using var req = new HttpRequestMessage(HttpMethod.Get, url);
                httpPolicy.Apply(req);
                using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                timeoutCts.CancelAfter(httpPolicy.RequestTimeout);
                response = await _httpClient.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, timeoutCts.Token);

                if (response.IsSuccessStatusCode)
                    return response;

                if (attempt < maxRetries && IsRetryableStatus(response.StatusCode))
                {
                    response.Dispose();
                    await DelayWithBackoffAsync(attempt, ct);
                    continue;
                }

                return response;
            }
            catch (Exception ex) when (!ct.IsCancellationRequested && IsTransient(ex))
            {
                response?.Dispose();
                if (attempt >= maxRetries)
                    return null;
                await DelayWithBackoffAsync(attempt, ct);
            }
        }

        return null;
    }

    private static bool IsTransient(Exception ex)
        => ex is HttpRequestException or SocketException or TaskCanceledException;

    private static bool IsRetryableStatus(HttpStatusCode code)
        => code is HttpStatusCode.TooManyRequests or HttpStatusCode.BadGateway or HttpStatusCode.ServiceUnavailable;

    private static Task DelayWithBackoffAsync(int attempt, CancellationToken ct)
    {
        var backoffMs = (int)(Math.Pow(2, attempt) * 1000) + Random.Shared.Next(0, 500);
        return Task.Delay(backoffMs, ct);
    }

    private static string ResolveDriver(DiscoveryConfig config)
    {
        if (config.Extra != null && config.Extra.TryGetValue("driver", out var driverEl) && driverEl.ValueKind == JsonValueKind.String)
            return driverEl.GetString() ?? string.Empty;

        return string.Empty;
    }

    private static string? ResolveEndpoint(DiscoveryConfig config)
    {
        if (!string.IsNullOrWhiteSpace(config.Url))
            return config.Url;

        if (config.Extra != null && config.Extra.TryGetValue("endpoint", out var endpointEl) && endpointEl.ValueKind == JsonValueKind.String)
            return endpointEl.GetString();

        return null;
    }

    private static (int StartYear, int EndYear) ResolveYearRange(DiscoveryConfig config, string parameterKey)
    {
        var currentYear = DateTime.UtcNow.Year;
        if (config.Params == null || !config.Params.TryGetValue(parameterKey, out var param))
            return (currentYear, currentYear);

        if (param is JsonElement je && je.ValueKind == JsonValueKind.Object)
        {
            var start = ReadIntProperty(je, "start", currentYear);
            if (start == currentYear)
                start = ReadIntProperty(je, "Start", currentYear);

            var end = currentYear;
            if (je.TryGetProperty("end", out var endEl) || je.TryGetProperty("End", out endEl))
            {
                end = endEl.ValueKind switch
                {
                    JsonValueKind.Number when endEl.TryGetInt32(out var ei) => ei,
                    JsonValueKind.String when endEl.GetString()?.Equals("current", StringComparison.OrdinalIgnoreCase) == true => currentYear,
                    JsonValueKind.String when int.TryParse(endEl.GetString(), out var parsed) => parsed,
                    _ => currentYear
                };
            }

            return (Math.Min(start, end), Math.Max(start, end));
        }

        return (currentYear, currentYear);
    }

    private static int ReadIntProperty(JsonElement obj, string propertyName, int fallback)
    {
        if (!obj.TryGetProperty(propertyName, out var value))
            return fallback;

        return value.ValueKind switch
        {
            JsonValueKind.Number when value.TryGetInt32(out var i) => i,
            JsonValueKind.String when int.TryParse(value.GetString(), out var i) => i,
            _ => fallback
        };
    }

    private static string? ExtractResourceLink(JsonElement item)
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

    private static string? ExtractNextPage(JsonElement root)
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
