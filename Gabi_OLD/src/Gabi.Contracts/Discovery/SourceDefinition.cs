using Gabi.Contracts.Fetch;

namespace Gabi.Contracts.Discovery;

/// <summary>
/// Represents a source definition from sources.yaml.
/// </summary>
public record SourceDefinition
{
    /// <summary>
    /// Unique identifier for the source.
    /// </summary>
    public string SourceId { get; init; } = null!;
    
    /// <summary>
    /// Display name of the source.
    /// </summary>
    public string Name { get; init; } = null!;
    
    /// <summary>
    /// Description of the source.
    /// </summary>
    public string Description { get; init; } = null!;
    
    /// <summary>
    /// Discovery configuration.
    /// </summary>
    public DiscoveryConfig Discovery { get; init; } = null!;
    
    /// <summary>
    /// Fetch configuration.
    /// </summary>
    public FetchConfig Fetch { get; init; } = null!;
}

/// <summary>
/// Range parameter for URL pattern expansion.
/// </summary>
public record RangeParameter
{
    /// <summary>
    /// Start value (inclusive).
    /// </summary>
    public int Start { get; init; }
    
    /// <summary>
    /// End value (inclusive). Null means current year.
    /// </summary>
    public int? End { get; init; }
    
    /// <summary>
    /// Step increment.
    /// </summary>
    public int Step { get; init; } = 1;
    
    /// <summary>
    /// Resolves the end value to an actual year.
    /// </summary>
    public int ResolveEnd(int? currentYear = null)
    {
        return End ?? (currentYear ?? DateTime.UtcNow.Year);
    }
}
