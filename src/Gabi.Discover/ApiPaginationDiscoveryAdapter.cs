using System.Text.Json;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Net.Http.Headers;
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

        if (driver.Equals("btcu_api_v1", StringComparison.OrdinalIgnoreCase))
        {
            await foreach (var d in DiscoverBtcuApiAsync(sourceId, config, httpPolicy, ct))
                yield return d;
            yield break;
        }

        if (driver.Equals("senado_legislacao_api_v1", StringComparison.OrdinalIgnoreCase))
        {
            await foreach (var d in DiscoverSenadoLegislacaoAsync(sourceId, config, httpPolicy, ct))
                yield return d;
            yield break;
        }

        var endpoint = ResolveEndpoint(config);
        if (string.IsNullOrWhiteSpace(endpoint))
            throw new ArgumentException("api_pagination requires 'url' or 'endpoint' in discovery config", nameof(config));

        await foreach (var d in DiscoverGenericPaginatedApiAsync(sourceId, endpoint, httpPolicy, ct))
            yield return d;
    }

    private async IAsyncEnumerable<DiscoveredSource> DiscoverBtcuApiAsync(
        string sourceId,
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

        var page = pageStart;
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
                using var resp = await SendWithRetryAsync(() =>
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

                await DelayWithBackoffAsync(payloadAttempt, ct);
            }

            if (doc == null)
                yield break;

            using (doc)
            {
            var root = doc.RootElement;

            if (root.TryGetProperty("totalPages", out var totalPagesEl))
            {
                var resolvedTotalPages = ReadIntValue(totalPagesEl, totalPages);
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
                        ["strategy"] = StrategyKey,
                        ["driver"] = "btcu_api_v1",
                        ["api_page"] = page,
                        ["btcu_codigo"] = GetJsonValue(item, "codigo"),
                        ["btcu_tipo"] = GetJsonValue(item, "indTipo"),
                        ["btcu_tipo_descricao"] = GetJsonString(item, "descricaoTipo"),
                        ["btcu_data_publicacao"] = GetJsonString(item, "dataPublicacao"),
                        ["btcu_numero"] = GetJsonValue(item, "numero"),
                        ["btcu_descricao"] = GetJsonString(item, "descricao")
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

    private async IAsyncEnumerable<DiscoveredSource> DiscoverSenadoLegislacaoAsync(
        string sourceId,
        DiscoveryConfig config,
        DiscoveryHttpRequestPolicy httpPolicy,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct)
    {
        var endpointTemplate = ResolveSenadoEndpointTemplate(config);
        var tipo = ResolveSenadoTipo(config);
        var (startYear, endYear) = ResolveYearRange(config, "start_year");
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        for (var year = startYear; year <= endYear; year++)
        {
            ct.ThrowIfCancellationRequested();
            var endpoint = endpointTemplate
                .Replace("{tipo}", tipo, StringComparison.OrdinalIgnoreCase)
                .Replace("{year}", year.ToString(), StringComparison.OrdinalIgnoreCase);

            using var resp = await SendWithRetryAsync(() =>
            {
                var req = new HttpRequestMessage(HttpMethod.Get, endpoint);
                req.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
                return req;
            }, httpPolicy, ct);

            if (resp == null || !resp.IsSuccessStatusCode)
                yield break;

            await using var stream = await resp.Content.ReadAsStreamAsync(ct);
            using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: ct);

            foreach (var item in EnumerateSenadoDocumentItems(doc.RootElement))
            {
                var link = ExtractSenadoDetailLink(item);
                if (string.IsNullOrWhiteSpace(link) || !seen.Add(link))
                    continue;

                var metadata = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase)
                {
                    ["strategy"] = StrategyKey,
                    ["driver"] = "senado_legislacao_api_v1",
                    ["source_family"] = "senado_legislacao",
                    ["document_kind"] = "norma",
                    ["approval_state"] = "aprovada",
                    ["normative_force"] = "desconhecido",
                    ["tipo"] = tipo,
                    ["year"] = year,
                    ["senado_id"] = GetJsonValue(item, "id"),
                    ["senado_tipo"] = GetJsonString(item, "tipo"),
                    ["senado_numero"] = GetJsonString(item, "numero"),
                    ["senado_norma"] = GetJsonString(item, "norma"),
                    ["senado_norma_nome"] = GetJsonString(item, "normaNome"),
                    ["senado_data_assinatura"] = GetJsonString(item, "dataassinatura"),
                    ["senado_ano_assinatura"] = GetJsonString(item, "anoassinatura"),
                    ["senado_ementa"] = GetJsonString(item, "ementa")
                };

                yield return new DiscoveredSource(link, sourceId, metadata, DateTime.UtcNow);
            }

            if (httpPolicy.RequestDelayMs > 0 && year < endYear)
                await Task.Delay(httpPolicy.RequestDelayMs, ct);
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

    private static string ResolveSenadoEndpointTemplate(DiscoveryConfig config)
    {
        const string defaultTemplate = "https://legis.senado.leg.br/dadosabertos/legislacao/lista?tipo={tipo}&ano={year}";
        if (config.Extra != null
            && config.Extra.TryGetValue("endpoint_template", out var endpointEl)
            && endpointEl.ValueKind == JsonValueKind.String
            && !string.IsNullOrWhiteSpace(endpointEl.GetString()))
        {
            return endpointEl.GetString()!;
        }

        return defaultTemplate;
    }

    private static string ResolveSenadoTipo(DiscoveryConfig config)
    {
        if (config.Extra != null
            && config.Extra.TryGetValue("tipo", out var tipoEl)
            && tipoEl.ValueKind == JsonValueKind.String
            && !string.IsNullOrWhiteSpace(tipoEl.GetString()))
        {
            return tipoEl.GetString()!;
        }

        return "LEI";
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

    private Task<HttpResponseMessage?> SendWithRetryAsync(
        string url,
        DiscoveryHttpRequestPolicy httpPolicy,
        CancellationToken ct)
        => SendWithRetryAsync(() => new HttpRequestMessage(HttpMethod.Get, url), httpPolicy, ct);

    private async Task<HttpResponseMessage?> SendWithRetryAsync(
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

    private static string? ExtractBtcuPdfLink(JsonElement item, string pdfEndpointTemplate)
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

    private static IEnumerable<JsonElement> EnumerateSenadoDocumentItems(JsonElement root)
    {
        if (!root.TryGetProperty("ListaDocumento", out var lista) || lista.ValueKind != JsonValueKind.Object)
            yield break;

        if (!lista.TryGetProperty("documentos", out var documentos) || documentos.ValueKind != JsonValueKind.Object)
            yield break;

        if (!documentos.TryGetProperty("documento", out var documento))
            yield break;

        if (documento.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in documento.EnumerateArray())
                if (item.ValueKind == JsonValueKind.Object)
                    yield return item;
            yield break;
        }

        if (documento.ValueKind == JsonValueKind.Object)
            yield return documento;
    }

    private static string? ExtractSenadoDetailLink(JsonElement item)
    {
        if (item.ValueKind != JsonValueKind.Object || !item.TryGetProperty("id", out var idEl))
            return null;

        var id = idEl.ValueKind switch
        {
            JsonValueKind.Number when idEl.TryGetInt64(out var n) => n.ToString(),
            JsonValueKind.String => idEl.GetString(),
            _ => null
        };

        if (string.IsNullOrWhiteSpace(id))
            return null;

        return $"https://legis.senado.leg.br/dadosabertos/legislacao/{id}";
    }

    private static string ResolveBtcuEndpointTemplate(DiscoveryConfig config)
    {
        const string defaultTemplate = "https://btcu.apps.tcu.gov.br/api/filtrarBtcuPublicados/page/{page}";
        if (config.Extra != null
            && config.Extra.TryGetValue("endpoint_template", out var endpointEl)
            && endpointEl.ValueKind == JsonValueKind.String
            && !string.IsNullOrWhiteSpace(endpointEl.GetString()))
        {
            return endpointEl.GetString()!;
        }

        return defaultTemplate;
    }

    private static string ResolveBtcuPdfEndpointTemplate(DiscoveryConfig config)
    {
        const string defaultTemplate = "https://btcu.apps.tcu.gov.br/api/obterDocumentoPdf/{id}";
        if (config.Extra != null
            && config.Extra.TryGetValue("pdf_endpoint_template", out var endpointEl)
            && endpointEl.ValueKind == JsonValueKind.String
            && !string.IsNullOrWhiteSpace(endpointEl.GetString()))
        {
            return endpointEl.GetString()!;
        }

        return defaultTemplate;
    }

    private static string ResolveBtcuRequestBody(DiscoveryConfig config)
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

    private static int ResolveBtcuPageStart(DiscoveryConfig config)
    {
        if (config.Extra != null
            && config.Extra.TryGetValue("page_start", out var pageStartEl))
        {
            return Math.Max(0, ReadIntValue(pageStartEl, 0));
        }

        return 0;
    }

    private static int ResolveBtcuMaxPages(DiscoveryConfig config)
    {
        if (config.Extra != null
            && config.Extra.TryGetValue("max_pages", out var maxPagesEl))
        {
            return Math.Max(1, ReadIntValue(maxPagesEl, 500));
        }

        return 500;
    }

    private static int ReadIntValue(JsonElement value, int fallback)
        => value.ValueKind switch
        {
            JsonValueKind.Number when value.TryGetInt32(out var i) => i,
            JsonValueKind.String when int.TryParse(value.GetString(), out var i) => i,
            _ => fallback
        };

    private static object GetJsonValue(JsonElement obj, string propertyName)
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

    private static string GetJsonString(JsonElement obj, string propertyName)
    {
        if (!obj.TryGetProperty(propertyName, out var value) || value.ValueKind != JsonValueKind.String)
            return string.Empty;

        return value.GetString() ?? string.Empty;
    }

    private static bool TryParseJsonPayload(string payload, out JsonDocument? doc)
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
