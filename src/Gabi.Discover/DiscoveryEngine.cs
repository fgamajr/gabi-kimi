using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Text.RegularExpressions;
using Gabi.Contracts.Discovery;

namespace Gabi.Discover;

/// <summary>
/// Engine de discovery que descobre URLs a partir de configurações.
/// </summary>
public class DiscoveryEngine : IDiscoveryEngine
{
    /// <inheritdoc />
    public Task<ChangeDetectionResult> CheckChangesAsync(
        DiscoveredSource source,
        ChangeDetectionConfig config,
        CancellationToken ct = default)
    {
        // Simplified implementation - in real scenario would check cache
        return Task.FromResult(new ChangeDetectionResult
        {
            HasChanged = true,
            ChangeType = "new"
        });
    }

    /// <inheritdoc />
    public async IAsyncEnumerable<DiscoveredSource> DiscoverAsync(
        string sourceId,
        DiscoveryConfig config,
        [EnumeratorCancellation] CancellationToken ct = default)
    {
        switch (config.Mode)
        {
            case DiscoveryMode.StaticUrl:
                if (string.IsNullOrEmpty(config.Url))
                    throw new ArgumentException("URL is required for StaticUrl mode", nameof(config));
                
                yield return new DiscoveredSource(
                    config.Url,
                    sourceId,
                    new Dictionary<string, object>(),
                    DateTime.UtcNow
                );
                break;

            case DiscoveryMode.UrlPattern:
                if (string.IsNullOrEmpty(config.UrlTemplate))
                    throw new ArgumentException("UrlTemplate is required for UrlPattern mode", nameof(config));
                
                await foreach (var source in GenerateUrlPatternSourcesAsync(sourceId, config, ct))
                    yield return source;
                break;

            case DiscoveryMode.WebCrawl:
                // Crawler/adaptador ainda não implementado; retorna vazio para não quebrar refresh/listagem
                yield break;

            case DiscoveryMode.ApiPagination:
                // Adaptador de API paginada ainda não implementado; retorna vazio
                yield break;

            default:
                throw new ArgumentException($"Unknown discovery mode: {config.Mode}");
        }
    }

    private static async IAsyncEnumerable<DiscoveredSource> GenerateUrlPatternSourcesAsync(
        string sourceId,
        DiscoveryConfig config,
        [EnumeratorCancellation] CancellationToken ct)
    {
        var template = config.UrlTemplate!;
        var parameters = config.Params;

        if (parameters == null || parameters.Count == 0)
        {
            yield return new DiscoveredSource(template, sourceId, new Dictionary<string, object>(), DateTime.UtcNow);
            yield break;
        }

        // Get the first parameter to iterate (for simplicity, we support one range parameter)
        var param = parameters.First();
        var paramName = param.Key;
        var paramValue = param.Value;

        // Parse parameter range using reflection or dictionary (accept Start/start, End/end, Step/step)
        int start, end, step = 1;
        var dict = AsDictionary(paramValue);
        if (dict != null)
        {
            start = GetInt(dict, "Start", "start");
            var endVal = GetObject(dict, "End", "end");
            end = ResolveEndValue(endVal);
            step = GetInt(dict, "Step", "step");
            if (step <= 0) step = 1;
        }
        else if (paramValue is ParameterRange range)
        {
            start = range.Start;
            end = range.End.Resolve();
            step = range.Step;
        }
        else
        {
            // Handle anonymous types and other objects via reflection
            var type = paramValue.GetType();
            var startProp = type.GetProperty("Start") ?? throw new ArgumentException($"Parameter '{paramName}' must have a 'Start' property");
            var endProp = type.GetProperty("End") ?? throw new ArgumentException($"Parameter '{paramName}' must have an 'End' property");
            var stepProp = type.GetProperty("Step");
            
            start = Convert.ToInt32(startProp.GetValue(paramValue));
            // Handle End as ParameterRangeEnd or other types
            var endValue = endProp.GetValue(paramValue);
            end = endValue switch
            {
                int i => i,
                string s when s.Equals("current", StringComparison.OrdinalIgnoreCase) => DateTime.UtcNow.Year,
                ParameterRangeEnd pre => pre.Resolve(),
                _ => Convert.ToInt32(endValue)
            };
            if (stepProp != null)
                step = Convert.ToInt32(stepProp.GetValue(paramValue));
        }

        // Validate template contains the parameter placeholder
        var placeholder = $"{{{paramName}}}";
        if (!template.Contains(placeholder))
            throw new ArgumentException($"Template '{template}' does not contain placeholder '{placeholder}'");

        // Generate URLs
        for (var i = start; i <= end; i += step)
        {
            ct.ThrowIfCancellationRequested();
            
            var url = template.Replace(placeholder, i.ToString());
            var metadata = new Dictionary<string, object> { [paramName] = i };
            
            yield return new DiscoveredSource(url, sourceId, metadata, DateTime.UtcNow);
            
            // Simulate async work
            await Task.Yield();
        }
    }

    private static Dictionary<string, object>? AsDictionary(object? value)
    {
        if (value is Dictionary<string, object> d) return d;
        if (value is JsonElement je && je.ValueKind == JsonValueKind.Object)
        {
            var dict = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
            foreach (var p in je.EnumerateObject())
                dict[p.Name] = p.Value.ValueKind switch
                {
                    JsonValueKind.Number => p.Value.TryGetInt32(out var i) ? i : p.Value.GetDouble(),
                    JsonValueKind.String => p.Value.GetString() ?? "",
                    JsonValueKind.Object => AsDictionary(p.Value) ?? (object)p.Value,
                    _ => p.Value.Clone()
                };
            return dict;
        }
        return null;
    }

    private static int GetInt(Dictionary<string, object> dict, string key1, string key2)
    {
        var v = GetObject(dict, key1, key2);
        if (v == null) return 0;
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
        if (dict.TryGetValue(key1, out var v)) return v;
        if (dict.TryGetValue(key2, out v)) return v;
        return null;
    }

    private static int ResolveEndValue(object? endVal)
    {
        return endVal switch
        {
            int i => i,
            long l => (int)l,
            string s when s.Equals("current", StringComparison.OrdinalIgnoreCase) => DateTime.UtcNow.Year,
            ParameterRangeEnd pre => pre.Resolve(),
            JsonElement je when je.ValueKind == JsonValueKind.String => je.GetString()?.Equals("current", StringComparison.OrdinalIgnoreCase) == true ? DateTime.UtcNow.Year : int.Parse(je.GetString() ?? "0"),
            JsonElement je when je.ValueKind == JsonValueKind.Number => je.TryGetInt32(out var i) ? i : (int)je.GetDouble(),
            _ => endVal is int i2 ? i2 : (endVal is string ? DateTime.UtcNow.Year : Convert.ToInt32(endVal))
        };
    }
}
