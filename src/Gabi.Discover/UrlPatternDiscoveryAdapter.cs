using System.Text.Json;
using Gabi.Contracts.Discovery;

namespace Gabi.Discover;

public sealed class UrlPatternDiscoveryAdapter : IDiscoveryAdapter
{
    public string StrategyKey => "url_pattern";

    public async IAsyncEnumerable<DiscoveredSource> DiscoverAsync(
        string sourceId,
        DiscoveryConfig config,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct = default)
    {
        if (string.IsNullOrWhiteSpace(config.UrlTemplate))
            throw new ArgumentException("UrlTemplate is required for url_pattern strategy", nameof(config));

        var template = config.UrlTemplate!;
        var parameters = config.Params;

        var snapshotYear = config.SnapshotAt?.Year ?? DateTime.UtcNow.Year;

        if (parameters == null || parameters.Count == 0)
        {
            yield return new DiscoveredSource(template, sourceId, new Dictionary<string, object>(), DateTime.UtcNow);
            yield break;
        }

        var param = parameters.First();
        var paramName = param.Key;
        var paramValue = param.Value;

        int start;
        int end;
        int step = 1;

        var dict = AsDictionary(paramValue);
        if (dict != null)
        {
            start = GetInt(dict, "Start", "start");
            var endVal = GetObject(dict, "End", "end");
            end = ResolveEndValue(endVal, snapshotYear);
            step = GetInt(dict, "Step", "step");
            if (step <= 0)
                step = 1;
        }
        else if (paramValue is ParameterRange range)
        {
            start = range.Start;
            end = range.End.Resolve(snapshotYear);
            step = range.Step;
        }
        else
        {
            var type = paramValue.GetType();
            var startProp = type.GetProperty("Start") ?? throw new ArgumentException($"Parameter '{paramName}' must have a 'Start' property");
            var endProp = type.GetProperty("End") ?? throw new ArgumentException($"Parameter '{paramName}' must have an 'End' property");
            var stepProp = type.GetProperty("Step");

            start = Convert.ToInt32(startProp.GetValue(paramValue));
            var endValue = endProp.GetValue(paramValue);
            end = endValue switch
            {
                int i => i,
                string s when s.Equals("current", StringComparison.OrdinalIgnoreCase) => snapshotYear,
                ParameterRangeEnd pre => pre.Resolve(snapshotYear),
                _ => Convert.ToInt32(endValue)
            };

            if (stepProp != null)
                step = Convert.ToInt32(stepProp.GetValue(paramValue));
        }

        var placeholder = $"{{{paramName}}}";
        if (!template.Contains(placeholder, StringComparison.Ordinal))
            throw new ArgumentException($"Template '{template}' does not contain placeholder '{placeholder}'");

        for (var i = start; i <= end; i += step)
        {
            ct.ThrowIfCancellationRequested();

            var url = template.Replace(placeholder, i.ToString(), StringComparison.Ordinal);
            var metadata = new Dictionary<string, object> { [paramName] = i };
            yield return new DiscoveredSource(url, sourceId, metadata, DateTime.UtcNow);
            await Task.Yield();
        }
    }

    private static Dictionary<string, object>? AsDictionary(object? value)
    {
        if (value is Dictionary<string, object> d)
            return d;

        if (value is JsonElement je && je.ValueKind == JsonValueKind.Object)
        {
            var dict = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
            foreach (var p in je.EnumerateObject())
            {
                dict[p.Name] = p.Value.ValueKind switch
                {
                    JsonValueKind.Number => p.Value.TryGetInt32(out var i) ? i : p.Value.GetDouble(),
                    JsonValueKind.String => p.Value.GetString() ?? string.Empty,
                    JsonValueKind.Object => AsDictionary(p.Value) ?? (object)p.Value,
                    _ => p.Value.Clone()
                };
            }
            return dict;
        }

        return null;
    }

    private static int GetInt(Dictionary<string, object> dict, string key1, string key2)
    {
        var v = GetObject(dict, key1, key2);
        if (v == null)
            return 0;

        return v switch
        {
            int i => i,
            long l => (int)l,
            JsonElement je when je.ValueKind == JsonValueKind.Number => je.TryGetInt32(out var i) ? i : (int)je.GetDouble(),
            _ => Convert.ToInt32(v)
        };
    }

    private static object? GetObject(Dictionary<string, object> dict, string key1, string key2)
    {
        if (dict.TryGetValue(key1, out var v))
            return v;
        if (dict.TryGetValue(key2, out v))
            return v;
        return null;
    }

    private static int ResolveEndValue(object? endVal, int? currentYear = null)
    {
        var year = currentYear ?? DateTime.UtcNow.Year;
        return endVal switch
        {
            int i => i,
            long l => (int)l,
            string s when s.Equals("current", StringComparison.OrdinalIgnoreCase) => year,
            ParameterRangeEnd pre => pre.Resolve(currentYear),
            JsonElement je when je.ValueKind == JsonValueKind.String =>
                je.GetString()?.Equals("current", StringComparison.OrdinalIgnoreCase) == true
                    ? year
                    : int.Parse(je.GetString() ?? "0"),
            JsonElement je when je.ValueKind == JsonValueKind.Number => je.TryGetInt32(out var i) ? i : (int)je.GetDouble(),
            _ => endVal is int i2 ? i2 : (endVal is string ? year : Convert.ToInt32(endVal))
        };
    }
}
