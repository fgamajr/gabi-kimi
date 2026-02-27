using System.Text.Json;

namespace Gabi.Worker.Jobs.Fetch;

internal static class FetchPayloadOptions
{
    public static int? ReadMaxDocsPerSource(Dictionary<string, object>? payload)
    {
        if (payload == null || !payload.TryGetValue("max_docs_per_source", out var raw) || raw == null)
            return null;

        static int? Normalize(int value) => value > 0 ? value : null;
        static int? ParseString(string? text)
        {
            if (string.IsNullOrWhiteSpace(text))
                return null;
            if (int.TryParse(text, out var parsed))
                return Normalize(parsed);
            if (long.TryParse(text, out var parsedLong) && parsedLong is > 0 and <= int.MaxValue)
                return (int)parsedLong;
            if (double.TryParse(text, out var parsedDouble) && parsedDouble > 0)
                return Normalize((int)Math.Floor(parsedDouble));
            return null;
        }

        return raw switch
        {
            int v => Normalize(v),
            long v when v > 0 && v <= int.MaxValue => (int)v,
            double v when v > 0 && v <= int.MaxValue => Normalize((int)Math.Floor(v)),
            float v when v > 0 && v <= int.MaxValue => Normalize((int)Math.Floor(v)),
            decimal v when v > 0 && v <= int.MaxValue => Normalize((int)Math.Floor(v)),
            string s => ParseString(s),
            JsonElement element => element.ValueKind switch
            {
                JsonValueKind.Number when element.TryGetInt32(out var parsedInt) => Normalize(parsedInt),
                JsonValueKind.Number when element.TryGetInt64(out var parsedLong) && parsedLong is > 0 and <= int.MaxValue => (int)parsedLong,
                JsonValueKind.String => ParseString(element.GetString()),
                _ => ParseString(element.ToString())
            },
            _ => ParseString(raw.ToString())
        };
    }

    public static bool ReadStrictCoverage(Dictionary<string, object>? payload)
    {
        if (payload == null || !payload.TryGetValue("strict_coverage", out var raw) || raw == null)
            return false;

        return raw switch
        {
            bool b => b,
            string s when bool.TryParse(s, out var parsedBool) => parsedBool,
            int i => i > 0,
            long l => l > 0,
            JsonElement element => element.ValueKind switch
            {
                JsonValueKind.True => true,
                JsonValueKind.False => false,
                JsonValueKind.String when bool.TryParse(element.GetString(), out var parsedBool) => parsedBool,
                JsonValueKind.Number when element.TryGetInt32(out var parsedInt) => parsedInt > 0,
                _ => false
            },
            _ => false
        };
    }

    /// <summary>Reads min_coverage_ratio from job payload (0.0–1.0; default 0.5). Used for discovery coverage gate.</summary>
    public static double ReadMinCoverageRatio(Dictionary<string, object>? payload)
    {
        if (payload == null || !payload.TryGetValue("min_coverage_ratio", out var raw) || raw == null)
            return 0.5;

        static double Clamp(double v) => Math.Clamp(v, 0.0, 1.0);
        return raw switch
        {
            double d => Clamp(d),
            float f => Clamp(f),
            int i => Clamp(i / 100.0),
            long l => Clamp(l / 100.0),
            decimal dec => Clamp((double)dec),
            string s when double.TryParse(s, System.Globalization.NumberStyles.Any, System.Globalization.CultureInfo.InvariantCulture, out var parsed) => Clamp(parsed),
            JsonElement element => element.ValueKind switch
            {
                JsonValueKind.Number when element.TryGetDouble(out var d) => Clamp(d),
                JsonValueKind.String when double.TryParse(element.GetString(), System.Globalization.NumberStyles.Any, System.Globalization.CultureInfo.InvariantCulture, out var d) => Clamp(d),
                _ => 0.5
            },
            _ => double.TryParse(raw.ToString(), System.Globalization.NumberStyles.Any, System.Globalization.CultureInfo.InvariantCulture, out var p) ? Clamp(p) : 0.5
        };
    }

    /// <summary>Reads zero_ok from job payload (when true, 0 links discovered is accepted; default false).</summary>
    public static bool ReadZeroOk(Dictionary<string, object>? payload)
    {
        if (payload == null || !payload.TryGetValue("zero_ok", out var raw) || raw == null)
            return false;

        return raw switch
        {
            bool b => b,
            string s when bool.TryParse(s, out var parsedBool) => parsedBool,
            int i => i > 0,
            long l => l > 0,
            JsonElement element => element.ValueKind switch
            {
                JsonValueKind.True => true,
                JsonValueKind.False => false,
                JsonValueKind.String when bool.TryParse(element.GetString(), out var parsedBool) => parsedBool,
                JsonValueKind.Number when element.TryGetInt32(out var parsedInt) => parsedInt > 0,
                _ => false
            },
            _ => false
        };
    }
}
