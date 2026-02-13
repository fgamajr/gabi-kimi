using System.Runtime.CompilerServices;
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

        // Parse parameter range using reflection or dictionary
        int start, end, step = 1;

        if (paramValue is Dictionary<string, object> dict)
        {
            start = Convert.ToInt32(dict["Start"]);
            // Handle End as int, string, or ParameterRangeEnd
            end = dict["End"] switch
            {
                int i => i,
                string s when s.Equals("current", StringComparison.OrdinalIgnoreCase) => DateTime.UtcNow.Year,
                ParameterRangeEnd pre => pre.Resolve(),
                _ => Convert.ToInt32(dict["End"])
            };
            if (dict.TryGetValue("Step", out var stepVal))
                step = Convert.ToInt32(stepVal);
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
}
