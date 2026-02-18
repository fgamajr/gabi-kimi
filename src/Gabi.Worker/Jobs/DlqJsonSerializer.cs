using System.Text.Json;

namespace Gabi.Worker.Jobs;

public static class DlqJsonSerializer
{
    public static string? SerializePayload(object? payload)
    {
        if (payload is null)
        {
            return null;
        }

        if (payload is JsonElement jsonElement)
        {
            return jsonElement.GetRawText();
        }

        if (payload is string text)
        {
            if (TryNormalizeJson(text, out var normalized))
            {
                return normalized;
            }

            return JsonSerializer.Serialize(text);
        }

        return JsonSerializer.Serialize(payload);
    }

    public static string? SerializeStackTrace(string? stackTrace)
    {
        if (string.IsNullOrWhiteSpace(stackTrace))
        {
            return null;
        }

        var lines = stackTrace
            .Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

        return JsonSerializer.Serialize(new
        {
            text = stackTrace,
            lines
        });
    }

    private static bool TryNormalizeJson(string value, out string normalizedJson)
    {
        try
        {
            using var document = JsonDocument.Parse(value);
            normalizedJson = JsonSerializer.Serialize(document.RootElement);
            return true;
        }
        catch (JsonException)
        {
            normalizedJson = string.Empty;
            return false;
        }
    }
}
