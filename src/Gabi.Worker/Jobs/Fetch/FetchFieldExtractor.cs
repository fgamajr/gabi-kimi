using System.Text.Json;
using System.Text.RegularExpressions;
using Gabi.Fetch;

namespace Gabi.Worker.Jobs.Fetch;

internal static class FetchFieldExtractor
{
    internal static string? ExtractDocumentId(Dictionary<string, string> fields, JsonElement? parseConfig)
    {
        if (parseConfig == null)
            return null;

        try
        {
            if (parseConfig.Value.TryGetProperty("fields", out var fieldsConfig) &&
                fieldsConfig.TryGetProperty("document_id", out var docIdConfig))
            {
                var source = docIdConfig.GetProperty("source").GetString();
                if (source != null && fields.TryGetValue(source, out var value))
                {
                    var transforms = GetTransforms(docIdConfig);
                    return Transforms.ApplyChain(value, transforms);
                }
            }
        }
        catch
        {
            return null;
        }

        return null;
    }

    internal static string? ExtractTitle(Dictionary<string, string> fields, JsonElement? parseConfig)
    {
        if (parseConfig == null)
            return null;

        try
        {
            if (parseConfig.Value.TryGetProperty("fields", out var fieldsConfig))
            {
                foreach (var prop in fieldsConfig.EnumerateObject())
                {
                    if (prop.Name == "title" || prop.Name == "year")
                    {
                        var source = prop.Value.GetProperty("source").GetString();
                        if (source != null && fields.TryGetValue(source, out var value))
                        {
                            var transforms = GetTransforms(prop.Value);
                            return Transforms.ApplyChain(value, transforms);
                        }
                    }
                }
            }
        }
        catch
        {
            return null;
        }

        return null;
    }

    internal static string? ExtractContent(Dictionary<string, string> fields, JsonElement? parseConfig)
    {
        if (parseConfig == null)
            return null;

        try
        {
            if (parseConfig.Value.TryGetProperty("fields", out var fieldsConfig) &&
                fieldsConfig.TryGetProperty("content", out var contentConfig))
            {
                var source = contentConfig.GetProperty("source").GetString();
                if (source != null && fields.TryGetValue(source, out var value))
                {
                    var transforms = GetTransforms(contentConfig);
                    return Transforms.ApplyChain(value, transforms);
                }
            }
        }
        catch
        {
            return null;
        }

        return null;
    }

    internal static List<string> GetTransforms(JsonElement fieldConfig)
    {
        var transforms = new List<string>();
        if (fieldConfig.TryGetProperty("transforms", out var transformsProp) &&
            transformsProp.ValueKind == JsonValueKind.Array)
        {
            foreach (var t in transformsProp.EnumerateArray())
            {
                var transform = t.GetString();
                if (transform != null)
                    transforms.Add(transform);
            }
        }
        return transforms;
    }

    internal static JsonElement? TryReadPath(JsonElement root, string path)
    {
        var current = root;
        foreach (var segment in path.Split('.', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var match = Regex.Match(segment, @"^(?<name>[^\[]+)(\[(?<index>\d+)\])?$");
            if (!match.Success)
                return null;

            var name = match.Groups["name"].Value;
            if (!current.TryGetProperty(name, out current))
                return null;

            if (match.Groups["index"].Success)
            {
                if (current.ValueKind != JsonValueKind.Array || !int.TryParse(match.Groups["index"].Value, out var idx))
                    return null;
                if (idx < 0 || idx >= current.GetArrayLength())
                    return null;
                current = current[idx];
            }
        }

        return current;
    }

    internal static string? TryReadPathAsString(JsonElement root, string path)
    {
        var element = TryReadPath(root, path);
        if (!element.HasValue)
            return null;

        return element.Value.ValueKind switch
        {
            JsonValueKind.String => element.Value.GetString(),
            JsonValueKind.Number => element.Value.GetRawText(),
            JsonValueKind.True => "true",
            JsonValueKind.False => "false",
            _ => null
        };
    }

    internal static string? TryReadMetadataValueAsString(string? linkMetadataJson, string key)
    {
        if (string.IsNullOrWhiteSpace(linkMetadataJson))
            return null;

        try
        {
            using var doc = JsonDocument.Parse(linkMetadataJson);
            if (doc.RootElement.ValueKind != JsonValueKind.Object)
                return null;

            if (!doc.RootElement.TryGetProperty(key, out var value))
                return null;

            return value.ValueKind switch
            {
                JsonValueKind.String => value.GetString(),
                JsonValueKind.Number => value.GetRawText(),
                JsonValueKind.True => "true",
                JsonValueKind.False => "false",
                _ => null
            };
        }
        catch
        {
            return null;
        }
    }

    public static string BuildDocumentMetadataJson(string? linkMetadataJson, IReadOnlyDictionary<string, string> rowFields)
    {
        var rowAsObjects = rowFields.ToDictionary(kv => kv.Key, kv => (object)kv.Value, StringComparer.OrdinalIgnoreCase);
        return BuildDocumentMetadataJson(linkMetadataJson, rowAsObjects);
    }

    public static string BuildDocumentMetadataJson(string? linkMetadataJson, IReadOnlyDictionary<string, object> extractedFields)
    {
        var merged = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);

        if (!string.IsNullOrWhiteSpace(linkMetadataJson))
        {
            try
            {
                using var doc = JsonDocument.Parse(linkMetadataJson);
                if (doc.RootElement.ValueKind == JsonValueKind.Object)
                {
                    foreach (var property in doc.RootElement.EnumerateObject())
                    {
                        merged[property.Name] = ConvertJsonElementToObject(property.Value);
                    }
                }
            }
            catch (JsonException)
            {
                // Ignore malformed link metadata and fallback to row fields only.
            }
        }

        foreach (var (key, value) in extractedFields)
        {
            merged[key] = value;
        }

        return JsonSerializer.Serialize(merged);
    }

    public static string DeriveNormativeForce(IEnumerable<string> comentarios)
    {
        var joined = string.Join(" ", comentarios ?? []);
        if (string.IsNullOrWhiteSpace(joined))
            return "desconhecido";

        if (Regex.IsMatch(joined, "revoga", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant))
            return "revogada";
        if (Regex.IsMatch(joined, "altera.{0,40}provis", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant))
            return "modificada_provisoriamente";
        if (Regex.IsMatch(joined, "altera", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant))
            return "modificada";

        return "desconhecido";
    }

    internal static IEnumerable<string> CollectComentarios(JsonElement? root)
    {
        if (!root.HasValue)
            yield break;

        foreach (var text in CollectComentariosRecursive(root.Value))
            yield return text;
    }

    internal static IEnumerable<string> CollectComentariosRecursive(JsonElement node)
    {
        if (node.ValueKind == JsonValueKind.Object)
        {
            foreach (var prop in node.EnumerateObject())
            {
                if (prop.NameEquals("comentario") && prop.Value.ValueKind == JsonValueKind.String)
                {
                    var value = prop.Value.GetString();
                    if (!string.IsNullOrWhiteSpace(value))
                        yield return value!;
                }

                foreach (var nested in CollectComentariosRecursive(prop.Value))
                    yield return nested;
            }
        }
        else if (node.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in node.EnumerateArray())
            {
                foreach (var nested in CollectComentariosRecursive(item))
                    yield return nested;
            }
        }
    }

    internal static object? ConvertJsonElementToObject(JsonElement value)
    {
        return value.ValueKind switch
        {
            JsonValueKind.String => value.GetString(),
            JsonValueKind.Number when value.TryGetInt64(out var i64) => i64,
            JsonValueKind.Number when value.TryGetDouble(out var dbl) => dbl,
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            JsonValueKind.Null => null,
            JsonValueKind.Object => value.EnumerateObject()
                .ToDictionary(prop => prop.Name, prop => ConvertJsonElementToObject(prop.Value)),
            JsonValueKind.Array => value.EnumerateArray()
                .Select(ConvertJsonElementToObject)
                .ToList(),
            _ => value.GetRawText()
        };
    }
}
