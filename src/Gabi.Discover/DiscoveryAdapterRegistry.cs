namespace Gabi.Discover;

public sealed class DiscoveryAdapterRegistry
{
    private readonly IReadOnlyDictionary<string, IDiscoveryAdapter> _adapters;

    public DiscoveryAdapterRegistry(IEnumerable<IDiscoveryAdapter> adapters)
    {
        var dict = new Dictionary<string, IDiscoveryAdapter>(StringComparer.OrdinalIgnoreCase);
        foreach (var adapter in adapters)
        {
            var key = Normalize(adapter.StrategyKey);
            if (dict.ContainsKey(key))
                throw new InvalidOperationException($"Duplicate discovery adapter registered for strategy '{key}'.");
            dict[key] = adapter;
        }

        _adapters = dict;
    }

    public IReadOnlyCollection<string> SupportedStrategies => _adapters.Keys.ToArray();

    public bool IsSupported(string? strategy)
    {
        var key = Normalize(strategy);
        return _adapters.ContainsKey(key);
    }

    public IDiscoveryAdapter ResolveOrThrow(string? strategy)
    {
        var key = Normalize(strategy);
        if (_adapters.TryGetValue(key, out var adapter))
            return adapter;

        var supported = string.Join(", ", SupportedStrategies.OrderBy(x => x));
        throw new NotSupportedException(
            $"Discovery strategy '{strategy ?? "(null)"}' is not supported. Supported strategies: [{supported}].");
    }

    public static string Normalize(string? strategy)
    {
        return (strategy ?? string.Empty)
            .Trim()
            .ToLowerInvariant();
    }
}
