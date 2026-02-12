namespace Gabi.Contracts.Discovery;

/// <summary>
/// Representa uma fonte de dados descoberta durante o processo de discovery.
/// </summary>
/// <param name="Url">URL da fonte de dados.</param>
/// <param name="SourceId">Identificador único da fonte.</param>
/// <param name="Metadata">Metadados adicionais da fonte.</param>
/// <param name="DiscoveredAt">Data/hora da descoberta.</param>
public record DiscoveredSource(
    string Url,
    string SourceId,
    IReadOnlyDictionary<string, object> Metadata,
    DateTime DiscoveredAt
);
