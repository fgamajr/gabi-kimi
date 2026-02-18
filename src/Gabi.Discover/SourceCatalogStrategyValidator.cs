using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace Gabi.Discover;

public sealed record UnsupportedDiscoveryStrategy(string SourceId, string Strategy);

public sealed class SourceCatalogStrategyValidator
{
    private readonly DiscoveryAdapterRegistry _registry;

    public SourceCatalogStrategyValidator(DiscoveryAdapterRegistry registry)
    {
        _registry = registry;
    }

    public IReadOnlyCollection<string> SupportedStrategies => _registry.SupportedStrategies;

    public IReadOnlyList<UnsupportedDiscoveryStrategy> FindUnsupportedEnabledStrategies(string yamlContent)
    {
        var deserializer = new DeserializerBuilder()
            .WithNamingConvention(UnderscoredNamingConvention.Instance)
            .IgnoreUnmatchedProperties()
            .Build();

        var doc = deserializer.Deserialize<SourceCatalogDocument>(yamlContent);
        if (doc?.Sources == null || doc.Sources.Count == 0)
            return Array.Empty<UnsupportedDiscoveryStrategy>();

        var invalid = new List<UnsupportedDiscoveryStrategy>();

        foreach (var (sourceId, source) in doc.Sources)
        {
            if (source == null || !source.Enabled)
                continue;

            var strategy = DiscoveryAdapterRegistry.Normalize(source.Discovery?.Strategy);
            if (!_registry.IsSupported(strategy))
            {
                invalid.Add(new UnsupportedDiscoveryStrategy(sourceId, source.Discovery?.Strategy ?? string.Empty));
            }
        }

        return invalid;
    }

    private sealed class SourceCatalogDocument
    {
        public Dictionary<string, SourceDefinition>? Sources { get; set; }
    }

    private sealed class SourceDefinition
    {
        public bool Enabled { get; set; } = true;
        public DiscoveryDefinition? Discovery { get; set; }
    }

    private sealed class DiscoveryDefinition
    {
        public string? Strategy { get; set; }
    }
}
