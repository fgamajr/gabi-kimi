using Gabi.Contracts.Discovery;

namespace Gabi.Postgres;

/// <summary>
/// Parse de payload JSON (e discoveryConfig) para uso pelo JobQueueRepository e pelo GabiJobRunner (Worker).
/// </summary>
public static class JobPayloadParser
{
    public static Dictionary<string, object> ParsePayload(string? payloadJson)
    {
        if (string.IsNullOrWhiteSpace(payloadJson)) return new Dictionary<string, object>();
        try
        {
            var doc = System.Text.Json.JsonSerializer.Deserialize<System.Text.Json.JsonElement>(payloadJson);
            return JsonElementToDictionary(doc);
        }
        catch
        {
            return new Dictionary<string, object>();
        }
    }

    public static DiscoveryConfig? ParseDiscoveryConfigFromPayload(string? payloadJson)
    {
        if (string.IsNullOrWhiteSpace(payloadJson)) return null;
        try
        {
            var doc = System.Text.Json.JsonSerializer.Deserialize<System.Text.Json.JsonElement>(payloadJson);
            if (!doc.TryGetProperty("discoveryConfig", out var dc)) return null;
            var innerJson = dc.ValueKind == System.Text.Json.JsonValueKind.String ? dc.GetString() : dc.GetRawText();
            if (string.IsNullOrWhiteSpace(innerJson)) return null;
            var options = new System.Text.Json.JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true,
                ReadCommentHandling = System.Text.Json.JsonCommentHandling.Skip,
                AllowTrailingCommas = true
            };
            try
            {
                return System.Text.Json.JsonSerializer.Deserialize<DiscoveryConfig>(innerJson, options);
            }
            catch
            {
                var fallback = System.Text.Json.JsonSerializer.Deserialize<System.Text.Json.JsonElement>(innerJson);
                var strategy = fallback.TryGetProperty("strategy", out var s) ? s.GetString() : null;
                var urlTemplate = fallback.TryGetProperty("urlTemplate", out var u) ? u.GetString() : null;
                if (string.IsNullOrEmpty(urlTemplate) && fallback.TryGetProperty("template", out var t))
                    urlTemplate = t.GetString();
                var url = fallback.TryGetProperty("url", out var urlNode) ? urlNode.GetString() : null;
                if (string.IsNullOrEmpty(strategy) && !string.IsNullOrEmpty(urlTemplate)) strategy = "url_pattern";
                if (string.IsNullOrEmpty(strategy)) strategy = "static_url";
                return new DiscoveryConfig
                {
                    Strategy = strategy ?? "static_url",
                    UrlTemplate = urlTemplate ?? "",
                    Url = url
                };
            }
        }
        catch
        {
            return null;
        }
    }

    private static Dictionary<string, object> JsonElementToDictionary(System.Text.Json.JsonElement el)
    {
        var d = new Dictionary<string, object>();
        foreach (var p in el.EnumerateObject())
        {
            d[p.Name] = p.Value.ValueKind switch
            {
                System.Text.Json.JsonValueKind.Object => JsonElementToDictionary(p.Value),
                System.Text.Json.JsonValueKind.Array => p.Value.EnumerateArray().Select(e => (object)e.Clone()).ToList(),
                System.Text.Json.JsonValueKind.String => p.Value.GetString() ?? "",
                System.Text.Json.JsonValueKind.Number => p.Value.TryGetInt64(out var n) ? n : p.Value.GetDouble(),
                System.Text.Json.JsonValueKind.True => true,
                System.Text.Json.JsonValueKind.False => false,
                _ => p.Value.Clone()
            };
        }
        return d;
    }
}
