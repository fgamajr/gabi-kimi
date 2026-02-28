using System.Security.Cryptography;
using System.Text;
using Gabi.Contracts.Discovery;
using Gabi.Contracts.Fetch;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace Gabi.Discover;

/// <summary>
/// Catalog that loads and provides access to source definitions from YAML configuration.
/// </summary>
public class SourceCatalog
{
    private readonly Dictionary<string, SourceDefinition> _sources = new();

    /// <summary>
    /// Creates a new SourceCatalog and loads sources from the specified YAML file.
    /// </summary>
    public SourceCatalog(string yamlFilePath)
    {
        if (!File.Exists(yamlFilePath))
            throw new FileNotFoundException($"Sources YAML file not found: {yamlFilePath}");

        var yaml = File.ReadAllText(yamlFilePath);
        LoadFromYaml(yaml);
    }

    /// <summary>
    /// Loads sources from YAML content.
    /// </summary>
    private void LoadFromYaml(string yaml)
    {
        var deserializer = new DeserializerBuilder()
            .WithNamingConvention(CamelCaseNamingConvention.Instance)
            .IgnoreUnmatchedProperties()
            .Build();

        var yamlDoc = deserializer.Deserialize<YamlSourceCatalog>(yaml);
        
        if (yamlDoc?.Sources == null)
            return;

        foreach (var sourceEntry in yamlDoc.Sources)
        {
            var sourceId = sourceEntry.Key;
            var sourceData = sourceEntry.Value;
            
            // Skip disabled sources
            if (sourceData is Dictionary<object, object> dict && 
                dict.TryGetValue("enabled", out var enabled) && 
                enabled is false)
            {
                continue;
            }
            
            var definition = ParseSourceDefinition(sourceId, sourceData);
            if (definition != null)
            {
                _sources[sourceId] = definition;
            }
        }
    }

    /// <summary>
    /// Parses a source definition from YAML data.
    /// </summary>
    private SourceDefinition? ParseSourceDefinition(string sourceId, object? sourceData)
    {
        if (sourceData is not Dictionary<object, object> sourceDict)
            return null;

        // Parse identity
        var identity = sourceDict.GetValueOrDefault("identity") as Dictionary<object, object>;
        if (identity == null)
            return null;

        // Parse discovery
        var discovery = sourceDict.GetValueOrDefault("discovery") as Dictionary<object, object>;
        var discoveryConfig = ParseDiscoveryConfig(discovery);

        // Parse fetch
        var fetch = sourceDict.GetValueOrDefault("fetch") as Dictionary<object, object>;
        var fetchConfig = ParseFetchConfig(fetch);

        return new SourceDefinition
        {
            SourceId = sourceId,
            Name = identity.GetValueOrDefault("name")?.ToString() ?? sourceId,
            Description = identity.GetValueOrDefault("description")?.ToString() ?? "",
            Discovery = discoveryConfig,
            Fetch = fetchConfig
        };
    }

    /// <summary>
    /// Parses discovery configuration from YAML data.
    /// </summary>
    private DiscoveryConfig ParseDiscoveryConfig(Dictionary<object, object>? discovery)
    {
        if (discovery == null)
            return new DiscoveryConfig();

        var strategy = discovery.GetValueOrDefault("strategy")?.ToString() ?? "static_url";
        var config = discovery.GetValueOrDefault("config") as Dictionary<object, object>;

        if (strategy == "url_pattern" && config != null)
        {
            var template = config.GetValueOrDefault("template")?.ToString() ?? "";
            var parameters = config.GetValueOrDefault("parameters") as Dictionary<object, object>;
            
            RangeParameter? yearRange = null;
            if (parameters != null && parameters.TryGetValue("year", out var yearObj))
            {
                if (yearObj is Dictionary<object, object> yearDict)
                {
                    var start = Convert.ToInt32(yearDict.GetValueOrDefault("start") ?? 0);
                    var step = Convert.ToInt32(yearDict.GetValueOrDefault("step") ?? 1);
                    var endVal = yearDict.GetValueOrDefault("end");
                    
                    int? end = endVal?.ToString() == "current" ? null : Convert.ToInt32(endVal ?? 0);
                    
                    yearRange = new RangeParameter
                    {
                        Start = start,
                        End = end,
                        Step = step
                    };
                }
            }

            return new DiscoveryConfig
            {
                Strategy = strategy,
                UrlPattern = new UrlPatternConfig
                {
                    Template = template,
                    YearRange = yearRange
                }
            };
        }
        else if (strategy == "static_url" && config != null)
        {
            var staticUrl = config.GetValueOrDefault("url")?.ToString();
            return new DiscoveryConfig
            {
                Strategy = strategy,
                StaticUrl = staticUrl
            };
        }

        return new DiscoveryConfig { Strategy = strategy };
    }

    /// <summary>
    /// Parses fetch configuration from YAML data.
    /// </summary>
    private FetchConfig ParseFetchConfig(Dictionary<object, object>? fetch)
    {
        if (fetch == null)
            return new FetchConfig();

        var protocol = fetch.GetValueOrDefault("protocol")?.ToString() ?? "https";
        var method = fetch.GetValueOrDefault("method")?.ToString() ?? "GET";
        
        var headers = new Dictionary<string, string>();
        if (fetch.GetValueOrDefault("headers") is Dictionary<object, object> headersDict)
        {
            foreach (var header in headersDict)
            {
                headers[header.Key.ToString()!] = header.Value?.ToString() ?? "";
            }
        }

        return new FetchConfig
        {
            Protocol = protocol == "https" ? HttpProtocol.Https : HttpProtocol.Http,
            Method = method,
            Headers = headers
        };
    }

    /// <summary>
    /// Gets all source definitions.
    /// </summary>
    public IReadOnlyList<SourceDefinition> GetAllSources()
    {
        return _sources.Values.ToList();
    }

    /// <summary>
    /// Gets a source definition by ID.
    /// </summary>
    public SourceDefinition? GetSource(string sourceId)
    {
        return _sources.GetValueOrDefault(sourceId);
    }

    /// <summary>
    /// YAML document structure for deserialization.
    /// </summary>
    private class YamlSourceCatalog
    {
        public Dictionary<string, object>? Sources { get; set; }
    }
}

/// <summary>
/// Extension methods for dictionary operations.
/// </summary>
internal static class DictionaryExtensions
{
    public static TValue? GetValueOrDefault<TKey, TValue>(this Dictionary<TKey, object> dict, TKey key)
        where TKey : notnull
    {
        return dict.TryGetValue(key, out var value) ? (TValue?)value : default;
    }
}
