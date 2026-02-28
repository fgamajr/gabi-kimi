using System.Text;
using System.Text.Json;
using Gabi.Contracts.Discovery;

namespace Gabi.Discover.Drivers;

internal static class BtcuDiscoveryDriver
{
    internal static async IAsyncEnumerable<DiscoveredSource> DiscoverBtcuApiAsync(
        HttpClient httpClient,
        string sourceId,
        string strategyKey,
        DiscoveryConfig config,
        DiscoveryHttpRequestPolicy httpPolicy,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct)
    {
        var endpointTemplate = ResolveBtcuEndpointTemplate(config);
        var pdfEndpointTemplate = ResolveBtcuPdfEndpointTemplate(config);
        var requestBodyJson = ResolveBtcuRequestBody(config);
        var pageStart = ResolveBtcuPageStart(config);
        var maxPages = ResolveBtcuMaxPages(config);
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        var page = Math.Max(pageStart, DiscoveryAdapterHelpers.ReadResumeCursorInt(config, "resume_btcu_page", pageStart));
        var pagesProcessed = 0;
        var totalPages = int.MaxValue;

        while (pagesProcessed < maxPages && page < totalPages)
        {
            ct.ThrowIfCancellationRequested();
            pagesProcessed++;

            var endpoint = endpointTemplate.Replace("{page}", page.ToString(), StringComparison.OrdinalIgnoreCase);
            JsonDocument? doc = null;
            const int maxPayloadAttempts = 3;
            for (var payloadAttempt = 1; payloadAttempt <= maxPayloadAttempts; payloadAttempt++)
            {
                using var resp = await DiscoveryAdapterHelpers.SendWithRetryAsync(httpClient, () =>
                {
                    var req = new HttpRequestMessage(HttpMethod.Post, endpoint);
                    req.Content = new StringContent(requestBodyJson, Encoding.UTF8, "application/json");
                    return req;
                }, httpPolicy, ct);

                if (resp == null || !resp.IsSuccessStatusCode)
                    yield break;

                var payload = await resp.Content.ReadAsStringAsync(ct);
                if (TryParseJsonPayload(payload, out var parsed))
                {
                    doc = parsed;
                    break;
                }

                if (payloadAttempt >= maxPayloadAttempts)
                {
                    yield break;
                }

                await DiscoveryAdapterHelpers.DelayWithBackoffAsync(payloadAttempt, ct);
            }

            if (doc == null)
                yield break;

            using (doc)
            {
                var root = doc.RootElement;

                if (root.TryGetProperty("totalPages", out var totalPagesEl))
                {
                    var resolvedTotalPages = DiscoveryAdapterHelpers.ReadIntValue(totalPagesEl, totalPages);
                    if (resolvedTotalPages > 0)
                        totalPages = resolvedTotalPages;
                }

                if (root.TryGetProperty("content", out var content) && content.ValueKind == JsonValueKind.Array)
                {
                    foreach (var item in content.EnumerateArray())
                    {
                        var link = ExtractBtcuPdfLink(item, pdfEndpointTemplate);
                        if (string.IsNullOrWhiteSpace(link) || !seen.Add(link))
                            continue;

                        var metadata = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase)
                        {
                            ["strategy"] = strategyKey,
                            ["driver"] = "btcu_api_v1",
                            ["api_page"] = page,
                            ["btcu_codigo"] = DiscoveryAdapterHelpers.GetJsonValue(item, "codigo"),
                            ["btcu_tipo"] = DiscoveryAdapterHelpers.GetJsonValue(item, "indTipo"),
                            ["btcu_tipo_descricao"] = DiscoveryAdapterHelpers.GetJsonString(item, "descricaoTipo"),
                            ["btcu_data_publicacao"] = DiscoveryAdapterHelpers.GetJsonString(item, "dataPublicacao"),
                            ["btcu_numero"] = DiscoveryAdapterHelpers.GetJsonValue(item, "numero"),
                            ["btcu_descricao"] = DiscoveryAdapterHelpers.GetJsonString(item, "descricao")
                        };

                        yield return new DiscoveredSource(link, sourceId, metadata, DateTime.UtcNow);
                    }
                }
            }

            page++;
            if (httpPolicy.RequestDelayMs > 0 && page < totalPages && pagesProcessed < maxPages)
                await Task.Delay(httpPolicy.RequestDelayMs, ct);
        }
    }

    internal static string ResolveBtcuEndpointTemplate(DiscoveryConfig config)
    {
        if (config.Extra != null
            && config.Extra.TryGetValue("endpoint_template", out var endpointEl)
            && endpointEl.ValueKind == JsonValueKind.String
            && !string.IsNullOrWhiteSpace(endpointEl.GetString()))
        {
            return endpointEl.GetString()!;
        }

        throw new ArgumentException(
            "btcu_api_v1 requires 'endpoint_template' in discovery config extra. " +
            "Add it to sources_v2.yaml — no URL defaults are allowed in code.",
            nameof(config));
    }

    internal static string ResolveBtcuPdfEndpointTemplate(DiscoveryConfig config)
    {
        if (config.Extra != null
            && config.Extra.TryGetValue("pdf_endpoint_template", out var endpointEl)
            && endpointEl.ValueKind == JsonValueKind.String
            && !string.IsNullOrWhiteSpace(endpointEl.GetString()))
        {
            return endpointEl.GetString()!;
        }

        throw new ArgumentException(
            "btcu_api_v1 requires 'pdf_endpoint_template' in discovery config extra. " +
            "Add it to sources_v2.yaml — no URL defaults are allowed in code.",
            nameof(config));
    }

    internal static string ResolveBtcuRequestBody(DiscoveryConfig config)
    {
        if (config.Extra != null
            && config.Extra.TryGetValue("request_body", out var bodyEl))
        {
            return bodyEl.ValueKind switch
            {
                JsonValueKind.Object => bodyEl.GetRawText(),
                JsonValueKind.Array => bodyEl.GetRawText(),
                JsonValueKind.String => bodyEl.GetString() ?? "{}",
                _ => "{}"
            };
        }

        return "{}";
    }

    internal static int ResolveBtcuPageStart(DiscoveryConfig config)
    {
        if (config.Extra != null
            && config.Extra.TryGetValue("page_start", out var pageStartEl))
        {
            return Math.Max(0, DiscoveryAdapterHelpers.ReadIntValue(pageStartEl, 0));
        }

        return 0;
    }

    internal static int ResolveBtcuMaxPages(DiscoveryConfig config)
    {
        if (config.Extra != null
            && config.Extra.TryGetValue("max_pages", out var maxPagesEl))
        {
            return Math.Max(1, DiscoveryAdapterHelpers.ReadIntValue(maxPagesEl, 500));
        }

        return 500;
    }

    internal static string? ExtractBtcuPdfLink(JsonElement item, string pdfEndpointTemplate)
    {
        if (item.ValueKind != JsonValueKind.Object)
            return null;

        if (!item.TryGetProperty("codigoDocumentoTramitavel", out var codeEl))
            return null;

        var code = codeEl.ValueKind switch
        {
            JsonValueKind.Number when codeEl.TryGetInt64(out var n) => n.ToString(),
            JsonValueKind.String => codeEl.GetString(),
            _ => null
        };

        if (string.IsNullOrWhiteSpace(code))
            return null;

        return pdfEndpointTemplate.Replace("{id}", code, StringComparison.OrdinalIgnoreCase);
    }

    internal static bool TryParseJsonPayload(string payload, out JsonDocument? doc)
    {
        doc = null;
        if (string.IsNullOrWhiteSpace(payload))
            return false;

        try
        {
            doc = JsonDocument.Parse(payload);
            return true;
        }
        catch (JsonException)
        {
            return false;
        }
    }
}
