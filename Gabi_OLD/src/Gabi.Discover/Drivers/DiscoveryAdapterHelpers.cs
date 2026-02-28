using System.Net;
using System.Net.Sockets;
using System.Text.Json;
using Gabi.Contracts.Discovery;

namespace Gabi.Discover.Drivers;

internal static class DiscoveryAdapterHelpers
{
    internal static Task<HttpResponseMessage?> SendWithRetryAsync(
        HttpClient httpClient,
        string url,
        DiscoveryHttpRequestPolicy httpPolicy,
        CancellationToken ct)
        => SendWithRetryAsync(httpClient, () => new HttpRequestMessage(HttpMethod.Get, url), httpPolicy, ct);

    internal static async Task<HttpResponseMessage?> SendWithRetryAsync(
        HttpClient httpClient,
        Func<HttpRequestMessage> requestFactory,
        DiscoveryHttpRequestPolicy httpPolicy,
        CancellationToken ct)
    {
        const int maxRetries = 3;
        for (var attempt = 1; attempt <= maxRetries; attempt++)
        {
            HttpResponseMessage? response = null;
            try
            {
                using var req = requestFactory();
                httpPolicy.Apply(req);
                using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                timeoutCts.CancelAfter(httpPolicy.RequestTimeout);
                response = await httpClient.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, timeoutCts.Token);

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

    internal static bool IsTransient(Exception ex)
        => ex is HttpRequestException or SocketException or TaskCanceledException;

    internal static bool IsRetryableStatus(HttpStatusCode code)
        => code is HttpStatusCode.TooManyRequests or HttpStatusCode.BadGateway or HttpStatusCode.ServiceUnavailable;

    internal static Task DelayWithBackoffAsync(int attempt, CancellationToken ct)
    {
        var backoffMs = (int)(Math.Pow(2, attempt) * 1000) + Random.Shared.Next(0, 500);
        return Task.Delay(backoffMs, ct);
    }

    internal static string ResolveDriver(DiscoveryConfig config)
    {
        if (config.Extra != null && config.Extra.TryGetValue("driver", out var driverEl) && driverEl.ValueKind == JsonValueKind.String)
            return driverEl.GetString() ?? string.Empty;

        return string.Empty;
    }

    internal static string? ResolveEndpoint(DiscoveryConfig config)
    {
        if (!string.IsNullOrWhiteSpace(config.Url))
            return config.Url;

        if (config.Extra != null && config.Extra.TryGetValue("endpoint", out var endpointEl) && endpointEl.ValueKind == JsonValueKind.String)
            return endpointEl.GetString();

        return null;
    }

    internal static string GetJsonString(JsonElement obj, string propertyName)
    {
        if (!obj.TryGetProperty(propertyName, out var value) || value.ValueKind != JsonValueKind.String)
            return string.Empty;

        return value.GetString() ?? string.Empty;
    }

    internal static object GetJsonValue(JsonElement obj, string propertyName)
    {
        if (!obj.TryGetProperty(propertyName, out var value))
            return string.Empty;

        return value.ValueKind switch
        {
            JsonValueKind.Number when value.TryGetInt64(out var n) => n,
            JsonValueKind.String => value.GetString() ?? string.Empty,
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            _ => value.GetRawText()
        };
    }

    internal static int ReadIntValue(JsonElement value, int fallback)
        => value.ValueKind switch
        {
            JsonValueKind.Number when value.TryGetInt32(out var i) => i,
            JsonValueKind.String when int.TryParse(value.GetString(), out var i) => i,
            _ => fallback
        };

    internal static int ReadIntProperty(JsonElement obj, string propertyName, int fallback)
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

    internal static int ReadResumeCursorInt(DiscoveryConfig config, string key, int defaultVal)
    {
        if (config.Extra != null && config.Extra.TryGetValue(key, out var v))
        {
            if (v.ValueKind == JsonValueKind.Number && v.TryGetInt32(out var i)) return i;
            if (v.ValueKind == JsonValueKind.String && int.TryParse(v.GetString(), out var i2)) return i2;
        }
        return defaultVal;
    }

    internal static string? ReadResumeCursorString(DiscoveryConfig config, string key)
        => config.Extra != null && config.Extra.TryGetValue(key, out var v) && v.ValueKind == JsonValueKind.String
            ? v.GetString() : null;

    internal static (int StartYear, int EndYear) ResolveYearRange(DiscoveryConfig config, string parameterKey)
    {
        var currentYear = config.SnapshotAt?.Year ?? DateTime.UtcNow.Year;
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
}
