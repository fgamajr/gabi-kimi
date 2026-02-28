using System.Net.Http.Headers;
using System.Text.Json;
using Gabi.Contracts.Discovery;

namespace Gabi.Discover.Drivers;

internal static class SenadoDiscoveryDriver
{
    internal static async IAsyncEnumerable<DiscoveredSource> DiscoverSenadoLegislacaoAsync(
        HttpClient httpClient,
        string sourceId,
        string strategyKey,
        DiscoveryConfig config,
        DiscoveryHttpRequestPolicy httpPolicy,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct)
    {
        var endpointTemplate = ResolveSenadoEndpointTemplate(config);
        var tipo = ResolveSenadoTipo(config);
        var (startYear, endYear) = DiscoveryAdapterHelpers.ResolveYearRange(config, "start_year");
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var resumeYear = DiscoveryAdapterHelpers.ReadResumeCursorInt(config, "resume_senado_year", startYear);

        for (var year = startYear; year <= endYear; year++)
        {
            if (year < resumeYear)
                continue; // skip years already fully processed before last checkpoint
            ct.ThrowIfCancellationRequested();
            var endpoint = endpointTemplate
                .Replace("{tipo}", tipo, StringComparison.OrdinalIgnoreCase)
                .Replace("{year}", year.ToString(), StringComparison.OrdinalIgnoreCase);

            using var resp = await DiscoveryAdapterHelpers.SendWithRetryAsync(httpClient, () =>
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
                    ["strategy"] = strategyKey,
                    ["driver"] = "senado_legislacao_api_v1",
                    ["source_family"] = "senado_legislacao",
                    ["document_kind"] = "norma",
                    ["approval_state"] = "aprovada",
                    ["normative_force"] = "desconhecido",
                    ["tipo"] = tipo,
                    ["year"] = year,
                    ["senado_id"] = DiscoveryAdapterHelpers.GetJsonValue(item, "id"),
                    ["senado_tipo"] = DiscoveryAdapterHelpers.GetJsonString(item, "tipo"),
                    ["senado_numero"] = DiscoveryAdapterHelpers.GetJsonString(item, "numero"),
                    ["senado_norma"] = DiscoveryAdapterHelpers.GetJsonString(item, "norma"),
                    ["senado_norma_nome"] = DiscoveryAdapterHelpers.GetJsonString(item, "normaNome"),
                    ["senado_data_assinatura"] = DiscoveryAdapterHelpers.GetJsonString(item, "dataassinatura"),
                    ["senado_ano_assinatura"] = DiscoveryAdapterHelpers.GetJsonString(item, "anoassinatura"),
                    ["senado_ementa"] = DiscoveryAdapterHelpers.GetJsonString(item, "ementa")
                };

                yield return new DiscoveredSource(link, sourceId, metadata, DateTime.UtcNow);
            }

            if (httpPolicy.RequestDelayMs > 0 && year < endYear)
                await Task.Delay(httpPolicy.RequestDelayMs, ct);
        }
    }

    internal static string ResolveSenadoEndpointTemplate(DiscoveryConfig config)
    {
        if (config.Extra != null
            && config.Extra.TryGetValue("endpoint_template", out var endpointEl)
            && endpointEl.ValueKind == JsonValueKind.String
            && !string.IsNullOrWhiteSpace(endpointEl.GetString()))
        {
            return endpointEl.GetString()!;
        }

        throw new ArgumentException(
            "senado_api_v1 requires 'endpoint_template' in discovery config extra. " +
            "Add it to sources_v2.yaml — no URL defaults are allowed in code.",
            nameof(config));
    }

    internal static string ResolveSenadoTipo(DiscoveryConfig config)
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

    internal static IEnumerable<JsonElement> EnumerateSenadoDocumentItems(JsonElement root)
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

    internal static string? ExtractSenadoDetailLink(JsonElement item)
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
}
