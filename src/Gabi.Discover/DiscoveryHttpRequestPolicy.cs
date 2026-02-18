using System.Text.Json;
using System.Threading;
using System.Collections.Concurrent;

namespace Gabi.Discover;

public sealed class DiscoveryHttpRequestPolicy
{
    private const string UserAgentFileEnvVar = "GABI_DISCOVERY_UA_FILE";
    private static readonly ConcurrentDictionary<string, IReadOnlyList<string>> UserAgentFileCache = new(StringComparer.OrdinalIgnoreCase);
    private int _requestIndex = -1;

    public IReadOnlyList<string> UserAgents { get; init; } = UserAgentCatalog.Default;
    public string UserAgentMode { get; init; } = "rotate";
    public TimeSpan RequestTimeout { get; init; } = TimeSpan.FromMinutes(2);
    public int RequestDelayMs { get; init; }

    public static DiscoveryHttpRequestPolicy FromConfig(Contracts.Discovery.DiscoveryConfig config)
    {
        var httpNode = ReadHttpNode(config.Extra);
        var mode = ReadString(httpNode, "user_agent_mode")
            ?? ReadString(httpNode, "mode")
            ?? "rotate";

        var configuredAgents = ReadStringArray(httpNode, "user_agents");
        if (configuredAgents.Count == 0)
        {
            var single = ReadString(httpNode, "user_agent");
            if (!string.IsNullOrWhiteSpace(single))
                configuredAgents.Add(single);
        }
        if (configuredAgents.Count == 0)
        {
            var filePath = ReadString(httpNode, "user_agents_file")
                ?? Environment.GetEnvironmentVariable(UserAgentFileEnvVar);
            configuredAgents.AddRange(ReadUserAgentsFromFile(filePath));
        }

        var timeout = ParseTimeout(
            ReadString(httpNode, "timeout")
            ?? ReadString(httpNode, "request_timeout")
            ?? ReadString(httpNode, "request_timeout_seconds"));
        var requestDelayMs = ParseInt(ReadString(httpNode, "request_delay_ms"), 0);

        return new DiscoveryHttpRequestPolicy
        {
            UserAgentMode = mode,
            UserAgents = configuredAgents.Count > 0 ? configuredAgents : UserAgentCatalog.Default,
            RequestTimeout = timeout,
            RequestDelayMs = requestDelayMs
        };
    }

    public void Apply(HttpRequestMessage request)
    {
        if (request == null)
            return;

        request.Headers.UserAgent.Clear();

        var ua = SelectUserAgent();
        if (!string.IsNullOrWhiteSpace(ua))
            request.Headers.TryAddWithoutValidation("User-Agent", ua);
    }

    private string SelectUserAgent()
    {
        if (UserAgents.Count == 0)
            return UserAgentCatalog.Default[0];

        if (UserAgentMode.Equals("fixed", StringComparison.OrdinalIgnoreCase))
            return UserAgents[0];

        if (UserAgentMode.Equals("random", StringComparison.OrdinalIgnoreCase))
            return UserAgents[Random.Shared.Next(0, UserAgents.Count)];

        var idx = Interlocked.Increment(ref _requestIndex);
        return UserAgents[idx % UserAgents.Count];
    }

    private static Dictionary<string, JsonElement> ReadHttpNode(Dictionary<string, JsonElement>? extra)
    {
        if (extra == null)
            return new Dictionary<string, JsonElement>(StringComparer.OrdinalIgnoreCase);

        if (!extra.TryGetValue("http", out var httpEl) || httpEl.ValueKind != JsonValueKind.Object)
            return extra;

        return httpEl.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.Clone(), StringComparer.OrdinalIgnoreCase);
    }

    private static string? ReadString(Dictionary<string, JsonElement> node, string key)
    {
        if (!node.TryGetValue(key, out var value))
            return null;

        return value.ValueKind switch
        {
            JsonValueKind.String => value.GetString(),
            JsonValueKind.Number => value.GetRawText(),
            _ => null
        };
    }

    private static List<string> ReadStringArray(Dictionary<string, JsonElement> node, string key)
    {
        if (!node.TryGetValue(key, out var value) || value.ValueKind != JsonValueKind.Array)
            return [];

        var items = new List<string>();
        foreach (var entry in value.EnumerateArray())
        {
            if (entry.ValueKind != JsonValueKind.String)
                continue;
            var str = entry.GetString();
            if (!string.IsNullOrWhiteSpace(str))
                items.Add(str);
        }

        return items;
    }

    private static IReadOnlyList<string> ReadUserAgentsFromFile(string? filePath)
    {
        if (string.IsNullOrWhiteSpace(filePath))
            return [];

        var absolutePath = Path.GetFullPath(filePath);

        try
        {
            return UserAgentFileCache.GetOrAdd(absolutePath, path =>
            {
                if (!File.Exists(path))
                    return [];

                var values = File.ReadAllLines(path)
                    .Select(l => l.Trim())
                    .Where(l => !string.IsNullOrWhiteSpace(l))
                    .Where(l => !l.StartsWith("#", StringComparison.Ordinal))
                    .Distinct(StringComparer.Ordinal)
                    .ToList();

                return values.Count == 0 ? [] : values;
            });
        }
        catch
        {
            return [];
        }
    }

    private static TimeSpan ParseTimeout(string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw))
            return TimeSpan.FromMinutes(2);

        if (int.TryParse(raw, out var seconds) && seconds > 0)
            return TimeSpan.FromSeconds(seconds);

        if (raw.EndsWith('s') && int.TryParse(raw[..^1], out var secondsSuffix) && secondsSuffix > 0)
            return TimeSpan.FromSeconds(secondsSuffix);

        if (raw.EndsWith('m') && int.TryParse(raw[..^1], out var minutesSuffix) && minutesSuffix > 0)
            return TimeSpan.FromMinutes(minutesSuffix);

        if (TimeSpan.TryParse(raw, out var parsed) && parsed > TimeSpan.Zero)
            return parsed;

        return TimeSpan.FromMinutes(2);
    }

    private static int ParseInt(string? raw, int defaultValue)
    {
        if (string.IsNullOrWhiteSpace(raw))
            return defaultValue;

        return int.TryParse(raw, out var v) && v >= 0 ? v : defaultValue;
    }
}
